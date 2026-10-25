
import sqlite3
import discord

from discord import app_commands
from discord.ext import commands
from database import DB_PATH


PURPLE = discord.Color.from_rgb(145, 103, 255)


def connect_db():
    return sqlite3.connect(DB_PATH)


def init_color_tables():
    with connect_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS color_roles (
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                role_id INTEGER NOT NULL,
                emoji TEXT NOT NULL DEFAULT '🎨',
                PRIMARY KEY (guild_id, name),
                UNIQUE (guild_id, role_id)
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS color_panels (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL
            )
        """)


def get_colors(guild_id):
    with connect_db() as db:
        return db.execute(
            """
            SELECT name, role_id, emoji
            FROM color_roles
            WHERE guild_id = ?
            ORDER BY name COLLATE NOCASE
            """,
            (guild_id,)
        ).fetchall()


def get_panel(guild_id):
    with connect_db() as db:
        return db.execute(
            """
            SELECT channel_id, message_id, title, description
            FROM color_panels
            WHERE guild_id = ?
            """,
            (guild_id,)
        ).fetchone()


def build_panel_container(guild_id, title, description):
    container = discord.ui.Container(accent_colour=PURPLE)
    container.add_item(discord.ui.TextDisplay(f"# 🎨・{title}"))
    container.add_item(discord.ui.TextDisplay(description))
    colors = get_colors(guild_id)
    if colors:
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            "**🌈 Cores disponíveis**\n" +
            "\n".join(f"{emoji} **{name}** — <@&{role_id}>" for name, role_id, emoji in colors)
        ))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            "**💡 Como escolher**\nClique no botão da cor desejada.\nClique novamente para remover sua cor."
        ))
    else:
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay("⚠️ Ainda não existem cores configuradas."))
    container.add_item(discord.ui.Separator())
    container.add_item(discord.ui.TextDisplay("-# Rei Dado • Family Alpha"))
    return container


class ColorPanelView(discord.ui.LayoutView):
    def __init__(self, bot, guild_id, colors, title="Escolha sua cor",
                 description="Clique no botão da sua cor favorita para receber o cargo."):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id
        self.add_item(build_panel_container(guild_id, title, description))
        row = discord.ui.ActionRow()
        row_count = 0

        for name, role_id, emoji in colors:
            button = discord.ui.Button(
                label=name[:80],
                emoji=emoji,
                style=discord.ButtonStyle.secondary,
                custom_id=f"srcolor:{role_id}"
            )
            button.callback = self.make_callback(role_id)
            if row_count == 5:
                self.add_item(row)
                row = discord.ui.ActionRow()
                row_count = 0
            row.add_item(button)
            row_count += 1

        if row_count:
            self.add_item(row)

    def make_callback(self, role_id):
        async def callback(interaction: discord.Interaction):
            if not interaction.guild or not isinstance(
                interaction.user, discord.Member
            ):
                return await interaction.response.send_message(
                    "❌ Este painel só funciona dentro do servidor.",
                    ephemeral=True
                )

            if interaction.guild.id != self.guild_id:
                return await interaction.response.send_message(
                    "❌ Este painel não pertence a este servidor.",
                    ephemeral=True
                )

            guild = interaction.guild
            member = interaction.user
            bot_member = guild.me

            if bot_member is None:
                return await interaction.response.send_message(
                    "❌ Não consegui verificar as permissões do bot.",
                    ephemeral=True
                )

            configured = get_colors(guild.id)
            configured_ids = {row[1] for row in configured}

            if role_id not in configured_ids:
                return await interaction.response.send_message(
                    "⚠️ Esta cor não está mais configurada.",
                    ephemeral=True
                )

            selected_role = guild.get_role(role_id)

            if selected_role is None:
                return await interaction.response.send_message(
                    "⚠️ O cargo desta cor não existe mais.",
                    ephemeral=True
                )

            if (
                selected_role.is_default()
                or selected_role.managed
                or selected_role >= bot_member.top_role
            ):
                return await interaction.response.send_message(
                    "❌ Não consigo gerenciar esse cargo. "
                    "Verifique a hierarquia do Rei Dado.",
                    ephemeral=True
                )

            member_colors = [
                guild.get_role(configured_id)
                for configured_id in configured_ids
            ]
            member_colors = [
                role for role in member_colors
                if role and role in member.roles
            ]

            try:
                if selected_role in member.roles:
                    await member.remove_roles(
                        selected_role,
                        reason="Remoção de cor pelo painel Rei Dado"
                    )
                    message = (
                        f"🎨 Você removeu a cor **{selected_role.name}**."
                    )
                else:
                    to_remove = [
                        role for role in member_colors
                        if role.id != selected_role.id
                        and role < bot_member.top_role
                    ]

                    if to_remove:
                        await member.remove_roles(
                            *to_remove,
                            reason="Troca de cor pelo painel Rei Dado"
                        )

                    await member.add_roles(
                        selected_role,
                        reason="Escolha de cor pelo painel Rei Dado"
                    )
                    message = (
                        f"💜 Sua cor agora é **{selected_role.name}**!"
                    )

                await interaction.response.send_message(
                    message,
                    ephemeral=True
                )

            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ Não tenho permissão para alterar esse cargo. "
                    "Confira Gerenciar cargos e a hierarquia.",
                    ephemeral=True
                )
            except discord.HTTPException:
                await interaction.response.send_message(
                    "❌ O Discord não conseguiu atualizar seu cargo. "
                    "Tente novamente.",
                    ephemeral=True
                )

        return callback


class ColorRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        init_color_tables()

        with connect_db() as db:
            panels = db.execute(
                """
                SELECT guild_id, channel_id, message_id, title, description
                FROM color_panels
                """
            ).fetchall()

        for guild_id, channel_id, message_id, title, description in panels:
            colors = get_colors(guild_id)
            view = ColorPanelView(self.bot, guild_id, colors, title, description)
            self.bot.add_view(view, message_id=message_id)
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except discord.HTTPException:
                    continue
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embeds=[], view=view)
            except discord.HTTPException:
                pass

    async def refresh_panel(self, guild_id):
        panel = get_panel(guild_id)

        if not panel:
            return

        channel_id, message_id, title, description = panel
        channel = self.bot.get_channel(channel_id)

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return

        try:
            message = await channel.fetch_message(message_id)
            view = ColorPanelView(
                self.bot, guild_id, get_colors(guild_id), title, description
            )
            await message.edit(embeds=[], view=view)
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            pass

    @app_commands.command(
        name="painel_cores",
        description="Cria ou atualiza o painel de cores do servidor."
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        canal="Canal onde o painel será publicado",
        titulo="Título personalizado do painel",
        descricao="Texto apresentado no painel"
    )
    async def painel_cores(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        titulo: app_commands.Range[str, 1, 200] = "Escolha sua cor",
        descricao: app_commands.Range[str, 1, 1500] =
            "Clique no botão da sua cor favorita para receber o cargo."
    ):
        guild = interaction.guild

        if guild is None:
            return await interaction.response.send_message(
                "Este comando só funciona em um servidor.",
                ephemeral=True
            )

        await interaction.response.defer(ephemeral=True)

        colors = get_colors(guild.id)
        view = ColorPanelView(self.bot, guild.id, colors, titulo, descricao)

        try:
            panel = get_panel(guild.id)

            if panel:
                old_channel_id, message_id, _, _ = panel
                old_channel = self.bot.get_channel(old_channel_id)

                if old_channel is None:
                    try:
                        old_channel = await self.bot.fetch_channel(
                            old_channel_id
                        )
                    except discord.HTTPException:
                        old_channel = None

                if old_channel is not None:
                    try:
                        old_message = await old_channel.fetch_message(
                            message_id
                        )
                        if old_channel.id == canal.id:
                            await old_message.edit(embeds=[], view=view)
                            message = old_message
                        else:
                            message = await canal.send(view=view)
                            await old_message.edit(embeds=[], view=None)
                    except discord.NotFound:
                        message = await canal.send(view=view)
                else:
                    message = await canal.send(view=view)
            else:
                message = await canal.send(view=view)

            with connect_db() as db:
                db.execute(
                    """
                    INSERT OR REPLACE INTO color_panels
                    (guild_id, channel_id, message_id, title, description)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        guild.id,
                        canal.id,
                        message.id,
                        titulo,
                        descricao
                    )
                )

            self.bot.add_view(view, message_id=message.id)

            await interaction.followup.send(
                f"✅ Painel de cores publicado em {canal.mention}!",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Não consigo publicar nesse canal. "
                "Verifique minhas permissões.",
                ephemeral=True
            )

    @app_commands.command(
        name="adicionar_cor",
        description="Adiciona uma cor ao painel."
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.describe(
        nome="Nome exibido no botão",
        cargo="Cargo do Discord correspondente à cor",
        emoji="Emoji exibido no botão"
    )
    async def adicionar_cor(
        self,
        interaction: discord.Interaction,
        nome: app_commands.Range[str, 1, 40],
        cargo: discord.Role,
        emoji: str = "🎨"
    ):
        guild = interaction.guild

        if guild is None:
            return await interaction.response.send_message(
                "Este comando só funciona em um servidor.",
                ephemeral=True
            )

        if cargo.is_default() or cargo.managed:
            return await interaction.response.send_message(
                "❌ Escolha um cargo normal, não um cargo gerenciado.",
                ephemeral=True
            )

        if cargo >= guild.me.top_role:
            return await interaction.response.send_message(
                "❌ O cargo do Rei Dado precisa ficar acima "
                "do cargo escolhido.",
                ephemeral=True
            )

        emoji = emoji.strip()

        if not emoji or len(emoji) > 100:
            return await interaction.response.send_message(
                "❌ Informe um emoji válido.",
                ephemeral=True
            )

        try:
            with connect_db() as db:
                db.execute(
                    """
                    INSERT INTO color_roles
                    (guild_id, name, role_id, emoji)
                    VALUES (?, ?, ?, ?)
                    """,
                    (guild.id, nome, cargo.id, emoji)
                )
        except sqlite3.IntegrityError:
            return await interaction.response.send_message(
                "❌ Esse nome ou cargo já está cadastrado como cor.",
                ephemeral=True
            )

        await self.refresh_panel(guild.id)

        await interaction.response.send_message(
            f"✅ Cor **{nome}** adicionada ao sistema! "
            "Publique o painel com `/painel_cores` se ainda não existir.",
            ephemeral=True
        )

    @app_commands.command(
        name="remover_cor",
        description="Remove uma cor das opções do painel."
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def remover_cor(
        self,
        interaction: discord.Interaction,
        nome: app_commands.Range[str, 1, 40]
    ):
        guild = interaction.guild

        if guild is None:
            return await interaction.response.send_message(
                "Este comando só funciona em um servidor.",
                ephemeral=True
            )

        with connect_db() as db:
            cursor = db.execute(
                """
                DELETE FROM color_roles
                WHERE guild_id = ? AND name = ?
                """,
                (guild.id, nome)
            )

        if cursor.rowcount == 0:
            return await interaction.response.send_message(
                f"❌ A cor **{nome}** não foi encontrada.",
                ephemeral=True
            )

        await self.refresh_panel(guild.id)

        await interaction.response.send_message(
            f"🗑️ A cor **{nome}** foi removida do painel. "
            "O cargo não foi apagado do servidor.",
            ephemeral=True
        )

    @app_commands.command(
        name="listar_cores",
        description="Lista as cores configuradas."
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def listar_cores(self, interaction: discord.Interaction):
        guild = interaction.guild

        if guild is None:
            return await interaction.response.send_message(
                "Este comando só funciona em um servidor.",
                ephemeral=True
            )

        colors = get_colors(guild.id)

        if not colors:
            return await interaction.response.send_message(
                "🎨 Nenhuma cor cadastrada ainda.",
                ephemeral=True
            )

        lines = []

        for nome, role_id, emoji in colors:
            role = guild.get_role(role_id)
            role_text = role.mention if role else f"`ID {role_id}`"
            lines.append(f"{emoji} **{nome}** — {role_text}")

        layout = discord.ui.LayoutView(timeout=None)
        panel = discord.ui.Container(accent_colour=PURPLE)
        panel.add_item(discord.ui.TextDisplay("# 🎨 Cores configuradas"))
        panel.add_item(discord.ui.TextDisplay("\n".join(lines)))
        panel.add_item(discord.ui.Separator())
        panel.add_item(discord.ui.TextDisplay("-# Rei Dado • Family Alpha"))
        layout.add_item(panel)

        await interaction.response.send_message(
            view=layout,
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(ColorRoles(bot))
