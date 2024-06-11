import asyncio
import json
import os
import time

import logging
import requests
from aiohttp import web
from discord import Client, Intents, Embed, Game
from discord_slash import SlashCommand, SlashContext, SlashCommandOptionType
from discord_slash.utils.manage_commands import create_option

try:
    GUILD_IDS = [int(x) for x in os.getenv('GUILD_IDS').split(',')]
except ValueError:
    GUILD_IDS = None

LOVENSE_DEVELOPER_TOKEN = os.getenv('LOVENSE_DEVELOPER_TOKEN')
TOKEN = os.getenv('TOKEN')
REQUEST_HEADRERS = {
        'User-Agent': 'ToyBot/beep-boop'
    }
API_URL_QR = 'https://api.lovense.com/api/lan/getQrCode'
API_URL_COMMAND = 'https://api.lovense.com/api/lan/v2/command'
CALLBACK_PORT = 8000

bot = Client(intents=Intents.default())
slash = SlashCommand(bot, sync_commands=True, debug_guild=os.getenv('DEBUG_GUILD_ID', None))
logging.basicConfig(format='[%(asctime)s] [%(name)s] [%(levelname)s] - %(message)s', level=logging.INFO, filename='ToyBot.log')
log = logging.getLogger('ToyBot')


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
            await bot.change_presence(activity=Game(name=playing))
        await asyncio.sleep(60)


@slash.subcommand(base='lovense', name="connect",
                  description="Connect a toy", guild_ids=GUILD_IDS)
async def connect(ctx: SlashContext):
    url = controller.get_connection_qr(str(ctx.guild_id), str(ctx.author_id))
    if url is None:
        await ctx.send("Sorry, I can't connect to Lovense right now", hidden=True)
        return

    embed = Embed(title='Connect with Lovense Remote', description="Using the Lovense Remote app, press the + button > Scan QR. " +
                                                                   "This is *your* personal QR code, sharing it might prevent the connection from working")
    embed.set_image(url=url)
    await ctx.send(embeds=[embed], hidden=True)


@slash.subcommand(base='lovense', name="status",
                  description="List connected toys", guild_ids=GUILD_IDS)
async def status(ctx: SlashContext):
    embed = Embed(title='Connected Toys')
    toy_count = {}
    for toy in controller.get_toys(str(ctx.guild_id)):
        toy_count[toy] = toy_count+1 if toy in toy_count else 1
    if not toy_count:
        await ctx.send("There are no toys connected")
        return
    for toy, count in toy_count.items():
        embed.add_field(name=toy.title(), value='{} connected'.format(count), inline=True)
    await ctx.send(embeds=[embed])


@slash.subcommand(base='lovense', name="vibrate",
                  description="Vibrate all toys",
                  guild_ids=GUILD_IDS,
                  options=[
                      create_option(
                          name="strength",
                          description="Vibration strength (1-20). Defaults to 10",
                          option_type=SlashCommandOptionType.INTEGER,
                          required=False
                      ),
                      create_option(
                          name="duration",
                          description="Number of seconds it lasts. Defaults to 10 secconds",
                          option_type=SlashCommandOptionType.INTEGER,
                          required=False
                      ),
                  ])
async def vibrate(ctx: SlashContext, strength=10, duration=10):
    if controller.vibrate(str(ctx.guild_id), duration=duration, strength=strength):
        await ctx.send("Buzz buzz!", hidden=True)
    else:
        await ctx.send("There aren't any toys connected", hidden=True)


@slash.subcommand(base='lovense', name="rotate",
                  description="Rotate all toys",
                  guild_ids=GUILD_IDS,
                  options=[
                      create_option(
                          name="strength",
                          description="Rotation strength (1-20). Defaults to 10",
                          option_type=SlashCommandOptionType.INTEGER,
                          required=False
                      ),
                      create_option(
                          name="duration",
                          description="Number of seconds it lasts. Defaults to 10 secconds",
                          option_type=SlashCommandOptionType.INTEGER,
                          required=False
                      ),
                  ])
async def rotate(ctx: SlashContext, strength=10, duration=10):
    if controller.rotate(str(ctx.guild_id), duration=duration, strength=strength):
        await ctx.send("You spin me right round baby...", hidden=True)
    else:
        await ctx.send("There aren't any toys connected", hidden=True)


@slash.subcommand(base='lovense', name="pump",
                  description="Pump all toys",
                  guild_ids=GUILD_IDS,
                  options=[
                      create_option(
                          name="strength",
                          description="Pump strength (1-3). Defaults to 2",
                          option_type=SlashCommandOptionType.INTEGER,
                          required=False
                      ),
                      create_option(
                          name="duration",
                          description="Number of seconds it lasts. Defaults to 10 secconds",
                          option_type=SlashCommandOptionType.INTEGER,
                          required=False
                      ),
                  ])
async def rotate(ctx: SlashContext, strength=2, duration=10):
    if controller.pump(str(ctx.guild_id), duration=duration, strength=strength):
        await ctx.send("Let's get pumped!", hidden=True)
    else:
        await ctx.send("There aren't any toys connected", hidden=True)


@slash.subcommand(base='lovense', name="pattern",
                  description="Send a pattern to all toys. Loops until stopped, or replaced with another vibration or pattern",
                  guild_ids=GUILD_IDS,
                  options=[
                      create_option(
                          name="pattern",
                          description="The pattern to send",
                          option_type=SlashCommandOptionType.STRING,
                          choices=['pulse', 'wave', 'fireworks', 'earthquake'],
                          required=True
                      )
                  ])
async def vibrate_pattern(ctx: SlashContext, pattern):
    if controller.pattern(str(ctx.guild_id), pattern):
        await ctx.send("Here comes the {}!".format(pattern), hidden=True)
    else:
        await ctx.send("There aren't any toys connected", hidden=True)


@slash.subcommand(base='lovense', name="stop",
                  description="Stop all toys", guild_ids=GUILD_IDS)
async def stop(ctx: SlashContext):
    if controller.stop(str(ctx.guild_id)):
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
