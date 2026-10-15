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
    """Encontra emojis personalizados do servidor ou aceita emoji Unicode."""
    value = (value or "").strip()

    if value:
        match = re.fullmatch(
            r"<a?:(?P<name>[A-Za-z0-9_]{2,32}):(?P<id>\d{15,22})>",
            value,
        )

        raw_id = match.group("id") if match else (
            value if value.isdigit() else None
        )

        if raw_id:
            found = discord.utils.get(guild.emojis, id=int(raw_id))
            return str(found) if found else None

        by_name = discord.utils.get(guild.emojis, name=value.strip(":"))
        if by_name:
            return str(by_name)

        if value.startswith("<"):
            return None

        return value

    wanted = normalise_name(label)

    if wanted:
        exact = next(
            (emoji for emoji in guild.emojis
             if normalise_name(emoji.name) == wanted),
            None,
        )
        if exact:
            return str(exact)

        partial = next(
            (emoji for emoji in guild.emojis
             if normalise_name(emoji.name) in wanted
             or wanted in normalise_name(emoji.name)),
            None,
        )
        if partial:
            return str(partial)

    return str(guild.emojis[0]) if guild.emojis else "🔔"
class PingRoles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id != TARGET_GUILD_ID:
            await interaction.response.send_message(
                "Este comando só pode ser usado no servidor Family Alpha.",
                ephemeral=True,
            )
            return False
        return True

    @app_commands.command(
        name="adicionar_ping",
        description="Adiciona um cargo ao painel de notificações.",
    )
    @app_commands.describe(
        nome="Nome para identificar o ping",
        cargo="Cargo que os membros poderão selecionar",
        emoji="Emoji do servidor, ID ou emoji Unicode (opcional)",
    )
    @app_commands.default_permissions(manage_roles=True)
    async def adicionar_ping(
        self,
        interaction: discord.Interaction,
        nome: str,
        cargo: discord.Role,
        emoji: str = "",
    ):
        guild = interaction.guild

        if guild is None or guild.id != TARGET_GUILD_ID:
            await interaction.response.send_message(
                "Servidor não permitido.", ephemeral=True
            )
            return

        nome = nome.strip()
        if not nome or len(nome) > 80:
            await interaction.response.send_message(
                "O nome deve ter entre 1 e 80 caracteres.",
                ephemeral=True,
            )
            return

        if cargo.is_default() or cargo.managed:
            await interaction.response.send_message(
                "Escolha um cargo normal que possa ser atribuído a membros.",
                ephemeral=True,
            )
            return

        bot_member = guild.me
        if bot_member is None or cargo >= bot_member.top_role:
            await interaction.response.send_message(
                "Meu cargo precisa estar acima do cargo selecionado.",
                ephemeral=True,
            )
            return

        emoji_value = resolve_server_emoji(guild, emoji, nome)
        if emoji_value is None:
            await interaction.response.send_message(
                "Não encontrei esse emoji neste servidor. Confira o nome ou ID.",
                ephemeral=True,
            )
            return

        try:
            with db_connect() as db:
                db.execute(
                    """INSERT INTO ping_roles (guild_id, name, role_id, emoji)
                       VALUES (?, ?, ?, ?)""",
                    (guild.id, nome, cargo.id, emoji_value),
                )
                db.commit()
        except sqlite3.IntegrityError:
            await interaction.response.send_message(
                "Esse nome ou cargo já está cadastrado nos pings.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"✅ Ping **{nome}** cadastrado com sucesso para {cargo.mention}!",
            ephemeral=True,
        )

    @app_commands.command(
        name="remover_ping",
        description="Remove um cargo do painel de notificações.",
    )
    @app_commands.describe(nome="Nome exato do ping cadastrado")
    @app_commands.default_permissions(manage_roles=True)
    async def remover_ping(
        self, interaction: discord.Interaction, nome: str
    ):
        guild = interaction.guild
        if guild is None or guild.id != TARGET_GUILD_ID:
            await interaction.response.send_message(
                "Servidor não permitido.", ephemeral=True
            )
            return

        with db_connect() as db:
            cursor = db.execute(
                "DELETE FROM ping_roles WHERE guild_id = ? AND name = ? COLLATE NOCASE",
                (guild.id, nome.strip()),
            )
            db.commit()

        if cursor.rowcount == 0:
            await interaction.response.send_message(
                "Não encontrei um ping com esse nome.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"✅ Ping **{nome}** removido do cadastro.",
            ephemeral=True,
        )

    @app_commands.command(
        name="listar_pings",
        description="Lista os cargos cadastrados no sistema de pings.",
    )
    async def listar_pings(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None or guild.id != TARGET_GUILD_ID:
            await interaction.response.send_message(
                "Servidor não permitido.", ephemeral=True
            )
            return

        pings = get_pings(guild.id)
        if not pings:
            await interaction.response.send_message(
                "Ainda não há cargos cadastrados. Use `/adicionar_ping`.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🔔 Cargos de ping cadastrados",
            color=PURPLE,
        )
        lines = []
        for name, role_id, emoji in pings:
            role = guild.get_role(role_id)
            if role is not None:
                lines.append(f"{emoji} **{name}** — {role.mention}")
            else:
                lines.append(f"{emoji} **{name}** — cargo não encontrado")

        # Evita ultrapassar o limite de caracteres de um embed.
        chunk = ""
        fields_added = 0
        for line in lines:
            if len(chunk) + len(line) + 1 > 1000:
                embed.add_field(
                    name=f"Lista {fields_added + 1}",
                    value=chunk,
                    inline=False,
                )
                fields_added += 1
                chunk = ""
            chunk += line + "\n"

        if chunk:
            embed.add_field(
                name=f"Lista {fields_added + 1}",
                value=chunk,
                inline=False,
            )

        embed.set_footer(text=f"Total: {len(pings)} cargos")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(
        name="painel_pings",
        description="Publica o painel para os membros escolherem seus pings.",
    )
    @app_commands.describe(
        titulo="Título do painel",
        descricao="Texto de instrução exibido no painel",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def painel_pings(
        self,
        interaction: discord.Interaction,
        titulo: str = "Escolha seus pings",
        descricao: str = "Selecione os cargos de notificações que deseja receber.",
    ):
        guild = interaction.guild
        channel = interaction.channel

        if guild is None or guild.id != TARGET_GUILD_ID:
            await interaction.response.send_message(
                "Servidor não permitido.", ephemeral=True
            )
            return

        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message(
                "Use este comando em um canal de texto.",
                ephemeral=True,
            )
            return

        pings = get_pings(guild.id)
        if not pings:
            await interaction.response.send_message(
                "Cadastre pelo menos um cargo usando `/adicionar_ping` primeiro.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title=f"🔔・{titulo[:240]}",
            description=descricao[:3500],
            color=PURPLE,
        )
        embed.add_field(
            name="Notificações disponíveis",
            value=f"Há **{len(pings)}** cargos cadastrados.",
            inline=False,
        )
        embed.add_field(
            name="Como usar",
            value=(
                "Clique em **Selecionar seus pings** para abrir seu menu privado. "
                "Se houver mais de 25 cargos, use os botões para navegar pelas páginas."
            ),
            inline=False,
        )
        embed.set_footer(text="Sr.Alpha • Family Alpha")

        # PingPanelView e PingSelectView devem existir no arquivo para
        # oferecer o menu interativo e a navegação entre páginas.
        view_class = globals().get("PingPanelView")
        if view_class is None:
            await interaction.response.send_message(
                "O menu interativo ainda não está definido neste arquivo. "
                "É necessário adicionar PingPanelView e PingSelectView.",
                ephemeral=True,
            )
            return

        message = await channel.send(embed=embed, view=view_class(self))
        save_panel(
            guild.id, channel.id, message.id, titulo[:240], descricao[:3500]
        )

        await interaction.response.send_message(
            f"✅ Painel publicado em {channel.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    init_tables()
    await bot.add_cog(PingRoles(bot))

