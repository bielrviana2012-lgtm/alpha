import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
from database import DB_PATH
import config

async def log_action(guild, text):
    if config.LOG_CHANNEL_ID:
        channel = guild.get_channel(config.LOG_CHANNEL_ID)
        if channel:
            try: await channel.send(text)
            except discord.HTTPException: pass

class Moderation(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="aviso", description="Registre um aviso para um membro")
    @app_commands.default_permissions(moderate_members=True)
    async def aviso(self, interaction: discord.Interaction, membro: discord.Member, motivo: app_commands.Range[str, 1, 300]):
        if membro.id == interaction.user.id or membro.bot: return await interaction.response.send_message("Escolha um membro válido.", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO warnings(guild_id,user_id,moderator_id,reason) VALUES(?,?,?,?)", (interaction.guild_id,membro.id,interaction.user.id,motivo)); await db.commit()
            cur = await db.execute("SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?", (interaction.guild_id,membro.id)); count = (await cur.fetchone())[0]
        await interaction.response.send_message(f"⚠️ {membro.mention} recebeu um aviso. Total de avisos: **{count}**.")
        await log_action(interaction.guild, f"⚠️ Aviso para {membro.mention} por {interaction.user.mention}: {motivo}")

    @app_commands.command(name="avisos", description="Consulte os avisos de um membro")
    @app_commands.default_permissions(moderate_members=True)
    async def avisos(self, interaction: discord.Interaction, membro: discord.Member):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT reason, moderator_id, created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10", (interaction.guild_id,membro.id)); rows = await cur.fetchall()
        desc = "\n".join(f"• {reason} — <@{mod}> ({when})" for reason,mod,when in rows) if rows else "Nenhum aviso registrado."
        await interaction.response.send_message(embed=discord.Embed(title=f"📋 Avisos: {membro}", description=desc, color=discord.Color.orange()), ephemeral=True)

    @app_commands.command(name="limpar", description="Apague mensagens recentes do canal")
    @app_commands.default_permissions(manage_messages=True)
    async def limpar(self, interaction: discord.Interaction, quantidade: app_commands.Range[int, 1, 100]):
        await interaction.response.defer(ephemeral=True)
        if not isinstance(interaction.channel, discord.TextChannel): return await interaction.followup.send("Use em um canal de texto.", ephemeral=True)
        deleted = await interaction.channel.purge(limit=quantidade)
        await interaction.followup.send(f"🧹 Apaguei **{len(deleted)}** mensagens.", ephemeral=True)
        await log_action(interaction.guild, f"🧹 {interaction.user.mention} apagou {len(deleted)} mensagens em {interaction.channel.mention}.")

    @app_commands.command(name="timeout", description="Coloque um membro em timeout por alguns minutos")
    @app_commands.default_permissions(moderate_members=True)
    async def timeout(self, interaction: discord.Interaction, membro: discord.Member, minutos: app_commands.Range[int, 1, 10080], motivo: str = "Sem motivo informado"):
        if membro.top_role >= interaction.user.top_role and interaction.guild.owner_id != interaction.user.id: return await interaction.response.send_message("Seu cargo precisa estar acima do cargo desse membro.", ephemeral=True)
        try:
            await membro.timeout(discord.utils.utcnow() + __import__('datetime').timedelta(minutes=minutos), reason=motivo)
        except discord.Forbidden: return await interaction.response.send_message("Não tenho permissão ou o cargo do membro está acima do meu.", ephemeral=True)
        await interaction.response.send_message(f"🔇 {membro.mention} recebeu timeout por **{minutos} minutos**. Motivo: {motivo}")
        await log_action(interaction.guild, f"🔇 Timeout: {membro.mention}, {minutos} min. Por {interaction.user.mention}. Motivo: {motivo}")

    @app_commands.command(name="expulsar", description="Expulse um membro do servidor")
    @app_commands.default_permissions(kick_members=True)
    async def expulsar(self, interaction: discord.Interaction, membro: discord.Member, motivo: str = "Sem motivo informado"):
        try: await membro.kick(reason=motivo)
        except discord.Forbidden: return await interaction.response.send_message("Não consigo expulsar esse membro; confira a hierarquia de cargos.", ephemeral=True)
        await interaction.response.send_message(f"👢 {membro} foi expulso. Motivo: {motivo}")
        await log_action(interaction.guild, f"👢 {membro} expulso por {interaction.user.mention}: {motivo}")

    @app_commands.command(name="banir", description="Bane um membro do servidor")
    @app_commands.default_permissions(ban_members=True)
    async def banir(self, interaction: discord.Interaction, membro: discord.Member, motivo: str = "Sem motivo informado"):
        try: await membro.ban(reason=motivo, delete_message_seconds=0)
        except discord.Forbidden: return await interaction.response.send_message("Não consigo banir esse membro; confira a hierarquia de cargos.", ephemeral=True)
        await interaction.response.send_message(f"🔨 {membro} foi banido. Motivo: {motivo}")
        await log_action(interaction.guild, f"🔨 {membro} banido por {interaction.user.mention}: {motivo}")

async def setup(bot): await bot.add_cog(Moderation(bot))
