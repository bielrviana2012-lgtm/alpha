
import discord
from discord import app_commands
from discord.ext import commands


class Updates(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="anunciar_atualizacao",
        description="Anuncia uma atualização do Sr.Alpha."
    )
    @app_commands.describe(
        canal="Canal onde o anúncio será enviado",
        titulo="Título da atualização",
        descricao="Descreva as novidades",
        versao="Versão da atualização (opcional)"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def anunciar_atualizacao(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        titulo: app_commands.Range[str, 1, 100],
        descricao: app_commands.Range[str, 1, 3000],
        versao: str = "1.0.0"
    ):
        embed = discord.Embed(
            title=f"🚀 {titulo}",
            description=descricao,
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow()
        )

        embed.add_field(
            name="📦 Versão",
            value=versao[:100],
            inline=True
        )
        embed.add_field(
            name="🤖 Bot",
            value="Sr.Alpha",
            inline=True
        )
        embed.set_footer(
            text=f"Atualização anunciada por {interaction.user.display_name}"
        )

        try:
            await canal.send(
                content="📢 **NOVA ATUALIZAÇÃO DISPONÍVEL!**",
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none()
            )
            await interaction.response.send_message(
                f"✅ Atualização anunciada em {canal.mention}!",
                ephemeral=True
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Não tenho permissão para enviar mensagens nesse canal.",
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(Updates(bot))
