import os
import json
import random
import time
import discord
from flask import Flask
from threading import Thread

from dotenv import load_dotenv

# This looks for the .env file and loads its contents
load_dotenv()

# ================= CONFIG =================
TOKEN = os.getenv("REF_TOKEN")
RESPONSES_FILE = "ref_responses.json"
COOLDOWN_SECONDS = 10

# ================= FLASK KEEP-ALIVE =================
app = Flask("ref")

@app.route("/")
def home():
    return "REF is alive."

def run_flask():
    app.run(host="0.0.0.0", port=8080)

Thread(target=run_flask, daemon=True).start()

# ================= DISCORD SETUP =================
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)

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

# ================= EVENTS =================
@client.event
async def on_ready():
    load_responses()
    print(f"🟨 REF connected as {client.user}")

@client.event
async def on_message(message: discord.Message):
    # 1. Ignore other bots
    if message.author.bot:
        return

    # 2. Identify the bot's mention strings
    # <@ID> is standard, <@!ID> is for nicknames
    bot_id_str = f"<@{client.user.id}>"
    bot_nick_str = f"<@!{client.user.id}>"

    # 3. TRIGGER CHECK: Must contain the @ mention in the actual text
    if bot_id_str not in message.content and bot_nick_str not in message.content:
        return

    # 4. Cooldown check (Unique to User + Server)
    now = time.time()
    guild_id = message.guild.id if message.guild else "dm"
    user_key = (message.author.id, guild_id)
    
    if now - USER_COOLDOWNS.get(user_key, 0) < COOLDOWN_SECONDS:
        return

    USER_COOLDOWNS[user_key] = now

    # 5. Reload and Respond
    load_responses()
    
    if REF_IMAGES and random.random() < IMAGE_CHANCE:
        await message.channel.send(random.choice(REF_IMAGES))
    elif REF_LINES:
        await message.channel.send(random.choice(REF_LINES))

# ================= START =================
if TOKEN:
    client.run(TOKEN)
else:
    print("❌ No TOKEN found in environment variables.")
