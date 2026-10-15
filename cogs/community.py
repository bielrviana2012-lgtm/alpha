import logging
import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

import config
from database import DB_PATH

log = logging.getLogger("Sr.Alpha.Community")
PURPLE = discord.Color.from_rgb(145, 103, 255)


# =========================================================
# BANCO DE DADOS — SUGESTÕES
# =========================================================

async def init_community_tables():
    """Cria/atualiza somente as tabelas usadas pelo sistema de comunidade antigo."""
    async with aiosqlite.connect(DB_PATH) as db:
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
        cursor = await db.execute("PRAGMA table_info(alpha_suggestions)")
        columns = {row[1] for row in await cursor.fetchall()}
        additions = {
            "guild_id": "INTEGER NOT NULL DEFAULT 0",
            "user_id": "INTEGER NOT NULL DEFAULT 0",
            "text": "TEXT NOT NULL DEFAULT ''",
            "channel_id": "INTEGER NOT NULL DEFAULT 0",
            "message_id": "INTEGER",
            "status": "TEXT NOT NULL DEFAULT 'Pendente'",
            "admin_id": "INTEGER",
            "response": "TEXT NOT NULL DEFAULT ''",
            "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
        }
        for name, definition in additions.items():
            if name not in columns:
                await db.execute(f"ALTER TABLE alpha_suggestions ADD COLUMN {name} {definition}")
        await db.commit()
    log.info("Tabelas antigas de comunidade/sugestões verificadas.")


# =========================================================
# EMBEDS E UTILITÁRIOS
# =========================================================

def make_embed(title: str, description: str = "", color=PURPLE):
    embed = discord.Embed(title=title[:256], description=description[:4096], color=color)
    embed.set_footer(text="Sr.Alpha • Family Alpha")
    return embed


class SuggestionView(discord.ui.View):
    """Botões de apoio da mensagem de sugestão."""
    def __init__(self, suggestion_id: int = 0):
        super().__init__(timeout=None)
        self.suggestion_id = suggestion_id

    @discord.ui.button(label="Apoiar", emoji="👍", style=discord.ButtonStyle.success, custom_id="sr_alpha:suggestion_yes")
    async def support(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.message.add_reaction("👍")
        except discord.HTTPException:
            log.exception("Não consegui adicionar reação de apoio.")
        await interaction.response.send_message("👍 Obrigado por apoiar a sugestão!", ephemeral=True)

    @discord.ui.button(label="Não apoiar", emoji="👎", style=discord.ButtonStyle.secondary, custom_id="sr_alpha:suggestion_no")
    async def oppose(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.message.add_reaction("👎")
        except discord.HTTPException:
            log.exception("Não consegui adicionar reação contrária.")
        await interaction.response.send_message("👎 Seu voto foi registrado!", ephemeral=True)


# =========================================================
# COMANDOS ANTIGOS DA COMMUNITY — SEM SISTEMA DE TICKETS
# =========================================================

class Community(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        channel_id = int(getattr(config, "WELCOME_CHANNEL_ID", 0) or 0)
