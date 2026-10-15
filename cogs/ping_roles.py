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
OPTIONS_PER_PAGE = 25  # Limite do Discord por menu, não limite total de pings.


def db_connect():
    return sqlite3.connect(DB_PATH)


def init_tables():
    with db_connect() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS ping_roles (
            guild_id INTEGER NOT NULL, name TEXT NOT NULL, role_id INTEGER NOT NULL,
            emoji TEXT NOT NULL DEFAULT '🔔', PRIMARY KEY (guild_id, name),
            UNIQUE (guild_id, role_id))""")
        db.execute("""CREATE TABLE IF NOT EXISTS ping_panels (
            guild_id INTEGER PRIMARY KEY, channel_id INTEGER NOT NULL,
            message_id INTEGER NOT NULL, title TEXT NOT NULL, description TEXT NOT NULL)""")
        db.commit()


def get_pings(guild_id: int):
    with db_connect() as db:
        return db.execute("""SELECT name, role_id, emoji FROM ping_roles
            WHERE guild_id = ? ORDER BY name COLLATE NOCASE""", (guild_id,)).fetchall()


def get_panel(guild_id: int):
    with db_connect() as db:
        return db.execute("SELECT channel_id, message_id, title, description FROM ping_panels WHERE guild_id = ?", (guild_id,)).fetchone()


def normalise_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in value if ch.isalnum())


def resolve_server_emoji(guild: discord.Guild, value: str | None, label: str):
    """Accepts emoji name, emoji ID, custom emoji markup, or Unicode. Defaults to a server emoji."""
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
        if value.startswith("<:") or value.startswith("<a:"):
            return None
        # A regular Unicode emoji is allowed, but custom emoji are preferred when omitted.
        if not value.startswith("<"):
            return value
        return None

    wanted = normalise_name(label)
    if wanted:
        exact = next((e for e in guild.emojis if normalise_name(e.name) == wanted), None)
        if exact:
            return str(exact)
        partial = next((e for e in guild.emojis if normalise_name(e.name) in wanted or wanted in normalise_name(e.name)), None)
        if partial:
            return str(partial)
    return str(guild.emojis[0]) if guild.emojis else "🔔"


def make_embed(guild_id: int, title: str, description: str):
    pings = get_pings(guild_id)
    embed = discord.Embed(title=f"🔔・{title}"[:256], description=description[:3500], color=PURPLE)
    embed.add_field(name="🔔 Notificações disponíveis", value=f"**{len(pings)}** opções de ping cadastradas.", inline=False)
    embed.add_field(name="✨ Como escolher", value=(
        "Clique em **Selecionar seus pings** e use o menu privado.\n"
        "Se houver muitas opções, navegue pelas páginas com os botões **Anterior** e **Próxima**.\n"
        "Suas escolhas ficam salvas nos cargos e podem ser alteradas quando quiser."
    ), inline=False)
    embed.set_footer(text="Sr.Alpha • Family Alpha")
    return embed


class PingSelect(discord.ui.Select):
    def __init__(self, cog, member: discord.Member, pings, page: int):
        self.cog = cog
        self.guild_id = member.guild.id
