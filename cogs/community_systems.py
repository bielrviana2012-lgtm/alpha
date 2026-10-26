import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from database import DB_PATH
from cogs.ui_v2 import make_v2_panel


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
        # Responder imediatamente para evitar expiração da interação enquanto o banco é consultado.
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            async with aiosqlite.connect(DB_PATH, timeout=10) as db:
                if membro:
                    rows = await (await db.execute(
                        "SELECT user_id, moderator_id, reason, created_at "
                        "FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10",
                        (interaction.guild_id, membro.id),
                    )).fetchall()
                else:
                    rows = await (await db.execute(
                        "SELECT user_id, moderator_id, reason, created_at "
                        "FROM warnings WHERE guild_id=? ORDER BY id DESC LIMIT 10",
                        (interaction.guild_id,),
                    )).fetchall()

            if not rows:
                description = (
                    f"Não há registros de avisos para {membro.mention}."
                    if membro else "Não há registros de avisos para mostrar."
                )
            else:
                description = "\\n".join(
                    f"• <@{uid}> — {discord.utils.escape_markdown(str(reason or 'Sem motivo'))[:120]}\\n"
                    f"  Responsável: <@{moderator_id}> · {created_at}"
                    for uid, moderator_id, reason, created_at in rows
                )

            await interaction.edit_original_response(
                view=make_v2_panel("🛡️ Registros de moderação", description)
            )
        except (aiosqlite.Error, discord.HTTPException):
            # Evita deixar a interação sem resposta se houver falha de banco ou API.
            try:
                await interaction.edit_original_response(
                    content="Não foi possível consultar os logs agora. Tente novamente em instantes.",
                    view=None,
                )
            except discord.HTTPException:
                pass


async def setup(bot):
    await bot.add_cog(CommunitySystems(bot))
