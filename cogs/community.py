import logging
import re
from typing import Optional

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

import config
from database import DB_PATH

log = logging.getLogger("Sr.Alpha.Community")
PURPLE = discord.Color.from_rgb(145, 103, 255)


# =========================================================
# BANCO DE DADOS / MIGRAÇÕES
# =========================================================

async def _ensure_columns(db, table: str, columns: dict):
    cursor = await db.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in await cursor.fetchall()}
    for column, definition in columns.items():
        if column not in existing:
            await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


async def init_community_tables():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS ticket_settings (
            guild_id INTEGER PRIMARY KEY,
            panel_channel_id INTEGER,
            panel_message_id INTEGER,
            panel_title TEXT NOT NULL DEFAULT 'Central de Atendimento',
            panel_description TEXT NOT NULL DEFAULT 'Escolha uma categoria no menu abaixo.',
            panel_color INTEGER NOT NULL DEFAULT 9533439,
            panel_image TEXT NOT NULL DEFAULT '',
            hours_text TEXT NOT NULL DEFAULT '',
            notices_text TEXT NOT NULL DEFAULT '',
            rating_channel_id INTEGER
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS ticket_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            emoji TEXT NOT NULL DEFAULT '🎫',
            description TEXT NOT NULL DEFAULT '',
            staff_role_id INTEGER NOT NULL,
            discord_category_id INTEGER,
            welcome_text TEXT NOT NULL DEFAULT 'Explique como podemos ajudar.',
            UNIQUE(guild_id, name)
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS ticket_records (
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
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS tickets (
            channel_id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'open'
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS alpha_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            channel_id INTEGER NOT NULL,
            message_id INTEGER,
            status TEXT NOT NULL DEFAULT 'Pendente',
            admin_id INTEGER,
            response TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )""")
        await _ensure_columns(db, "ticket_settings", {
            "panel_channel_id": "INTEGER", "panel_message_id": "INTEGER",
            "panel_title": "TEXT NOT NULL DEFAULT 'Central de Atendimento'",
            "panel_description": "TEXT NOT NULL DEFAULT 'Escolha uma categoria no menu abaixo.'",
            "panel_color": "INTEGER NOT NULL DEFAULT 9533439",
            "panel_image": "TEXT NOT NULL DEFAULT ''", "hours_text": "TEXT NOT NULL DEFAULT ''",
            "notices_text": "TEXT NOT NULL DEFAULT ''", "rating_channel_id": "INTEGER",
        })
        await _ensure_columns(db, "ticket_categories", {
            "emoji": "TEXT NOT NULL DEFAULT '🎫'", "description": "TEXT NOT NULL DEFAULT ''",
            "staff_role_id": "INTEGER NOT NULL DEFAULT 0", "discord_category_id": "INTEGER",
            "welcome_text": "TEXT NOT NULL DEFAULT 'Explique como podemos ajudar.'",
