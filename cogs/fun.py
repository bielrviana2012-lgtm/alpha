
import random
import asyncio
import logging
import discord
import aiosqlite

from discord import app_commands
from discord.ext import commands

from database import DB_PATH, ensure_user, has_infinite_coins, format_coins, register_game_use
import config


COR = discord.Color.from_rgb(145, 103, 255)
VERDE = discord.Color.from_rgb(46, 204, 113)
VERMELHO = discord.Color.from_rgb(231, 76, 60)
OURO = discord.Color.from_rgb(241, 196, 15)

MODOS = [
    app_commands.Choice(name="🎮 Brincadeira grátis", value="free"),
    app_commands.Choice(name="🪙 Apostar Alpha Coins", value="bet"),
]

# Uma única partida de Mines ativa por jogador neste processo.
ACTIVE_MINES = set()
BLACKJACK_LOG = logging.getLogger("Rei Dado.games")


def embed_jogo(titulo, descricao, cor=COR, partida=None, jogo=None):
    layout = discord.ui.LayoutView(timeout=None)
    panel = discord.ui.Container(accent_colour=cor)
    panel.add_item(discord.ui.TextDisplay(f"# ✦ REI DADO • {titulo}"))
    panel.add_item(discord.ui.Separator())
    panel.add_item(discord.ui.TextDisplay(descricao[:4000]))
    panel.add_item(discord.ui.Separator())
    panel.add_item(discord.ui.TextDisplay(f"-# {jogo or titulo} • Partida: {partida:05d}" if partida is not None else "-# Family Alpha • Arcade Premium"))
    layout.add_item(panel)
    return layout

async def aposta_efetiva(interaction, modo, aposta):
    """Nunca transforma uma aposta omitida em aposta de carteira inteira."""
    if modo != "bet":
        return 0
    # O valor precisa ser informado explicitamente; evita all-in acidental.
    return aposta if aposta is not None else 0


