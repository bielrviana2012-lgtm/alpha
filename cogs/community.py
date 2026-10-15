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
        channel = member.guild.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(embed=make_embed(
                    "👋 Boas-vindas à Family Alpha!",
                    f"Seja bem-vindo(a), {member.mention}! Leia as regras e aproveite a comunidade.",
                ))
            except discord.HTTPException:
                log.exception("Não consegui enviar boas-vindas para %s.", member.id)

    @app_commands.command(name="sugerir", description="Envie uma sugestão para a equipe do servidor.")
    @app_commands.describe(texto="Explique sua sugestão com detalhes.")
    @app_commands.guild_only()
    async def sugerir(self, interaction: discord.Interaction, texto: app_commands.Range[str, 10, 1800]):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Use este comando dentro do servidor.", ephemeral=True)

        channel_id = int(getattr(config, "SUGGESTION_CHANNEL_ID", 0) or 0)
        channel = guild.get_channel(channel_id) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return await interaction.response.send_message(
                "Canal de sugestões não configurado. Confira `SUGGESTION_CHANNEL_ID` no Railway.",
                ephemeral=True,
            )

        embed = make_embed("💡 Nova sugestão", texto)
        embed.add_field(name="Autor", value=f"{interaction.user.mention}\n`{interaction.user}`", inline=False)
        embed.add_field(name="📌 Status", value="🟡 Pendente", inline=True)
        embed.add_field(name="👍 Apoio", value="0", inline=True)
        embed.add_field(name="👎 Não apoio", value="0", inline=True)
        embed.set_footer(text="Sr.Alpha • Sistema de sugestões")

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    "INSERT INTO alpha_suggestions (guild_id, user_id, text, channel_id) VALUES (?, ?, ?, ?)",
                    (guild.id, interaction.user.id, texto, channel.id),
                )
                suggestion_id = cursor.lastrowid
                await db.commit()

            embed.add_field(name="Protocolo", value=f"`#{suggestion_id}`", inline=True)
            message = await channel.send(embed=embed, view=SuggestionView(suggestion_id))
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE alpha_suggestions SET message_id=? WHERE id=?",
                    (message.id, suggestion_id),
                )
                await db.commit()
        except Exception:
            log.exception("Não consegui publicar/salvar a sugestão.")
            return await interaction.followup.send(
                "❌ Não consegui concluir a sugestão. Consulte os logs do Railway.", ephemeral=True
            )

        await interaction.followup.send(
            f"✅ Sua sugestão foi enviada em {channel.mention}! Protocolo: `#{suggestion_id}`",
            ephemeral=True,
        )

    @app_commands.command(name="status_sugestao", description="Atualize o status de uma sugestão.")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.choices(status=[
        app_commands.Choice(name="Em análise", value="Em análise"),
        app_commands.Choice(name="Aprovada", value="Aprovada"),
        app_commands.Choice(name="Recusada", value="Recusada"),
    ])
    async def status_sugestao(
        self,
        interaction: discord.Interaction,
        numero: app_commands.Range[int, 1, 1000000],
        status: app_commands.Choice[str],
        resposta: str = "",
    ):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message(
                "Você precisa da permissão Gerenciar mensagens para alterar sugestões.", ephemeral=True
            )

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "SELECT message_id, channel_id FROM alpha_suggestions WHERE id=? AND guild_id=?",
                (numero, interaction.guild_id),
            )
            row = await cursor.fetchone()
            if not row:
                return await interaction.response.send_message("Sugestão não encontrada.", ephemeral=True)
            message_id, channel_id = row
            await db.execute(
                "UPDATE alpha_suggestions SET status=?, admin_id=?, response=? WHERE id=? AND guild_id=?",
                (status.value, interaction.user.id, resposta.strip()[:1024], numero, interaction.guild_id),
            )
            await db.commit()

        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return await interaction.response.send_message(
                    "O canal da sugestão não está acessível ao bot.", ephemeral=True
                )
        try:
            message = await channel.fetch_message(message_id)
        except (discord.HTTPException, AttributeError):
            return await interaction.response.send_message(
                "Não consegui encontrar a mensagem da sugestão.", ephemeral=True
            )
        if not message.embeds:
            return await interaction.response.send_message(
                "A mensagem da sugestão não contém um embed editável.", ephemeral=True
            )

        embed = message.embeds[0]
        emoji = {"Aprovada": "🟢", "Recusada": "🔴", "Em análise": "🟡"}[status.value]
        status_text = f"{emoji} {status.value}"
        index = next((i for i, field in enumerate(embed.fields) if field.name in ("📌 Status", "Estado")), None)
        if index is None:
            embed.add_field(name="📌 Status", value=status_text, inline=True)
        else:
            embed.set_field_at(index, name="📌 Status", value=status_text, inline=True)

        decision = f"**Responsável:** {interaction.user.mention}\n**Resultado:** {status.value}"
        index = next((i for i, field in enumerate(embed.fields) if field.name == "🛡️ Decisão da equipe"), None)
        if index is None:
            embed.add_field(name="🛡️ Decisão da equipe", value=decision, inline=False)
        else:
            embed.set_field_at(index, name="🛡️ Decisão da equipe", value=decision, inline=False)

        response = resposta.strip()[:1024]
        index = next((i for i, field in enumerate(embed.fields) if field.name == "💬 Resposta da equipe"), None)
        if response:
            if index is None:
                embed.add_field(name="💬 Resposta da equipe", value=response, inline=False)
            else:
                embed.set_field_at(index, name="💬 Resposta da equipe", value=response, inline=False)

        try:
            await message.edit(embed=embed, view=SuggestionView(numero))
        except discord.HTTPException:
            log.exception("Não consegui atualizar o embed da sugestão #%s.", numero)
            return await interaction.response.send_message(
                "Não consegui editar a mensagem no Discord. Confira as permissões do bot.", ephemeral=True
            )

        await interaction.response.send_message(
            f"✅ Sugestão `#{numero}` atualizada para **{status.value}** por {interaction.user.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await init_community_tables()
    await bot.add_cog(Community(bot))
    bot.add_view(SuggestionView())
    log.info("Módulo de comunidade antigo carregado (boas-vindas e sugestões; sem tickets).")
