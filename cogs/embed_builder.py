
"""Comando para criar painéis personalizados usando Components V2."""

import logging

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("Sr.Alpha.EmbedBuilder")

PURPLE = discord.Color.from_rgb(145, 103, 255)
MAX_FIELDS = 25
MAX_TOTAL_TEXT = 3800


class EmbedBuilder(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="criar_embed",
        description="Cria um painel personalizado com até 25 campos.",
    )
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(
        titulo="Título do painel",
        descricao="Descrição principal do painel",
        canal="Canal onde o painel será enviado",
        cor="Cor hexadecimal, exemplo: #9167FF",
        campos=(
            "Um campo por linha, no formato Título | Texto. "
            "Máximo de 25 campos."
        ),
    )
    async def criar_embed(
        self,
        interaction: discord.Interaction,
        titulo: app_commands.Range[str, 1, 200],
        descricao: app_commands.Range[str, 1, 2000],
        canal: discord.TextChannel,
        cor: str = "#9167FF",
        campos: str = "",
    ):
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

        # Analisa os campos informados.
        parsed_fields = []

        if campos.strip():
            for line_number, line in enumerate(campos.splitlines(), start=1):
                line = line.strip()

                if not line:
                    continue

                if "|" not in line:
                    await interaction.response.send_message(
                        f"❌ A linha {line_number} está incorreta.\n"
                        "Use o formato `Título | Texto`.",
                        ephemeral=True,
                    )
                    return

                field_title, field_text = line.split("|", 1)
                field_title = field_title.strip()
                field_text = field_text.strip()

                if not field_title or not field_text:
                    await interaction.response.send_message(
                        f"❌ A linha {line_number} precisa ter "
                        "título e texto.",
                        ephemeral=True,
                    )
                    return

                if len(field_title) > 256:
                    await interaction.response.send_message(
                        f"❌ O título do campo da linha {line_number} "
                        "ultrapassa 256 caracteres.",
                        ephemeral=True,
                    )
                    return

                if len(field_text) > 1000:
                    await interaction.response.send_message(
                        f"❌ O texto do campo da linha {line_number} "
                        "ultrapassa 1000 caracteres.",
                        ephemeral=True,
                    )
                    return

                parsed_fields.append((field_title, field_text))

                if len(parsed_fields) > MAX_FIELDS:
                    await interaction.response.send_message(
                        f"❌ Você pode adicionar no máximo {MAX_FIELDS} campos.",
                        ephemeral=True,
                    )
                    return

        # Componentes V2 têm limite total de 4000 caracteres de texto.
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
        bot_member = interaction.guild.me if interaction.guild else None

        if bot_member is None:
            await interaction.response.send_message(
                "❌ Este comando só pode ser usado dentro de um servidor.",
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

        # Monta o painel Components V2.
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