async def finalizar_jogo(interaction, modo, aposta, titulo, descricao,
                         premio=0, empate=False):
    """Premio é o retorno TOTAL, incluindo a aposta devolvida."""
    if interaction.guild is None:
        return await interaction.response.send_message(
            "Este jogo só funciona dentro do servidor.",
            ephemeral=True,
        )

    if modo == "free":
        embed = embed_jogo(
            titulo,
            f"{descricao}\n\n🎮 **Modo brincadeira**\n"
            "Nenhuma moeda foi ganha ou perdida.",
            partida=interaction.extras.get("game_partida"),
            jogo=interaction.extras.get("game_nome", titulo),
        )
        return await interaction.response.send_message(view=embed)

    if aposta is None or aposta < 1:
        return await interaction.response.send_message(
            "Escolha uma aposta de pelo menos 1 Alpha Coin.",
            ephemeral=True,
        )

    guild_id = interaction.guild.id
    user_id = interaction.user.id
    await ensure_user(guild_id, user_id)
    infinite = has_infinite_coins(user_id)

    async with aiosqlite.connect(DB_PATH) as db:
        # Serializa a operação completa. Dois jogos simultâneos não podem
        # validar o mesmo saldo e depois debitar/prêmio de forma inconsistente.
        await db.execute("BEGIN IMMEDIATE")
        cursor = await db.execute(
            "SELECT wallet FROM users WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()

        if not infinite and (row is None or row[0] < aposta):
            saldo = row[0] if row else 0
            BLACKJACK_LOG.warning(
                "saldo_insuficiente guild_id=%s user_id=%s db_path=%s wallet=%s aposta=%s",
                guild_id, user_id, str(DB_PATH), saldo, aposta,
            )
            await db.rollback()
            return await interaction.response.send_message(
                f"Saldo insuficiente para <@{user_id}> (ID: `{user_id}`). "
                f"Sua carteira nesta base de dados tem **{saldo:,} {config.CURRENCY_NAME}** "
                f"e a aposta é **{aposta:,}**. Nenhuma moeda foi alterada. "
                f"Servidor ID: `{guild_id}`.",
                ephemeral=True,
            )

        if not infinite:
            cursor = await db.execute(
                "UPDATE users SET wallet=wallet-?+? "
                "WHERE guild_id=? AND user_id=? AND wallet>=?",
                (aposta, premio, guild_id, user_id, aposta),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return await interaction.response.send_message(
                    "Não consegui confirmar seu saldo; nenhuma moeda foi alterada. "
                    "Confira /saldo e tente novamente.",
                    ephemeral=True,
                )

        cursor = await db.execute(
            "SELECT wallet FROM users WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        current = await cursor.fetchone()
        novo_saldo = current[0] if current else 0
        await db.commit()

    if empate:
        resultado = f"🤝 Empate! A aposta foi devolvida: **{aposta:,}**."
        cor = OURO
    elif premio > aposta:
        lucro = premio - aposta
        resultado = f"🏆 Você venceu e lucrou **{lucro:,}** moedas!"
        cor = VERDE
    elif premio == aposta:
        resultado = "🤝 Sua aposta foi devolvida."
        cor = OURO
    else:
        resultado = f"💨 Você perdeu **{aposta:,}** moedas."
        cor = VERMELHO

    saldo_formatado = "∞" if infinite else f"{novo_saldo:,}"
    embed = embed_jogo(
        titulo,
        f"**Jogador:** <@{user_id}> (ID: {user_id})\n"
        f"{descricao}\n\n{resultado}\n\n"
        f"💰 **Carteira atual:** {saldo_formatado} {config.CURRENCY_NAME}",
        cor,
        partida=interaction.extras.get("game_partida"),
        jogo=interaction.extras.get("game_nome", titulo),
    )
    await interaction.response.send_message(view=embed)


class MinesView(discord.ui.LayoutView):
    """Mines com quantidade configurável de minas e saque manual."""

    TILE_COUNT = 24

    def __init__(self, owner_id, guild_id, modo, aposta, minas, partida=None):
        super().__init__(timeout=120)
        self.owner_id, self.guild_id = owner_id, guild_id
        self.modo, self.aposta, self.mine_count = modo, aposta, minas
        self.partida = partida
        self.mine_positions = set(random.sample(range(self.TILE_COUNT), minas))
        self.revealed = set()
        self.done = False
        self.result_text = ""
        self.message = None
        self._settlement_lock = asyncio.Lock()
        self._active_key = (guild_id, owner_id)
        self._build()

    def _release_active(self):
        ACTIVE_MINES.discard(self._active_key)

    def _multiplier(self):
        probability = 1.0
        for i in range(len(self.revealed)):
            probability *= (self.TILE_COUNT - self.mine_count - i) / (self.TILE_COUNT - i)
        return 0.0 if probability <= 0 else 0.97 / probability

    def _build(self):
        self.clear_items()
        panel = discord.ui.Container(accent_colour=COR)
        panel.add_item(discord.ui.TextDisplay("# 💣 REI DADO • Mines"))
        panel.add_item(discord.ui.Separator())
        safe_count = len(self.revealed)
        multiplier = self._multiplier() if safe_count else 1.0
        info = f"**Minas:** {self.mine_count} de {self.TILE_COUNT}\n**Casas seguras:** {safe_count}\n"
        if self.modo == "bet":
            info += (f"**Aposta:** {self.aposta:,} {config.CURRENCY_NAME}\n"
                     f"**Retorno se sacar agora:** {int(self.aposta * multiplier):,} "
                     f"{config.CURRENCY_NAME} ({multiplier:.2f}x)")
        else:
            info += "**Modo:** 🎮 Brincadeira grátis"
        panel.add_item(discord.ui.TextDisplay(info))
        if self.done:
            panel.add_item(discord.ui.Separator())
            panel.add_item(discord.ui.TextDisplay(self.result_text))
            panel.add_item(discord.ui.TextDisplay(f"-# Partida: {self.partida:05d} • Family Alpha" if self.partida is not None else "-# Family Alpha • Arcade Premium"))
            self.add_item(panel)
            return
        panel.add_item(discord.ui.TextDisplay(
            "Revele casas seguras. Se encontrar uma mina, perde a rodada. "
            "Depois de revelar uma casa segura, você pode usar **💰 Sacar**."
        ))
        panel.add_item(discord.ui.TextDisplay(f"-# Partida: {self.partida:05d} • Family Alpha" if self.partida is not None else "-# Family Alpha • Arcade Premium"))
        self.add_item(panel)

        # 24 casas e o botão Sacar cabem em cinco linhas de cinco botões.
        for row_index in range(5):
            row = discord.ui.ActionRow()
            for index in range(row_index * 5, min(row_index * 5 + 5, self.TILE_COUNT)):
                if index in self.revealed:
                    label = "💣" if index in self.mine_positions else "💎"
                    button = discord.ui.Button(label=label, style=discord.ButtonStyle.danger if label == "💣" else discord.ButtonStyle.success, disabled=True)
                else:
                    button = discord.ui.Button(label="❔", style=discord.ButtonStyle.secondary)
                    button.callback = self.make_tile_callback(index)
                row.add_item(button)
            if row_index == 4:
                cashout = discord.ui.Button(label="💰 Sacar", style=discord.ButtonStyle.success, disabled=(safe_count == 0))
                cashout.callback = self.cash_out
                row.add_item(cashout)
            self.add_item(row)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("Esta partida pertence a outra pessoa.", ephemeral=True)
            return False
        return True

    def make_tile_callback(self, index):
        async def callback(interaction: discord.Interaction):
            async with self._settlement_lock:
                if self.done:
                    return await interaction.response.send_message("Esta partida já terminou.", ephemeral=True)
                if index in self.revealed:
                    return await interaction.response.send_message("Essa casa já foi revelada.", ephemeral=True)
                if index in self.mine_positions:
                    self.revealed.add(index)
                    self.done = True
                    self.revealed.update(self.mine_positions)
                    self.result_text = "💥 **Você encontrou uma mina!** "
                    self.result_text += f"Você perdeu a aposta de {self.aposta:,} moedas." if self.modo == "bet" else "Fim da rodada grátis."
                    self._build()
                    self._release_active()
                    self.stop()
                    BLACKJACK_LOG.info("mines=loss guild=%s user=%s mode=%s bet=%s mines=%s",
                        self.guild_id, self.owner_id, self.modo, self.aposta, self.mine_count)
                    return await interaction.response.edit_message(view=self)
                self.revealed.add(index)
                self._build()
                await interaction.response.edit_message(view=self)
        return callback

    async def cash_out(self, interaction: discord.Interaction):
        async with self._settlement_lock:
            if self.done:
                return await interaction.response.send_message("Esta partida já terminou.", ephemeral=True)
            if not self.revealed:
                return await interaction.response.send_message("Revele pelo menos uma casa segura antes de sacar.", ephemeral=True)
            self.done = True
            retorno = int(self.aposta * self._multiplier()) if self.modo == "bet" else 0
            if self.modo == "bet":
                if has_infinite_coins(self.owner_id):
                    saldo_texto = "∞"
                else:
                    await ensure_user(self.guild_id, self.owner_id)
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute("BEGIN IMMEDIATE")
                        await db.execute("UPDATE users SET wallet=wallet+? WHERE guild_id=? AND user_id=?",
                            (retorno, self.guild_id, self.owner_id))
                        cursor = await db.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?",
                            (self.guild_id, self.owner_id))
                        row = await cursor.fetchone()
                        await db.commit()
                    saldo_texto = f"{row[0]:,}" if row else "0"
                self.result_text = (f"💰 **Retorno total: {retorno:,} {config.CURRENCY_NAME}**\n"
                    f"Lucro líquido: **{retorno - self.aposta:+,}** moedas.\n"
                    f"Carteira atual: **{saldo_texto}** {config.CURRENCY_NAME}")
            else:
                self.result_text = f"💎 Você sacou após revelar **{len(self.revealed)}** casas seguras!"
            self._build()
            self._release_active()
            self.stop()
            BLACKJACK_LOG.info("mines=cashout guild=%s user=%s mode=%s bet=%s mines=%s safe=%s payout=%s",
                self.guild_id, self.owner_id, self.modo, self.aposta, self.mine_count, len(self.revealed), retorno)
            await interaction.response.edit_message(view=self)

    async def on_timeout(self):
        async with self._settlement_lock:
            if self.done:
                self._release_active()
                return
            self.done = True
            if self.modo == "bet" and self.aposta > 0:
                # Sem nenhuma casa revelada, devolve a reserva. Se já houve
                # progresso, liquida como saque automático para evitar abuso.
                retorno = int(self.aposta * self._multiplier()) if self.revealed else self.aposta
                if has_infinite_coins(self.owner_id):
                    saldo_texto = "∞"
                else:
                    await ensure_user(self.guild_id, self.owner_id)
                    async with aiosqlite.connect(DB_PATH) as db:
                        await db.execute("BEGIN IMMEDIATE")
                        await db.execute("UPDATE users SET wallet=wallet+? WHERE guild_id=? AND user_id=?",
                            (retorno, self.guild_id, self.owner_id))
                        cursor = await db.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?",
                            (self.guild_id, self.owner_id))
                        row = await cursor.fetchone()
                        await db.commit()
                    saldo_texto = f"{row[0]:,}" if row else "0"
                if self.revealed:
                    self.result_text = (
                        f"⌛ Tempo esgotado; saque automático de {retorno:,} "
                        f"{config.CURRENCY_NAME}. Carteira: {saldo_texto}."
                    )
                else:
                    self.result_text = (
                        f"⌛ Expirou sem casas reveladas. A aposta de {self.aposta:,} "
                        f"{config.CURRENCY_NAME} foi devolvida. Carteira: {saldo_texto}."
                    )
            else:
                self.result_text = "⌛ A partida grátis expirou."
            self._build()
            if self.message:
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    pass
            self._release_active()
            BLACKJACK_LOG.info("mines=timeout guild=%s user=%s mode=%s bet=%s safe=%s",
                self.guild_id, self.owner_id, self.modo, self.aposta, len(self.revealed))


class QuizView(discord.ui.LayoutView):
    def __init__(self, options, answer, owner_id, question, partida=None):
        super().__init__(timeout=30)
        self.answer = answer
        self.owner_id = owner_id
        self.question = question
        self.partida = partida
        self.done = False
        self.result_title = None
        self.result_description = None
        self.result_color = COR
        self._build_layout(options)

    def _build_layout(self, options=None):
        self.clear_items()
        panel = discord.ui.Container(accent_colour=self.result_color)
        if self.done:
            panel.add_item(discord.ui.TextDisplay(f"# ✦ REI DADO • {self.result_title}"))
            panel.add_item(discord.ui.Separator())
            panel.add_item(discord.ui.TextDisplay(self.result_description))
            panel.add_item(discord.ui.TextDisplay("-# Family Alpha • Arcade Premium"))
            self.add_item(panel)
            return

        panel.add_item(discord.ui.TextDisplay("# 🧠 Quiz Alpha"))
        panel.add_item(discord.ui.Separator())
        panel.add_item(discord.ui.TextDisplay(f"**{self.question}**\n\nEscolha uma resposta abaixo!"))
        panel.add_item(discord.ui.TextDisplay("-# Family Alpha • Arcade Premium"))
        self.add_item(panel)

        row = discord.ui.ActionRow()
        for i, option in enumerate(options or []):
            button = discord.ui.Button(label=option, style=discord.ButtonStyle.primary)
            button.callback = self.make_callback(i, options)
            row.add_item(button)
        self.add_item(row)

    def make_callback(self, index, options):
        async def callback(interaction):
            if interaction.user.id != self.owner_id:
                return await interaction.response.send_message(
                    "Este quiz pertence a outra pessoa.", ephemeral=True
                )
            if self.done:
                return await interaction.response.send_message(
                    "Esta pergunta já foi respondida.", ephemeral=True
                )
            self.done = True
            correto = index == self.answer
            self.result_title = "Quiz Alpha"
            self.result_description = "🎉 Resposta correta!" if correto else "❌ Resposta incorreta! Tente novamente."
            self.result_color = VERDE if correto else VERMELHO
            self._build_layout()
            await interaction.response.edit_message(embeds=[], view=self)
        return callback


QUESTIONS = [
    ("Qual é o planeta conhecido como planeta vermelho?",
     ["Marte", "Vênus", "Júpiter", "Saturno"], 0),
    ("Quantos lados tem um hexágono?",
     ["5", "6", "7", "8"], 1),
    ("Qual é o maior oceano da Terra?",
     ["Atlântico", "Índico", "Pacífico", "Ártico"], 2),
    ("Qual linguagem é muito usada com discord.py?",
     ["Python", "CSS", "SQL apenas", "HTML apenas"], 0),
    ("Qual é o resultado de 9 × 7?",
     ["56", "63", "72", "79"], 1),
]


class Fun(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="jogos", aliases=["games"])
    async def listar_jogos(self, ctx: commands.Context):
        """Lista os jogos disponíveis usando o prefixo !."""
        painel = embed_jogo(
            "🎮 Arcade da Family Alpha",
            "**Jogos disponíveis**\n\n"
            "🧠 !jogos — mostra esta lista\n"
            "🧩 /quiz — perguntas de conhecimentos gerais\n"
            "✊ /ppt — pedra, papel e tesoura\n"
            "🪙 /moeda — jogue uma moeda\n"
            "🎲 /dado — role um dado\n"
            "🎰 /slots — caça-níquel\n"
            "🎡 /roleta — roleta de cores\n"
            "🎲 /dados — duelo de dados\n"
            "💣 /mines — escolha a quantidade de minas e saque no momento certo\n"
            "🪙 /caraoucoroa — adivinhe cara ou coroa\n"
            "🎁 /bau — abra um baú misterioso\n"
            "🔮 /8ball — consulte a bola mágica\n"
            "⚔️ /duelo — duelo de sorte\n\n"
            "Nos jogos com aposta, escolha o modo de Alpha Coins quando disponível."
        )
        await ctx.send(view=painel)

    @app_commands.command(
        name="quiz",
        description="Responda a uma pergunta de conhecimentos gerais",
    )
    async def quiz(self, interaction: discord.Interaction):
        pergunta, opcoes, resposta = random.choice(QUESTIONS)
        await interaction.response.send_message(
            view=QuizView(opcoes, resposta, interaction.user.id, pergunta, interaction.extras.get("game_partida")),
        )

    @app_commands.command(
        name="ppt",
        description="Pedra, papel e tesoura com o Rei Dado",
    )
    @app_commands.choices(
        escolha=[
            app_commands.Choice(name=x, value=x.lower())
            for x in ["Pedra", "Papel", "Tesoura"]
        ],
        modo=MODOS,
    )
    async def ppt(
        self,
        interaction: discord.Interaction,
        escolha: app_commands.Choice[str],
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 1000000000] = None,
    ):
        interaction.extras["game_nome"] = "ppt"
        interaction.extras["game_partida"] = await register_game_use(interaction.guild_id or 0, "ppt")
        interaction.extras["game_nome"] = "quiz"
        interaction.extras["game_partida"] = await register_game_use(interaction.guild_id or 0, "quiz")
        aposta = await aposta_efetiva(interaction, modo.value, aposta)
        jogador = escolha.value
        bot = random.choice(["pedra", "papel", "tesoura"])

        if jogador == bot:
            premio = aposta or 0
            empate = True
            resultado = "🤝 Empate!"
        elif (jogador, bot) in [
            ("pedra", "tesoura"),
            ("papel", "pedra"),
            ("tesoura", "papel"),
        ]:
            premio = (aposta or 0) * 2
            empate = False
            resultado = "🏆 Você venceu!"
        else:
            premio = 0
            empate = False
            resultado = "💨 O Rei Dado venceu!"

        await finalizar_jogo(
            interaction, modo.value, aposta, "✊ Pedra, papel e tesoura",
            f"Você: **{jogador.title()}**\n"
            f"Rei Dado: **{bot.title()}**\n{resultado}",
            premio, empate,
        )

    @app_commands.command(name="moeda", description="Jogue uma moeda virtual")
    @app_commands.choices(modo=MODOS)
    @app_commands.choices(
        escolha=[
            app_commands.Choice(name="Cara", value="Cara"),
            app_commands.Choice(name="Coroa", value="Coroa"),
        ]
    )
    async def moeda(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        escolha: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 10000] = None,
    ):
        interaction.extras["game_nome"] = "CoinFlip"
        interaction.extras["game_partida"] = await register_game_use(interaction.guild_id or 0, "CoinFlip")
        aposta = await aposta_efetiva(interaction, modo.value, aposta)
        resultado = random.choice(["Cara", "Coroa"])
        venceu = escolha.value == resultado
        premio = (aposta or 0) * 2 if venceu else 0

        await finalizar_jogo(
            interaction, modo.value, aposta, "🪙 Cara ou coroa",
            f"Sua escolha: **{escolha.value}**\n"
            f"Resultado: **{resultado}**\n"
            f"{'🏆 Você acertou!' if venceu else '💨 Não foi dessa vez!'}",
            premio,
        )

    @app_commands.command(name="dado", description="Role um dado de seis lados")
    @app_commands.choices(modo=MODOS)
    async def dado(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 10000] = None,
    ):
        interaction.extras["game_nome"] = "dado"
        interaction.extras["game_partida"] = await register_game_use(interaction.guild_id or 0, "dado")
        aposta = await aposta_efetiva(interaction, modo.value, aposta)
        resultado = random.randint(1, 6)
        venceu = resultado >= 4
        premio = (aposta or 0) * 2 if venceu else 0

        await finalizar_jogo(
            interaction, modo.value, aposta, "🎲 Dado Alpha",
            f"Você tirou **{resultado}**.\n"
            f"{'🏆 Você venceu! (4 a 6)' if venceu else '💨 Você perdeu! (1 a 3)'}",
            premio,
        )

    @app_commands.command(name="slots", description="Jogue no caça-níquel Alpha")
    @app_commands.choices(modo=MODOS)
    async def slots(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 10000] = None,
    ):
        interaction.extras["game_nome"] = "slots"
        interaction.extras["game_partida"] = await register_game_use(interaction.guild_id or 0, "slots")
        aposta = await aposta_efetiva(interaction, modo.value, aposta)
        simbolos = ["🍒", "💎", "⭐", "🍀", "🔔"]
        rolos = [random.choice(simbolos) for _ in range(3)]
        iguais = len(set(rolos)) == 1
        dois = len(set(rolos)) == 2

        multiplicador = 5 if iguais else 2 if dois else 0
        premio = (aposta or 0) * multiplicador

        await finalizar_jogo(
            interaction, modo.value, aposta, "🎰 Slots Alpha",
            f"╭────────────╮\n"
            f"│  {'  '.join(rolos)}  │\n"
            f"╰────────────╯\n\n"
            f"{'💎 Trinca! Retorno de 5x!' if iguais else '✨ Dois símbolos! Retorno de 2x!' if dois else '💨 Nenhuma combinação.'}",
            premio,
        )

    @app_commands.command(name="roleta", description="Escolha vermelho, preto ou verde")
    @app_commands.choices(
        modo=MODOS,
        cor=[
            app_commands.Choice(name="🔴 Vermelho", value="vermelho"),
            app_commands.Choice(name="⚫ Preto", value="preto"),
            app_commands.Choice(name="🟢 Verde", value="verde"),
        ],
    )
    async def roleta(
        self,
        interaction: discord.Interaction,
        cor: app_commands.Choice[str],
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 10000] = None,
    ):
        interaction.extras["game_nome"] = "roleta"
        interaction.extras["game_partida"] = await register_game_use(interaction.guild_id or 0, "roleta")
        aposta = await aposta_efetiva(interaction, modo.value, aposta)
        resultado = random.choices(
            ["vermelho", "preto", "verde"],
            weights=[5, 5, 1],
        )[0]
        multiplicador = 10 if resultado == "verde" else 2
        venceu = cor.value == resultado
        premio = (aposta or 0) * multiplicador if venceu else 0

        await finalizar_jogo(
            interaction, modo.value, aposta, "🎡 Roleta Alpha",
            f"Sua cor: **{cor.value.title()}**\n"
            f"Resultado: **{resultado.title()}**\n"
            f"{'🏆 Você acertou a cor!' if venceu else '💨 A sorte não estava do seu lado.'}",
            premio,
        )

    @app_commands.command(name="dados", description="Desafie o Rei Dado nos dados")
    @app_commands.choices(modo=MODOS)
    async def dados(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 10000] = None,
    ):
        interaction.extras["game_nome"] = "dados"
        interaction.extras["game_partida"] = await register_game_use(interaction.guild_id or 0, "dados")
        aposta = await aposta_efetiva(interaction, modo.value, aposta)
        seu = random.randint(1, 6)
        alpha = random.randint(1, 6)
        empate = seu == alpha
        venceu = seu > alpha
        premio = (aposta or 0) * 2 if venceu else (aposta or 0) if empate else 0

        await finalizar_jogo(
            interaction, modo.value, aposta, "🎲 Duelo de dados",
            f"Você: **{seu}**\nRei Dado: **{alpha}**\n"
            f"{'🏆 Você venceu!' if venceu else '🤝 Empate!' if empate else '💨 Rei Dado venceu!'}",
            premio, empate,
        )

    @app_commands.command(name="mines", description="Encontre casas seguras e saque antes de acertar uma mina")
    @app_commands.choices(modo=MODOS)
    async def mines(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        minas: app_commands.Range[int, 1, 23],
        aposta: app_commands.Range[int, 1, 1000000000] = None,
    ):
        interaction.extras["game_nome"] = "mines"
        interaction.extras["game_partida"] = await register_game_use(interaction.guild_id or 0, "mines")
        if interaction.guild is None:
            return await interaction.response.send_message("Este jogo só funciona dentro do servidor.", ephemeral=True)
        if modo.value == "bet" and (aposta is None or aposta < 1):
            return await interaction.response.send_message("Informe uma aposta de pelo menos 1 Alpha Coin.", ephemeral=True)

        active_key = (interaction.guild.id, interaction.user.id)
        if active_key in ACTIVE_MINES:
            return await interaction.response.send_message("Você já tem uma partida de **Mines** em andamento. Termine-a antes de iniciar outra.", ephemeral=True)
        ACTIVE_MINES.add(active_key)
        valor_aposta = aposta if modo.value == "bet" else 0
        infinite = has_infinite_coins(interaction.user.id)
        try:
            if modo.value == "bet":
                await ensure_user(interaction.guild.id, interaction.user.id)
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("BEGIN IMMEDIATE")
                    cursor = await db.execute("SELECT wallet FROM users WHERE guild_id=? AND user_id=?",
                        (interaction.guild.id, interaction.user.id))
                    row = await cursor.fetchone()
                    saldo = row[0] if row else 0
                    if not infinite and saldo < valor_aposta:
                        await db.rollback()
                        ACTIVE_MINES.discard(active_key)
                        return await interaction.response.send_message(f"Saldo insuficiente. Sua carteira tem {saldo:,} {config.CURRENCY_NAME}.", ephemeral=True)
                    if not infinite:
                        cursor = await db.execute("UPDATE users SET wallet=wallet-? WHERE guild_id=? AND user_id=? AND wallet>=?",
                            (valor_aposta, interaction.guild.id, interaction.user.id, valor_aposta))
                        if cursor.rowcount != 1:
                            await db.rollback()
                            ACTIVE_MINES.discard(active_key)
                            return await interaction.response.send_message("Não consegui reservar sua aposta. Nenhuma moeda foi alterada.", ephemeral=True)
                    await db.commit()
        except Exception:
            ACTIVE_MINES.discard(active_key)
            raise

        partida = MinesView(interaction.user.id, interaction.guild.id, modo.value, valor_aposta, minas, interaction.extras.get("game_partida"))
        try:
            await interaction.response.send_message(view=partida)
            partida.message = await interaction.original_response()
        except discord.HTTPException:
            partida.done = True
            partida.stop()
            if modo.value == "bet" and valor_aposta > 0 and not infinite:
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("BEGIN IMMEDIATE")
                    await db.execute("UPDATE users SET wallet=wallet+? WHERE guild_id=? AND user_id=?",
                        (valor_aposta, interaction.guild.id, interaction.user.id))
                    await db.commit()
                BLACKJACK_LOG.warning("mines=publish_failure_refund guild=%s user=%s bet=%s",
                    interaction.guild.id, interaction.user.id, valor_aposta)
            ACTIVE_MINES.discard(active_key)
            raise
        except Exception:
            partida.done = True
            partida.stop()
            ACTIVE_MINES.discard(active_key)
            raise

    @app_commands.command(name="caraoucoroa", description="Adivinhe o resultado da moeda")
    @app_commands.choices(
        modo=MODOS,
        escolha=[
            app_commands.Choice(name="Cara", value="Cara"),
            app_commands.Choice(name="Coroa", value="Coroa"),
        ],
    )
    async def caraoucoroa(
        self,
        interaction: discord.Interaction,
        escolha: app_commands.Choice[str],
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 10000] = None,
    ):
        interaction.extras["game_nome"] = "caraoucoroa"
        interaction.extras["game_partida"] = await register_game_use(interaction.guild_id or 0, "caraoucoroa")
        aposta = await aposta_efetiva(interaction, modo.value, aposta)
        resultado = random.choice(["Cara", "Coroa"])
        venceu = escolha.value == resultado

        await finalizar_jogo(
            interaction, modo.value, aposta, "🪙 Cara ou coroa",
            f"Sua escolha: **{escolha.value}**\nResultado: **{resultado}**\n"
            f"{'🏆 Você acertou!' if venceu else '💨 Tente novamente!'}",
            (aposta or 0) * 2 if venceu else 0,
        )

    @app_commands.command(name="bau", description="Abra um baú misterioso")
    @app_commands.choices(modo=MODOS)
    async def bau(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 10000] = None,
    ):
        interaction.extras["game_nome"] = "bau"
        interaction.extras["game_partida"] = await register_game_use(interaction.guild_id or 0, "bau")
        aposta = await aposta_efetiva(interaction, modo.value, aposta)
        evento = random.choices(
            ["jackpot", "premio", "nada"],
            weights=[1, 4, 5],
        )[0]
        multiplicador = {"jackpot": 5, "premio": 2, "nada": 0}[evento]
        descricao = {
            "jackpot": "🌟 O baú tinha um tesouro lendário! Retorno total de 5x a aposta (aposta incluída).",
            "premio": "🎁 Você encontrou um tesouro! Retorno total de 2x a aposta (aposta incluída).",
            "nada": "📦 O baú estava vazio... Você perdeu a aposta.",
        }[evento]

        await finalizar_jogo(
            interaction, modo.value, aposta, "🎁 Baú misterioso",
            descricao, (aposta or 0) * multiplicador,
        )

    @app_commands.command(name="8ball", description="Analisa sua pergunta e responde com contexto")
    async def oito_bola(self, interaction: discord.Interaction, pergunta: str):
        import os
        import aiohttp

        pergunta = pergunta.strip()
        if not pergunta:
            return await interaction.response.send_message(
                "Escreva uma pergunta para eu analisar.", ephemeral=True
            )

        await interaction.response.defer(thinking=True)

        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        modelo = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip() or "gemini-3.6-flash"
        resposta = None

        if api_key:
            instrucoes = (
                "Você é a Bola Mágica inteligente do bot Discord Rei Dado. "
                "Responda sempre em português brasileiro, de forma direta e útil. "
                "Não sorteie respostas genéricas e nunca diga apenas 'pergunte novamente mais tarde'. "
                "Para perguntas de sim/não, dê SIM ou NÃO logo no começo e explique brevemente os motivos. "
                "Para perguntas como 'qual personagem é o mais forte?', compare personagens usando "
                "informações conhecidas do universo citado, feitos, habilidades e versões/cânone; "
                "diga qual vence segundo esses critérios e ressalve quando depende da versão ou contexto. "
                "Para perguntas factuais, use conhecimento confiável e admita incerteza quando necessário. "
                "Não invente estatísticas nem afirme que consultou fontes ao vivo. "
                "Se houver ambiguidade, responda com a interpretação mais provável e diga qual assumiu. "
                "Mantenha a resposta em até 120 palavras."
            )
            try:
                timeout = aiohttp.ClientTimeout(total=25)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(
                        f"https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent",
                        headers={
                            "x-goog-api-key": api_key,
                            "Content-Type": "application/json",
                        },
                        json={
                            "systemInstruction": {
                                "parts": [{"text": instrucoes}]
                            },
                            "contents": [{
                                "role": "user",
                                "parts": [{"text": pergunta}],
                            }],
                            "generationConfig": {
                                "temperature": 0.2,
                                "maxOutputTokens": 220,
                            },
                        },
                    ) as response:
                        data = await response.json()
                        if response.status == 200:
                            resposta = (
                                data.get("candidates", [{}])[0]
                                .get("content", {})
                                .get("parts", [{}])[0]
                                .get("text", "")
                                .strip()
                            ) or None
                        else:
                            # Registra a causa no log do Railway sem revelar a chave.
                            import logging
                            logging.getLogger("Rei Dado").error(
                                "Gemini API retornou HTTP %s: %s",
                                response.status,
                                str(data)[:700],
                            )
            except (aiohttp.ClientError, asyncio.TimeoutError, KeyError, IndexError, TypeError, ValueError) as exc:
                import logging
                logging.getLogger("Rei Dado").exception("Falha ao consultar a Gemini: %s", exc)

        if not resposta:
            resposta = (
                "Não consegui obter uma resposta da Gemini agora. "
                "Confira se GEMINI_API_KEY está configurada no Railway e se o modelo "
                "definido em GEMINI_MODEL está disponível para sua chave. "
                "Se continuar, confira os logs do serviço para ver o erro da API."
            )

        painel = embed_jogo(
            "🔮 Bola mágica • Análise",
            f"**Pergunta:** {pergunta[:1000]}\n\n**Análise do Rei Dado:** {resposta[:3500]}",
            partida=interaction.extras.get("game_partida"), jogo="8ball",
        )
        await interaction.followup.send(view=painel)

    @app_commands.command(name="duelo", description="Desafie a sorte em um duelo")
    @app_commands.choices(modo=MODOS)
    async def duelo(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 10000] = None,
    ):
        interaction.extras["game_nome"] = "duelo"
        interaction.extras["game_partida"] = await register_game_use(interaction.guild_id or 0, "duelo")
        interaction.extras["game_nome"] = "8ball"
        interaction.extras["game_partida"] = await register_game_use(interaction.guild_id or 0, "8ball")
        aposta = await aposta_efetiva(interaction, modo.value, aposta)
        seu = random.randint(1, 100)
        alpha = random.randint(1, 100)
        empate = seu == alpha
        venceu = seu > alpha
        premio = (aposta or 0) * 2 if venceu else (aposta or 0) if empate else 0

        await finalizar_jogo(
            interaction, modo.value, aposta, "⚔️ Duelo Alpha",
            f"Seu poder: **{seu}**\nPoder do Rei Dado: **{alpha}**\n"
            f"{'🏆 Vitória!' if venceu else '🤝 Empate!' if empate else '💨 Derrota!'}",
            premio, empate,
        )


async def setup(bot):
    await bot.add_cog(Fun(bot))
