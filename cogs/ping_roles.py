import logging
import re
import sqlite3
import unicodedata

import discord
from discord import app_commands
from discord.ext import commands

from database import DB_PATH

log = logging.getLogger("Sr.Alpha.PingRoles")
PURPLE = discord.Color.from_rgb(145, 103, 255)
TARGET_GUILD_ID = 1536903015678873710
OPTIONS_PER_PAGE = 25


def db_connect():
    return sqlite3.connect(DB_PATH)


def init_tables():
    with db_connect() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS ping_roles (
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                role_id INTEGER NOT NULL,
                emoji TEXT NOT NULL DEFAULT '🔔',
                PRIMARY KEY (guild_id, name),
                UNIQUE (guild_id, role_id)
            )"""
        )
        db.execute(
            """CREATE TABLE IF NOT EXISTS ping_panels (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL
            )"""
        )
        db.commit()


def get_pings(guild_id: int):
    with db_connect() as db:
        return db.execute(
            """SELECT name, role_id, emoji FROM ping_roles
               WHERE guild_id = ? ORDER BY name COLLATE NOCASE""",
            (guild_id,),
        ).fetchall()


def get_panel(guild_id: int):
    with db_connect() as db:
        return db.execute(
            """SELECT channel_id, message_id, title, description
               FROM ping_panels WHERE guild_id = ?""",
            (guild_id,),
        ).fetchone()


def save_panel(guild_id: int, channel_id: int, message_id: int, title: str, description: str):
    with db_connect() as db:
        db.execute(
            """INSERT INTO ping_panels (guild_id, channel_id, message_id, title, description)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(guild_id) DO UPDATE SET
                 channel_id=excluded.channel_id,
                 message_id=excluded.message_id,
                 title=excluded.title,
                 description=excluded.description""",
            (guild_id, channel_id, message_id, title, description),
        )
        db.commit()


def normalise_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in value if ch.isalnum())


def resolve_server_emoji(guild: discord.Guild, value: str | None, label: str):
    """Resolve server custom emoji by markup, ID, or name; allow Unicode as fallback."""
    value = (value or "").strip()
    if value:
        match = re.fullmatch(r"<a?:(?P<name>[A-Za-z0-9_]{2,32}):(?P<id>\d{15,22})>", value)
        raw_id = match.group("id") if match else (value if value.isdigit() else None)
        if raw_id:
            found = discord.utils.get(guild.emojis, id=int(raw_id))
            return str(found) if found else None
        by_name = discord.utils.get(guild.emojis, name=value.strip(":"))
        if by_name:
            return str(by_name)
        if value.startswith("<:") or value.startswith("<a:") or value.startswith("<"):
