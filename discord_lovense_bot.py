import asyncio
import json
import os
import time
import logging
import requests
from aiohttp import web
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

intents = discord.Intents.all()
bot = commands.Bot(command_prefix='!', intents=intents)

GUILD_IDS = [int(x) for x in os.getenv('GUILD_IDS', '').split(',') if x]

LOVENSE_DEVELOPER_TOKEN = os.getenv('LOVENSE_DEVELOPER_TOKEN')
TOKEN = os.getenv('TOKEN')
REQUEST_HEADERS = {
    'User-Agent': 'ToyBot/beep-boop'
}
API_URL_QR = 'https://api.lovense.com/api/lan/getQrCode'
API_URL_COMMAND = 'https://api.lovense.com/api/lan/v2/command'
CALLBACK_PORT = 8000

logging.basicConfig(format='[%(asctime)s] [%(name)s] [%(levelname)s] - %(message)s', level=logging.INFO, filename='ToyBot.log')
log = logging.getLogger('ToyBot')


@bot.hybrid_command()
async def ping(ctx):
    """ Replies with pong """
    await ctx.send("Pong!")


@bot.hybrid_command()
async def sync(ctx):
    synced = await bot.tree.sync()
    await ctx.send(f"Synced {len(synced)} command(s)")


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    bot.loop.create_task(update_activity())
    bot.loop.create_task(callbacks.webserver())


async def update_activity():
    if not bot.is_ready():
        await bot.wait_until_ready()
    toy_count = 0
    while True:
        last_count = toy_count
        toy_count = sum([len(controller.get_toys(str(x))) for x in GUILD_IDS])
        if toy_count != last_count:
            playing = 'with ' + ('no toys' if toy_count == 0 else '1 toy' if toy_count == 1 else '{} toys'.format(toy_count))
            log.info("Toy count is now {}, was {}. Updating presence.".format(toy_count, last_count))
            await bot.change_presence(activity=discord.Game(name=playing))
        await asyncio.sleep(60)


@bot.hybrid_command()
async def connect(ctx):
    url = controller.get_connection_qr(str(ctx.guild.id), str(ctx.author.id))
    if url is None:
        await ctx.send("Sorry, I can't connect to Lovense right now", hidden=True)
        return

    embed = discord.Embed(title='Connect with Lovense Remote', description="Using the Lovense Remote app, press the + button > Scan QR. " +
                                                                           "This is *your* personal QR code, sharing it might prevent the connection from working")
    embed.set_image(url=url)
    await ctx.send(embed=embed, hidden=True)


@bot.hybrid_command()
async def status(ctx):
    embed = discord.Embed(title='Connected Toys')
    toy_count = {}
    for toy in controller.get_toys(str(ctx.guild.id)):
        toy_count[toy] = toy_count.get(toy, 0) + 1
    if not toy_count:
        await ctx.send("There are no toys connected")
        return
    for toy, count in toy_count.items():
        embed.add_field(name=toy.title(), value='{} connected'.format(count), inline=True)
    await ctx.send(embed=embed)


@bot.hybrid_command()
async def vibrate(ctx, strength: int = 10, duration: int = 10):
    if controller.vibrate(str(ctx.guild.id), duration=duration, strength=strength):
        await ctx.send("Buzz buzz!", hidden=True)
    else:
        await ctx.send("There aren't any toys connected", hidden=True)


@bot.hybrid_command()
async def rotate(ctx, strength: int = 10, duration: int = 10):
    if controller.rotate(str(ctx.guild.id), duration=duration, strength=strength):
        await ctx.send("You spin me right round baby...", hidden=True)
    else:
        await ctx.send("There aren't any toys connected", hidden=True)


@bot.hybrid_command()
async def pump(ctx, strength: int = 2, duration: int = 10):
    if controller.pump(str(ctx.guild.id), duration=duration, strength=strength):
        await ctx.send("Let's get pumped!", hidden=True)
    else:
        await ctx.send("There aren't any toys connected", hidden=True)


@bot.hybrid_command()
async def pattern(ctx, pattern: str):
    if controller.pattern(str(ctx.guild.id), pattern):
        await ctx.send(f"Here comes the {pattern}!", hidden=True)
    else:
        await ctx.send("There aren't any toys connected", hidden=True)


