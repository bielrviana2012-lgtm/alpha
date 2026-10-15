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

async def init_community_tables():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_settings (
                guild_id INTEGER PRIMARY KEY,
                panel_channel_id INTEGER,
                panel_message_id INTEGER,
                panel_title TEXT NOT NULL DEFAULT 'Central de Atendimento',
                panel_description TEXT NOT NULL DEFAULT
                    'Escolha no menu abaixo a categoria para a qual deseja atendimento.',
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

        # Compatibilidade com a tabela antiga de tickets.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open'
            )
        """)

        # Tabela própria para não depender da estrutura antiga
        # do sistema de sugestões.
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

        await db.commit()


async def get_ticket_settings(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM ticket_settings WHERE guild_id = ?",
            (guild_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_ticket_categories(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            """
            SELECT * FROM ticket_categories
            WHERE guild_id = ?
            ORDER BY id
            """,
            (guild_id,),
        )
        return [dict(row) for row in await cur.fetchall()]


async def get_ticket_record(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM ticket_records WHERE channel_id = ?",
            (channel_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def save_ticket_record(
    channel_id: int,
    guild_id: int,
    user_id: int,
    category_id: int,
):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR REPLACE INTO ticket_records
                (channel_id, guild_id, user_id, category_id, status)
            VALUES (?, ?, ?, ?, 'open')
            """,
            (channel_id, guild_id, user_id, category_id),
        )

        await db.execute(
            """
            INSERT OR REPLACE INTO tickets
                (channel_id, guild_id, user_id, status)
            VALUES (?, ?, ?, 'open')
            """,
            (channel_id, guild_id, user_id),
        )

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

    values = {
        key: value
        for key, value in values.items()
        if key in allowed
    }

    if not values:
        return

    columns = ", ".join(f"{key} = ?" for key in values)
    params = list(values.values()) + [guild_id]

    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT OR IGNORE INTO ticket_settings (guild_id)
            VALUES (?)
            """,
            (guild_id,),
        )

        await db.execute(
            f"UPDATE ticket_settings SET {columns} WHERE guild_id = ?",
            params,
        )
        await db.commit()


def is_admin(member: discord.Member) -> bool:
    return (
        member.guild_permissions.administrator
        or member.guild_permissions.manage_guild
    )


def make_embed(
    title: str,
    description: str = "",
    color: discord.Color = PURPLE,
):
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
    )
    embed.set_footer(text="Sr.Alpha • Family Alpha")
    return embed


def parse_color(value: str) -> discord.Color | None:
    value = value.strip().replace("#", "")

    if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        return None

    return discord.Color(int(value, 16))# =========================================================
# PAINEL DE TICKETS
# =========================================================

def build_ticket_embed(settings: dict | None):
    settings = settings or {}

    color_value = settings.get("panel_color") or 9533439
    embed = discord.Embed(
        title=settings.get("panel_title") or "Central de Atendimento",
        description=(
            settings.get("panel_description")
            or "Escolha uma categoria no menu abaixo."
        ),
        color=discord.Color(color_value),
    )

    hours = settings.get("hours_text")
    notices = settings.get("notices_text")
    image = settings.get("panel_image")

    if hours:
        embed.add_field(
            name="🕒 Horário de atendimento",
            value=hours[:1024],
            inline=False,
        )

    if notices:
        embed.add_field(
            name="📌 Informações importantes",
            value=notices[:1024],
            inline=False,
        )

    if image and image.startswith(("https://", "http://")):
        embed.set_image(url=image)

    embed.set_footer(text="Sr.Alpha • Selecione uma categoria para continuar")
    return embed


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

        opener = guild.get_member(record["user_id"])
        category_id = record["category_id"]
        categories = await get_ticket_categories(guild.id)
        ticket_category = next(
            (item for item in categories if item["id"] == category_id),
            None,
        )

        is_opener = interaction.user.id == record["user_id"]
        staff_role_id = (
            ticket_category["staff_role_id"]
            if ticket_category else None
        )
        is_staff = (
            interaction.user.guild_permissions.manage_channels
            or interaction.user.guild_permissions.administrator
            or (
                staff_role_id is not None
                and isinstance(interaction.user, discord.Member)
                and any(
                    role.id == staff_role_id
                    for role in interaction.user.roles
                )
            )
        )

        if not is_opener and not is_staff:
            await interaction.response.send_message(
                "Somente quem abriu o ticket ou a equipe responsável "
                "pode fechá-lo.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)

        # O responsável pelo fechamento será avaliado.
        attendant_id = interaction.user.id

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                UPDATE ticket_records
                SET status = 'closed',
                    attendant_id = ?,
                    closed_at = CURRENT_TIMESTAMP
                WHERE channel_id = ?
                """,
                (attendant_id, channel.id),
            )
            await db.execute(
                "UPDATE tickets SET status = 'closed' WHERE channel_id = ?",
                (channel.id,),
            )
            await db.commit()

        await channel.send(
            embed=make_embed(
                "🔒 Ticket fechado",
                f"Fechado por {interaction.user.mention}.\n"
                "O canal será mantido para registro da equipe.",
            )
        )

        # Impede que o autor continue enviando mensagens.
        if opener:
            try:
                await channel.set_permissions(
                    opener,
                    view_channel=True,
                    send_messages=False,
                    read_message_history=True,
                )
            except discord.Forbidden:
                log.warning(
                    "Sem permissão para atualizar o ticket %s",
                    channel.id,
                )

        try:
            await channel.edit(
                name=f"fechado-{channel.name}"[:100]
            )
        except discord.HTTPException:
            pass

        # Solicita a avaliação em mensagem privada.
        try:
            await opener.send(
                embed=make_embed(
                    "⭐ Avalie seu atendimento",
                    f"Seu ticket em **{guild.name}** foi fechado.\n\n"
                    "Como foi o atendimento recebido? "
                    "Escolha uma nota de 1 a 5 estrelas abaixo.",
                ),
                view=RatingView(channel.id, guild.id, attendant_id),
            )
        except (discord.Forbidden, AttributeError):
            await channel.send(
                "Não consegui enviar a avaliação por mensagem privada. "
                "Verifique se suas DMs estão abertas."
            )

        await interaction.followup.send(
            "Ticket fechado! A avaliação foi solicitada por mensagem privada.",
            ephemeral=True,
        )


