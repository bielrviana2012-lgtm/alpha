import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
from database import DB_PATH
import config

class SuggestionView(discord.ui.View):
    def __init__(self, suggestion_id: int):
        super().__init__(timeout=None); self.suggestion_id = suggestion_id
    async def vote(self, interaction: discord.Interaction, vote: int):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT id FROM suggestions WHERE message_id=? AND guild_id=?", (interaction.message.id, interaction.guild_id))
            row = await cur.fetchone()
            if not row: return await interaction.response.send_message("Não encontrei esta sugestão no banco de dados.", ephemeral=True)
            sid = row[0]
            cur = await db.execute("SELECT vote FROM suggestion_votes WHERE suggestion_id=? AND user_id=?", (sid,interaction.user.id))
            previous = await cur.fetchone()
            if previous and previous[0] == vote:
                return await interaction.response.send_message("Você já votou dessa forma. Seu voto foi mantido.", ephemeral=True)
            await db.execute("INSERT INTO suggestion_votes(suggestion_id,user_id,vote) VALUES(?,?,?) ON CONFLICT(suggestion_id,user_id) DO UPDATE SET vote=excluded.vote", (sid,interaction.user.id,vote))
            cur = await db.execute("SELECT SUM(CASE WHEN vote=1 THEN 1 ELSE 0 END), SUM(CASE WHEN vote=-1 THEN 1 ELSE 0 END) FROM suggestion_votes WHERE suggestion_id=?", (sid,))
            yes,no = await cur.fetchone(); await db.commit()
        embed = interaction.message.embeds[0]
        embed.set_footer(text=f"Sugestão #{sid} • 👍 {yes or 0} | 👎 {no or 0} • Alpha BOT")
        await interaction.response.edit_message(embed=embed, view=self)
    @discord.ui.button(label="Apoiar", emoji="👍", style=discord.ButtonStyle.success, custom_id="alpha_suggest_yes")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button): await self.vote(interaction, 1)
    @discord.ui.button(label="Não apoiar", emoji="👎", style=discord.ButtonStyle.secondary, custom_id="alpha_suggest_no")
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button): await self.vote(interaction, -1)

class TicketView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Abrir ticket", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="alpha_ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        existing = discord.utils.find(lambda c: c.topic == f"alpha-ticket:{interaction.user.id}", guild.text_channels)
        if existing: return await interaction.response.send_message(f"Você já tem um ticket aberto: {existing.mention}", ephemeral=True)
        overwrites = {guild.default_role: discord.PermissionOverwrite(view_channel=False), interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True), guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)}
        channel = await guild.create_text_channel(f"ticket-{interaction.user.name}"[:90], overwrites=overwrites, topic=f"alpha-ticket:{interaction.user.id}")
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR REPLACE INTO tickets(channel_id,guild_id,user_id,status) VALUES(?,?,?,'open')", (channel.id,guild.id,interaction.user.id)); await db.commit()
        await channel.send(f"Olá {interaction.user.mention}! Conte como podemos ajudar.", view=CloseTicketView())
        await interaction.response.send_message(f"🎫 Ticket criado: {channel.mention}", ephemeral=True)

class CloseTicketView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Fechar ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="alpha_ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_channels and not (interaction.channel.topic or "").endswith(str(interaction.user.id)):
            return await interaction.response.send_message("Só o dono do ticket ou a equipe pode fechá-lo.", ephemeral=True)
        await interaction.response.send_message("🔒 Ticket será fechado em alguns segundos.")
        await interaction.channel.delete(reason=f"Ticket fechado por {interaction.user}")

