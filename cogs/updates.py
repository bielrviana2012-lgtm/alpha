import random
import discord

from discord import app_commands
from discord.ext import commands

COR = discord.Color.from_rgb(145, 103, 255)


class SorteioView(discord.ui.LayoutView):
    def __init__(self, duracao_min: int, vencedores: int, titulo: str, descricao: str):
        super().__init__(timeout=duracao_min * 60)
        self.participantes = set()
        self.quantidade_vencedores = vencedores
        self.titulo = titulo
        self.descricao = descricao
        self.message = None
        self.encerrado = False
        self.ganhadores = None
        self._montar_layout()

    def _montar_layout(self):
        self.clear_items()
        container = discord.ui.Container(
            accent_colour=discord.Color.green() if self.encerrado else COR
        )
        container.add_item(discord.ui.TextDisplay(f"# 🎉 {self.titulo}"))
        container.add_item(discord.ui.TextDisplay(self.descricao))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"**👥 Participantes**\n{len(self.participantes)}\n\n"
            f"**🏆 Vencedores**\n{self.quantidade_vencedores}"
        ))
        if self.encerrado:
            result = (
                "**🎊 Ganhadores**\n" + "\n".join(f"🏆 <@{uid}>" for uid in self.ganhadores)
                if self.ganhadores else "**Resultado**\nNão houve participantes."
            )
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay(result))
            container.add_item(discord.ui.TextDisplay("-# Sorteio encerrado • Sr.Alpha"))
        else:
            container.add_item(discord.ui.Separator())
            container.add_item(discord.ui.TextDisplay("Clique no botão abaixo para participar ou cancelar sua participação."))
            container.add_item(discord.ui.TextDisplay("-# Sr.Alpha • Family Alpha"))

        self.add_item(container)
        if not self.encerrado:
            row = discord.ui.ActionRow()
            button = discord.ui.Button(
                label="Participar do sorteio", emoji="🎉",
                style=discord.ButtonStyle.primary,
                custom_id="sr_alpha_sorteio_participar",
            )
            button.callback = self.participar
            row.add_item(button)
            self.add_item(row)

    async def participar(self, interaction: discord.Interaction):
        if self.encerrado:
            return await interaction.response.send_message("Este sorteio já foi encerrado.", ephemeral=True)
        if interaction.user.bot:
            return await interaction.response.send_message("Bots não podem participar.", ephemeral=True)

        if interaction.user.id in self.participantes:
            self.participantes.remove(interaction.user.id)
            mensagem = "Sua participação foi cancelada."
        else:
            self.participantes.add(interaction.user.id)
            mensagem = "Você está participando do sorteio! 🍀"

        self._montar_layout()
        await interaction.response.send_message(mensagem, ephemeral=True)
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def on_timeout(self):
        if self.encerrado:
            return
        self.encerrado = True
        participantes = list(self.participantes)
        self.ganhadores = random.sample(
            participantes, min(self.quantidade_vencedores, len(participantes))
        )
        self._montar_layout()
        if self.message:
            try:
                await self.message.edit(embeds=[], view=self)
                if self.ganhadores:
                    await self.message.channel.send(
                        "🎉 Parabéns aos vencedores: " +
                        ", ".join(f"<@{uid}>" for uid in self.ganhadores)
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
        self, interaction: discord.Interaction, canal: discord.TextChannel,
        titulo: str, descricao: str, versao: str = "1.0.0",
    ):
        layout = discord.ui.LayoutView(timeout=None)
        panel = discord.ui.Container(accent_colour=COR)
        panel.add_item(discord.ui.TextDisplay(f"# ✨ {titulo[:250]}"))
        panel.add_item(discord.ui.TextDisplay(descricao[:4000]))
        panel.add_item(discord.ui.Separator())
        panel.add_item(discord.ui.TextDisplay(f"**📦 Versão**\n{versao[:100]}"))
        panel.add_item(discord.ui.Separator())
        panel.add_item(discord.ui.TextDisplay("-# Sr.Alpha • Atualizações • Family Alpha"))
        layout.add_item(panel)

        try:
            await canal.send(view=layout)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "Não tenho permissão para enviar mensagens nesse canal.", ephemeral=True
            )

        await interaction.response.send_message(
            f"✅ Anúncio publicado em {canal.mention}!", ephemeral=True
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
        self, interaction: discord.Interaction, canal: discord.TextChannel,
        titulo: str, descricao: str,
        duracao_min: app_commands.Range[int, 1, 10080],
        vencedores: app_commands.Range[int, 1, 20] = 1,
    ):
        if len(self.sorteios_ativos) >= 10:
            return await interaction.response.send_message(
                "Já existem 10 sorteios ativos neste processo.", ephemeral=True
            )

        view = SorteioView(duracao_min, vencedores, titulo, descricao)
        try:
            mensagem = await canal.send(view=view)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "Não tenho permissão para enviar mensagens nesse canal.", ephemeral=True
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
            f"🎉 Sorteio criado com sucesso em {canal.mention}!", ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(Updates(bot))
