import random
import time
from datetime import date, timedelta

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from database import DB_PATH, ensure_user, has_infinite_coins
from cogs.ui_v2 import make_v2_panel

PURPLE = discord.Color.from_rgb(145, 103, 255)
CURRENCY = "Dado Coins"


class CommunitySystems(commands.Cog):
    """Sistemas extras do Rei Dado, separados dos módulos existentes."""

    def __init__(self, bot):
        self.bot = bot
        self.recent_messages = {}

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS alpha_event_entries (
                    event_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY(event_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS alpha_antispam_settings (
                    guild_id INTEGER PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 0,
                    max_messages INTEGER NOT NULL DEFAULT 5,
                    window_seconds INTEGER NOT NULL DEFAULT 7
                );
                CREATE TABLE IF NOT EXISTS alpha_weekly_claims (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    week_start TEXT NOT NULL,
                    reward INTEGER NOT NULL,
                    PRIMARY KEY(guild_id, user_id, week_start)
                );
            """)
            await db.commit()

    @app_commands.command(name="missoes", description="Consulte suas missões diárias e semanais")
    @app_commands.guild_only()
    async def missoes(self, interaction: discord.Interaction):
        await interaction.response.send_message(
            view=make_v2_panel(
                "🎯 Missões do Rei Dado",
                "• `/missao` — resgate a missão diária já existente.\\n"
                "• `/missao_semanal` — resgate a missão semanal de **500 Dado Coins**.\\n"
                "Os resgates são limitados por período e registrados no banco persistente."
            ), ephemeral=True,
        )

    @app_commands.command(name="missao_semanal", description="Resgate sua recompensa semanal de Dado Coins")
    @app_commands.guild_only()
    async def missao_semanal(self, interaction: discord.Interaction):
        guild_id, user_id = interaction.guild_id, interaction.user.id
        today = date.today()
        week_start = (today - timedelta(days=today.weekday())).isoformat()
        reward = 500
        await ensure_user(guild_id, user_id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("BEGIN IMMEDIATE")
            existing = await (await db.execute(
                "SELECT reward FROM alpha_weekly_claims WHERE guild_id=? AND user_id=? AND week_start=?",
                (guild_id, user_id, week_start),
            )).fetchone()
            if existing:
                await db.rollback()
                return await interaction.response.send_message(
                    f"Você já resgatou a missão semanal desta semana: **{existing[0]:,} Dado Coins**.", ephemeral=True,
                )
            await db.execute(
                "INSERT INTO alpha_weekly_claims(guild_id,user_id,week_start,reward) VALUES(?,?,?,?)",
                (guild_id, user_id, week_start, reward),
            )
            await db.execute(
                "UPDATE users SET wallet=wallet+? WHERE guild_id=? AND user_id=?",
                (reward, guild_id, user_id),
            )
            await db.commit()
        await interaction.response.send_message(
            f"🎯 Missão semanal concluída! Você recebeu **{reward:,} Dado Coins**. Volte na próxima semana.",
        )

    @app_commands.command(name="colecao", description="Veja sua coleção de itens e cosméticos")
    @app_commands.guild_only()
    async def colecao(self, interaction: discord.Interaction, membro: discord.Member | None = None):
        target = membro or interaction.user
        async with aiosqlite.connect(DB_PATH) as db:
            rows = await (await db.execute(
                "SELECT item, quantity FROM inventory WHERE guild_id=? AND user_id=? AND quantity>0 ORDER BY item",
                (interaction.guild_id, target.id),
            )).fetchall()
        text = "\n".join(f"• **{discord.utils.escape_markdown(name)}** × {qty}" for name, qty in rows)
        await interaction.response.send_message(
            view=make_v2_panel(f"🎒 Coleção de {target.display_name}", text or "Nenhum item na coleção ainda. Confira /loja."),
            ephemeral=True,
        )

    @app_commands.command(name="usar_item", description="Use uma Caixa Misteriosa do seu inventário")
    @app_commands.guild_only()
    async def usar_item(self, interaction: discord.Interaction, item: str):
        if item.casefold() != "caixa misteriosa":
            return await interaction.response.send_message(
                "Por enquanto, apenas **Caixa Misteriosa** pode ser aberta. Os outros itens ficam guardados na coleção.",
                ephemeral=True,
            )
        guild_id, user_id = interaction.guild_id, interaction.user.id
        await ensure_user(guild_id, user_id)
        reward = random.randint(75, 450)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute(
                "UPDATE inventory SET quantity=quantity-1 WHERE guild_id=? AND user_id=? AND item=? AND quantity>0",
                (guild_id, user_id, "Caixa Misteriosa"),
            )
            if cur.rowcount != 1:
                await db.rollback()
                return await interaction.response.send_message("Você não tem uma Caixa Misteriosa no inventário.", ephemeral=True)
            await db.execute("UPDATE users SET wallet=wallet+? WHERE guild_id=? AND user_id=?", (reward, guild_id, user_id))
            await db.commit()
        await interaction.response.send_message(
            f"🎁 Você abriu a Caixa Misteriosa e recebeu **{reward:,} {CURRENCY}**!"
        )

    @app_commands.command(name="clan_convite", description="Convide um membro para o seu clã")
    @app_commands.guild_only()
    async def clan_convite(self, interaction: discord.Interaction, membro: discord.Member):
        if membro.bot or membro.id == interaction.user.id:
            return await interaction.response.send_message("Escolha outro membro humano.", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            clan = await (await db.execute(
                "SELECT c.id,c.name FROM alpha_clans c JOIN alpha_clan_members m ON m.clan_id=c.id "
                "WHERE c.guild_id=? AND m.user_id=? AND c.owner_id=?",
                (interaction.guild_id, interaction.user.id, interaction.user.id),
            )).fetchone()
            if not clan:
                return await interaction.response.send_message("Somente o líder do seu clã pode convidar membros.", ephemeral=True)
            existing = await (await db.execute(
                "SELECT 1 FROM alpha_clan_members WHERE guild_id=? AND user_id=?",
                (interaction.guild_id, membro.id),
            )).fetchone()
            if existing:
                return await interaction.response.send_message("Esse membro já pertence a um clã.", ephemeral=True)
            await db.execute(
                "INSERT INTO alpha_clan_members(guild_id,clan_id,user_id) VALUES(?,?,?)",
                (interaction.guild_id, clan[0], membro.id),
            )
            await db.commit()
        await interaction.response.send_message(
            f"🛡️ {membro.mention} entrou no clã **{discord.utils.escape_markdown(clan[1])}** por convite.",
            allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
        )

    @app_commands.command(name="eventos", description="Veja os eventos cadastrados no servidor")
    @app_commands.guild_only()
    async def eventos(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            rows = await (await db.execute(
                "SELECT id,title,starts_at,description FROM alpha_events WHERE guild_id=? ORDER BY id DESC LIMIT 10",
                (interaction.guild_id,),
            )).fetchall()
        if not rows:
            return await interaction.response.send_message("Ainda não há eventos cadastrados.", ephemeral=True)
        text = "\n\n".join(
            f"**#{event_id} · {discord.utils.escape_markdown(title)}**\n"
            f"🗓️ {discord.utils.escape_markdown(when)}\n{discord.utils.escape_markdown(description)[:250]}"
            for event_id, title, when, description in rows
        )
        await interaction.response.send_message(view=make_v2_panel("📅 Eventos da Family Alpha", text), ephemeral=True)

    @app_commands.command(name="evento_inscrever", description="Inscreva-se em um evento pelo ID")
    @app_commands.guild_only()
    async def evento_inscrever(self, interaction: discord.Interaction, evento_id: app_commands.Range[int, 1, 2147483647]):
        async with aiosqlite.connect(DB_PATH) as db:
            event = await (await db.execute(
                "SELECT title FROM alpha_events WHERE id=? AND guild_id=?",
                (evento_id, interaction.guild_id),
            )).fetchone()
            if not event:
                return await interaction.response.send_message("Não encontrei esse evento. Confira /eventos.", ephemeral=True)
            try:
                await db.execute(
                    "INSERT INTO alpha_event_entries(event_id,user_id) VALUES(?,?)",
                    (evento_id, interaction.user.id),
                )
            except aiosqlite.IntegrityError:
                return await interaction.response.send_message("Você já está inscrito nesse evento.", ephemeral=True)
            await db.commit()
            count = (await (await db.execute(
                "SELECT COUNT(*) FROM alpha_event_entries WHERE event_id=?", (evento_id,)
            )).fetchone())[0]
        await interaction.response.send_message(
            f"✅ Inscrição confirmada para **{discord.utils.escape_markdown(event[0])}**. Participantes inscritos: **{count}**."
        )

    @app_commands.command(name="mod_logs", description="Consulte os registros recentes de moderação")
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.guild_only()
    async def mod_logs(self, interaction: discord.Interaction, membro: discord.Member | None = None):
        async with aiosqlite.connect(DB_PATH) as db:
            if membro:
                rows = await (await db.execute(
                    "SELECT user_id,moderator_id,reason,created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10",
                    (interaction.guild_id, membro.id),
                )).fetchall()
            else:
                rows = await (await db.execute(
                    "SELECT user_id,moderator_id,reason,created_at FROM warnings WHERE guild_id=? ORDER BY id DESC LIMIT 10",
                    (interaction.guild_id,),
                )).fetchall()
        if not rows:
            return await interaction.response.send_message("Não há registros de avisos para mostrar.", ephemeral=True)
        text = "\n".join(
            f"• <@{uid}> — {discord.utils.escape_markdown(reason)[:120]}\n"
            f"  Responsável: <@{mod}> · {created}"
            for uid, mod, reason, created in rows
        )
        await interaction.response.send_message(view=make_v2_panel("🛡️ Registros de moderação", text), ephemeral=True)

    @app_commands.command(name="config_antispam", description="Ative ou configure a proteção contra spam")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    @app_commands.describe(ativo="Ativar ou desativar a proteção", limite="Mensagens permitidas na janela", janela_segundos="Duração da janela em segundos")
    async def config_antispam(
        self, interaction: discord.Interaction, ativo: bool,
        limite: app_commands.Range[int, 3, 10] = 5,
        janela_segundos: app_commands.Range[int, 3, 15] = 7,
    ):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO alpha_antispam_settings(guild_id,enabled,max_messages,window_seconds) VALUES(?,?,?,?) "
                "ON CONFLICT(guild_id) DO UPDATE SET enabled=excluded.enabled,max_messages=excluded.max_messages,window_seconds=excluded.window_seconds",
                (interaction.guild_id, int(ativo), limite, janela_segundos),
            )
            await db.commit()
        status = "ativada" if ativo else "desativada"
        await interaction.response.send_message(
            f"🛡️ Proteção antispam **{status}**. Limite configurado: **{limite} mensagens em {janela_segundos}s**.",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or not message.content:
            return
        async with aiosqlite.connect(DB_PATH) as db:
            row = await (await db.execute(
                "SELECT enabled,max_messages,window_seconds FROM alpha_antispam_settings WHERE guild_id=?",
                (message.guild.id,),
            )).fetchone()
        if not row or not row[0]:
            return
        enabled, maximum, window = row
        key = (message.guild.id, message.author.id)
        now = time.monotonic()
        history = [stamp for stamp in self.recent_messages.get(key, []) if now - stamp <= window]
        history.append(now)
        self.recent_messages[key] = history
        if len(history) < maximum:
            return
        try:
            await message.channel.send(
                f"🛡️ {message.author.mention}, diminua a velocidade das mensagens.",
                delete_after=5,
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
            # Não pune nem apaga mensagens automaticamente; apenas alerta e aplica cooldown de alerta.
        except discord.HTTPException:
            pass
        self.recent_messages[key] = []

    @app_commands.command(name="estatisticas", description="Veja estatísticas gerais do servidor")
    @app_commands.guild_only()
    async def estatisticas(self, interaction: discord.Interaction):
        guild = interaction.guild
        humans = sum(not member.bot for member in guild.members)
        bots = sum(member.bot for member in guild.members)
        async with aiosqlite.connect(DB_PATH) as db:
            clan_count = (await (await db.execute("SELECT COUNT(*) FROM alpha_clans WHERE guild_id=?", (guild.id,))).fetchone())[0]
            event_count = (await (await db.execute("SELECT COUNT(*) FROM alpha_events WHERE guild_id=?", (guild.id,))).fetchone())[0]
            warning_count = (await (await db.execute("SELECT COUNT(*) FROM warnings WHERE guild_id=?", (guild.id,))).fetchone())[0]
        await interaction.response.send_message(view=make_v2_panel(
            f"📊 Estatísticas de {guild.name}",
            f"👥 Membros humanos em cache: **{humans}**\n🤖 Bots em cache: **{bots}**\n"
            f"🛡️ Clãs cadastrados: **{clan_count}**\n📅 Eventos cadastrados: **{event_count}**\n"
            f"⚠️ Avisos registrados: **{warning_count}**\n💬 Canais de texto: **{len(guild.text_channels)}**",
        ), ephemeral=True)

    @app_commands.command(name="atividade_servidor", description="Veja indicadores de atividade do servidor")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def atividade_servidor(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            uses = await (await db.execute(
                "SELECT command_name, SUM(uses) FROM game_command_uses WHERE guild_id=? GROUP BY command_name ORDER BY SUM(uses) DESC LIMIT 8",
                (interaction.guild_id,),
            )).fetchall()
        text = "\n".join(f"• **{name}** — {count} usos" for name, count in uses) or "Ainda não há dados de uso de jogos."
        await interaction.response.send_message(view=make_v2_panel("📈 Atividade registrada", text), ephemeral=True)

    @app_commands.command(name="central_admin", description="Abra a central administrativa do Rei Dado")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def central_admin(self, interaction: discord.Interaction):
        guild = interaction.guild
        async with aiosqlite.connect(DB_PATH) as db:
            users = (await (await db.execute("SELECT COUNT(*) FROM users WHERE guild_id=?", (guild.id,))).fetchone())[0]
            events = (await (await db.execute("SELECT COUNT(*) FROM alpha_events WHERE guild_id=?", (guild.id,))).fetchone())[0]
            warnings = (await (await db.execute("SELECT COUNT(*) FROM warnings WHERE guild_id=?", (guild.id,))).fetchone())[0]
            clans = (await (await db.execute("SELECT COUNT(*) FROM alpha_clans WHERE guild_id=?", (guild.id,))).fetchone())[0]
        await interaction.response.send_message(view=make_v2_panel(
            "👑 Central administrativa do Rei Dado",
            f"**Economia:** {users} contas registradas; saldos preservados.\\n"
            f"**Comunidade:** {events} eventos e {clans} clãs.\\n"
            f"**Moderação:** {warnings} avisos registrados.\\n\\n"
            "Use os comandos administrativos específicos para gerenciar cada sistema."
        ), ephemeral=True)

    @app_commands.command(name="resumo_servidor", description="Abra o resumo administrativo do servidor")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def resumo_servidor(self, interaction: discord.Interaction):
        guild = interaction.guild
        async with aiosqlite.connect(DB_PATH) as db:
            users = (await (await db.execute("SELECT COUNT(*) FROM users WHERE guild_id=?", (guild.id,))).fetchone())[0]
            events = (await (await db.execute("SELECT COUNT(*) FROM alpha_events WHERE guild_id=?", (guild.id,))).fetchone())[0]
            warnings = (await (await db.execute("SELECT COUNT(*) FROM warnings WHERE guild_id=?", (guild.id,))).fetchone())[0]
            clans = (await (await db.execute("SELECT COUNT(*) FROM alpha_clans WHERE guild_id=?", (guild.id,))).fetchone())[0]
        await interaction.response.send_message(view=make_v2_panel(
            "👑 Central administrativa do Rei Dado",
            f"**Economia:** {users} contas registradas; saldos preservados.\n"
            f"**Comunidade:** {events} eventos e {clans} clãs.\n"
            f"**Moderação:** {warnings} avisos registrados.\n\n"
            "Ações administrativas continuam protegidas por permissões do Discord.",
        ), ephemeral=True)


async def setup(bot):
    await bot.add_cog(CommunitySystems(bot))