class Community(commands.Cog):
    def __init__(self, bot): self.bot = bot
    @app_commands.command(name="sugerir", description="Envie uma sugestão para a comunidade")
    async def sugerir(self, interaction: discord.Interaction, texto: app_commands.Range[str, 8, 1000]):
        channel = interaction.guild.get_channel(config.SUGGESTION_CHANNEL_ID) if config.SUGGESTION_CHANNEL_ID else interaction.channel
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("INSERT INTO suggestions(guild_id,user_id,text,channel_id) VALUES(?,?,?,?)", (interaction.guild_id,interaction.user.id,texto,channel.id)); sid = cur.lastrowid; await db.commit()
        embed = discord.Embed(title=f"💡 Sugestão #{sid}", description=texto, color=discord.Color.blurple())
        embed.add_field(name="Status", value="🟡 Em análise", inline=True); embed.set_footer(text=f"Enviada por {interaction.user} • Alpha BOT")
        msg = await channel.send(embed=embed, view=SuggestionView(sid))
        async with aiosqlite.connect(DB_PATH) as db: await db.execute("UPDATE suggestions SET message_id=? WHERE id=?", (msg.id,sid)); await db.commit()
        await interaction.response.send_message(f"✅ Sugestão enviada em {channel.mention}!", ephemeral=True)

    @app_commands.command(name="status_sugestao", description="Atualize o status de uma sugestão")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.choices(status=[app_commands.Choice(name=s,value=s) for s in ["Em análise","Aprovada","Recusada"]])
    async def status_sugestao(self, interaction: discord.Interaction, numero: app_commands.Range[int,1,1000000], status: app_commands.Choice[str], resposta: str = ""):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT message_id,channel_id FROM suggestions WHERE id=? AND guild_id=?", (numero,interaction.guild_id)); row = await cur.fetchone()
            if not row: return await interaction.response.send_message("Sugestão não encontrada.", ephemeral=True)
            await db.execute("UPDATE suggestions SET status=? WHERE id=?", (status.value,numero)); await db.commit()
        channel = self.bot.get_channel(row[1])
        if channel is None: return await interaction.response.send_message("Canal da sugestão não está acessível ao bot.", ephemeral=True)
        msg = await channel.fetch_message(row[0])
        embed = msg.embeds[0]; embed.set_field_at(0,name="Status",value=f"{'🟢' if status.value=='Aprovada' else '🔴' if status.value=='Recusada' else '🟡'} {status.value}",inline=True)
        if resposta: embed.add_field(name="Resposta da equipe", value=resposta[:1024], inline=False)
        await msg.edit(embed=embed); await interaction.response.send_message(f"Sugestão #{numero} atualizada para **{status.value}**.", ephemeral=True)

    @app_commands.command(name="ticket", description="Envie um painel para abrir tickets de suporte")
    @app_commands.default_permissions(manage_channels=True)
    async def ticket(self, interaction: discord.Interaction):
        embed = discord.Embed(title="🎫 Suporte Alpha", description="Clique no botão abaixo para abrir um canal privado com a equipe.", color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, view=TicketView())

    @app_commands.command(name="fechar_ticket", description="Feche o canal de ticket atual")
    async def fechar_ticket(self, interaction: discord.Interaction):
        topic = interaction.channel.topic or ""
        if not topic.startswith("alpha-ticket:") and not interaction.user.guild_permissions.manage_channels:
            return await interaction.response.send_message("Este canal não parece ser um ticket.", ephemeral=True)
        await interaction.response.send_message("🔒 Fechando ticket...")
        await interaction.channel.delete(reason=f"Ticket fechado por {interaction.user}")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if config.WELCOME_CHANNEL_ID:
            channel = member.guild.get_channel(config.WELCOME_CHANNEL_ID)
            if channel:
                embed = discord.Embed(title="👋 Bem-vindo à comunidade!", description=f"{member.mention}, seja bem-vindo ao **{member.guild.name}**!\nVocê é o membro **{member.guild.member_count}**.", color=discord.Color.blurple())
                embed.set_thumbnail(url=member.display_avatar.url)
                try: await channel.send(embed=embed)
                except discord.HTTPException: pass

async def setup(bot):
    await bot.add_cog(Community(bot))
    bot.add_view(TicketView()); bot.add_view(CloseTicketView()); bot.add_view(SuggestionView(0))
