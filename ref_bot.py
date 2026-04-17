import os
import json
import random
import time
import asyncio
from datetime import datetime, timezone

import discord
import requests
from flask import Flask
from threading import Thread
from discord import app_commands
from dotenv import load_dotenv

# ================= LOAD ENV =================
load_dotenv()

# ================= CONFIG =================
TOKEN = os.getenv("REF_TOKEN")
TOPGG_TOKEN = os.getenv("TOPGG_TOKEN")  # your top.gg API key
RESPONSES_FILE = "ref_responses.json"
COOLDOWN_SECONDS = 10
LOG_CHANNEL_ID = int(os.getenv("REF_LOG_CHANNEL_ID", "0"))  # private channel in your own server
PORT = int(os.getenv("PORT", "8080"))

# ================= FLASK KEEP-ALIVE =================
app = Flask("ref")

@app.route("/")
def home():
    return "REF is alive."

def run_flask():
    app.run(host="0.0.0.0", port=PORT)

Thread(target=run_flask, daemon=True).start()

# ================= DISCORD SETUP =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.guilds = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

# ================= DATA LOADING =================
_last_mtime = 0
REF_LINES = []
REF_IMAGES = []
IMAGE_CHANCE = 0.2

def load_responses():
    global _last_mtime, REF_LINES, REF_IMAGES, IMAGE_CHANCE
    try:
        if not os.path.exists(RESPONSES_FILE):
            return
        mtime = os.path.getmtime(RESPONSES_FILE)
        if mtime != _last_mtime:
            with open(RESPONSES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            REF_LINES = data.get("lines", [])
            REF_IMAGES = data.get("images", [])
            IMAGE_CHANCE = data.get("image_chance", 0.2)
            _last_mtime = mtime
            print("🟨 REF responses reloaded")
    except Exception as e:
        print(f"❌ Failed to load responses: {e}")

# ================= COOLDOWN =================
USER_COOLDOWNS = {}

# ================= TOP.GG =================
def guild_count() -> int:
    return len(client.guilds)

def post_topgg_stats():
    if not TOPGG_TOKEN:
        print("⚠️ No TOPGG_TOKEN found, skipping top.gg update.")
        return

    if not client.user:
        print("⚠️ Bot user not ready yet, skipping top.gg update.")
        return

    url = f"https://top.gg/api/bots/{client.user.id}/stats"
    headers = {
        "Authorization": TOPGG_TOKEN,
        "Content-Type": "application/json",
    }
    payload = {
        "server_count": guild_count()
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if 200 <= r.status_code < 300:
            print(f"✅ Posted top.gg stats: {payload['server_count']} servers")
        else:
            print(f"❌ top.gg update failed: {r.status_code} | {r.text}")
    except Exception as e:
        print(f"❌ Error posting top.gg stats: {e}")

async def post_topgg_stats_async():
    await asyncio.to_thread(post_topgg_stats)

async def topgg_loop():
    await client.wait_until_ready()
    while not client.is_closed():
        await post_topgg_stats_async()
        await asyncio.sleep(1800)  # every 30 mins

# ================= PRIVATE LOGGING =================
async def send_private_log(embed: discord.Embed):
    if not LOG_CHANNEL_ID:
        print("⚠️ REF_LOG_CHANNEL_ID not set.")
        return

    channel = client.get_channel(LOG_CHANNEL_ID)
    if channel is None:
        try:
            channel = await client.fetch_channel(LOG_CHANNEL_ID)
        except Exception as e:
            print(f"❌ Could not fetch log channel: {e}")
            return

    try:
        await channel.send(embed=embed)
    except Exception as e:
        print(f"❌ Failed to send log embed: {e}")

def build_guild_embed(guild: discord.Guild, action: str) -> discord.Embed:
    colour = discord.Color.green() if action == "added" else discord.Color.red()
    title = "✅ REF Added to Server" if action == "added" else "❌ REF Removed from Server"

    owner_text = "Unknown"
    if guild.owner:
        owner_text = f"{guild.owner} ({guild.owner.id})"

    embed = discord.Embed(
        title=title,
        colour=colour,
        timestamp=datetime.now(timezone.utc)
    )
    embed.add_field(name="Server Name", value=guild.name, inline=False)
    embed.add_field(name="Server ID", value=str(guild.id), inline=True)
    embed.add_field(name="Members", value=str(guild.member_count or 0), inline=True)
    embed.add_field(name="Owner", value=owner_text, inline=False)
    embed.add_field(name="Total Servers", value=str(guild_count()), inline=False)

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    return embed

# ================= EVENTS =================
@client.event
async def on_ready():
    load_responses()

    try:
        await tree.sync()
        print("✅ Slash commands synced")
    except Exception as e:
        print(f"❌ Failed to sync slash commands: {e}")

    if not hasattr(client, "_topgg_loop_started"):
        client._topgg_loop_started = True
        client.loop.create_task(topgg_loop())

    await post_topgg_stats_async()
    print(f"🟨 REF connected as {client.user} | Guilds: {guild_count()}")

@client.event
async def on_guild_join(guild: discord.Guild):
    print(f"✅ Joined guild: {guild.name} ({guild.id})")
    await post_topgg_stats_async()
    await send_private_log(build_guild_embed(guild, "added"))

@client.event
async def on_guild_remove(guild: discord.Guild):
    print(f"❌ Removed from guild: {guild.name} ({guild.id})")
    await post_topgg_stats_async()
    await send_private_log(build_guild_embed(guild, "removed"))

@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    bot_id_str = f"<@{client.user.id}>"
    bot_nick_str = f"<@!{client.user.id}>"

    if bot_id_str not in message.content and bot_nick_str not in message.content:
        return

    now = time.time()
    guild_id = message.guild.id if message.guild else "dm"
    user_key = (message.author.id, guild_id)

    if now - USER_COOLDOWNS.get(user_key, 0) < COOLDOWN_SECONDS:
        return

    USER_COOLDOWNS[user_key] = now

    load_responses()

    if REF_IMAGES and random.random() < IMAGE_CHANCE:
        await message.channel.send(random.choice(REF_IMAGES))
    elif REF_LINES:
        await message.channel.send(random.choice(REF_LINES))

# ================= SLASH COMMANDS =================
@tree.command(name="vote", description="Get the vote link for REF.")
async def vote_command(interaction: discord.Interaction):
    bot_id = client.user.id
    vote_url = f"https://top.gg/bot/{bot_id}/vote"

    embed = discord.Embed(
        title="Vote for REF",
        description=f"Vote here:\n{vote_url}",
        colour=discord.Color.blurple()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================= START =================
if TOKEN:
    client.run(TOKEN)
else:
    print("❌ No REF_TOKEN found in environment variables.")
