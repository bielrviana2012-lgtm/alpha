import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
from database import DB_PATH, get_user

class Levels(commands.Cog):
    def __init__(self, bot): self.bot = bot
    @commands.Cog.listener()
    async def on_message(self, message):
        if not message.guild or message.author.bot or not message.content.strip(): return
        row = await get_user(message.guild.id, message.author.id)
        import random
        xp_gain = random.randint(8, 15)
        new_xp = row['xp'] + xp_gain
        needed = 100 + row['level'] * 50
        level = row['level']
        leveled = new_xp >= needed
        if leveled: new_xp -= needed; level += 1
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET xp=?,level=? WHERE guild_id=? AND user_id=?", (new_xp,level,message.guild.id,message.author.id)); await db.commit()
        if leveled:
            try: await message.channel.send(f"🎉 {message.author.mention} subiu para o **nível {level}**!", delete_after=12)
            except discord.HTTPException: pass
    @app_commands.command(name="perfil", description="Veja seu perfil e progresso")
    async def perfil(self, interaction: discord.Interaction, membro: discord.Member | None = None):
        user = membro or interaction.user; row = await get_user(interaction.guild_id,user.id)
        needed = 100 + row['level'] * 50
        embed = discord.Embed(title=f"🌟 Perfil de {user.display_name}", color=discord.Color.blurple())
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="Nível", value=str(row['level']))
        embed.add_field(name="XP", value=f"{row['xp']} / {needed}")
        embed.add_field(name="Progresso", value=f"{int(row['xp']/needed*100)}%", inline=False)
        await interaction.response.send_message(embed=embed)
    @app_commands.command(name="level", description="Veja seu nível atual")
    async def level(self, interaction: discord.Interaction):
        row = await get_user(interaction.guild_id,interaction.user.id)
        await interaction.response.send_message(f"🌟 Você está no nível **{row['level']}** com **{row['xp']} XP**. Use `/perfil` para ver os detalhes.", ephemeral=True)

async def setup(bot): await bot.add_cog(Levels(bot))
