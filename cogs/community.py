import logging
import re
import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

import config
from database import DB_PATH

log = logging.getLogger("Sr.Alpha.Community")
PURPLE = discord.Color.from_rgb(145, 103, 255)

# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------

async def init_community_tables():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_settings (
                guild_id INTEGER PRIMARY KEY,
                panel_channel_id INTEGER,
                panel_message_id INTEGER,
                panel_title TEXT NOT NULL DEFAULT 'Central de Atendimento',
                panel_description TEXT NOT NULL DEFAULT 'Escolha no menu abaixo a categoria para a qual deseja atendimento.',
                panel_color INTEGER NOT NULL DEFAULT 9533439,
                panel_image TEXT NOT NULL DEFAULT '',
                hours_text TEXT NOT NULL DEFAULT '',
                notices_text TEXT NOT NULL DEFAULT '',
                rating_channel_id INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                emoji TEXT NOT NULL DEFAULT '🎫',
                description TEXT NOT NULL DEFAULT '',
                staff_role_id INTEGER NOT NULL,
                discord_category_id INTEGER,
                welcome_text TEXT NOT NULL DEFAULT 'Explique como podemos ajudar.',
                UNIQUE(guild_id, name)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_records (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                category_id INTEGER,
                attendant_id INTEGER,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                closed_at TEXT,
                rating INTEGER,
                rating_comment TEXT,
                rating_message_id INTEGER
            )
        """)
        # Legacy compatibility: preserve the old tickets table if it exists.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open'
            )
        """)
        await db.commit()


async def get_ticket_settings(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM ticket_settings WHERE guild_id=?", (guild_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_ticket_categories(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM ticket_categories WHERE guild_id=? ORDER BY id",
            (guild_id,),
        )
        return [dict(row) for row in await cur.fetchall()]


async def get_ticket_record(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
