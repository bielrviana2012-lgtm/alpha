
import random
import asyncio
import discord

from discord import app_commands
from discord.ext import commands


COR = discord.Color.from_rgb(145, 103, 255)


class SorteioView(discord.ui.View):
    def __init__(self, duracao_min: int, vencedores: int, titulo: str):
        super().__init__(timeout=duracao_min * 60)
        self.participantes = set()
        self.quantidade_vencedores = vencedores
        self.titulo = titulo
        self.message = None
        self.encerrado = False

    @discord.ui.button(
        label="Participar do sorteio",
        emoji="🎉",
        style=discord.ButtonStyle.primary,
        custom_id="sr_alpha_sorteio_participar",
    )
    async def participar(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        if self.encerrado:
            return await interaction.response.send_message(
                "Este sorteio já foi encerrado.",
                ephemeral=True,
            )

        if interaction.user.bot:
            return await interaction.response.send_message(
                "Bots não podem participar.",
                ephemeral=True,
            )

        if interaction.user.id in self.participantes:
            self.participantes.remove(interaction.user.id)
            mensagem = "Sua participação foi cancelada."
        else:
            self.participantes.add(interaction.user.id)
            mensagem = "Você está participando do sorteio! 🍀"

        await interaction.response.send_message(
            mensagem,
            ephemeral=True,
        )

        if self.message:
            try:
                await self.message.edit(
                    embed=self.criar_embed(),
                    view=self,
                )
            except discord.HTTPException:
                pass

    def criar_embed(self, encerrado=False, ganhadores=None):
        embed = discord.Embed(
            title=f"🎉 {self.titulo}",
            color=discord.Color.green() if encerrado else COR,
        )

        embed.description = (
            "O sorteio foi encerrado!"
            if encerrado
            else "Clique no botão abaixo para participar!"
        )

        embed.add_field(
            name="👥 Participantes",
            value=str(len(self.participantes)),
            inline=True,
        )
        embed.add_field(
            name="🏆 Vencedores",
            value=str(self.quantidade_vencedores),
            inline=True,
        )

        if encerrado:
            if ganhadores:
                embed.add_field(
                    name="🎊 Ganhadores",
                    value="\n".join(
                        f"🏆 <@{uid}>" for uid in ganhadores
                    ),
                    inline=False,
                )
            else:
                embed.add_field(
                    name="Resultado",
                    value="Não houve participantes.",
                    inline=False,
                )

        embed.set_footer(text="Sr.Alpha • Family Alpha")
        return embed

    async def on_timeout(self):
        if self.encerrado:
            return

        self.encerrado = True
        participantes = list(self.participantes)

        ganhadores = random.sample(
            participantes,
            min(self.quantidade_vencedores, len(participantes)),
        )

        for item in self.children:
            item.disabled = True

        if self.message:
            try:
                await self.message.edit(
                    embed=self.criar_embed(
                        encerrado=True,
                        ganhadores=ganhadores,
                    ),
                    view=self,
                )

                if ganhadores:
                    await self.message.channel.send(
                        "🎉 Parabéns aos vencedores: "
                        + ", ".join(f"<@{uid}>" for uid in ganhadores)
                    )
            except discord.HTTPException:
                pass


class Updates(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sorteios_ativos = set()

    @app_commands.command(
        name="anunciar_atualizacao",
        description="Publica um anúncio de atualização do Sr.Alpha.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.describe(
        canal="Canal onde o anúncio será publicado",
        titulo="Título do anúncio",
        descricao="Descrição da atualização",
        versao="Versão do bot (opcional)",
    )
    async def anunciar_atualizacao(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        titulo: str,
        descricao: str,
        versao: str = "1.0.0",
    ):
        embed = discord.Embed(
            title=f"✨ {titulo}",
            description=descricao,
            color=COR,
            timestamp=discord.utils.utcnow(),
        )
        embed.set_author(
            name="Sr.Alpha • Atualizações",
            icon_url=self.bot.user.display_avatar.url
            if self.bot.user else None,
        )
        embed.add_field(
            name="📦 Versão",
            value=versao,
            inline=True,
        )
        embed.set_footer(text="Family Alpha")

        try:
            await canal.send(embed=embed)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "Não tenho permissão para enviar mensagens nesse canal.",
                ephemeral=True,
            )

        await interaction.response.send_message(
            f"✅ Anúncio publicado em {canal.mention}!",
            ephemeral=True,
        )

    @app_commands.command(
        name="sorteio",
        description="Cria um sorteio interativo no servidor.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.guild_only()
    @app_commands.describe(
        canal="Canal onde o sorteio será publicado",
        titulo="Prêmio ou título do sorteio",
        descricao="Regras e detalhes do sorteio",
        duracao_min="Duração em minutos (1 a 10080)",
        vencedores="Quantidade de vencedores (1 a 20)",
    )
    async def sorteio(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        titulo: str,
        descricao: str,
        duracao_min: app_commands.Range[int, 1, 10080],
        vencedores: app_commands.Range[int, 1, 20] = 1,
    ):
        if len(self.sorteios_ativos) >= 10:
            return await interaction.response.send_message(
                "Já existem 10 sorteios ativos neste processo.",
                ephemeral=True,
            )

        view = SorteioView(duracao_min, vencedores, titulo)
        embed = view.criar_embed()
        embed.insert_field_at(
            0,
            name="🎁 Prêmio e detalhes",
            value=descricao,
            inline=False,
        )
        embed.add_field(
            name="⏱️ Duração",
            value=f"{duracao_min} minuto(s)",
            inline=True,
        )

        try:
            mensagem = await canal.send(embed=embed, view=view)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "Não tenho permissão para enviar mensagens nesse canal.",
                ephemeral=True,
            )

        view.message = mensagem
        self.sorteios_ativos.add(mensagem.id)

        async def acompanhar_sorteio():
            try:
                await view.wait()
            finally:
                self.sorteios_ativos.discard(mensagem.id)

        self.bot.loop.create_task(acompanhar_sorteio())

        await interaction.response.send_message(
            f"🎉 Sorteio criado com sucesso em {canal.mention}!",
            ephemeral=True,
        )


async def setup(bot):
    await bot.add_cog(Updates(bot))
