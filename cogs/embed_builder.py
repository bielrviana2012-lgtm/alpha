"""Comando administrativo para criar painéis personalizados com Components V2."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

from cogs.community import get_ticket_categories, TicketCategorySelect

log = logging.getLogger("Sr.Alpha.EmbedBuilder")


async def open_ticket_callback(interaction: discord.Interaction):
    if interaction.guild is None:
        return await interaction.response.send_message(
            "Este botão só funciona dentro de um servidor.", ephemeral=True
        )
    await interaction.response.defer(ephemeral=True, thinking=True)
    categories = await get_ticket_categories(interaction.guild.id)
    layout = discord.ui.LayoutView(timeout=180)
    panel = discord.ui.Container(accent_colour=discord.Color.from_rgb(145, 103, 255))
    panel.add_item(discord.ui.TextDisplay("# 🎫 Abrir um ticket"))
    panel.add_item(discord.ui.TextDisplay(
        "Selecione abaixo a categoria que melhor corresponde à sua solicitação."
    ))
    layout.add_item(panel)
    row = discord.ui.ActionRow()
    row.add_item(TicketCategorySelect(interaction.guild.id, categories))
    layout.add_item(row)
    await interaction.followup.send(view=layout, ephemeral=True)


class TicketShortcutView(discord.ui.LayoutView):
    """Botão persistente que abre o seletor de categorias de ticket."""

    def __init__(self):
        super().__init__(timeout=None)
        self.add_ticket_button(self)

    @staticmethod
    def add_ticket_button(layout: discord.ui.LayoutView):
        row = discord.ui.ActionRow()
        button = discord.ui.Button(
            label="Abrir ticket", emoji="🎫", style=discord.ButtonStyle.primary,
            custom_id="alpha_embed_open_ticket",
        )
        button.callback = open_ticket_callback
        row.add_item(button)
        layout.add_item(row)


class EmbedBuilder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="criar_embed",
        description="Cria uma mensagem personalizada usando Components V2.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        titulo="Título que aparecerá no painel",
        descricao="Texto principal do painel",
        canal="Canal onde o painel será publicado",
        cor="Cor hexadecimal, por exemplo #9167FF",
        campo1_titulo="Título opcional do primeiro campo",
        campo1_texto="Texto opcional do primeiro campo",
        campo2_titulo="Título opcional do segundo campo",
        campo2_texto="Texto opcional do segundo campo",
        campo3_titulo="Título opcional do terceiro campo",
        campo3_texto="Texto opcional do terceiro campo",
        botao_ticket="Adiciona um botão para abrir ticket usando as categorias configuradas",
    )
    async def criar_embed(
        self,
        interaction: discord.Interaction,
        titulo: app_commands.Range[str, 1, 200],
        descricao: app_commands.Range[str, 1, 3500],
        canal: discord.TextChannel,
        cor: app_commands.Range[str, 4, 7] = "#9167FF",
        campo1_titulo: app_commands.Range[str, 1, 100] | None = None,
        campo1_texto: app_commands.Range[str, 1, 1000] | None = None,
        campo2_titulo: app_commands.Range[str, 1, 100] | None = None,
        campo2_texto: app_commands.Range[str, 1, 1000] | None = None,
        campo3_titulo: app_commands.Range[str, 1, 100] | None = None,
        campo3_texto: app_commands.Range[str, 1, 1000] | None = None,
        botao_ticket: bool = False,
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Este comando só pode ser usado dentro de um servidor.",
                ephemeral=True,
            )
            return

        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "Apenas administradores podem criar painéis.",
                ephemeral=True,
            )
            return

        bot_member = interaction.guild.me
        if bot_member is None or not canal.permissions_for(bot_member).send_messages:
            await interaction.response.send_message(
                f"Não tenho permissão para enviar mensagens em {canal.mention}.",
                ephemeral=True,
            )
            return

        hex_color = cor.strip().removeprefix("#")
        if len(hex_color) not in (3, 6) or any(c not in "0123456789abcdefABCDEF" for c in hex_color):
            await interaction.response.send_message(
                "Cor inválida. Use um código hexadecimal como #9167FF.",
                ephemeral=True,
            )
            return

        if len(hex_color) == 3:
            hex_color = "".join(char * 2 for char in hex_color)

        accent = discord.Color(int(hex_color, 16))
        fields = [
            (campo1_titulo, campo1_texto),
            (campo2_titulo, campo2_texto),
            (campo3_titulo, campo3_texto),
        ]

        for field_title, field_text in fields:
            if bool(field_title) != bool(field_text):
                await interaction.response.send_message(
                    "Para cada campo, preencha o título e o texto juntos.",
                    ephemeral=True,
                )
                return

        layout = discord.ui.LayoutView(timeout=None)
        container = discord.ui.Container(accent_colour=accent)
        container.add_item(discord.ui.TextDisplay(f"# {titulo}"))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(descricao))

        for field_title, field_text in fields:
            if field_title and field_text:
                container.add_item(discord.ui.Separator())
                container.add_item(discord.ui.TextDisplay(f"**{field_title}**\n{field_text}"))

        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay("-# Sr.Alpha • Family Alpha"))
        layout.add_item(container)
        if botao_ticket:
            TicketShortcutView.add_ticket_button(layout)

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            await canal.send(view=layout, allowed_mentions=discord.AllowedMentions.none())
            await interaction.followup.send(
                f"Painel publicado em {canal.mention} usando Components V2.",
                ephemeral=True,
            )
            log.info(
                "Painel Components V2 publicado por %s em #%s (%s).",
                interaction.user,
                canal.name,
                canal.id,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                f"Não tenho permissão para publicar o painel em {canal.mention}.",
                ephemeral=True,
            )
        except discord.HTTPException:
            log.exception("Falha ao publicar painel Components V2.")
            await interaction.followup.send(
                "Não consegui publicar o painel. Confira as permissões do bot e tente novamente.",
                ephemeral=True,
            )


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedBuilder(bot))
    bot.add_view(TicketShortcutView())
