
import logging
import re
import aiosqlite
import discord

from discord import app_commands
from discord.ext import commands

import config
from database import DB_PATH

log = logging.getLogger("Sr.Alpha.Community")
PURPLE = discord.Color.from_rgb(145, 103, 255)


# =========================================================
# BANCO DE DADOS
# =========================================================

async def _ensure_columns(db, table: str, columns: dict):
    """Adiciona colunas ausentes sem apagar os dados existentes."""
    cursor = await db.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in await cursor.fetchall()}

    for column, definition in columns.items():
        if column not in existing:
            await db.execute(
                f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
            )


async def init_community_tables():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_settings (
                guild_id INTEGER PRIMARY KEY,
                panel_channel_id INTEGER,
                panel_message_id INTEGER,
                panel_title TEXT NOT NULL DEFAULT 'Central de Atendimento',
                panel_description TEXT NOT NULL DEFAULT
                    'Escolha uma categoria no menu abaixo.',
                panel_color INTEGER NOT NULL DEFAULT 9533439,
                panel_image TEXT NOT NULL DEFAULT '',
                hours_text TEXT NOT NULL DEFAULT '',
                notices_text TEXT NOT NULL DEFAULT '',
                rating_channel_id INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                emoji TEXT NOT NULL DEFAULT '🎫',
                description TEXT NOT NULL DEFAULT '',
                staff_role_id INTEGER NOT NULL,
                discord_category_id INTEGER,
                welcome_text TEXT NOT NULL DEFAULT
                    'Explique como podemos ajudar.',
                UNIQUE(guild_id, name)
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_records (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                category_id INTEGER,
                attendant_id INTEGER,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                closed_at TEXT,
                rating INTEGER,
                rating_comment TEXT,
                rating_message_id INTEGER
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open'
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS alpha_suggestions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                status TEXT NOT NULL DEFAULT 'Pendente',
                admin_id INTEGER,
                response TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migração segura de bancos de versões anteriores.
        await _ensure_columns(db, "ticket_settings", {
            "panel_channel_id": "INTEGER",
            "panel_message_id": "INTEGER",
            "panel_title": "TEXT NOT NULL DEFAULT 'Central de Atendimento'",
            "panel_description": "TEXT NOT NULL DEFAULT 'Escolha uma categoria no menu abaixo.'",
            "panel_color": "INTEGER NOT NULL DEFAULT 9533439",
            "panel_image": "TEXT NOT NULL DEFAULT ''",
            "hours_text": "TEXT NOT NULL DEFAULT ''",
            "notices_text": "TEXT NOT NULL DEFAULT ''",
            "rating_channel_id": "INTEGER",
        })

        await _ensure_columns(db, "ticket_categories", {
            "emoji": "TEXT NOT NULL DEFAULT '🎫'",
            "description": "TEXT NOT NULL DEFAULT ''",
            "staff_role_id": "INTEGER NOT NULL DEFAULT 0",
            "discord_category_id": "INTEGER",
            "welcome_text": "TEXT NOT NULL DEFAULT 'Explique como podemos ajudar.'",
        })

        await _ensure_columns(db, "ticket_records", {
            "guild_id": "INTEGER NOT NULL DEFAULT 0",
            "user_id": "INTEGER NOT NULL DEFAULT 0",
            "category_id": "INTEGER",
            "attendant_id": "INTEGER",
            "status": "TEXT NOT NULL DEFAULT 'open'",
            "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
            "closed_at": "TEXT",
            "rating": "INTEGER",
            "rating_comment": "TEXT",
            "rating_message_id": "INTEGER",
        })

        await _ensure_columns(db, "tickets", {
            "guild_id": "INTEGER NOT NULL DEFAULT 0",
            "user_id": "INTEGER NOT NULL DEFAULT 0",
            "status": "TEXT NOT NULL DEFAULT 'open'",
        })

        await _ensure_columns(db, "alpha_suggestions", {
            "guild_id": "INTEGER NOT NULL DEFAULT 0",
            "user_id": "INTEGER NOT NULL DEFAULT 0",
            "text": "TEXT NOT NULL DEFAULT ''",
            "channel_id": "INTEGER NOT NULL DEFAULT 0",
            "message_id": "INTEGER",
            "status": "TEXT NOT NULL DEFAULT 'Pendente'",
            "admin_id": "INTEGER",
            "response": "TEXT NOT NULL DEFAULT ''",
            "created_at": "TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP",
        })

        await db.commit()

    log.info("Tabelas de comunidade verificadas.")


async def get_ticket_settings(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM ticket_settings WHERE guild_id = ?",
            (guild_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_ticket_categories(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT * FROM ticket_categories
            WHERE guild_id = ?
            ORDER BY id
        """, (guild_id,))
        return [dict(row) for row in await cursor.fetchall()]


async def get_ticket_record(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM ticket_records WHERE channel_id = ?",
            (channel_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def save_ticket_record(
    channel_id: int,
    guild_id: int,
    user_id: int,
    category_id: int,
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR REPLACE INTO ticket_records
                (channel_id, guild_id, user_id, category_id, status)
            VALUES (?, ?, ?, ?, 'open')
        """, (channel_id, guild_id, user_id, category_id))

        await db.execute("""
            INSERT OR REPLACE INTO tickets
                (channel_id, guild_id, user_id, status)
            VALUES (?, ?, ?, 'open')
        """, (channel_id, guild_id, user_id))

        await db.commit()


async def update_ticket_setting(guild_id: int, **values):
    allowed = {
        "panel_channel_id",
        "panel_message_id",
        "panel_title",
        "panel_description",
        "panel_color",
        "panel_image",
        "hours_text",
        "notices_text",
        "rating_channel_id",
    }

    values = {key: value for key, value in values.items() if key in allowed}

    if not values:
        return

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR IGNORE INTO ticket_settings (guild_id) VALUES (?)",
            (guild_id,),
        )

        columns = ", ".join(f"{key} = ?" for key in values)
        await db.execute(
            f"UPDATE ticket_settings SET {columns} WHERE guild_id = ?",
            (*values.values(), guild_id),
        )
        await db.commit()


# =========================================================
# UTILITÁRIOS
# =========================================================

def make_embed(title: str, description: str = "", color=PURPLE):
    embed = discord.Embed(
        title=title[:256],
        description=description[:4096],
        color=color,
    )
    embed.set_footer(text="Sr.Alpha • Family Alpha")
    return embed


def parse_color(value: str):
    value = value.strip().replace("#", "")

    if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return None

    return discord.Color(int(value, 16))


def is_admin(interaction: discord.Interaction):
    member = interaction.user

    return (
        interaction.guild is not None
        and isinstance(member, discord.Member)
        and (
            member.guild_permissions.administrator
            or member.guild_permissions.manage_guild
        )
    )


def build_ticket_embed(settings: dict | None):
    settings = settings or {}

    try:
        color = discord.Color(
            int(settings.get("panel_color") or 9533439)
        )
    except (ValueError, TypeError):
        color = PURPLE

    embed = discord.Embed(
        title=(settings.get("panel_title") or "Central de Atendimento")[:256],
        description=(
            settings.get("panel_description")
            or "Escolha uma categoria no menu abaixo."
        )[:4096],
        color=color,
    )

    if settings.get("hours_text"):
        embed.add_field(
            name="🕒 Horário de atendimento",
            value=settings["hours_text"][:1024],
            inline=False,
        )

    if settings.get("notices_text"):
        embed.add_field(
            name="📌 Informações importantes",
            value=settings["notices_text"][:1024],
            inline=False,
        )

    image = (settings.get("panel_image") or "").strip()

    if image.startswith(("https://", "http://")):
        embed.set_image(url=image)

    embed.set_footer(text="Sr.Alpha • Selecione uma categoria")
    return embed


# =========================================================
# AVALIAÇÃO DO ATENDIMENTO
# =========================================================

class RatingView(discord.ui.View):
    def __init__(self, channel_id: int, guild_id: int, attendant_id: int):
        super().__init__(timeout=604800)
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.attendant_id = attendant_id

        for stars in range(1, 6):
            button = discord.ui.Button(
                label=f"{stars} estrela{'s' if stars != 1 else ''}",
                emoji="⭐",
                style=discord.ButtonStyle.primary,
            )
            button.callback = self.make_callback(stars)
            self.add_item(button)

    def make_callback(self, stars: int):
        async def callback(interaction: discord.Interaction):
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute("""
                    SELECT user_id, rating
                    FROM ticket_records
                    WHERE channel_id = ?
                """, (self.channel_id,))
                record = await cursor.fetchone()

                if not record:
                    await interaction.response.send_message(
                        "Não encontrei este atendimento.",
                        ephemeral=True,
                    )
                    return

                user_id, previous_rating = record

                if interaction.user.id != user_id:
                    await interaction.response.send_message(
                        "Esta avaliação pertence a outra pessoa.",
                        ephemeral=True,
                    )
                    return

                if previous_rating is not None:
                    await interaction.response.send_message(
                        "Você já avaliou este atendimento. Obrigado!",
                        ephemeral=True,
                    )
                    return

                await db.execute("""
                    UPDATE ticket_records
                    SET rating = ?
                    WHERE channel_id = ?
                """, (stars, self.channel_id))
                await db.commit()

            guild = interaction.client.get_guild(self.guild_id)
            settings = await get_ticket_settings(self.guild_id)
            rating_channel = None

            if guild and settings and settings.get("rating_channel_id"):
                rating_channel = guild.get_channel(
                    settings["rating_channel_id"]
                )

            if isinstance(rating_channel, discord.TextChannel):
                attendant = guild.get_member(self.attendant_id)
                attendant_text = (
                    attendant.mention
                    if attendant
                    else f"`{self.attendant_id}`"
                )

                embed = make_embed(
                    "⭐ Nova avaliação",
                    f"**Cliente:** {interaction.user.mention}\n"
                    f"**Atendente:** {attendant_text}\n"
                    f"**Nota:** {'⭐' * stars} ({stars}/5)\n"
                    f"**Ticket:** `{self.channel_id}`",
                )

                try:
                    await rating_channel.send(embed=embed)
                except discord.HTTPException:
                    log.exception("Não consegui publicar a avaliação.")

            for item in self.children:
                item.disabled = True

            await interaction.response.edit_message(
                content=f"Obrigado pela avaliação! {'⭐' * stars}",
                view=self,
            )

        return callback


# =========================================================
# FECHAMENTO DE TICKET
# =========================================================

class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Fechar ticket",
        emoji="🔒",
        style=discord.ButtonStyle.danger,
        custom_id="sr_alpha:ticket_close",
    )
    async def close_ticket(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        channel = interaction.channel
        guild = interaction.guild
        member = interaction.user

        if not isinstance(channel, discord.TextChannel) or guild is None:
            await interaction.response.send_message(
                "Este botão só funciona dentro de um ticket.",
                ephemeral=True,
            )
            return

        record = await get_ticket_record(channel.id)

        if not record or record["status"] != "open":
            await interaction.response.send_message(
                "Este ticket já está fechado ou não está registrado.",
                ephemeral=True,
            )
            return

        categories = await get_ticket_categories(guild.id)
        category = next(
            (
                item for item in categories
                if item["id"] == record["category_id"]
            ),
            None,
        )

        is_opener = member.id == record["user_id"]
        staff_role_id = category["staff_role_id"] if category else None

        is_staff = False

        if isinstance(member, discord.Member):
            is_staff = (
                member.guild_permissions.manage_channels
                or member.guild_permissions.administrator
                or (
                    staff_role_id is not None
                    and any(
                        role.id == staff_role_id
                        for role in member.roles
                    )
                )
            )

        if not is_opener and not is_staff:
            await interaction.response.send_message(
                "Somente o autor do ticket ou a equipe responsável "
                "pode fechá-lo.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        attendant_id = member.id

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                UPDATE ticket_records
                SET status = 'closed',
                    attendant_id = ?,
                    closed_at = CURRENT_TIMESTAMP
                WHERE channel_id = ?
            """, (attendant_id, channel.id))

            await db.execute(
                "UPDATE tickets SET status = 'closed' WHERE channel_id = ?",
                (channel.id,),
            )
            await db.commit()

        try:
            await channel.send(
                embed=make_embed(
                    "🔒 Ticket fechado",
                    f"Fechado por {member.mention}.\n"
                    "O canal será mantido como registro.",
                )
            )
        except discord.HTTPException:
            log.exception("Não consegui enviar o aviso de fechamento.")

        opener = guild.get_member(record["user_id"])

        if opener:
            try:
                await channel.set_permissions(
                    opener,
                    view_channel=True,
                    send_messages=False,
                    read_message_history=True,
                )
            except discord.HTTPException:
                log.exception(
                    "Não consegui atualizar as permissões do ticket."
                )

            try:
                await opener.send(
                    embed=make_embed(
                        "⭐ Avalie seu atendimento",
                        f"Seu ticket em **{guild.name}** foi fechado.\n"
                        "Escolha uma nota de 1 a 5 estrelas.",
                    ),
                    view=RatingView(
                        channel.id,
                        guild.id,
                        attendant_id,
                    ),
                )
            except discord.HTTPException:
                log.info(
                    "Não foi possível enviar a avaliação por DM para %s.",
                    opener.id,
                )

        try:
            if not channel.name.startswith("fechado-"):
                await channel.edit(
                    name=f"fechado-{channel.name}"[:100]
                )
        except discord.HTTPException:
            log.exception("Não consegui renomear o ticket fechado.")

        await interaction.followup.send(
            "✅ Ticket fechado. O canal foi mantido como registro.",
            ephemeral=True,
        )


# =========================================================
# MENU DE CATEGORIAS E CRIAÇÃO DE TICKET
# =========================================================

class TicketCategorySelect(discord.ui.Select):
    def __init__(self, categories: list[dict]):
        options = []

        for item in categories[:25]:
            options.append(
                discord.SelectOption(
                    label=item["name"][:100],
                    value=str(item["id"]),
                    description=(
                        item.get("description") or item["name"]
                    )[:100],
                )
            )

        super().__init__(
            placeholder="Selecione o tipo de atendimento...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="sr_alpha:ticket_category_select",
        )

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user

        if guild is None or not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "Use o painel dentro do servidor.",
                ephemeral=True,
            )
            return

        try:
            selected_id = int(self.values[0])
        except (ValueError, IndexError):
            await interaction.response.send_message(
                "A categoria selecionada é inválida.",
                ephemeral=True,
            )
            return

        categories = await get_ticket_categories(guild.id)
        selected = next(
            (
                item for item in categories
                if item["id"] == selected_id
            ),
            None,
        )

        if selected is None:
            await interaction.response.send_message(
                "Essa categoria não existe mais. Avise a administração.",
                ephemeral=True,
            )
            return

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                SELECT channel_id
                FROM ticket_records
                WHERE guild_id = ?
                  AND user_id = ?
                  AND status = 'open'
            """, (guild.id, member.id))
            existing = await cursor.fetchone()

        if existing:
            existing_channel = guild.get_channel(existing[0])

            if existing_channel:
                await interaction.response.send_message(
                    f"Você já tem um ticket aberto: "
                    f"{existing_channel.mention}",
                    ephemeral=True,
                )
                return

            # O canal pode ter sido excluído manualmente.
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    UPDATE ticket_records
                    SET status = 'closed',
                        closed_at = CURRENT_TIMESTAMP
                    WHERE channel_id = ?
                """, (existing[0],))
                await db.execute(
                    "UPDATE tickets SET status = 'closed' WHERE channel_id = ?",
                    (existing[0],),
                )
                await db.commit()

        staff_role = guild.get_role(selected["staff_role_id"])

        if staff_role is None:
            await interaction.response.send_message(
                "O cargo responsável não existe mais. "
                "Peça à administração para configurar a categoria novamente.",
                ephemeral=True,
            )
            return

        bot_member = guild.me

        if bot_member is None:
            await interaction.response.send_message(
                "Não consegui identificar o membro do bot no servidor.",
                ephemeral=True,
            )
            return

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True,
            ),
            staff_role: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_messages=True,
            ),
            bot_member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
                embed_links=True,
                attach_files=True,
            ),
        }

        parent = None
        parent_id = selected.get("discord_category_id")

        if parent_id:
            candidate = guild.get_channel(parent_id)

            if isinstance(candidate, discord.CategoryChannel):
                parent = candidate

        safe_name = re.sub(
            r"[^a-zA-Z0-9-]",
            "-",
            member.name.lower(),
        ).strip("-")[:65] or "usuario"

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            channel = await guild.create_text_channel(
                name=f"ticket-{safe_name}",
                category=parent,
                overwrites=overwrites,
                topic=(
                    f"Ticket de {member.id} | "
                    f"Categoria: {selected['name']}"
                )[:1024],
                reason=f"Ticket aberto por {member} ({member.id})",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Não tenho permissão para criar canais. "
                "Conceda ao Sr.Alpha a permissão **Gerenciar canais**.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as error:
            log.exception("Erro ao criar canal de ticket.")

            await interaction.followup.send(
                "❌ O Discord não conseguiu criar o ticket.\n"
                f"Código: `{error.code}` | HTTP: `{error.status}`",
                ephemeral=True,
            )
            return

        try:
            await save_ticket_record(
                channel.id,
                guild.id,
                member.id,
                selected["id"],
            )
        except Exception:
            log.exception("Não consegui registrar o ticket no banco.")

            try:
                await channel.delete(
                    reason="Falha ao registrar ticket no banco de dados"
                )
            except discord.HTTPException:
                pass

            await interaction.followup.send(
                "❌ O ticket não pôde ser registrado no banco de dados.",
                ephemeral=True,
            )
            return

        welcome = (
            selected.get("welcome_text")
            or "Explique como podemos ajudar."
        )

        embed = make_embed(
            f"{selected.get('emoji') or '🎫'} {selected['name']}",
            f"{member.mention}, seu atendimento começou.\n\n{welcome}",
        )
        embed.add_field(
            name="Equipe responsável",
            value=staff_role.mention,
            inline=False,
        )

        try:
            await channel.send(
                content=f"{member.mention} {staff_role.mention}",
                embed=embed,
                view=TicketCloseView(),
                allowed_mentions=discord.AllowedMentions(
                    users=True,
                    roles=True,
                ),
            )
        except discord.HTTPException:
            log.exception("Canal criado, mas não consegui enviar a mensagem inicial.")

            await interaction.followup.send(
                f"⚠️ O canal foi criado: {channel.mention}, mas não consegui "
                "enviar a mensagem inicial. Verifique as permissões do bot.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"✅ Seu ticket foi criado: {channel.mention}",
            ephemeral=True,
        )


class TicketPanelView(discord.ui.View):
    def __init__(self, categories: list[dict]):
        super().__init__(timeout=None)

        if categories:
            self.add_item(TicketCategorySelect(categories))


# =========================================================
# SUGESTÕES
# =========================================================

class SuggestionView(discord.ui.View):
    def __init__(self, suggestion_id: int = 0):
        super().__init__(timeout=None)
        self.suggestion_id = suggestion_id

    @discord.ui.button(
        label="Apoiar",
        emoji="👍",
        style=discord.ButtonStyle.success,
        custom_id="sr_alpha:suggestion_yes",
    )
    async def support(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        try:
            await interaction.message.add_reaction("👍")
        except discord.HTTPException:
            log.exception("Não consegui adicionar reação de apoio.")

        await interaction.response.send_message(
            "👍 Obrigado por apoiar a sugestão!",
            ephemeral=True,
        )

    @discord.ui.button(
        label="Não apoiar",
        emoji="👎",
        style=discord.ButtonStyle.secondary,
        custom_id="sr_alpha:suggestion_no",
    )
    async def oppose(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        try:
            await interaction.message.add_reaction("👎")
        except discord.HTTPException:
            log.exception("Não consegui adicionar reação contrária.")

        await interaction.response.send_message(
            "👎 Seu voto foi registrado!",
            ephemeral=True,
        )


# =========================================================
# COG E COMANDOS
# =========================================================

class Community(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # -----------------------------------------------------
    # SUGERIR
    # -----------------------------------------------------

    @app_commands.command(
        name="sugerir",
        description="Envie uma sugestão para a equipe do servidor.",
    )
    @app_commands.describe(
        texto="Explique sua sugestão com detalhes."
    )
    async def sugerir(
        self,
        interaction: discord.Interaction,
        texto: app_commands.Range[str, 10, 1800],
    ):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "Use este comando dentro do servidor.",
                ephemeral=True,
            )
            return

        channel_id = int(
            getattr(config, "SUGGESTION_CHANNEL_ID", 0) or 0
        )
        channel = guild.get_channel(channel_id) if channel_id else None

        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "O canal de sugestões não está configurado. "
                "Confira `SUGGESTION_CHANNEL_ID` nas variáveis do Railway.",
                ephemeral=True,
            )
            return

        embed = make_embed("💡 Nova sugestão", texto)
        embed.add_field(
            name="Autor",
            value=interaction.user.mention,
            inline=True,
        )
        embed.add_field(
            name="Estado",
            value="🟡 Pendente",
            inline=True,
        )

        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            message = await channel.send(embed=embed)
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Não tenho permissão para enviar mensagens no canal "
                "de sugestões.",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            log.exception("Não consegui publicar a sugestão.")

            await interaction.followup.send(
                "❌ Não consegui publicar a sugestão. "
                "Consulte os logs do Railway.",
                ephemeral=True,
            )
            return

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute("""
                    INSERT INTO alpha_suggestions
                        (guild_id, user_id, text, channel_id, message_id)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    guild.id,
                    interaction.user.id,
                    texto,
                    channel.id,
                    message.id,
                ))
                suggestion_id = cursor.lastrowid
                await db.commit()
        except Exception:
            log.exception("Não consegui salvar a sugestão no banco.")

            await interaction.followup.send(
                "⚠️ A mensagem foi publicada, mas não consegui salvar "
                "o protocolo no banco de dados.",
                ephemeral=True,
            )
            return

        embed.add_field(
            name="Protocolo",
            value=f"`#{suggestion_id}`",
            inline=True,
        )

        try:
            await message.edit(
                embed=embed,
                view=SuggestionView(suggestion_id),
            )
        except discord.HTTPException:
            log.exception("Não consegui atualizar os botões da sugestão.")

        await interaction.followup.send(
            f"✅ Sugestão enviada! Protocolo: `#{suggestion_id}`",
            ephemeral=True,
        )

    # -----------------------------------------------------
    # STATUS DA SUGESTÃO
    # -----------------------------------------------------

    @app_commands.command(
        name="status_sugestao",
        description="Aceite ou recuse uma sugestão e registre sua decisão.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.choices(status=[
        app_commands.Choice(name="Aceitar", value="Aceita"),
        app_commands.Choice(name="Recusar", value="Recusada"),
        app_commands.Choice(name="Em análise", value="Em análise"),
    ])
    @app_commands.describe(
        protocolo="Número do protocolo, sem o #.",
        status="Nova situação da sugestão.",
        resposta="Justificativa ou mensagem para o autor.",
    )
    async def status_sugestao(
        self,
        interaction: discord.Interaction,
        protocolo: app_commands.Range[int, 1, 999999999],
        status: app_commands.Choice[str],
        resposta: app_commands.Range[str, 1, 1000],
    ):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "Use este comando no servidor.",
                ephemeral=True,
            )
            return

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                SELECT user_id, channel_id, message_id, text
                FROM alpha_suggestions
                WHERE id = ? AND guild_id = ?
            """, (protocolo, guild.id))
            record = await cursor.fetchone()

            if not record:
                await interaction.response.send_message(
                    "Não encontrei esse protocolo.",
                    ephemeral=True,
                )
                return

            user_id, channel_id, message_id, suggestion_text = record

            await db.execute("""
                UPDATE alpha_suggestions
                SET status = ?, admin_id = ?, response = ?
                WHERE id = ? AND guild_id = ?
            """, (
                status.value,
                interaction.user.id,
                resposta,
                protocolo,
                guild.id,
            ))
            await db.commit()

        await interaction.response.defer(ephemeral=True, thinking=True)

        channel = guild.get_channel(channel_id)

        if isinstance(channel, discord.TextChannel) and message_id:
            try:
                message = await channel.fetch_message(message_id)

                embed = (
                    message.embeds[0].copy()
                    if message.embeds
                    else make_embed("💡 Sugestão", suggestion_text)
                )

                found_status = False

                for index, field in enumerate(embed.fields):
                    if field.name == "Estado":
                        embed.set_field_at(
                            index,
                            name="Estado",
                            value=f"**{status.value}**",
                            inline=True,
                        )
                        found_status = True
                        break

                if not found_status:
                    embed.add_field(
                        name="Estado",
                        value=f"**{status.value}**",
                        inline=True,
                    )

                # Evita acumular várias decisões ao editar uma sugestão.
                existing_decision = next(
                    (
                        index for index, field in enumerate(embed.fields)
                        if field.name == "Decisão da administração"
                    ),
                    None,
                )

                decision_text = (
                    f"**Responsável:** {interaction.user.mention}\n"
                    f"**Resposta:** {resposta}"
                )

                if existing_decision is not None:
                    embed.set_field_at(
                        existing_decision,
                        name="Decisão da administração",
                        value=decision_text,
                        inline=False,
                    )
                else:
                    embed.add_field(
                        name="Decisão da administração",
                        value=decision_text,
                        inline=False,
                    )

                await message.edit(embed=embed)

            except discord.NotFound:
                log.warning(
                    "A mensagem da sugestão #%s não existe mais.",
                    protocolo,
                )
            except discord.HTTPException:
                log.exception("Não consegui atualizar a mensagem da sugestão.")

        try:
            user = await self.bot.fetch_user(user_id)
            await user.send(
                embed=make_embed(
                    f"📣 Atualização da sugestão #{protocolo}",
                    f"**Estado:** {status.value}\n"
                    f"**Resposta da equipe:** {resposta}",
                )
            )
        except discord.HTTPException:
            log.info(
                "Não consegui enviar DM ao autor da sugestão #%s.",
                protocolo,
            )

        await interaction.followup.send(
            f"✅ Sugestão `#{protocolo}` atualizada para **{status.value}**.",
            ephemeral=True,
        )

    # -----------------------------------------------------
    # CONFIGURAR CANAL DE AVALIAÇÕES
    # -----------------------------------------------------

    @app_commands.command(
        name="ticket_configurar",
        description="Define o canal onde as avaliações serão publicadas.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticket_configurar(
        self,
        interaction: discord.Interaction,
        canal_avaliacoes: discord.TextChannel,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Use este comando no servidor.",
                ephemeral=True,
            )
            return

        await update_ticket_setting(
            interaction.guild.id,
            rating_channel_id=canal_avaliacoes.id,
        )

        await interaction.response.send_message(
            f"⭐ As avaliações serão publicadas em "
            f"{canal_avaliacoes.mention}.",
            ephemeral=True,
        )

    # -----------------------------------------------------
    # ADICIONAR CATEGORIA
    # -----------------------------------------------------

    @app_commands.command(
        name="ticket_categoria_adicionar",
        description="Cria uma categoria de atendimento com sua equipe.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        nome="Nome da categoria.",
        cargo="Cargo que atenderá os tickets desta categoria.",
        emoji="Emoji exibido nas mensagens do ticket.",
        descricao="Descrição curta exibida no menu.",
        categoria_canais="Categoria do Discord onde os tickets serão criados.",
        mensagem_inicial="Mensagem mostrada ao abrir o ticket.",
    )
    async def ticket_categoria_adicionar(
        self,
        interaction: discord.Interaction,
        nome: app_commands.Range[str, 2, 80],
        cargo: discord.Role,
        emoji: str = "🎫",
        descricao: str = "Fale com nossa equipe.",
        categoria_canais: discord.CategoryChannel | None = None,
        mensagem_inicial: str = "Explique como podemos ajudar.",
    ):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "Use este comando no servidor.",
                ephemeral=True,
            )
            return

        nome = nome.strip()

        if not nome:
            await interaction.response.send_message(
                "Informe um nome válido.",
                ephemeral=True,
            )
            return

        if cargo.is_default():
            await interaction.response.send_message(
                "Escolha um cargo específico para atender os tickets.",
                ephemeral=True,
            )
            return

        emoji = (emoji or "🎫").strip()[:20] or "🎫"
        descricao = (descricao or nome).strip()[:100]
        mensagem_inicial = (
            mensagem_inicial or "Explique como podemos ajudar."
        ).strip()[:1000]

        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""
                    INSERT INTO ticket_categories
                        (guild_id, name, emoji, description, staff_role_id,
                         discord_category_id, welcome_text)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    guild.id,
                    nome,
                    emoji,
                    descricao,
                    cargo.id,
                    categoria_canais.id if categoria_canais else None,
                    mensagem_inicial,
                ))
                await db.commit()

        except aiosqlite.IntegrityError:
            await interaction.response.send_message(
                "Já existe uma categoria com esse nome.",
                ephemeral=True,
            )
            return

        except Exception:
            log.exception("Erro ao adicionar categoria de ticket.")

            await interaction.response.send_message(
                "Não consegui salvar a categoria. Consulte os logs do Railway.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            embed=make_embed(
                "✅ Categoria criada",
                f"**Categoria:** {emoji} {nome}\n"
                f"**Equipe:** {cargo.mention}\n"
                f"**Categoria de canais:** "
                f"{categoria_canais.name if categoria_canais else 'Não definida'}\n\n"
                "Publique novamente o painel usando `/painel_tickets`.",
            ),
            ephemeral=True,
        )

    # -----------------------------------------------------
    # REMOVER CATEGORIA
    # -----------------------------------------------------

    @app_commands.command(
        name="ticket_categoria_remover",
        description="Remove uma categoria de atendimento.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticket_categoria_remover(
        self,
        interaction: discord.Interaction,
        nome: str,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Use este comando no servidor.",
                ephemeral=True,
            )
            return

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                DELETE FROM ticket_categories
                WHERE guild_id = ? AND name = ?
            """, (interaction.guild.id, nome.strip()))
            await db.commit()
            deleted = cursor.rowcount

        if not deleted:
            await interaction.response.send_message(
                "Não encontrei uma categoria com esse nome.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(
            f"✅ Categoria **{nome}** removida.\n"
            "Publique novamente o painel para atualizar o menu.",
            ephemeral=True,
        )

    # -----------------------------------------------------
    # PUBLICAR PAINEL
    # -----------------------------------------------------

    @app_commands.command(
        name="painel_tickets",
        description="Publica o painel de atendimento no canal escolhido.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(
        canal="Canal onde o painel será publicado.",
        titulo="Título do painel.",
        descricao="Texto de apresentação do painel.",
        cor="Cor hexadecimal, exemplo: #9167FF.",
        imagem="URL de uma imagem opcional.",
        horarios="Horário de atendimento (opcional).",
        avisos="Informações importantes (opcional).",
    )
    async def painel_tickets(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        titulo: str = "🎫 Central de Atendimento",
        descricao: str = "Selecione abaixo a categoria para abrir seu ticket.",
        cor: str = "#9167FF",
        imagem: str = "",
        horarios: str = "",
        avisos: str = "",
    ):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "Use este comando no servidor.",
                ephemeral=True,
            )
            return

        categories = await get_ticket_categories(guild.id)

        if not categories:
            await interaction.response.send_message(
                "Você ainda não criou categorias.\n"
                "Use primeiro `/ticket_categoria_adicionar`.",
                ephemeral=True,
            )
            return

        parsed_color = parse_color(cor)

        if parsed_color is None:
            await interaction.response.send_message(
                "Cor inválida. Use um hexadecimal, como `#9167FF`.",
                ephemeral=True,
            )
            return

        imagem = (imagem or "").strip()

        if imagem and not imagem.startswith(("https://", "http://")):
            await interaction.response.send_message(
                "A imagem precisa ser uma URL começando com `https://`.",
                ephemeral=True,
            )
            return

        titulo = (titulo or "🎫 Central de Atendimento").strip()
        descricao = (
            descricao or "Selecione abaixo a categoria para abrir seu ticket."
        ).strip()

        if not titulo or not descricao:
            await interaction.response.send_message(
                "O título e a descrição não podem ficar vazios.",
                ephemeral=True,
            )
            return

        settings = {
            "panel_title": titulo[:256],
            "panel_description": descricao[:4000],
            "panel_color": parsed_color.value,
            "panel_image": imagem[:500],
            "hours_text": (horarios or "")[:1024],
            "notices_text": (avisos or "")[:1024],
            "panel_channel_id": canal.id,
        }

        view = TicketPanelView(categories)

        # Responde antes da operação de rede para evitar expiração da interação.
        await interaction.response.defer(ephemeral=True, thinking=True)

        try:
            message = await canal.send(
                embed=build_ticket_embed(settings),
                view=view,
            )

        except discord.Forbidden:
            log.exception(
                "Sr.Alpha não tem permissão para publicar no canal %s.",
                canal.id,
            )
            await interaction.followup.send(
                "❌ Não tenho permissão para publicar nesse canal.\n"
                "Confira **Ver canal**, **Enviar mensagens** e "
                "**Incorporar links** nas permissões do Sr.Alpha.",
                ephemeral=True,
            )
            return

        except discord.HTTPException as error:
            log.exception("Erro HTTP ao publicar o painel de tickets.")
            await interaction.followup.send(
                "❌ O Discord rejeitou o painel.\n"
                f"**Código:** `{error.code}`\n"
                f"**Status HTTP:** `{error.status}`\n"
                "Consulte os logs do Railway para ver o erro completo.",
                ephemeral=True,
            )
            return

        except Exception:
            log.exception("Erro inesperado ao publicar o painel.")
            await interaction.followup.send(
                "❌ Ocorreu um erro inesperado ao publicar o painel. "
                "Consulte os logs do Railway.",
                ephemeral=True,
            )
            return

        try:
            await update_ticket_setting(
                guild.id,
                **settings,
                panel_message_id=message.id,
            )
        except Exception:
            log.exception(
                "Painel publicado, mas não consegui salvar suas configurações."
            )
            await interaction.followup.send(
                f"⚠️ O painel foi publicado em {canal.mention}, "
                "mas não consegui salvar suas configurações no banco.",
                ephemeral=True,
            )
            return

        await interaction.followup.send(
            f"✅ Painel publicado com sucesso em {canal.mention}.\n"
            "Se você alterar as categorias, publique o painel novamente.",
            ephemeral=True,
        )

    # -----------------------------------------------------
    # COMANDO ANTIGO /ticket
    # -----------------------------------------------------

    @app_commands.command(
        name="ticket",
        description="Mostra onde abrir um atendimento.",
    )
    async def ticket(self, interaction: discord.Interaction):
        guild = interaction.guild

        if guild is None:
            await interaction.response.send_message(
                "Use este comando dentro do servidor.",
                ephemeral=True,
            )
            return

        settings = await get_ticket_settings(guild.id)
        channel_id = settings.get("panel_channel_id") if settings else None
        channel = guild.get_channel(channel_id) if channel_id else None

        if isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                f"🎫 Para abrir um atendimento, acesse {channel.mention}.",
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                "O painel ainda não foi publicado. "
                "Peça à administração para usar `/painel_tickets`.",
                ephemeral=True,
            )


# =========================================================
# CARREGAMENTO DO MÓDULO
# =========================================================

async def setup(bot: commands.Bot):
    await init_community_tables()
    await bot.add_cog(Community(bot))

    # Mantém o botão de fechamento funcional após reiniciar o bot.
    bot.add_view(TicketCloseView())

    # Mantém os botões das sugestões antigas funcionais.
    bot.add_view(SuggestionView())

    # Restaura o menu do painel do servidor configurado.
    guild_id = int(getattr(config, "GUILD_ID", 0) or 0)

    if guild_id:
        categories = await get_ticket_categories(guild_id)

        if categories:
            bot.add_view(TicketPanelView(categories))

    log.info("Sistema de comunidade e tickets carregado.")
