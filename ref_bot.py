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
TOPGG_TOKEN = os.getenv("TOPGG_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO")  # e.g. "saraargh/ref-bot"
RESPONSES_FILE = "ref_responses.json"
IMAGES_FOLDER = "images"
COOLDOWN_SECONDS = 10
LOG_CHANNEL_ID = int(os.getenv("REF_LOG_CHANNEL_ID", "0"))
PORT = int(os.getenv("PORT", "8080"))
DEV_GUILD = int(os.getenv("REF_DEV_GUILD_ID", "0"))

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
    global _last_mtime, REF_LINES, IMAGE_CHANCE
    try:
        if not os.path.exists(RESPONSES_FILE):
            return
        mtime = os.path.getmtime(RESPONSES_FILE)
        if mtime != _last_mtime:
            with open(RESPONSES_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            REF_LINES = data.get("lines", [])
            IMAGE_CHANCE = data.get("image_chance", 0.2)
            _last_mtime = mtime
            print("🟨 REF responses reloaded")
    except Exception as e:
        print(f"❌ Failed to load responses: {e}")

def load_images_from_github():
    global REF_IMAGES
    if not GITHUB_TOKEN or not GITHUB_REPO:
        print("⚠️ GITHUB_TOKEN or GITHUB_REPO not set, skipping image load.")
        return

    url = f"https://api.github.com/repos/{GITHUB_REPO}/contents/{IMAGES_FOLDER}"
    headers = {"Authorization": f"token {GITHUB_TOKEN}"}

    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            files = r.json()
            REF_IMAGES = [
                f["download_url"] for f in files
                if f["type"] == "file"
                and f["name"].lower().endswith((".jpg", ".jpeg", ".png", ".gif", ".webp"))
            ]
            print(f"🟨 Loaded {len(REF_IMAGES)} images from GitHub")
        elif r.status_code == 404:
            print(f"⚠️ images/ folder not found in {GITHUB_REPO} — no images loaded.")
        else:
            print(f"❌ GitHub images fetch failed: {r.status_code} | {r.text}")
    except Exception as e:
        print(f"❌ Error fetching images from GitHub: {e}")

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

    embed = discord.Embed(
        title="📥 Bot added to server" if action == "added" else "📤 Bot removed from server",
        colour=colour,
        timestamp=datetime.now(timezone.utc)
    )

    owner_text = "Unknown"
    if guild.owner:
        owner_text = f"{guild.owner} ({guild.owner.id})"

    embed.description = (
        f"**Name:** {guild.name}\n"
        f"**Guild ID:** {guild.id}\n"
        f"**Owner ID:** {guild.owner_id}\n"
        f"**Member count:** {guild.member_count or 0}\n"
        f"**Created:** {guild.created_at.strftime('%A, %d %B %Y at %H:%M')}"
    )

    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    return embed

# ================= EVENTS =================
@client.event
async def on_ready():
    load_responses()
    load_images_from_github()

    try:
        await tree.sync()
        if DEV_GUILD:
            await tree.sync(guild=discord.Object(id=DEV_GUILD))
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

@tree.command(
    name="serverlist",
    description="List all servers this bot is currently in"
)
@app_commands.guilds(DEV_GUILD)
@app_commands.checks.has_permissions(administrator=True)
async def serverlist_command(interaction: discord.Interaction):
    guilds = sorted(client.guilds, key=lambda g: (g.member_count or 0), reverse=True)

    if not guilds:
        await interaction.response.send_message("REF isn't in any servers.", ephemeral=True)
        return

    lines = []
    for i, guild in enumerate(guilds, start=1):
        lines.append(
            f"**{i}. {guild.name}**\n"
            f"ID: `{guild.id}`\n"
            f"Members: `{guild.member_count or 0}`"
        )

    chunks = []
    current = ""
    for line in lines:
        if len(current) + len(line) + 2 > 1900:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n\n{line}" if current else line
    if current:
        chunks.append(current)

    await interaction.response.send_message(
        f"REF is in **{len(guilds)}** server(s):\n\n{chunks[0]}",
        ephemeral=True
    )

    for chunk in chunks[1:]:
        await interaction.followup.send(chunk, ephemeral=True)

@tree.command(name="reloadimages", description="Reload images from GitHub (dev only).")
@app_commands.guilds(DEV_GUILD)
@app_commands.checks.has_permissions(administrator=True)
async def reloadimages_command(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    await asyncio.to_thread(load_images_from_github)
    await interaction.followup.send(f"✅ Reloaded — {len(REF_IMAGES)} image(s) loaded.", ephemeral=True)

# ================= START =================
if TOKEN:
    client.run(TOKEN)
else:
    print("❌ No REF_TOKEN found in environment variables.")
