"""Jogos opcionais de sorte usando somente moedas virtuais do servidor.

Não aceita dinheiro real, pagamentos, compras ou transferências externas.
Cada membro precisa ativar a participação voluntariamente.
"""
import random
from datetime import datetime, timezone

import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands

from database import DB_PATH, ensure_user, get_user, has_infinite_coins, format_coins
import config

MIN_BET = 1
MAX_BET = 1000000000


async def init_betting_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS betting_preferences (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (guild_id, user_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS betting_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                game TEXT NOT NULL,
                wager INTEGER NOT NULL,
                net_result INTEGER NOT NULL,
                result TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.commit()


async def betting_enabled(guild_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT enabled FROM betting_preferences WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cur.fetchone()
        return bool(row and row[0])


async def set_betting_enabled(guild_id: int, user_id: int, enabled: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO betting_preferences(guild_id,user_id,enabled)
               VALUES(?,?,?)
               ON CONFLICT(guild_id,user_id) DO UPDATE SET enabled=excluded.enabled""",
            (guild_id, user_id, int(enabled)),
        )
        await db.commit()


class OptionalBetting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def resolve_wager(self, interaction: discord.Interaction, wager):
        """Não converte uma aposta omitida em aposta de carteira inteira."""
        if wager is None:
            return 0
        return wager

    async def check_ready(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id is None:
            await interaction.response.send_message(
                "Estes jogos só funcionam dentro de um servidor.", ephemeral=True
            )
            return False
        if not await betting_enabled(interaction.guild_id, interaction.user.id):
            await interaction.response.send_message(
                "🔒 Você não ativou os jogos opcionais. Use `/apostar_ativar` se quiser participar. "
                "A participação é voluntária e usa apenas moedas virtuais.", ephemeral=True
            )
            return False
        return True

    async def play(self, interaction: discord.Interaction, game: str, wager: int,
                   won: bool, payout: int, result: str):
        guild_id = interaction.guild_id
        user_id = interaction.user.id
        if guild_id is None:
            return
        if wager is None or wager < MIN_BET or wager > MAX_BET:
            return await interaction.response.send_message(
                f"Informe explicitamente uma aposta entre {MIN_BET:,} e {MAX_BET:,} "
                f"{config.CURRENCY_NAME}. O Sr.Alpha nunca apostará sua carteira inteira automaticamente.",
                ephemeral=True,
            )
        await ensure_user(guild_id, user_id)

        # Débito e prêmio ficam na mesma transação; aposta omitida nunca usa a carteira inteira.
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("BEGIN IMMEDIATE")
            infinite = has_infinite_coins(user_id)
            if not infinite:
                cur = await db.execute(
                    "UPDATE users SET wallet=wallet-? WHERE guild_id=? AND user_id=? AND wallet>=?",
                    (wager, guild_id, user_id, wager),
                )
                if cur.rowcount != 1:
                    await db.rollback()
                    return await interaction.response.send_message(
                        "💸 Você não tem moedas suficientes na carteira para essa jogada. "
                        "Confira com `/saldo` ou ganhe moedas com `/daily` e `/trabalhar`.",
                        ephemeral=True,
                    )
                if payout:
                    await db.execute(
                        "UPDATE users SET wallet=wallet+? WHERE guild_id=? AND user_id=?",
                        (payout, guild_id, user_id),
                    )
            net = payout - wager
            await db.execute(
                """INSERT INTO betting_history
                   (guild_id,user_id,game,wager,net_result,result)
                   VALUES(?,?,?,?,?,?)""",
                (guild_id, user_id, game, wager, net, result),
            )
            await db.commit()

        if won:
            heading = "🎉 Você ganhou!"
            details = f"Prêmio recebido: **{payout:,} {config.CURRENCY_NAME}**"
        else:
            heading = "🎲 Não foi desta vez"
            details = f"Esta rodada custou **{wager:,} {config.CURRENCY_NAME}**"
        panel = discord.ui.LayoutView(timeout=None)
        container = discord.ui.Container(
            discord.ui.TextDisplay(f"## {heading}"),
            discord.ui.Separator(),
            discord.ui.TextDisplay(
                f"**Jogo:** {game}\n{result}\n\n{details}\n"
                f"**Resultado líquido:** {('∞' if infinite else f'{net:+,}')} {config.CURRENCY_NAME}\n"
                f"**Aposta:** {format_coins(user_id, wager)} {config.CURRENCY_NAME}\n\n"
                "Jogos opcionais com moedas virtuais; não há valor em dinheiro real."
            ),
            accent_colour=discord.Colour.from_rgb(145, 103, 255),
        )
        panel.add_item(container)
        await interaction.response.send_message(view=panel, ephemeral=True)

    @app_commands.command(name="apostar_ativar", description="Ative voluntariamente os jogos de moedas virtuais")
    @app_commands.guild_only()
    async def apostar_ativar(self, interaction: discord.Interaction):
        await set_betting_enabled(interaction.guild_id, interaction.user.id, True)
        await interaction.response.send_message(
            "✅ Jogos opcionais ativados para você. Use `/apostar_desativar` a qualquer momento. "
            f"Limite por rodada: {MIN_BET}–{MAX_BET:,} {config.CURRENCY_NAME}. "
            "São apenas moedas virtuais, sem dinheiro real.",
            ephemeral=True,
        )

    @app_commands.command(name="apostar_desativar", description="Desative sua participação nos jogos opcionais")
    @app_commands.guild_only()
    async def apostar_desativar(self, interaction: discord.Interaction):
        await set_betting_enabled(interaction.guild_id, interaction.user.id, False)
        await interaction.response.send_message(
            "🔒 Jogos opcionais desativados para você. Seus saldos e histórico anteriores foram mantidos.",
            ephemeral=True,
        )

    @app_commands.command(name="apostar_cara_coroa", description="Jogue cara ou coroa com moedas virtuais")
    @app_commands.describe(valor="Moedas virtuais (10 a 1000)", escolha="Seu palpite")
    @app_commands.choices(escolha=[
        app_commands.Choice(name="Cara", value="cara"),
        app_commands.Choice(name="Coroa", value="coroa"),
    ])
    @app_commands.guild_only()
    async def apostar_cara_coroa(
        self, interaction: discord.Interaction,
        escolha: app_commands.Choice[str],
        valor: app_commands.Range[int, MIN_BET, MAX_BET] = None,
    ):
        if not await self.check_ready(interaction):
            return
        valor = await self.resolve_wager(interaction, valor)
        result = random.choice(("cara", "coroa"))
        won = escolha.value == result
        payout = valor * 2 if won else 0
        await self.play(interaction, "Cara ou coroa", valor, won, payout,
                        f"A moeda caiu em **{result.title()}**. Sua escolha: **{escolha.name}**.")

    @app_commands.command(name="apostar_sorte", description="Adivinhe um número de 1 a 5")
    @app_commands.describe(valor="Moedas virtuais (10 a 1000)", numero="Escolha um número de 1 a 5")
    @app_commands.guild_only()
    async def apostar_sorte(
        self, interaction: discord.Interaction,
        numero: app_commands.Range[int, 1, 5],
        valor: app_commands.Range[int, MIN_BET, MAX_BET] = None,
    ):
        if not await self.check_ready(interaction):
            return
        valor = await self.resolve_wager(interaction, valor)
        drawn = random.randint(1, 5)
        won = numero == drawn
        payout = valor * 4 if won else 0
        await self.play(interaction, "Número da sorte", valor, won, payout,
                        f"Número sorteado: **{drawn}**. Seu palpite: **{numero}**.")

    @app_commands.command(name="apostar_slots", description="Gire três símbolos em um caça-níquel virtual")
    @app_commands.describe(valor="Moedas virtuais (10 a 1000)")
    @app_commands.guild_only()
    async def apostar_slots(
        self, interaction: discord.Interaction,
        valor: app_commands.Range[int, MIN_BET, MAX_BET] = None,
    ):
        if not await self.check_ready(interaction):
            return
        valor = await self.resolve_wager(interaction, valor)
        symbols = [random.choice(("🍒", "🍋", "⭐", "💎", "🔔")) for _ in range(3)]
        if symbols[0] == symbols[1] == symbols[2]:
            payout = valor * 4
        elif len(set(symbols)) == 2:
            payout = valor * 2
        else:
            payout = 0
        won = payout > 0
        await self.play(interaction, "Caça-níquel virtual", valor, won, payout,
                        " | ".join(symbols))

    @app_commands.command(name="apostar", description="Abra o menu de apostas com Sr.Coins virtuais")
    @app_commands.describe(
        jogo="Escolha o jogo",
        valor="Quantidade de Sr.Coins que deseja apostar",
        escolha="Palpite para cara ou coroa",
        numero="Número da sorte entre 1 e 5",
    )
    @app_commands.choices(
        jogo=[
            app_commands.Choice(name="Cara ou coroa", value="cara_coroa"),
            app_commands.Choice(name="Número da sorte", value="sorte"),
            app_commands.Choice(name="Caça-níquel", value="slots"),
        ],
        escolha=[
            app_commands.Choice(name="Cara", value="cara"),
            app_commands.Choice(name="Coroa", value="coroa"),
        ],
    )
    @app_commands.guild_only()
    async def apostar(
        self,
        interaction: discord.Interaction,
        jogo: app_commands.Choice[str],
        valor: app_commands.Range[int, MIN_BET, MAX_BET],
        escolha: app_commands.Choice[str] = None,
        numero: app_commands.Range[int, 1, 5] = None,
    ):
        if not await self.check_ready(interaction):
            return

        if jogo.value == "cara_coroa":
            if escolha is None:
                return await interaction.response.send_message(
                    "Escolha Cara ou Coroa no campo escolha.", ephemeral=True
                )
            drawn = random.choice(("cara", "coroa"))
            won = escolha.value == drawn
            payout = valor * 2 if won else 0
            result = f"A moeda caiu em **{drawn.title()}**. Sua escolha: **{escolha.name}**."
            game_name = "Cara ou coroa"
        elif jogo.value == "sorte":
            if numero is None:
                return await interaction.response.send_message(
                    "Informe seu palpite de 1 a 5 no campo numero.", ephemeral=True
                )
            drawn = random.randint(1, 5)
            won = numero == drawn
            payout = valor * 4 if won else 0
            result = f"Número sorteado: **{drawn}**. Seu palpite: **{numero}**."
            game_name = "Número da sorte"
        else:
            symbols = [random.choice(("🍒", "🍋", "⭐", "💎", "🔔")) for _ in range(3)]
            if symbols[0] == symbols[1] == symbols[2]:
                payout = valor * 4
            elif len(set(symbols)) == 2:
                payout = valor * 2
            else:
                payout = 0
            won = payout > 0
            result = " | ".join(symbols)
            game_name = "Caça-níquel virtual"

        await self.play(interaction, game_name, valor, won, payout, result)

    @app_commands.command(name="apostar_historico", description="Veja seu histórico recente dos jogos opcionais")
    @app_commands.guild_only()
    async def apostar_historico(self, interaction: discord.Interaction):
        if interaction.guild_id is None:
            return await interaction.response.send_message("Use este comando em um servidor.", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                """SELECT game,wager,net_result,result,created_at FROM betting_history
                   WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10""",
                (interaction.guild_id, interaction.user.id),
            )
            rows = await cur.fetchall()
        if not rows:
            return await interaction.response.send_message(
                "Você ainda não tem rodadas registradas. Se quiser participar, use `/apostar_ativar`.",
                ephemeral=True,
            )
        lines = [
            f"**{game}** — líquido: {net:+,} {config.CURRENCY_NAME} (aposta {wager:,})\n"
            f"_{result[:120]} · {created_at}_"
            for game, wager, net, result, created_at in rows
        ]
        view = discord.ui.LayoutView(timeout=None)
        view.add_item(discord.ui.Container(
            discord.ui.TextDisplay("## 📊 Seu histórico recente"),
            discord.ui.Separator(),
            discord.ui.TextDisplay("\n\n".join(lines)),
            accent_colour=discord.Colour.from_rgb(145, 103, 255),
        ))
        await interaction.response.send_message(view=view, ephemeral=True)


async def setup(bot: commands.Bot):
    await init_betting_db()
    await bot.add_cog(OptionalBetting(bot))