class RatingView(discord.ui.View):
    def __init__(
        self,
        channel_id: int,
        guild_id: int,
        attendant_id: int,
    ):
        super().__init__(timeout=604800)
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.attendant_id = attendant_id

        for stars in range(1, 6):
            button = discord.ui.Button(
                label=f"{stars} estrela{'s' if stars > 1 else ''}",
                emoji="⭐",
                style=discord.ButtonStyle.primary,
                custom_id=f"sr_alpha:rating:{channel_id}:{stars}",
            )
            button.callback = self.make_callback(stars)
            self.add_item(button)

    def make_callback(self, stars: int):
        async def callback(interaction: discord.Interaction):
            async with aiosqlite.connect(DB_PATH) as db:
                cur = await db.execute(
                    """
                    SELECT user_id, status, rating
                    FROM ticket_records
                    WHERE channel_id = ?
                    """,
                    (self.channel_id,),
                )
                record = await cur.fetchone()

                if not record:
                    await interaction.response.send_message(
                        "Não encontrei esse atendimento no banco de dados.",
                        ephemeral=True,
                    )
                    return

                user_id, status, previous_rating = record

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

                await db.execute(
                    """
                    UPDATE ticket_records
                    SET rating = ?
                    WHERE channel_id = ?
                    """,
                    (stars, self.channel_id),
                )
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
                    attendant.mention if attendant else f"`{self.attendant_id}`"
                )

                embed = make_embed(
                    "⭐ Nova avaliação de atendimento",
                    f"**Cliente:** {interaction.user.mention}\n"
                    f"**Atendente:** {attendant_text}\n"
                    f"**Nota:** {'⭐' * stars} ({stars}/5)\n"
                    f"**Ticket:** `{self.channel_id}`",
                )
                try:
                    await rating_channel.send(embed=embed)
                except discord.Forbidden:
                    log.warning(
                        "Sem permissão para publicar avaliações em %s",
                        rating_channel.id,
                    )

            for item in self.children:
                item.disabled = True

            await interaction.response.edit_message(
                content=f"Obrigado por avaliar! Sua nota: {'⭐' * stars}.",
                view=self,
            )

        return callback


