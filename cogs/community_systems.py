import logging

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from database import DB_PATH
from cogs.ui_v2 import make_v2_panel


logger = logging.getLogger("Rei Dado")


class CommunitySystems(commands.Cog):
    """Mantém somente o comando de consulta aos logs de moderação."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="mod_logs", description="Consulte os registros recentes de moderação")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def mod_logs(
        self,
        interaction: discord.Interaction,
        membro: discord.Member | None = None,
    ):
        # Esta deve ser a primeira operação de rede do comando.
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except discord.NotFound as error:
            # 10062 significa que o token da interação já expirou/é inválido.
            logger.warning(
                "Discord rejeitou a interação de /mod_logs antes do defer (código %s).",
                getattr(error, "code", "desconhecido"),
            )
            return
        except discord.HTTPException:
            logger.exception("Falha ao confirmar a interação de /mod_logs.")
            return

        try:
            async with aiosqlite.connect(DB_PATH, timeout=10) as db:
                if membro:
                    cursor = await db.execute(
                        "SELECT user_id, moderator_id, reason, created_at "
                        "FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10",
                        (interaction.guild_id, membro.id),
                    )
                else:
                    cursor = await db.execute(
                        "SELECT user_id, moderator_id, reason, created_at "
                        "FROM warnings WHERE guild_id=? ORDER BY id DESC LIMIT 10",
                        (interaction.guild_id,),
                    )
                rows = await cursor.fetchall()

            if not rows:
                description = (
                    f"Não há registros de avisos para {membro.mention}."
                    if membro else "Não há registros de avisos para mostrar."
                )
            else:
                description = "\n".join(
                    f"• <@{uid}> — {discord.utils.escape_markdown(str(reason or 'Sem motivo'))[:120]}\n"
                    f"  Responsável: <@{moderator_id}> · {created_at}"
                    for uid, moderator_id, reason, created_at in rows
                )

            await interaction.edit_original_response(
                view=make_v2_panel("🛡️ Registros de moderação", description)
            )
        except (aiosqlite.Error, discord.HTTPException):
            logger.exception("Falha ao consultar ou exibir os logs de moderação.")
            try:
                await interaction.edit_original_response(
                    content="Não foi possível consultar os logs agora. Tente novamente em instantes.",
                    view=None,
                )
            except discord.HTTPException:
                logger.warning("Não foi possível enviar a mensagem de falha de /mod_logs.")


async def setup(bot):
    await bot.add_cog(CommunitySystems(bot))
