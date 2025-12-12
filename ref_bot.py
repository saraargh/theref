# ref_bot.py

import os
import json
import random
import time
import discord
from flask import Flask
from threading import Thread

# ===== CONFIG =====
TOKEN = os.getenv("REF_TOKEN")
REF_ROLE_ID = 1449021154596749342>  # <-- PUT REF ROLE ID HERE
RESPONSES_FILE = "ref_responses.json"

# ===== FLASK KEEP-ALIVE =====
app = Flask("ref")

@app.route("/")
def home():
    return "REF is alive."

def run_flask():
    app.run(host="0.0.0.0", port=8080)

Thread(target=run_flask, daemon=True).start()

# ===== DISCORD INTENTS =====
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)

# ===== RESPONSE DATA (HOT RELOAD) =====
_last_mtime = 0
REF_LINES = []
REF_IMAGES = []
IMAGE_CHANCE = 0.2

def load_responses():
    global _last_mtime, REF_LINES, REF_IMAGES, IMAGE_CHANCE

    try:
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

# ===== EVENTS =====
@client.event
async def on_ready():
    load_responses()
    print(f"🟨 REF connected as {client.user}")

@client.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    if not message.role_mentions:
        return

    mentioned_role_ids = [role.id for role in message.role_mentions]

    if REF_ROLE_ID not in mentioned_role_ids:
        return

    # Hot reload check
    load_responses()

    # Respond
    if REF_IMAGES and random.random() < IMAGE_CHANCE:
        await message.channel.send(random.choice(REF_IMAGES))
    elif REF_LINES:
        await message.channel.send(random.choice(REF_LINES))

# ===== START =====
client.run(TOKEN)