@bot.hybrid_command()
async def stop(ctx):
    if controller.stop(str(ctx.guild.id)):
        await ctx.send("Break-time!", hidden=True)
    else:
        await ctx.send("There aren't any toys connected", hidden=True)


class ToyController:
    BASE_REQ = {
        'token': LOVENSE_DEVELOPER_TOKEN,
        'apiVer': '1'
    }
    guilds = {}

    def __init__(self):
        try:
            with open('guilds.json', 'r') as f:
                self.guilds = json.loads(f.read())
        except (FileNotFoundError, IOError, json.decoder.JSONDecodeError):
            self.guilds = {}

    def get_connection_qr(self, guild_id: str, uid: str):
        req = {**self.BASE_REQ, **{
            'uid': guild_id + ':' + uid,
        }}
        try:
            with requests.post(API_URL_QR, json=req) as response:
                return response.json().get('message', None)
        except (json.JSONDecodeError, AttributeError):
            return None

    def add_user(self, guild_id: str, uid: str, user):
        if guild_id not in self.guilds:
            log.info("Adding new guild with GID {}".format(guild_id))
            self.guilds[guild_id] = {}
        if uid not in self.guilds.get(guild_id):
            log.info("Added new user with GID:UID {}:{}".format(guild_id, uid))
        user['last_updated'] = round(time.time())
        self.guilds[guild_id][uid] = user
        self._save()

    def get_toys(self, guild_id: str):
        self._refresh()
        toys = []
        if guild_id not in self.guilds:
            return []
        for uid, user in self.guilds.get(guild_id).items():
            toys += [y.get('name') for x, y in user.get('toys').items()]
        return toys

    def stop(self, guild_id: str):
        return self._function(guild_id, 'Stop', None, 0, 0)

    def pattern(self, guild_id: str, pattern, uid: str = None):
        self._refresh()
        if self.guilds.get(guild_id) is None:
            return False
        if uid is not None and uid not in self.guilds.get(guild_id):
            return False
        uids = [x.get('uid') for x in (self.guilds.get(guild_id).values() if uid is None else [self.guilds.get(guild_id).get(uid)])]
        req = {**self.BASE_REQ, **{
            'uid': ','.join(uids),
            'command': 'Preset',
            'name': pattern,
            'timeSec': 0,
        }}
        with requests.post(API_URL_COMMAND, json=req, timeout=5) as response:
            return response.status_code == 200

    def vibrate(self, guild_id: str, uid: str = None, strength: int = 10, duration: int = 10):
        return self._function(guild_id, 'Vibrate', uid, strength, duration)

    def rotate(self, guild_id: str, uid: str = None, strength: int = 10, duration: int = 10):
        return self._function(guild_id, 'Rotate', uid, strength, duration)

    def pump(self, guild_id: str, uid: str = None, strength: int = 10, duration: int = 10):
        return self._function(guild_id, 'Pump', uid, strength, duration)

    def _function(self, guild_id: str, action: str, uid: str = None, strength: int = 10, duration: int = 10):
        self._refresh()
        if guild_id not in self.guilds:
            return False
        if uid is not None and uid not in self.guilds.get(guild_id):
            return False
        if strength > 0:
            action += ':{}'.format(strength)
        uids = [x.get('uid') for x in (self.guilds.get(guild_id).values() if uid is None else [self.guilds.get(guild_id).get(uid)])]
        req = {**self.BASE_REQ, **{
            'uid': ','.join(uids),
            'command': 'Function',
            'action': action,
            'timeSec': duration,
        }}
        with requests.post(API_URL_COMMAND, json=req, timeout=5) as response:
            return response.status_code == 200

    def _refresh(self):
        now = round(time.time())
        old = {**self.guilds}
        for guild_id, guild in old.items():
            for uid, user in guild.items():
                if now - user.get('last_updated', now) > 7200:
                    del self.guilds[guild_id][uid]
            if not self.guilds.get(guild_id):
                del self.guilds[guild_id]
        if old != self.guilds:
            log.info("Purged guild data")
            self._save()

    def _save(self):
        with open('guilds.json', 'w') as f:
            f.write(json.dumps(self.guilds))


controller = ToyController()

bot.run(TOKEN)
