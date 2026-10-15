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

# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------

async def init_community_tables():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ticket_settings (
                guild_id INTEGER PRIMARY KEY,
                panel_channel_id INTEGER,
                panel_message_id INTEGER,
                panel_title TEXT NOT NULL DEFAULT 'Central de Atendimento',
                panel_description TEXT NOT NULL DEFAULT 'Escolha no menu abaixo a categoria para a qual deseja atendimento.',
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
                welcome_text TEXT NOT NULL DEFAULT 'Explique como podemos ajudar.',
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
        # Legacy compatibility: preserve the old tickets table if it exists.
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tickets (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'open'
            )
        """)
        await db.commit()


async def get_ticket_settings(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM ticket_settings WHERE guild_id=?", (guild_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_ticket_categories(guild_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM ticket_categories WHERE guild_id=? ORDER BY id",
            (guild_id,),
        )
        return [dict(row) for row in await cur.fetchall()]


async def get_ticket_record(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM ticket_records WHERE channel_id=?", (channel_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None


def parse_color(value: str) -> discord.Color:
    cleaned = value.strip().replace("#", "")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", cleaned):
        raise ValueError("Use uma cor hexadecimal de 6 caracteres, por exemplo #9167FF.")
    return discord.Color(int(cleaned, 16))


# ---------------------------------------------------------------------------
# SUGGESTIONS (preserved)
# ---------------------------------------------------------------------------

class SuggestionView(discord.ui.View):
    def __init__(self, suggestion_id: int):
        super().__init__(timeout=None)
        self.suggestion_id = suggestion_id

    async def vote(self, interaction: discord.Interaction, vote: int):
        if not interaction.guild_id or not interaction.message:
            return await interaction.response.send_message(
                "Este botão só funciona dentro do servidor.", ephemeral=True
            )
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT id FROM suggestions WHERE message_id=? AND guild_id=?",
                (interaction.message.id, interaction.guild_id),
            )
            row = await cur.fetchone()
            if not row:
                return await interaction.response.send_message(
                    "Não encontrei esta sugestão no banco de dados.", ephemeral=True
                )
            sid = row[0]
            cur = await db.execute(
                "SELECT vote FROM suggestion_votes WHERE suggestion_id=? AND user_id=?",
                (sid, interaction.user.id),
            )
            previous = await cur.fetchone()
            if previous and previous[0] == vote:
                return await interaction.response.send_message(
                    "Você já votou dessa forma. Seu voto foi mantido.", ephemeral=True
                )
            await db.execute(
                """INSERT INTO suggestion_votes(suggestion_id,user_id,vote)
                VALUES(?,?,?) ON CONFLICT(suggestion_id,user_id)
                DO UPDATE SET vote=excluded.vote""",
                (sid, interaction.user.id, vote),
            )
            cur = await db.execute(
                """SELECT SUM(CASE WHEN vote=1 THEN 1 ELSE 0 END),
                SUM(CASE WHEN vote=-1 THEN 1 ELSE 0 END)
                FROM suggestion_votes WHERE suggestion_id=?""",
                (sid,),
            )
            yes, no = await cur.fetchone()
            await db.commit()

        embed = interaction.message.embeds[0]
        embed.set_footer(
            text=f"Sugestão #{sid} • 👍 {yes or 0} | 👎 {no or 0} • Sr.Alpha"
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(
        label="Apoiar", emoji="👍", style=discord.ButtonStyle.success,
        custom_id="alpha_suggest_yes",
    )
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.vote(interaction, 1)

    @discord.ui.button(
        label="Não apoiar", emoji="👎", style=discord.ButtonStyle.secondary,
        custom_id="alpha_suggest_no",
    )
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.vote(interaction, -1)


# ---------------------------------------------------------------------------
# TICKET PANEL + CATEGORY MENU
# ---------------------------------------------------------------------------

def ticket_panel_embed(settings: dict, categories: list[dict]) -> discord.Embed:
    embed = discord.Embed(
        title=settings["panel_title"],
        description=settings["panel_description"],
        color=discord.Color(settings["panel_color"]),
    )
    if settings.get("hours_text"):
        embed.add_field(name="🕒 Horário de funcionamento", value=settings["hours_text"][:1024], inline=False)
    if settings.get("notices_text"):
        embed.add_field(name="📌 Avisos", value=settings["notices_text"][:1024], inline=False)
    if categories:
        lines = []
        for item in categories:
            lines.append(f"{item['emoji']} **{item['name']}** — {item['description'] or 'Solicite atendimento nesta categoria.'}")
        embed.add_field(name="📂 Categorias disponíveis", value="\n".join(lines)[:1024], inline=False)
    else:
        embed.add_field(
            name="⚙️ Configuração", value="A equipe ainda não cadastrou categorias.", inline=False
        )
    if settings.get("panel_image"):
        embed.set_image(url=settings["panel_image"])
    embed.set_footer(text="Sr.Alpha • Central de Atendimento")
    return embed


class TicketCategorySelect(discord.ui.Select):
    def __init__(self, guild_id: int, categories: list[dict]):
        options = [
            discord.SelectOption(
                label=item["name"][:100],
                value=str(item["id"]),
                description=(item["description"] or "Abrir um ticket nesta categoria.")[:100],
                emoji=item["emoji"] if item["emoji"] else "🎫",
            )
            for item in categories[:25]
        ]
        if not options:
            options = [discord.SelectOption(label="Nenhuma categoria configurada", value="none", emoji="⚙️")]
        super().__init__(
            placeholder="🎟️ Selecione uma categoria para abrir um ticket...",
            min_values=1, max_values=1, options=options,
            custom_id="alpha_ticket_category_select",
        )
        self.guild_id = guild_id

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or interaction.guild.id != self.guild_id:
            return await interaction.response.send_message("Este painel pertence a outro servidor.", ephemeral=True)
        if self.values[0] == "none":
            return await interaction.response.send_message("A equipe ainda não configurou categorias.", ephemeral=True)
        cog = interaction.client.get_cog("Community")
        if cog is None:
            return await interaction.response.send_message("O sistema de tickets está indisponível.", ephemeral=True)
        await cog.create_ticket(interaction, int(self.values[0]))


class TicketPanelView(discord.ui.View):
    def __init__(self, guild_id: int, categories: list[dict]):
        super().__init__(timeout=None)
        self.add_item(TicketCategorySelect(guild_id, categories))


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Assumir atendimento", emoji="🧑‍💼", style=discord.ButtonStyle.success, custom_id="alpha_ticket_claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Use este botão no servidor.", ephemeral=True)
        record = await get_ticket_record(interaction.channel_id)
        if not record or record["status"] != "open":
            return await interaction.response.send_message("Este ticket não está aberto.", ephemeral=True)
        categories = await get_ticket_categories(interaction.guild.id)
        category = next((c for c in categories if c["id"] == record["category_id"]), None)
        if not interaction.user.guild_permissions.manage_channels and (
            not category or category["staff_role_id"] not in [r.id for r in interaction.user.roles]
        ):
            return await interaction.response.send_message("Somente a equipe responsável pode assumir este ticket.", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE ticket_records SET attendant_id=? WHERE channel_id=? AND status='open'",
                (interaction.user.id, interaction.channel_id),
            )
            await db.commit()
        await interaction.response.send_message(f"🧑‍💼 Atendimento assumido por {interaction.user.mention}.")
        try:
            await interaction.channel.edit(topic=f"sr-ticket:{record['user_id']}:{record['category_id']}:{interaction.user.id}")
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Fechar ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="alpha_ticket_close_v2")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        cog = interaction.client.get_cog("Community")
        if cog is None:
            return await interaction.response.send_message("O sistema de tickets está indisponível.", ephemeral=True)
        await cog.close_ticket(interaction)


class RatingView(discord.ui.View):
    def __init__(self, channel_id: int):
        super().__init__(timeout=None)
        self.channel_id = channel_id
        for score in range(1, 6):
            button = discord.ui.Button(
                label=f"{score} estrela" if score == 1 else f"{score} estrelas",
                emoji="⭐", style=discord.ButtonStyle.secondary,
                custom_id=f"alpha_ticket_rating:{channel_id}:{score}",
            )
            button.callback = self.make_callback(score)
            self.add_item(button)

    def make_callback(self, score: int):
        async def callback(interaction: discord.Interaction):
            async with aiosqlite.connect(DB_PATH) as db:
                db.row_factory = aiosqlite.Row
                cur = await db.execute(
                    "SELECT * FROM ticket_records WHERE channel_id=? AND user_id=?",
                    (self.channel_id, interaction.user.id),
                )
                record = await cur.fetchone()
                if not record:
                    return await interaction.response.send_message("Não encontrei este atendimento.", ephemeral=True)
                if record["rating"] is not None:
                    return await interaction.response.send_message("Você já avaliou este atendimento. Obrigado!", ephemeral=True)
                await db.execute(
                    "UPDATE ticket_records SET rating=? WHERE channel_id=?",
                    (score, self.channel_id),
                )
                await db.commit()

            await interaction.response.send_modal(RatingCommentModal(self.channel_id, score))
        return callback


class RatingCommentModal(discord.ui.Modal, title="Comentário da avaliação"):
    comment = discord.ui.TextInput(
        label="Comentário (opcional)", placeholder="Conte como foi seu atendimento...",
        required=False, max_length=800, style=discord.TextStyle.paragraph,
    )

    def __init__(self, channel_id: int, score: int):
        super().__init__(timeout=300)
        self.channel_id = channel_id
        self.score = score

    async def on_submit(self, interaction: discord.Interaction):
        comment = str(self.comment.value or "").strip()
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM ticket_records WHERE channel_id=? AND user_id=?",
                (self.channel_id, interaction.user.id),
            )
            record = await cur.fetchone()
            if not record:
                return await interaction.response.send_message("Atendimento não encontrado.", ephemeral=True)
            await db.execute(
                "UPDATE ticket_records SET rating_comment=? WHERE channel_id=?",
                (comment, self.channel_id),
            )
            await db.commit()

        settings = await get_ticket_settings(record["guild_id"])
        guild = interaction.client.get_guild(record["guild_id"])
        target = guild.get_channel(settings["rating_channel_id"]) if guild and settings and settings.get("rating_channel_id") else None
        if target is None and guild and settings and settings.get("rating_channel_id"):
            try:
                target = await interaction.client.fetch_channel(settings["rating_channel_id"])
            except discord.HTTPException:
                target = None

        if target:
            embed = discord.Embed(
                title="⭐ Nova avaliação de atendimento",
                description=f"**Nota:** {'⭐' * self.score} ({self.score}/5)\n**Pessoa atendida:** <@{record['user_id']}>\n**Atendente:** <@{record['attendant_id']}>"
                if record["attendant_id"] else
                f"**Nota:** {'⭐' * self.score} ({self.score}/5)\n**Pessoa atendida:** <@{record['user_id']}>\n**Atendente:** Não identificado",
                color=PURPLE,
            )
            embed.add_field(name="Categoria", value=f"ID: {record['category_id']}" if record["category_id"] else "Não informada", inline=True)
            embed.add_field(name="Comentário", value=comment or "Nenhum comentário enviado.", inline=False)
            embed.set_footer(text=f"Sr.Alpha • Atendimento {self.channel_id}")
            try:
                await target.send(embed=embed)
            except discord.HTTPException:
                log.exception("Não foi possível publicar a avaliação.")
        await interaction.response.send_message("Obrigado! Sua avaliação foi registrada.", ephemeral=True)


# ---------------------------------------------------------------------------
# MAIN COG
# ---------------------------------------------------------------------------

class Community(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self):
        await init_community_tables()
        # Register persistent views for existing panels and open tickets.
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT guild_id, panel_message_id FROM ticket_settings WHERE panel_message_id IS NOT NULL")
            panels = await cur.fetchall()
            cur = await db.execute("SELECT channel_id FROM ticket_records WHERE status='open'")
            open_tickets = await cur.fetchall()
            cur = await db.execute("SELECT channel_id FROM ticket_records WHERE status='closed' AND rating IS NULL")
            awaiting_ratings = await cur.fetchall()
        for guild_id, message_id in panels:
            categories = await get_ticket_categories(guild_id)
            self.bot.add_view(TicketPanelView(guild_id, categories), message_id=message_id)
        for (channel_id,) in open_tickets:
            self.bot.add_view(TicketControlView(), message_id=None)
        for (channel_id,) in awaiting_ratings:
            self.bot.add_view(RatingView(channel_id))

    async def refresh_panel(self, guild: discord.Guild):
        settings = await get_ticket_settings(guild.id)
        if not settings or not settings.get("panel_message_id"):
            return
        channel = guild.get_channel(settings["panel_channel_id"])
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(settings["panel_channel_id"])
            except discord.HTTPException:
                return
        try:
            message = await channel.fetch_message(settings["panel_message_id"])
            categories = await get_ticket_categories(guild.id)
            await message.edit(embed=ticket_panel_embed(settings, categories), view=TicketPanelView(guild.id, categories))
            self.bot.add_view(TicketPanelView(guild.id, categories), message_id=message.id)
        except discord.HTTPException:
            log.exception("Não foi possível atualizar o painel de tickets.")

    async def create_ticket(self, interaction: discord.Interaction, category_id: int):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Este comando só funciona no servidor.", ephemeral=True)
        categories = await get_ticket_categories(guild.id)
        category = next((c for c in categories if c["id"] == category_id), None)
        if not category:
            return await interaction.response.send_message("Esta categoria não está mais disponível.", ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT channel_id FROM ticket_records WHERE guild_id=? AND user_id=? AND status='open'",
                (guild.id, interaction.user.id),
            )
            existing = await cur.fetchone()
        if existing:
            channel = guild.get_channel(existing[0])
            if channel:
                return await interaction.response.send_message(f"Você já tem um ticket aberto: {channel.mention}", ephemeral=True)

        staff_role = guild.get_role(category["staff_role_id"])
        if staff_role is None:
            return await interaction.response.send_message("O cargo da equipe desta categoria não existe mais. Avise um administrador.", ephemeral=True)
        bot_member = guild.me
        if bot_member is None:
            return await interaction.response.send_message("Não consegui verificar as permissões do bot.", ephemeral=True)

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True),
            staff_role: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_messages=True),
            bot_member: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True),
        }
        parent = guild.get_channel(category["discord_category_id"]) if category["discord_category_id"] else None
        safe_name = re.sub(r"[^a-z0-9-]", "-", interaction.user.name.lower()).strip("-")[:35] or "membro"
        try:
            channel = await guild.create_text_channel(
                f"ticket-{safe_name}",
                category=parent if isinstance(parent, discord.CategoryChannel) else None,
                overwrites=overwrites,
                topic=f"sr-ticket:{interaction.user.id}:{category_id}:0",
                reason=f"Ticket aberto por {interaction.user} ({category['name']})",
            )
        except discord.Forbidden:
            return await interaction.response.send_message("Não tenho permissão para criar tickets. Verifique Gerenciar canais.", ephemeral=True)
        except discord.HTTPException:
            log.exception("Falha ao criar ticket.")
            return await interaction.response.send_message("Não consegui criar o ticket. Tente novamente.", ephemeral=True)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT OR REPLACE INTO ticket_records
                (channel_id,guild_id,user_id,category_id,attendant_id,status)
                VALUES(?,?,?,?,NULL,'open')""",
                (channel.id, guild.id, interaction.user.id, category_id),
            )
            # Keep compatibility with the old ticket table used by previous versions.
            await db.execute(
                "INSERT OR REPLACE INTO tickets(channel_id,guild_id,user_id,status) VALUES(?,?,?,'open')",
                (channel.id, guild.id, interaction.user.id),
            )
            await db.commit()

        embed = discord.Embed(
            title=f"{category['emoji']} {category['name']}",
            description=category["welcome_text"] or "Explique como podemos ajudar.",
            color=PURPLE,
        )
        embed.add_field(name="👤 Solicitante", value=interaction.user.mention, inline=True)
        embed.add_field(name="🛡️ Equipe responsável", value=staff_role.mention, inline=True)
        embed.set_footer(text="Sr.Alpha • Central de Atendimento")
        await channel.send(
            content=f"{interaction.user.mention} {staff_role.mention}",
            embed=embed,
            view=TicketControlView(),
            allowed_mentions=discord.AllowedMentions(users=True, roles=True),
        )
        await interaction.response.send_message(f"🎫 Seu ticket foi criado: {channel.mention}", ephemeral=True)

    async def close_ticket(self, interaction: discord.Interaction):
        channel = interaction.channel
        record = await get_ticket_record(channel.id)
        if not record or record["status"] != "open":
            return await interaction.response.send_message("Este canal não é um ticket aberto registrado.", ephemeral=True)
        if not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Não consegui verificar suas permissões.", ephemeral=True)

        categories = await get_ticket_categories(record["guild_id"])
        category = next((c for c in categories if c["id"] == record["category_id"]), None)
        is_staff = interaction.user.guild_permissions.manage_channels or (
            category is not None and category["staff_role_id"] in [r.id for r in interaction.user.roles]
        )
        if interaction.user.id != record["user_id"] and not is_staff:
            return await interaction.response.send_message("Só o solicitante ou a equipe responsável pode fechar este ticket.", ephemeral=True)

        attendant_id = record["attendant_id"]
        if attendant_id is None and is_staff:
            attendant_id = interaction.user.id

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE ticket_records SET status='closed', attendant_id=?, closed_at=CURRENT_TIMESTAMP WHERE channel_id=?",
                (attendant_id, channel.id),
            )
            await db.execute("UPDATE tickets SET status='closed' WHERE channel_id=?", (channel.id,))
            await db.commit()

        await interaction.response.send_message("🔒 Ticket fechado. Vou enviar a opção de avaliação por mensagem privada.")
        guild = interaction.guild
        opener = guild.get_member(record["user_id"]) if guild else None
        if opener is None:
            try:
                opener = await self.bot.fetch_user(record["user_id"])
            except discord.HTTPException:
                opener = None
        if opener:
            try:
                await opener.send(
                    f"⭐ Seu atendimento no servidor **{guild.name if guild else 'Discord'}** foi encerrado. Avalie o atendimento abaixo:",
                    view=RatingView(channel.id),
                )
            except discord.Forbidden:
                log.info("DM desativada para o usuário %s; não foi possível enviar avaliação.", record["user_id"])
            except discord.HTTPException:
                log.exception("Falha ao enviar DM de avaliação.")
        try:
            await channel.delete(reason=f"Ticket fechado por {interaction.user}")
        except discord.HTTPException:
            log.exception("Não foi possível apagar o canal de ticket.")

    # ----------------- Ticket administration -----------------

    @app_commands.command(name="painel_tickets", description="Publica ou personaliza o painel de atendimento.")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def painel_tickets(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        titulo: app_commands.Range[str, 1, 200] = "🔔 Central de Atendimento",
        descricao: app_commands.Range[str, 1, 1500] = "Escolha no menu abaixo a categoria para a qual deseja atendimento.",
        cor: str = "#9167FF",
        imagem_url: str = "",
        horarios: str = "",
        avisos: str = "",
    ):
        try:
            color = parse_color(cor)
        except ValueError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        if imagem_url and not imagem_url.startswith(("https://", "http://")):
            return await interaction.response.send_message("A URL da imagem precisa começar com http:// ou https://.", ephemeral=True)
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Este comando só funciona em um servidor.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO ticket_settings
                (guild_id,panel_channel_id,panel_title,panel_description,panel_color,panel_image,hours_text,notices_text)
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(guild_id) DO UPDATE SET
                panel_channel_id=excluded.panel_channel_id,panel_title=excluded.panel_title,
                panel_description=excluded.panel_description,panel_color=excluded.panel_color,
                panel_image=excluded.panel_image,hours_text=excluded.hours_text,notices_text=excluded.notices_text""",
                (guild.id, canal.id, titulo, descricao, color.value, imagem_url.strip(), horarios[:1024], avisos[:1024]),
            )
            await db.commit()
        settings = await get_ticket_settings(guild.id)
        categories = await get_ticket_categories(guild.id)
        message = await canal.send(embed=ticket_panel_embed(settings, categories), view=TicketPanelView(guild.id, categories))
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE ticket_settings SET panel_message_id=? WHERE guild_id=?", (message.id, guild.id))
            await db.commit()
        self.bot.add_view(TicketPanelView(guild.id, categories), message_id=message.id)
        await interaction.followup.send(f"✅ Painel publicado em {canal.mention}. O botão “Meus Tickets” não foi incluído.", ephemeral=True)

    @app_commands.command(name="ticket_categoria_adicionar", description="Adiciona uma categoria personalizável ao menu de tickets.")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def ticket_categoria_adicionar(
        self,
        interaction: discord.Interaction,
        nome: app_commands.Range[str, 2, 80],
        equipe: discord.Role,
        descricao: app_commands.Range[str, 1, 100] = "Solicite atendimento nesta categoria.",
        emoji: str = "🎫",
        categoria_discord: discord.CategoryChannel = None,
        mensagem_inicial: app_commands.Range[str, 1, 1500] = "Olá! Explique como podemos ajudar.",
    ):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Este comando só funciona em um servidor.", ephemeral=True)
        if equipe.is_default() or equipe.managed:
            return await interaction.response.send_message("Escolha um cargo de equipe válido.", ephemeral=True)
        if not emoji.strip() or len(emoji) > 100:
            return await interaction.response.send_message("Informe um emoji válido.", ephemeral=True)
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    """INSERT INTO ticket_categories
                    (guild_id,name,emoji,description,staff_role_id,discord_category_id,welcome_text)
                    VALUES(?,?,?,?,?,?,?)""",
                    (guild.id, nome, emoji.strip(), descricao, equipe.id, categoria_discord.id if categoria_discord else None, mensagem_inicial),
                )
                await db.commit()
        except aiosqlite.IntegrityError:
            return await interaction.response.send_message("Já existe uma categoria com esse nome.", ephemeral=True)
        await self.refresh_panel(guild)
        await interaction.response.send_message(f"✅ Categoria **{nome}** adicionada. Equipe responsável: {equipe.mention}.", ephemeral=True)

    @app_commands.command(name="ticket_categoria_editar", description="Edita a descrição, emoji, equipe ou mensagem inicial de uma categoria.")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def ticket_categoria_editar(
        self,
        interaction: discord.Interaction,
        nome: str,
        nova_descricao: app_commands.Range[str, 1, 100] = None,
        novo_emoji: str = None,
        nova_equipe: discord.Role = None,
        mensagem_inicial: app_commands.Range[str, 1, 1500] = None,
    ):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Este comando só funciona em um servidor.", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT id FROM ticket_categories WHERE guild_id=? AND name=?", (guild.id, nome))
            row = await cur.fetchone()
            if not row:
                return await interaction.response.send_message("Categoria não encontrada.", ephemeral=True)
            updates, values = [], []
            if nova_descricao is not None:
                updates.append("description=?"); values.append(nova_descricao)
            if novo_emoji is not None:
                updates.append("emoji=?"); values.append(novo_emoji)
            if nova_equipe is not None:
                updates.append("staff_role_id=?"); values.append(nova_equipe.id)
            if mensagem_inicial is not None:
                updates.append("welcome_text=?"); values.append(mensagem_inicial)
            if updates:
                values.extend([guild.id, nome])
                await db.execute(f"UPDATE ticket_categories SET {', '.join(updates)} WHERE guild_id=? AND name=?", values)
                await db.commit()
        await self.refresh_panel(guild)
        await interaction.response.send_message(f"✅ Categoria **{nome}** atualizada.", ephemeral=True)

    @app_commands.command(name="ticket_categoria_remover", description="Remove uma categoria do menu de tickets.")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def ticket_categoria_remover(self, interaction: discord.Interaction, nome: str):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Este comando só funciona em um servidor.", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("DELETE FROM ticket_categories WHERE guild_id=? AND name=?", (guild.id, nome))
            await db.commit()
            if cur.rowcount == 0:
                return await interaction.response.send_message("Categoria não encontrada.", ephemeral=True)
        await self.refresh_panel(guild)
        await interaction.response.send_message(f"🗑️ Categoria **{nome}** removida do painel. Tickets existentes não são apagados.", ephemeral=True)

    @app_commands.command(name="ticket_configurar_avaliacoes", description="Define o canal onde as avaliações serão publicadas.")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def ticket_configurar_avaliacoes(self, interaction: discord.Interaction, canal: discord.TextChannel):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """INSERT INTO ticket_settings(guild_id,rating_channel_id) VALUES(?,?)
                ON CONFLICT(guild_id) DO UPDATE SET rating_channel_id=excluded.rating_channel_id""",
                (interaction.guild_id, canal.id),
            )
            await db.commit()
        await interaction.response.send_message(f"✅ As avaliações serão publicadas em {canal.mention}.", ephemeral=True)

    # ----------------- Suggestions (preserved) -----------------

    @app_commands.command(name="sugerir", description="Envie uma sugestão para a comunidade")
    @app_commands.guild_only()
    async def sugerir(self, interaction: discord.Interaction, texto: app_commands.Range[str, 8, 1000]):
        channel = interaction.guild.get_channel(config.SUGGESTION_CHANNEL_ID) if config.SUGGESTION_CHANNEL_ID else interaction.channel
        if channel is None:
            return await interaction.response.send_message("O canal de sugestões configurado não foi encontrado. Avise a equipe.", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "INSERT INTO suggestions(guild_id,user_id,text,channel_id) VALUES(?,?,?,?)",
                (interaction.guild_id, interaction.user.id, texto, channel.id),
            )
            sid = cur.lastrowid
            await db.commit()
        embed = discord.Embed(title=f"💡 Sugestão #{sid}", description=texto, color=PURPLE)
        embed.add_field(name="👤 Sugerida por", value=f"{interaction.user.mention}\n`{interaction.user}`", inline=False)
        embed.add_field(name="📌 Status", value="🟡 Em análise", inline=True)
        embed.add_field(name="👍 Apoio", value="0", inline=True)
        embed.add_field(name="👎 Não apoio", value="0", inline=True)
        embed.set_footer(text="Sr.Alpha • Sistema de sugestões")
        msg = await channel.send(embed=embed, view=SuggestionView(sid))
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE suggestions SET message_id=? WHERE id=?", (msg.id, sid))
            await db.commit()
        await interaction.response.send_message(f"✅ Sua sugestão foi enviada em {channel.mention}!", ephemeral=True)

    @app_commands.command(name="status_sugestao", description="Atualize o status de uma sugestão")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.choices(status=[app_commands.Choice(name=s, value=s) for s in ["Em análise", "Aprovada", "Recusada"]])
    async def status_sugestao(self, interaction: discord.Interaction, numero: app_commands.Range[int, 1, 1000000], status: app_commands.Choice[str], resposta: str = ""):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("Você precisa da permissão Gerenciar mensagens para alterar sugestões.", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT message_id,channel_id FROM suggestions WHERE id=? AND guild_id=?", (numero, interaction.guild_id))
            row = await cur.fetchone()
            if not row:
                return await interaction.response.send_message("Sugestão não encontrada.", ephemeral=True)
            message_id, channel_id = row
            await db.execute("UPDATE suggestions SET status=? WHERE id=? AND guild_id=?", (status.value, numero, interaction.guild_id))
            await db.commit()
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return await interaction.response.send_message("O canal da sugestão não está acessível ao bot.", ephemeral=True)
        try:
            msg = await channel.fetch_message(message_id)
        except discord.HTTPException:
            return await interaction.response.send_message("Não consegui encontrar a mensagem da sugestão.", ephemeral=True)
        embed = msg.embeds[0]
        emoji = {"Aprovada": "🟢", "Recusada": "🔴", "Em análise": "🟡"}[status.value]
        index = next((i for i, field in enumerate(embed.fields) if field.name == "📌 Status"), None)
        if index is None:
            embed.add_field(name="📌 Status", value=f"{emoji} {status.value}", inline=True)
        else:
            embed.set_field_at(index, name="📌 Status", value=f"{emoji} {status.value}", inline=True)
        decision = f"**Responsável:** {interaction.user.mention}\n**Resultado:** {status.value}"
        index = next((i for i, field in enumerate(embed.fields) if field.name == "🛡️ Decisão da equipe"), None)
        if index is None:
            embed.add_field(name="🛡️ Decisão da equipe", value=decision, inline=False)
        else:
            embed.set_field_at(index, name="🛡️ Decisão da equipe", value=decision, inline=False)
        response = resposta.strip()[:1024]
        index = next((i for i, field in enumerate(embed.fields) if field.name == "💬 Resposta da equipe"), None)
        if response:
            if index is None:
                embed.add_field(name="💬 Resposta da equipe", value=response, inline=False)
            else:
                embed.set_field_at(index, name="💬 Resposta da equipe", value=response, inline=False)
        await msg.edit(embed=embed, view=SuggestionView(numero))
        await interaction.response.send_message(f"✅ Sugestão #{numero} atualizada para **{status.value}** por {interaction.user.mention}.", ephemeral=True)

    @app_commands.command(name="ticket", description="Cria um painel de tickets com as configurações atuais")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def ticket(self, interaction: discord.Interaction, canal: discord.TextChannel):
        # Compatibility alias: uses the same customizable panel system.
        settings = await get_ticket_settings(interaction.guild_id)
        if not settings:
            settings = {
                "panel_title": "🔔 Central de Atendimento",
                "panel_description": "Escolha no menu abaixo a categoria para a qual deseja atendimento.",
                "panel_color": PURPLE.value, "panel_image": "", "hours_text": "",
                "notices_text": "", "panel_channel_id": canal.id, "panel_message_id": None,
            }
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO ticket_settings(guild_id,panel_channel_id,panel_title,panel_description,panel_color) VALUES(?,?,?,?,?)",
                    (interaction.guild_id, canal.id, settings["panel_title"], settings["panel_description"], settings["panel_color"]),
                )
                await db.commit()
        categories = await get_ticket_categories(interaction.guild_id)
        await interaction.response.defer(ephemeral=True)
        message = await canal.send(embed=ticket_panel_embed(settings, categories), view=TicketPanelView(interaction.guild_id, categories))
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE ticket_settings SET panel_channel_id=?,panel_message_id=? WHERE guild_id=?", (canal.id, message.id, interaction.guild_id))
            await db.commit()
        self.bot.add_view(TicketPanelView(interaction.guild_id, categories), message_id=message.id)
        await interaction.followup.send(f"✅ Painel de tickets publicado em {canal.mention}.", ephemeral=True)

    @app_commands.command(name="fechar_ticket", description="Feche o ticket atual")
    @app_commands.guild_only()
    async def fechar_ticket(self, interaction: discord.Interaction):
        await self.close_ticket(interaction)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if config.WELCOME_CHANNEL_ID:
            channel = member.guild.get_channel(config.WELCOME_CHANNEL_ID)
            if channel:
                embed = discord.Embed(
                    title="👋 Bem-vindo à comunidade!",
                    description=f"{member.mention}, seja bem-vindo ao **{member.guild.name}**!\nVocê é o membro **{member.guild.member_count}**.",
                    color=PURPLE,
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    log.exception("Não foi possível enviar mensagem de boas-vindas.")


async def setup(bot: commands.Bot):
    await init_community_tables()
    await bot.add_cog(Community(bot))
    bot.add_view(SuggestionView(0))
    bot.add_view(TicketControlView())