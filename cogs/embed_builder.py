
"""Comando para criar painéis personalizados usando Components V2."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("Sr.Alpha.EmbedBuilder")

PURPLE = discord.Color.from_rgb(145, 103, 255)
MAX_FIELDS = 10
MAX_TOTAL_TEXT = 3800


class EmbedBuilder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="criar_embed",
        description="Cria um painel personalizado com até 10 campos.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        titulo="Título do painel",
        descricao="Descrição principal do painel",
        canal="Canal onde o painel será enviado",
        cor="Cor hexadecimal, exemplo: #9167FF",
        campo1_titulo="Título do campo 1",
        campo1_descricao="Descrição do campo 1",
        campo2_titulo="Título do campo 2",
        campo2_descricao="Descrição do campo 2",
        campo3_titulo="Título do campo 3",
        campo3_descricao="Descrição do campo 3",
        campo4_titulo="Título do campo 4",
        campo4_descricao="Descrição do campo 4",
        campo5_titulo="Título do campo 5",
        campo5_descricao="Descrição do campo 5",
        campo6_titulo="Título do campo 6",
        campo6_descricao="Descrição do campo 6",
        campo7_titulo="Título do campo 7",
        campo7_descricao="Descrição do campo 7",
        campo8_titulo="Título do campo 8",
        campo8_descricao="Descrição do campo 8",
        campo9_titulo="Título do campo 9",
        campo9_descricao="Descrição do campo 9",
        campo10_titulo="Título do campo 10",
        campo10_descricao="Descrição do campo 10",
    )
    async def criar_embed(
        self,
        interaction: discord.Interaction,
        titulo: app_commands.Range[str, 1, 200],
        descricao: app_commands.Range[str, 1, 2000],
        canal: discord.TextChannel,
        cor: str = "#9167FF",
        campo1_titulo: str = None,
        campo1_descricao: str = None,
        campo2_titulo: str = None,
        campo2_descricao: str = None,
        campo3_titulo: str = None,
        campo3_descricao: str = None,
        campo4_titulo: str = None,
        campo4_descricao: str = None,
        campo5_titulo: str = None,
        campo5_descricao: str = None,
        campo6_titulo: str = None,
        campo6_descricao: str = None,
        campo7_titulo: str = None,
        campo7_descricao: str = None,
        campo8_titulo: str = None,
        campo8_descricao: str = None,
        campo9_titulo: str = None,
        campo9_descricao: str = None,
        campo10_titulo: str = None,
        campo10_descricao: str = None,
    ):
        # Verifica se o comando foi usado dentro de um servidor.
        if interaction.guild is None:
            await interaction.response.send_message(
                "❌ Este comando só pode ser usado dentro de um servidor.",
                ephemeral=True,
            )
            return

        # Verifica as permissões de quem executou o comando.
        if not interaction.user.guild_permissions.administrator:
            await interaction.response.send_message(
                "❌ Você precisa ser administrador para usar este comando.",
                ephemeral=True,
            )
            return

        # Verifica a cor hexadecimal.
        cor = cor.strip().removeprefix("#")

        if (
            len(cor) not in (3, 6)
            or any(char not in "0123456789abcdefABCDEF" for char in cor)
        ):
            await interaction.response.send_message(
                "❌ Cor inválida. Use um hexadecimal como `#9167FF`.",
                ephemeral=True,
            )
            return

        if len(cor) == 3:
            cor = "".join(char * 2 for char in cor)

        accent = discord.Color(int(cor, 16))

        # Organiza os campos separados.
        campos_recebidos = [
            (campo1_titulo, campo1_descricao),
            (campo2_titulo, campo2_descricao),
            (campo3_titulo, campo3_descricao),
            (campo4_titulo, campo4_descricao),
            (campo5_titulo, campo5_descricao),
            (campo6_titulo, campo6_descricao),
            (campo7_titulo, campo7_descricao),
            (campo8_titulo, campo8_descricao),
            (campo9_titulo, campo9_descricao),
            (campo10_titulo, campo10_descricao),
        ]

        parsed_fields = []

        for numero, (field_title, field_text) in enumerate(
            campos_recebidos, start=1
        ):
            field_title = field_title.strip() if field_title else ""
            field_text = field_text.strip() if field_text else ""

            # Ignora campos completamente vazios.
            if not field_title and not field_text:
                continue

            # Exige título e descrição juntos.
            if not field_title or not field_text:
                await interaction.response.send_message(
                    f"❌ O campo {numero} está incompleto. "
                    "Preencha o título e a descrição, ou deixe ambos vazios.",
                    ephemeral=True,
                )
                return

            if len(field_title) > 256:
                await interaction.response.send_message(
                    f"❌ O título do campo {numero} ultrapassa "
                    "256 caracteres.",
                    ephemeral=True,
                )
                return

            if len(field_text) > 1000:
                await interaction.response.send_message(
                    f"❌ A descrição do campo {numero} ultrapassa "
                    "1000 caracteres.",
                    ephemeral=True,
                )
                return

            parsed_fields.append((field_title, field_text))

        # Verifica o limite total de texto.
        total_text = len(titulo) + len(descricao)

        for field_title, field_text in parsed_fields:
            total_text += len(field_title) + len(field_text) + 4

        if total_text > MAX_TOTAL_TEXT:
            await interaction.response.send_message(
                "❌ O conteúdo ficou muito grande para uma única mensagem "
                "Components V2. Reduza a descrição ou os textos dos campos.",
                ephemeral=True,
            )
            return

        # Verifica as permissões do bot no canal.
        bot_member = interaction.guild.me

        if bot_member is None:
            await interaction.response.send_message(
                "❌ Não consegui identificar o membro do bot no servidor.",
                ephemeral=True,
            )
            return

        permissions = canal.permissions_for(bot_member)

        if not permissions.view_channel or not permissions.send_messages:
            await interaction.response.send_message(
                "❌ Não tenho permissão para enviar mensagens nesse canal.",
                ephemeral=True,
            )
            return

        # Monta o painel com Components V2.
        layout = discord.ui.LayoutView(timeout=None)
        container = discord.ui.Container(accent_colour=accent)

        container.add_item(
            discord.ui.TextDisplay(f"# {titulo}")
        )
        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay(descricao)
        )

        for field_title, field_text in parsed_fields:
            container.add_item(discord.ui.Separator())
            container.add_item(
                discord.ui.TextDisplay(
                    f"**{field_title}**\n{field_text}"
                )
            )

        container.add_item(discord.ui.Separator())
        container.add_item(
            discord.ui.TextDisplay("-# Sr.Alpha • Family Alpha")
        )

        layout.add_item(container)

        # Publica o painel.
        try:
            await canal.send(
                view=layout,
                allowed_mentions=discord.AllowedMentions.none(),
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Não tenho permissão para enviar o painel nesse canal.",
                ephemeral=True,
            )
            return

        except discord.HTTPException:
            log.exception("Erro ao enviar painel Components V2.")

            await interaction.response.send_message(
                "❌ O Discord não conseguiu publicar o painel. "
                "Verifique o tamanho do conteúdo e as permissões.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"✅ Painel criado e enviado para {canal.mention}!",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedBuilder(bot))
