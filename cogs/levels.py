
import random

import discord
import aiosqlite
from discord import app_commands
from discord.ext import commands

from database import DB_PATH, get_user


class Levels(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if (
            message.guild is None
            or message.author.bot
            or not message.content.strip()
        ):
            return

        row = await get_user(
            message.guild.id,
            message.author.id,
        )

        xp_gain = random.randint(8, 15)
        new_xp = row["xp"] + xp_gain
        level = row["level"]
        needed = 100 + level * 50

        if new_xp >= needed:
            new_xp -= needed
            level += 1

            # Mantém o aviso de evolução.
            try:
                await message.channel.send(
                    f"🎉 {message.author.mention} subiu para "
                    f"o **nível {level}**!",
                    delete_after=12,
                )
            except discord.HTTPException:
                pass

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                """
                UPDATE users
                SET xp = ?, level = ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (
                    new_xp,
                    level,
                    message.guild.id,
                    message.author.id,
                ),
            )
            await db.commit()

    @app_commands.command(
        name="level",
        description="Veja seu nível e XP atual.",
    )
    async def level(self, interaction: discord.Interaction):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Este comando só funciona dentro do servidor.",
                ephemeral=True,
            )

        row = await get_user(
            interaction.guild.id,
            interaction.user.id,
        )

        await interaction.response.send_message(
            f"🌟 Você está no nível **{row['level']}**, "
            f"com **{row['xp']} XP**. "
            "Use `/perfil` para consultar seu perfil completo.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
