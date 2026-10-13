
import discord
import aiosqlite

from discord import app_commands
from discord.ext import commands

from database import DB_PATH, ensure_user
import config


COR = discord.Color.from_rgb(145, 103, 255)


class Premium(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def obter_usuario(self, guild_id: int, user_id: int):
        await ensure_user(guild_id, user_id)

        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT wallet, bank, xp, level
                FROM users
                WHERE guild_id = ? AND user_id = ?
                """,
                (guild_id, user_id),
            )
            row = await cursor.fetchone()

        return dict(row) if row else None

    @app_commands.command(
        name="perfil",
        description="Mostra o perfil de um membro do Family Alpha."
    )
    @app_commands.describe(membro="Membro que você quer consultar")
    async def perfil(
        self,
        interaction: discord.Interaction,
        membro: discord.Member = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este comando só funciona dentro do servidor.",
                ephemeral=True,
            )
            return

        alvo = membro or interaction.user
        dados = await self.obter_usuario(
            interaction.guild.id, alvo.id
        )

        if dados is None:
            await interaction.response.send_message(
                "Não consegui carregar esse perfil.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(
            title="✦ PERFIL ALPHA",
            description=f"Confira a jornada de {alvo.mention}.",
            color=COR,
        )
        embed.set_thumbnail(url=alvo.display_avatar.url)
        embed.add_field(
            name="⭐ Nível",
            value=f"`{dados['level']}`",
            inline=True,
        )
        embed.add_field(
            name="✨ XP",
            value=f"`{dados['xp']:,}`",
            inline=True,
        )
        embed.add_field(
            name="💰 Carteira",
            value=f"`{dados['wallet']:,}` {config.CURRENCY_NAME}",
            inline=False,
        )
        embed.add_field(
            name="🏦 Banco",
            value=f"`{dados['bank']:,}` {config.CURRENCY_NAME}",
            inline=True,
        )
        embed.add_field(
            name="🪙 Patrimônio",
            value=(
                f"`{dados['wallet'] + dados['bank']:,}` "
                f"{config.CURRENCY_NAME}"
            ),
            inline=True,
        )
        embed.set_footer(
            text="Sr.Alpha • Family Alpha",
            icon_url=self.bot.user.display_avatar.url
            if self.bot.user else None,
        )

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="conquistas",
        description="Consulta as conquistas de um membro."
    )
    @app_commands.describe(membro="Membro que você quer consultar")
    async def conquistas(
        self,
        interaction: discord.Interaction,
        membro: discord.Member = None,
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este comando só funciona dentro do servidor.",
                ephemeral=True,
            )
            return

        alvo = membro or interaction.user
        dados = await self.obter_usuario(
            interaction.guild.id, alvo.id
        )

        if dados is None:
            await interaction.response.send_message(
                "Não consegui carregar as conquistas.",
                ephemeral=True,
            )
            return

        level = dados["level"]
        xp = dados["xp"]
        patrimonio = dados["wallet"] + dados["bank"]

        conquistas = [
            (level >= 5, "🌟", "Primeiros passos", "Alcançar nível 5"),
            (level >= 10, "💜", "Veterano Alpha", "Alcançar nível 10"),
            (level >= 25, "👑", "Lenda Alpha", "Alcançar nível 25"),
            (xp >= 1000, "⚡", "Sempre ativo", "Acumular 1.000 XP"),
            (patrimonio >= 1000, "💰", "Primeira fortuna",
             "Acumular 1.000 Alpha Coins"),
            (patrimonio >= 10000, "💎", "Magnata Alpha",
             "Acumular 10.000 Alpha Coins"),
        ]

        desbloqueadas = [
            f"{emoji} **{nome}** — {descricao}"
            for obtida, emoji, nome, descricao in conquistas
            if obtida
        ]
        bloqueadas = [
            f"🔒 **{nome}** — {descricao}"
            for obtida, emoji, nome, descricao in conquistas
            if not obtida
        ]

        embed = discord.Embed(
            title=f"🏆 Conquistas de {alvo.display_name}",
            description=(
                "\n".join(desbloqueadas)
                if desbloqueadas
                else "Nenhuma conquista desbloqueada ainda."
            ),
            color=COR,
        )

        if bloqueadas:
            embed.add_field(
                name="Próximas conquistas",
                value="\n".join(bloqueadas),
                inline=False,
            )

        embed.set_thumbnail(url=alvo.display_avatar.url)
        embed.set_footer(text="Continue evoluindo no Family Alpha!")

        await interaction.response.send_message(embed=embed)

    @app_commands.command(
        name="top",
        description="Exibe o ranking dos membros do servidor."
    )
    @app_commands.choices(tipo=[
        app_commands.Choice(name="Nível", value="level"),
        app_commands.Choice(name="XP", value="xp"),
        app_commands.Choice(name="Fortuna", value="fortune"),
    ])
    async def top(
        self,
        interaction: discord.Interaction,
        tipo: app_commands.Choice[str],
    ):
        if interaction.guild is None:
            await interaction.response.send_message(
                "Este comando só funciona dentro do servidor.",
                ephemeral=True,
            )
            return

        coluna = {
            "level": "level",
            "xp": "xp",
            "fortune": "(wallet + bank)",
        }[tipo.value]

        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                f"""
                SELECT user_id, wallet, bank, xp, level
                FROM users
                WHERE guild_id = ?
                ORDER BY {coluna} DESC, xp DESC
                LIMIT 10
                """,
                (interaction.guild.id,),
            )
            membros = await cursor.fetchall()

        if not membros:
            await interaction.response.send_message(
                "Ainda não existem dados para o ranking.",
                ephemeral=True,
            )
            return

        linhas = []
        medalhas = ["🥇", "🥈", "🥉"]

        for posicao, membro in enumerate(membros, start=1):
            user_id, wallet, bank, xp, level = membro
            medalha = (
                medalhas[posicao - 1]
                if posicao <= 3 else f"`#{posicao}`"
            )

            membro_servidor = interaction.guild.get_member(user_id)
            nome = (
                membro_servidor.display_name
                if membro_servidor
                else f"Usuário {user_id}"
            )

            if tipo.value == "level":
                valor = f"Nível {level}"
            elif tipo.value == "xp":
                valor = f"{xp:,} XP"
            else:
                valor = f"{wallet + bank:,} {config.CURRENCY_NAME}"

            linhas.append(f"{medalha} **{nome}** — {valor}")

        embed = discord.Embed(
            title=f"🏆 RANKING ALPHA • {tipo.name.upper()}",
            description="\n".join(linhas),
            color=COR,
        )
        embed.set_footer(text="Family Alpha • Top 10")

        await interaction.response.send_message(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Premium(bot))
