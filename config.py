import os
from dotenv import load_dotenv

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = int(os.getenv("GUILD_ID", "0") or 0)
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "0") or 0)
BUG_REPORT_CHANNEL_ID = int(os.getenv("BUG_REPORT_CHANNEL_ID", "0") or 0)
SUGGESTION_CHANNEL_ID = int(os.getenv("SUGGESTION_CHANNEL_ID", "0") or 0)
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", "0") or 0)
VOICE_CHANNEL_ID = int(os.getenv("VOICE_CHANNEL_ID", "0") or 0)
CURRENCY_NAME = os.getenv("CURRENCY_NAME", "Alpha Coins")
