
import sqlite3
import discord

from discord import app_commands
from discord.ext import commands
from database import DB_PATH

PURPLE = discord.Color.from_rgb(145, 103, 255)


def db_connect():
    return sqlite3.connect(DB_PATH)


def init_tables():
    with db_connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS ping_roles (
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                role_id INTEGER NOT NULL,
                emoji TEXT NOT NULL DEFAULT '🔔',
                PRIMARY KEY (guild_id, name),
                UNIQUE (guild_id, role_id)
            )
        """)

        db.execute("""
            CREATE TABLE IF NOT EXISTS ping_panels (
                guild_id INTEGER PRIMARY KEY,
                channel_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT NOT NULL
            )
        """)


def get_pings(guild_id):
    with db_connect() as db:
        return db.execute("""
            SELECT name, role_id, emoji
            FROM ping_roles
            WHERE guild_id = ?
            ORDER BY name COLLATE NOCASE
        """, (guild_id,)).fetchall()


def get_panel(guild_id):
    with db_connect() as db:
        return db.execute("""
            SELECT channel_id, message_id, title, description
            FROM ping_panels
            WHERE guild_id = ?
        """, (guild_id,)).fetchone()


def make_embed(guild_id, title, description):
    embed = discord.Embed(
        title=f"🔔・{title}",
        description=description,
        color=PURPLE
    )

    pings = get_pings(guild_id)

    if pings:
        embed.add_field(
            name="📌 Opções disponíveis",
            value="\n".join(
                f"{emoji} **{name}** — <@&{role_id}>"
                for name, role_id, emoji in pings
            ),
            inline=False
        )
        embed.add_field(
            name="Como funciona?",
            value=(
                "Clique no botão para receber o cargo.\n"
                "Clique novamente para removê-lo."
            ),
            inline=False
        )
    else:
        embed.description = (
            f"{description}\n\n"
            "Nenhum ping foi cadastrado ainda."
        )

    embed.set_footer(text="Sr.Alpha • Family Alpha")
    return embed


class PingPanelView(discord.ui.View):
    def __init__(self, bot, guild_id, pings):
        super().__init__(timeout=None)
        self.bot = bot
        self.guild_id = guild_id

        for name, role_id, emoji in pings:
            button = discord.ui.Button(
                label=name[:80],
                emoji=emoji,
                style=discord.ButtonStyle.secondary,
                custom_id=f"srping:{role_id}"
            )
            button.callback = self.make_callback(role_id)
            self.add_item(button)

    def make_callback(self, role_id):
        async def callback(interaction: discord.Interaction):
            guild = interaction.guild
            member = interaction.user

            if (
                guild is None
                or guild.id != self.guild_id
                or not isinstance(member, discord.Member)
            ):
                return await interaction.response.send_message(
                    "Este painel só funciona no servidor correto.",
                    ephemeral=True
                )

            bot_member = guild.me
            if bot_member is None:
                return await interaction.response.send_message(
                    "Não consegui verificar minhas permissões.",
                    ephemeral=True
                )

            configured = get_pings(guild.id)
            configured_ids = {row[1] for row in configured}

            if role_id not in configured_ids:
                return await interaction.response.send_message(
                    "Esta opção não está mais cadastrada.",
                    ephemeral=True
                )

            role = guild.get_role(role_id)

            if role is None:
                return await interaction.response.send_message(
                    "O cargo associado a esta opção não existe mais.",
                    ephemeral=True
                )

            if (
                role.is_default()
                or role.managed
                or role >= bot_member.top_role
            ):
                return await interaction.response.send_message(
                    "Não consigo gerenciar este cargo. "
                    "Verifique a hierarquia do bot.",
                    ephemeral=True
                )

            try:
                if role in member.roles:
                    await member.remove_roles(
                        role,
                        reason="Membro desativou um ping pelo painel"
                    )
                    message = f"🔕 Cargo **{role.name}** removido."
                else:
                    await member.add_roles(
                        role,
                        reason="Membro ativou um ping pelo painel"
                    )
                    message = f"🔔 Cargo **{role.name}** ativado!"

                await interaction.response.send_message(
                    message,
                    ephemeral=True
                )

            except discord.Forbidden:
                await interaction.response.send_message(
                    "Não tenho permissão para alterar este cargo.",
                    ephemeral=True
                )
            except discord.HTTPException:
                await interaction.response.send_message(
                    "Ocorreu um erro ao atualizar o cargo. Tente novamente.",
                    ephemeral=True
                )

        return callback


class PingRoles(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        init_tables()

        with db_connect() as db:
            panels = db.execute("""
                SELECT guild_id, message_id FROM ping_panels
            """).fetchall()

        for guild_id, message_id in panels:
            self.bot.add_view(
                PingPanelView(self.bot, guild_id, get_pings(guild_id)),
                message_id=message_id
            )

    async def atualizar_painel(self, guild_id):
        panel = get_panel(guild_id)
        if not panel:
            return

        channel_id, message_id, title, description = panel
        channel = self.bot.get_channel(channel_id)

        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return

        try:
            message = await channel.fetch_message(message_id)
            view = PingPanelView(
                self.bot, guild_id, get_pings(guild_id)
            )
            await message.edit(
                embed=make_embed(guild_id, title, description),
                view=view
            )
        except discord.HTTPException:
            pass

    @app_commands.command(
        name="adicionar_ping",
        description="Cadastra uma opção de ping no painel."
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def adicionar_ping(
        self,
        interaction: discord.Interaction,
        nome: app_commands.Range[str, 1, 40],
        cargo: discord.Role,
        emoji: str = "🔔"
    ):
        guild = interaction.guild
        if guild is None:
            return

        bot_member = guild.me

        if (
            cargo.is_default()
            or cargo.managed
            or bot_member is None
            or cargo >= bot_member.top_role
        ):
            return await interaction.response.send_message(
                "Cargo inválido ou acima do cargo do Sr.Alpha.",
                ephemeral=True
            )

        emoji = emoji.strip()
        if not emoji or len(emoji) > 100:
            return await interaction.response.send_message(
                "Informe um emoji válido.",
                ephemeral=True
            )

        try:
            with db_connect() as db:
                db.execute("""
                    INSERT INTO ping_roles (guild_id, name, role_id, emoji)
                    VALUES (?, ?, ?, ?)
                """, (guild.id, nome, cargo.id, emoji))
        except sqlite3.IntegrityError:
            return await interaction.response.send_message(
                "Esse nome ou cargo já está cadastrado.",
                ephemeral=True
            )

        await self.atualizar_painel(guild.id)

        await interaction.response.send_message(
            f"✅ Opção **{nome}** cadastrada!",
            ephemeral=True
        )

    @app_commands.command(
        name="remover_ping",
        description="Remove uma opção de ping do painel."
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def remover_ping(
        self,
        interaction: discord.Interaction,
        nome: app_commands.Range[str, 1, 40]
    ):
        guild = interaction.guild
        if guild is None:
            return

        with db_connect() as db:
            cursor = db.execute("""
                DELETE FROM ping_roles
                WHERE guild_id = ? AND name = ?
            """, (guild.id, nome))

        if cursor.rowcount == 0:
            return await interaction.response.send_message(
                "Essa opção não foi encontrada.",
                ephemeral=True
            )

        await self.atualizar_painel(guild.id)

        await interaction.response.send_message(
            f"🗑️ Opção **{nome}** removida. "
            "O cargo do Discord não foi apagado.",
            ephemeral=True
        )

    @app_commands.command(
        name="listar_pings",
        description="Lista as opções de ping cadastradas."
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def listar_pings(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            return

        pings = get_pings(guild.id)

        if not pings:
            return await interaction.response.send_message(
                "Nenhuma opção cadastrada.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="🔔 Opções de ping",
            description="\n".join(
                f"{emoji} **{name}** — <@&{role_id}>"
                for name, role_id, emoji in pings
            ),
            color=PURPLE
        )
        await interaction.response.send_message(
            embed=embed,
            ephemeral=True
        )

    @app_commands.command(
        name="painel_pings",
        description="Cria ou atualiza o painel personalizável de pings."
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    async def painel_pings(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        titulo: app_commands.Range[str, 1, 200] = "Escolha seus pings",
        descricao: app_commands.Range[str, 1, 1500] =
            "Clique nos botões para ativar ou desativar as notificações."
    ):
        guild = interaction.guild
        if guild is None:
            return

        await interaction.response.defer(ephemeral=True)

        embed = make_embed(guild.id, titulo, descricao)
        view = PingPanelView(self.bot, guild.id, get_pings(guild.id))

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

                old_message = None
                if old_channel is not None:
                    try:
                        old_message = await old_channel.fetch_message(
                            message_id
                        )
                    except discord.HTTPException:
                        pass

                if old_message and old_channel.id == canal.id:
                    message = old_message
                    await message.edit(embed=embed, view=view)
                else:
                    message = await canal.send(embed=embed, view=view)
                    if old_message:
                        try:
                            await old_message.edit(view=None)
                        except discord.HTTPException:
                            pass
            else:
                message = await canal.send(embed=embed, view=view)

            with db_connect() as db:
                db.execute("""
                    INSERT OR REPLACE INTO ping_panels
                    (guild_id, channel_id, message_id, title, description)
                    VALUES (?, ?, ?, ?, ?)
                """, (guild.id, canal.id, message.id, titulo, descricao))

            self.bot.add_view(view, message_id=message.id)

            await interaction.followup.send(
                f"✅ Painel publicado em {canal.mention}!",
                ephemeral=True
            )

        except discord.Forbidden:
            await interaction.followup.send(
                "Não tenho permissão para publicar nesse canal.",
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(PingRoles(bot))
