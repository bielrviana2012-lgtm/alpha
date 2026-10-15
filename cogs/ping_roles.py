```python
import logging
import re
import sqlite3
import unicodedata

import discord
from discord import app_commands
from discord.ext import commands

from database import DB_PATH

log = logging.getLogger("Sr.Alpha.PingRoles")

PURPLE = discord.Color.from_rgb(145, 103, 255)
TARGET_GUILD_ID = 1536903015678873710
OPTIONS_PER_PAGE = 25


# =========================================================
# BANCO DE DADOS
# =========================================================

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

        db.commit()


def get_pings(guild_id: int):
    with db_connect() as db:
        return db.execute("""
            SELECT name, role_id, emoji
            FROM ping_roles
            WHERE guild_id = ?
            ORDER BY name COLLATE NOCASE
        """, (guild_id,)).fetchall()


def save_panel(
    guild_id: int,
    channel_id: int,
    message_id: int,
    title: str,
    description: str,
):
    with db_connect() as db:
        db.execute("""
            INSERT INTO ping_panels (
                guild_id, channel_id, message_id, title, description
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                message_id = excluded.message_id,
                title = excluded.title,
                description = excluded.description
        """, (
            guild_id,
            channel_id,
            message_id,
            title,
            description,
        ))
        db.commit()


# =========================================================
# EMOJIS
# =========================================================

def normalise_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    return "".join(ch for ch in value if ch.isalnum())


def resolve_server_emoji(
    guild: discord.Guild,
    value: str | None,
    label: str,
):
    """Aceita emoji personalizado, ID, nome ou emoji Unicode."""

    value = (value or "").strip()

    if value:
        match = re.fullmatch(
            r"<a?:(?P<name>[A-Za-z0-9_]{2,32}):(?P<id>\d{15,22})>",
            value,
        )

        raw_id = (
            match.group("id")
            if match
            else value if value.isdigit() else None
        )

        if raw_id:
            found = discord.utils.get(guild.emojis, id=int(raw_id))
            return str(found) if found else None

        by_name = discord.utils.get(
            guild.emojis,
            name=value.strip(":"),
        )

        if by_name:
            return str(by_name)

        # Não aceitar IDs ou marcações inválidas como Unicode.
        if value.startswith("<"):
            return None

        return value

    wanted = normalise_name(label)

    if wanted:
        exact = next(
            (
                emoji for emoji in guild.emojis
                if normalise_name(emoji.name) == wanted
            ),
            None,
        )

        if exact:
            return str(exact)

        partial = next(
            (
                emoji for emoji in guild.emojis
                if normalise_name(emoji.name) in wanted
                or wanted in normalise_name(emoji.name)
            ),
            None,
        )

        if partial:
            return str(partial)

    return str(guild.emojis[0]) if guild.emojis else "🔔"


def option_emoji(value: str):
    """Converte a marcação de emoji para o formato do discord.py."""
    try:
        if value.startswith("<") and value.endswith(">"):
            return discord.PartialEmoji.from_str(value)
        return value
    except (TypeError, ValueError):
        return "🔔"


# =========================================================
# MENU DE SELEÇÃO DE PINGS
# =========================================================

class PingRoleSelect(discord.ui.Select):
    def __init__(self, parent_view):
        self.parent_view = parent_view

        guild = parent_view.guild
        member = parent_view.member
        all_pings = parent_view.pings

        start = parent_view.page * OPTIONS_PER_PAGE
        page_pings = all_pings[start:start + OPTIONS_PER_PAGE]

        member_role_ids = {role.id for role in member.roles}

        options = []

        for name, role_id, emoji in page_pings:
            role = guild.get_role(role_id)

            if role is None:
                continue

            options.append(
                discord.SelectOption(
                    label=name[:100],
                    value=str(role_id),
                    description=f"Receber notificações de {name}"[:100],
                    emoji=option_emoji(emoji),
                    default=role_id in member_role_ids,
                )
            )

        # O Discord não aceita um select vazio.
        if not options:
            options = [
                discord.SelectOption(
                    label="Nenhum cargo disponível nesta página",
                    value="none",
                    emoji="⚠️",
                )
            ]
            disabled = True
        else:
            disabled = False

        super().__init__(
            placeholder="Selecione os pings que deseja receber...",
            min_values=0,
            max_values=len(options),
            options=options,
            disabled=disabled,
            custom_id=None,
            row=0,
        )

    async def callback(self, interaction: discord.Interaction):
        await self.parent_view.apply_selection(interaction, self.values)


class PingSelectView(discord.ui.View):
    def __init__(
        self,
        cog,
        guild: discord.Guild,
        member: discord.Member,
        page: int = 0,
    ):
        super().__init__(timeout=180)

        self.cog = cog
        self.guild = guild
        self.member = member
        self.pings = get_pings(guild.id)

        total_pages = max(
            1,
            (len(self.pings) + OPTIONS_PER_PAGE - 1)
            // OPTIONS_PER_PAGE,
        )

        self.page = max(0, min(page, total_pages - 1))
        self.total_pages = total_pages

        self.add_item(PingRoleSelect(self))

        self.previous_page.disabled = self.page <= 0
        self.next_page.disabled = self.page >= total_pages - 1

        self.previous_page.label = "◀ Anterior"
        self.next_page.label = "Próxima ▶"

        self.page_indicator.label = (
            f"Página {self.page + 1}/{self.total_pages}"
        )

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.guild_id != TARGET_GUILD_ID:
            await interaction.response.send_message(
                "Este painel pertence ao servidor Family Alpha.",
                ephemeral=True,
            )
            return False

        if interaction.user.id != self.member.id:
            await interaction.response.send_message(
                "Este menu foi aberto por outra pessoa. "
                "Clique no painel para abrir o seu.",
                ephemeral=True,
            )
            return False

        return True

    async def apply_selection(
        self,
        interaction: discord.Interaction,
        selected_values: list[str],
    ):
        guild = interaction.guild

        if guild is None or guild.id != TARGET_GUILD_ID:
            await interaction.response.send_message(
                "Servidor não permitido.",
                ephemeral=True,
            )
            return

        member = guild.get_member(interaction.user.id)

        if member is None:
            try:
                member = await guild.fetch_member(interaction.user.id)
            except discord.HTTPException:
                await interaction.response.send_message(
                    "Não consegui encontrar seu membro no servidor.",
                    ephemeral=True,
                )
                return

        if "none" in selected_values:
            await interaction.response.send_message(
                "Não há cargos disponíveis nesta página.",
                ephemeral=True,
            )
            return

        bot_member = guild.me

        if bot_member is None:
            await interaction.response.send_message(
                "Não consegui verificar as permissões do bot.",
                ephemeral=True,
            )
            return

        if not bot_member.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "Preciso da permissão **Gerenciar cargos** para "
                "atualizar seus pings.",
                ephemeral=True,
            )
            return

        selected_ids = {
            int(value)
            for value in selected_values
            if value.isdigit()
        }

        start = self.page * OPTIONS_PER_PAGE
        page_pings = self.pings[start:start + OPTIONS_PER_PAGE]

        added = []
        removed = []
        unavailable = []

        # Só altera os cargos desta página.
        # Os cargos selecionados em outras páginas são preservados.
        for name, role_id, emoji in page_pings:
            role = guild.get_role(role_id)

            if role is None:
                unavailable.append(name)
                continue

            has_role = role in member.roles
            wants_role = role_id in selected_ids

            if has_role == wants_role:
                continue

            if role.managed or role >= bot_member.top_role:
                unavailable.append(name)
                continue

            try:
                if wants_role:
                    await member.add_roles(
                        role,
                        reason="Seleção de ping pelo painel Sr.Alpha",
                    )
                    added.append(name)
                else:
                    await member.remove_roles(
                        role,
                        reason="Remoção de ping pelo painel Sr.Alpha",
                    )
                    removed.append(name)

            except discord.Forbidden:
                unavailable.append(name)

            except discord.HTTPException:
                unavailable.append(name)

        # Atualiza os valores selecionados no menu.
        updated_member = guild.get_member(member.id) or member

        self.member = updated_member
        self.pings = get_pings(guild.id)
        self.total_pages = max(
            1,
            (len(self.pings) + OPTIONS_PER_PAGE - 1)
            // OPTIONS_PER_PAGE,
        )
        self.page = min(self.page, self.total_pages - 1)

        new_view = PingSelectView(
            self.cog,
            guild,
            updated_member,
            self.page,
        )

        messages = []

        if added:
            messages.append(f"✅ **Adicionados:** {len(added)}")
        if removed:
            messages.append(f"🗑️ **Removidos:** {len(removed)}")
        if unavailable:
            messages.append(
                f"⚠️ **Não foi possível alterar:** {len(unavailable)}"
            )
        if not messages:
            messages.append("ℹ️ Nenhuma alteração foi necessária.")

        await interaction.response.edit_message(
            content="\n".join(messages),
            view=new_view,
        )

    @discord.ui.button(
        label="◀ Anterior",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def previous_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        new_view = PingSelectView(
            self.cog,
            self.guild,
            self.member,
            self.page - 1,
        )

        await interaction.response.edit_message(view=new_view)

    @discord.ui.button(
        label="Página",
        style=discord.ButtonStyle.secondary,
        disabled=True,
        row=1,
    )
    async def page_indicator(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        pass

    @discord.ui.button(
        label="Próxima ▶",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def next_page(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        new_view = PingSelectView(
            self.cog,
            self.guild,
            self.member,
            self.page + 1,
        )

        await interaction.response.edit_message(view=new_view)


# =========================================================
# BOTÃO PERSISTENTE DO PAINEL PÚBLICO
# =========================================================

class PingPanelView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Selecionar seus pings",
        style=discord.ButtonStyle.primary,
        emoji="🔔",
        custom_id="sr_alpha:open_ping_selector",
    )
    async def open_selector(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        guild = interaction.guild

        if guild is None or guild.id != TARGET_GUILD_ID:
            await interaction.response.send_message(
                "Este painel só funciona no servidor Family Alpha.",
                ephemeral=True,
            )
            return

        if not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message(
                "Não consegui identificar seu membro no servidor.",
                ephemeral=True,
            )
            return

        pings = get_pings(guild.id)

        if not pings:
            await interaction.response.send_message(
                "Não há cargos de ping cadastrados no momento.",
                ephemeral=True,
            )
            return

        view = PingSelectView(
            self.cog,
            guild,
            interaction.user,
        )

        await interaction.response.send_message(
            content=(
                "🔔 **Personalize suas notificações**\n"
                "Marque os cargos que deseja receber. "
                "Desmarque os que não deseja mais.\n\n"
                "Suas escolhas em outras páginas serão preservadas."
            ),
            view=view,
            ephemeral=True,
        )


# =========================================================
# COMANDOS
# =========================================================

class PingRoles(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="adicionar_ping",
        description="Adiciona um cargo ao painel de notificações.",
    )
    @app_commands.describe(
        nome="Nome para identificar o ping",
        cargo="Cargo que os membros poderão selecionar",
        emoji="Emoji do servidor, ID ou emoji Unicode (opcional)",
    )
    @app_commands.default_permissions(manage_roles=True)
    async def adicionar_ping(
        self,
        interaction: discord.Interaction,
        nome: str,
        cargo: discord.Role,
        emoji: str = "",
    ):
        guild = interaction.guild

        if guild is None or guild.id != TARGET_GUILD_ID:
            await interaction.response.send_message(
                "Este comando só pode ser usado no servidor Family Alpha.",
                ephemeral=True,
            )
            return

        nome = nome.strip()

        if not nome or len(nome) > 80:
            await interaction.response.send_message(
                "O nome deve ter entre 1 e 80 caracteres.",
                ephemeral=True,
            )
            return

        if cargo.is_default() or cargo.managed:
            await interaction.response.send_message(
                "Escolha um cargo normal que possa ser atribuído a membros.",
                ephemeral=True,
            )
            return

        bot_member = guild.me

        if (
            bot_member is None
            or not bot_member.guild_permissions.manage_roles
        ):
            await interaction.response.send_message(
                "Preciso da permissão **Gerenciar cargos**.",
                ephemeral=True,
            )
            return

        if cargo >= bot_member.top_role:
            await interaction.response.send_message(
                "Meu cargo precisa estar acima do cargo selecionado.",
                ephemeral=True,
            )
            return

        emoji_value = resolve_server_emoji(guild, emoji, nome)

        if emoji_value is None:
            await interaction.response.send_message(
                "Não encontrei esse emoji no servidor. "
                "Confira o nome ou ID.",
                ephemeral=True,
            )
            return

        try:
            with db_connect() as db:
                db.execute("""
                    INSERT INTO ping_roles (guild_id, name, role_id, emoji)
                    VALUES (?, ?, ?, ?)
                """, (guild.id, nome, cargo.id, emoji_value))
                db.commit()

        except sqlite3.IntegrityError:
            await interaction.response.send_message(
                "Esse nome ou cargo já está cadastrado nos pings.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"✅ Ping **{nome}** cadastrado para {cargo.mention}!",
            ephemeral=True,
        )

    @app_commands.command(
        name="remover_ping",
        description="Remove um cargo do painel de notificações.",
    )
    @app_commands.describe(nome="Nome exato do ping cadastrado")
    @app_commands.default_permissions(manage_roles=True)
    async def remover_ping(
        self,
        interaction: discord.Interaction,
        nome: str,
    ):
        guild = interaction.guild

        if guild is None or guild.id != TARGET_GUILD_ID:
            await interaction.response.send_message(
                "Este comando só pode ser usado no servidor Family Alpha.",
                ephemeral=True,
            )
            return

        with db_connect() as db:
            cursor = db.execute("""
                DELETE FROM ping_roles
                WHERE guild_id = ? AND name = ? COLLATE NOCASE
            """, (guild.id, nome.strip()))
            db.commit()

        if cursor.rowcount == 0:
            await interaction.response.send_message(
                "Não encontrei um ping com esse nome.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"✅ Ping **{nome}** removido do cadastro.",
            ephemeral=True,
        )

    @app_commands.command(
        name="listar_pings",
        description="Lista os cargos cadastrados no sistema de pings.",
    )
    async def listar_pings(self, interaction: discord.Interaction):
        guild = interaction.guild

        if guild is None or guild.id != TARGET_GUILD_ID:
            await interaction.response.send_message(
                "Este comando só pode ser usado no servidor Family Alpha.",
                ephemeral=True,
            )
            return

        pings = get_pings(guild.id)

        if not pings:
            await interaction.response.send_message(
                "Ainda não há cargos cadastrados. Use `/adicionar_ping`.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="🔔 Cargos de ping cadastrados",
            color=PURPLE,
        )

        lines = []

        for name, role_id, emoji in pings:
            role = guild.get_role(role_id)

            if role:
                lines.append(f"{emoji} **{name}** — {role.mention}")
            else:
                lines.append(f"{emoji} **{name}** — cargo não encontrado")

        chunk = ""
        field_number = 1

        for line in lines:
            if len(chunk) + len(line) + 1 > 1000:
                embed.add_field(
                    name=f"Lista {field_number}",
                    value=chunk,
                    inline=False,
                )
                field_number += 1
                chunk = ""

            chunk += line + "\n"

        if chunk:
            embed.add_field(
                name=f"Lista {field_number}",
                value=chunk,
                inline=False,
            )

        embed.set_footer(text=f"Sr.Alpha • Total: {len(pings)} cargos")

        await interaction.response.send_message(
            embed=embed,
            ephemeral=True,
        )

    @app_commands.command(
        name="painel_pings",
        description="Publica o painel para os membros escolherem seus pings.",
    )
    @app_commands.describe(
        titulo="Título do painel",
        descricao="Texto de instrução exibido no painel",
    )
    @app_commands.default_permissions(manage_guild=True)
    async def painel_pings(
        self,
        interaction: discord.Interaction,
        titulo: str = "Escolha seus pings",
        descricao: str = (
            "Selecione os cargos de notificações que deseja receber."
        ),
    ):
        guild = interaction.guild
        channel = interaction.channel

        if guild is None or guild.id != TARGET_GUILD_ID:
            await interaction.response.send_message(
                "Este comando só pode ser usado no servidor Family Alpha.",
                ephemeral=True,
            )
            return

        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message(
                "Use este comando em um canal de texto.",
                ephemeral=True,
            )
            return

        pings = get_pings(guild.id)

        if not pings:
            await interaction.response.send_message(
                "Cadastre pelo menos um cargo com `/adicionar_ping` primeiro.",
                ephemeral=True,
            )
            return

        titulo = titulo.strip() or "Escolha seus pings"
        descricao = descricao.strip() or (
            "Selecione os cargos de notificações que deseja receber."
        )

        titulo = titulo[:240]
        descricao = descricao[:3500]

        embed = discord.Embed(
            title=f"🔔・{titulo}",
            description=descricao,
            color=PURPLE,
        )

        embed.add_field(
            name="📢 Notificações disponíveis",
            value=f"Há **{len(pings)}** cargos cadastrados.",
            inline=False,
        )

        embed.add_field(
            name="📌 Como funciona",
            value=(
                "Clique em **Selecionar seus pings** para abrir seu menu "
                "privado. Se houver mais de 25 cargos, utilize os botões "
                "para navegar pelas páginas."
            ),
            inline=False,
        )

        embed.set_footer(text="Sr.Alpha • Family Alpha")

        view = PingPanelView(self)

        try:
            message = await channel.send(embed=embed, view=view)
        except discord.Forbidden:
            await interaction.response.send_message(
                "Não tenho permissão para enviar mensagens ou incorporar "
                "links neste canal.",
                ephemeral=True,
            )
            return

        save_panel(
            guild.id,
            channel.id,
            message.id,
            titulo,
            descricao,
        )

        await interaction.response.send_message(
            f"✅ Painel publicado em {channel.mention}!",
            ephemeral=True,
        )


# =========================================================
# INICIALIZAÇÃO DA EXTENSÃO
# =========================================================

async def setup(bot: commands.Bot):
    init_tables()

    cog = PingRoles(bot)
    await bot.add_cog(cog)

    # Mantém o botão público funcionando após reinicializações.
    bot.add_view(PingPanelView(cog))

    log.info("Sistema de pings do Sr.Alpha carregado.")
```