class TicketCategorySelect(discord.ui.Select):
    def __init__(self, categories: list[dict]):
        options = []

        for item in categories[:25]:
            emoji = item.get("emoji") or "🎫"
            description = item.get("description") or item["name"]
            options.append(
                discord.SelectOption(
                    label=item["name"][:100],
                    value=str(item["id"]),
                    description=description[:100],
                    emoji=emoji,
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
        if interaction.guild is None:
            await interaction.response.send_message(
                "Use este painel dentro do servidor.",
                ephemeral=True,
            )
            return

        category_id = int(self.values[0])
        categories = await get_ticket_categories(interaction.guild.id)
        selected = next(
            (item for item in categories if item["id"] == category_id),
            None,
        )

        if not selected:
            await interaction.response.send_message(
                "Essa categoria não existe mais. Avise a administração.",
                ephemeral=True,
            )
            return

        guild = interaction.guild
        member = interaction.user

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                """
                SELECT channel_id FROM ticket_records
                WHERE guild_id = ? AND user_id = ? AND status = 'open'
                """,
                (guild.id, member.id),
            )
            existing = await cur.fetchone()

        if existing:
            existing_channel = guild.get_channel(existing[0])
            if existing_channel:
                await interaction.response.send_message(
                    f"Você já tem um ticket aberto: {existing_channel.mention}",
                    ephemeral=True,
                )
                return

        staff_role = guild.get_role(selected["staff_role_id"])
        if staff_role is None:
            await interaction.response.send_message(
                "O cargo responsável desta categoria não existe mais. "
                "Peça à administração para configurá-lo novamente.",
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
        }

        bot_member = guild.me
        if bot_member:
            overwrites[bot_member] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                manage_channels=True,
            )

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
        ).strip("-")[:70] or "usuario"

        try:
            channel = await guild.create_text_channel(
                name=f"ticket-{safe_name}",
                category=parent,
                overwrites=overwrites,
                topic=f"Ticket de {member.id} | Categoria: {selected['name']}",
                reason=f"Ticket aberto por {member} ({member.id})",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "Não tenho permissão para criar canais de ticket.",
                ephemeral=True,
            )
            return

        await save_ticket_record(
            channel.id,
            guild.id,
            member.id,
            selected["id"],
        )

        await interaction.response.send_message(
            f"Ticket criado: {channel.mention}",
            ephemeral=True,
        )

        welcome_text = (
            selected.get("welcome_text")
            or "Explique como podemos ajudar."
        )

        embed = make_embed(
            f"{selected.get('emoji', '🎫')} {selected['name']}",
            f"{member.mention}, seu atendimento começou.\n\n"
            f"{welcome_text}",
        )
        embed.add_field(
            name="Equipe responsável",
            value=staff_role.mention,
            inline=False,
        )

        await channel.send(
            content=f"{member.mention} {staff_role.mention}",
            embed=embed,
            view=TicketCloseView(),
            allowed_mentions=discord.AllowedMentions(
                users=True,
                roles=True,
            ),
        )


class TicketPanelView(discord.ui.View):
    def __init__(self, categories: list[dict]):
        super().__init__(timeout=None)
        if categories:
            self.add_item(TicketCategorySelect(categories))# =========================================================
# VOTAÇÃO DE SUGESTÕES
# =========================================================

class SuggestionView(discord.ui.View):
    def __init__(self, suggestion_id: int):
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
        embed = interaction.message.embeds[0]
        votes = {"👍": 0, "👎": 0}

        for reaction in interaction.message.reactions:
            if str(reaction.emoji) in votes:
                votes[str(reaction.emoji)] = reaction.count

        await interaction.response.send_message(
            "Obrigado por apoiar a sugestão!",
            ephemeral=True,
        )

        try:
            await interaction.message.add_reaction("👍")
        except discord.HTTPException:
            pass

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
        await interaction.response.send_message(
            "Seu voto foi registrado!",
            ephemeral=True,
        )

        try:
            await interaction.message.add_reaction("👎")
        except discord.HTTPException:
            pass


# =========================================================
# COG PRINCIPAL
# =========================================================

class Community(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await init_community_tables()

    # -----------------------------------------------------
    # SUGESTÕES
    # -----------------------------------------------------

    @app_commands.command(
        name="sugerir",
        description="Envie uma sugestão para a equipe do servidor.",
    )
    @app_commands.describe(
        texto="Explique sua sugestão com detalhes.",
    )
    async def sugerir(
        self,
        interaction: discord.Interaction,
        texto: app_commands.Range[str, 10, 1800],
    ):
        channel_id = getattr(config, "SUGGESTION_CHANNEL_ID", 0)

        if not channel_id:
            await interaction.response.send_message(
                "O canal de sugestões não está configurado.",
                ephemeral=True,
            )
            return

        channel = interaction.guild.get_channel(channel_id) if interaction.guild else None

        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                "O canal de sugestões não foi encontrado.",
                ephemeral=True,
            )
            return

        embed = make_embed(
            "💡 Nova sugestão",
            texto,
        )
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

        try:
            message = await channel.send(embed=embed)
        except discord.Forbidden:
            await interaction.response.send_message(
                "Não tenho permissão para publicar sugestões nesse canal.",
                ephemeral=True,
            )
            return

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                """
                INSERT INTO alpha_suggestions
                    (guild_id, user_id, text, channel_id, message_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    interaction.guild_id,
                    interaction.user.id,
                    texto,
                    channel.id,
                    message.id,
                ),
            )
            suggestion_id = cur.lastrowid
            await db.commit()

        embed.add_field(
            name="Protocolo",
            value=f"`#{suggestion_id}`",
            inline=True,
        )

        await message.edit(
            embed=embed,
            view=SuggestionView(suggestion_id),
        )
