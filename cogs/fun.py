
import random
import discord
import aiosqlite

from discord import app_commands
from discord.ext import commands

from database import DB_PATH, ensure_user, has_infinite_coins, format_coins
import config


COR = discord.Color.from_rgb(145, 103, 255)
VERDE = discord.Color.from_rgb(46, 204, 113)
VERMELHO = discord.Color.from_rgb(231, 76, 60)
OURO = discord.Color.from_rgb(241, 196, 15)

MODOS = [
    app_commands.Choice(name="🎮 Brincadeira grátis", value="free"),
    app_commands.Choice(name="🪙 Apostar Alpha Coins", value="bet"),
]


def embed_jogo(titulo, descricao, cor=COR):
    layout = discord.ui.LayoutView(timeout=None)
    panel = discord.ui.Container(accent_colour=cor)
    panel.add_item(discord.ui.TextDisplay(f"# ✦ SR.ALPHA • {titulo}"))
    panel.add_item(discord.ui.Separator())
    panel.add_item(discord.ui.TextDisplay(descricao[:4000]))
    panel.add_item(discord.ui.Separator())
    panel.add_item(discord.ui.TextDisplay("-# Family Alpha • Arcade Premium"))
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

    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT wallet FROM users WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        row = await cursor.fetchone()

        infinite = has_infinite_coins(user_id)
        if not infinite and (row is None or row[0] < aposta):
            saldo = row[0] if row else 0
            await interaction.response.send_message(
                f"Saldo insuficiente! Sua carteira tem "
                f"**{saldo:,} {config.CURRENCY_NAME}**.",
                ephemeral=True,
            )
            return

        # A operação é atômica: impede saldo negativo.
        if not infinite:
            await db.execute(
                """
                UPDATE users
                SET wallet = wallet - ? + ?
                WHERE guild_id = ? AND user_id = ? AND wallet >= ?
                """,
                (aposta, premio, guild_id, user_id, aposta),
            )
            await db.commit()

        cursor = await db.execute(
            "SELECT wallet FROM users WHERE guild_id=? AND user_id=?",
            (guild_id, user_id),
        )
        novo_saldo = (await cursor.fetchone())[0]

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

    embed = embed_jogo(
        titulo,
        f"{descricao}\n\n{resultado}\n\n"
        f"💰 **Carteira atual:** {format_coins(user_id, novo_saldo)} "
        f"{config.CURRENCY_NAME}",
        cor,
    )
    await interaction.response.send_message(view=embed)


class BlackjackView(discord.ui.LayoutView):
    """Jogo de 21 com ações de comprar carta ou parar."""

    def __init__(self, owner_id, guild_id, modo, aposta):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.modo = modo
        self.aposta = aposta
        self.done = False
        self.deck = self._make_deck()
        random.shuffle(self.deck)
        self.player_cards = [self.deck.pop(), self.deck.pop()]
        self.dealer_cards = [self.deck.pop(), self.deck.pop()]
        self.result_text = ""
        self.message = None
        self._build()

    @staticmethod
    def _make_deck():
        suits = ["♠", "♥", "♦", "♣"]
        cards = []
        for suit in suits:
            for label, value in [
                ("A", 11), ("2", 2), ("3", 3), ("4", 4), ("5", 5),
                ("6", 6), ("7", 7), ("8", 8), ("9", 9), ("10", 10),
                ("J", 10), ("Q", 10), ("K", 10),
            ]:
                cards.append((label, value, suit))
        return cards

    @staticmethod
    def _points(cards):
        total = sum(card[1] for card in cards)
        aces = sum(1 for card in cards if card[1] == 11)
        while total > 21 and aces:
            total -= 10
            aces -= 1
        return total

    @staticmethod
    def _show_cards(cards):
        return "  ".join(f"[{label}{suit}]" for label, _, suit in cards)

    def _build(self):
        self.clear_items()
        panel = discord.ui.Container(accent_colour=COR)
        panel.add_item(discord.ui.TextDisplay("# 🃏 SR.ALPHA • Desafio 21"))
        panel.add_item(discord.ui.Separator())
        dealer_cards = self._show_cards(self.dealer_cards) if self.done else f"[{self.dealer_cards[0][0]}{self.dealer_cards[0][2]}]  [??]"
        dealer_points = self._points(self.dealer_cards) if self.done else "?"
        text = (
            f"**Sr.Alpha:** {dealer_cards}\nPontos: **{dealer_points}**\n\n"
            f"**Você:** {self._show_cards(self.player_cards)}\n"
            f"Pontos: **{self._points(self.player_cards)}**"
        )
        if self.modo == "bet":
            text += f"\n\n🪙 Aposta: **{self.aposta:,} {config.CURRENCY_NAME}**"
        else:
            text += "\n\n🎮 Modo brincadeira grátis"
        panel.add_item(discord.ui.TextDisplay(text))

        if self.done:
            panel.add_item(discord.ui.Separator())
            panel.add_item(discord.ui.TextDisplay(self.result_text))
            panel.add_item(discord.ui.TextDisplay("-# Family Alpha • Arcade Premium"))
            self.add_item(panel)
            return

        panel.add_item(discord.ui.TextDisplay("Escolha uma ação: **comprar carta** ou **parar**."))
        panel.add_item(discord.ui.TextDisplay("-# Family Alpha • Arcade Premium"))
        self.add_item(panel)
        row = discord.ui.ActionRow()
        hit = discord.ui.Button(label="🃏 Comprar carta", style=discord.ButtonStyle.primary)
        stand = discord.ui.Button(label="✋ Parar", style=discord.ButtonStyle.success)
        hit.callback = self.hit
        stand.callback = self.stand
        row.add_item(hit)
        row.add_item(stand)
        self.add_item(row)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Esta partida pertence a outra pessoa.", ephemeral=True
            )
            return False
        return True

    async def hit(self, interaction: discord.Interaction):
        if self.done:
            return await interaction.response.send_message("Esta partida já terminou.", ephemeral=True)
        self.player_cards.append(self.deck.pop())
        if self._points(self.player_cards) > 21:
            await self._finish(interaction, "bust")
        else:
            self._build()
            await interaction.response.edit_message(view=self)

    async def stand(self, interaction: discord.Interaction):
        if self.done:
            return await interaction.response.send_message("Esta partida já terminou.", ephemeral=True)
        await self._finish(interaction, "stand")

    async def _finish(self, interaction: discord.Interaction, reason: str):
        self.done = True
        player_points = self._points(self.player_cards)
        dealer_points = self._points(self.dealer_cards)

        if reason != "bust":
            while dealer_points < 17 and self.deck:
                self.dealer_cards.append(self.deck.pop())
                dealer_points = self._points(self.dealer_cards)

        if self.modo == "free":
            if player_points > 21:
                self.result_text = "💥 Você passou de 21! Sr.Alpha venceu."
            elif dealer_points > 21 or player_points > dealer_points:
                self.result_text = "🏆 Você venceu o Sr.Alpha!"
            elif player_points == dealer_points:
                self.result_text = "🤝 Empate!"
            else:
                self.result_text = "💨 Sr.Alpha venceu desta vez."
        else:
            if player_points > 21:
                retorno = 0
                self.result_text = f"💥 Você passou de 21 e perdeu {self.aposta:,} moedas."
            elif dealer_points > 21 or player_points > dealer_points:
                retorno = self.aposta * 2
                self.result_text = f"🏆 Você venceu e recebeu {retorno:,} moedas (aposta incluída)!"
            elif player_points == dealer_points:
                retorno = self.aposta
                self.result_text = f"🤝 Empate! Sua aposta de {self.aposta:,} moedas foi devolvida."
            else:
                retorno = 0
                self.result_text = f"💨 Você perdeu {self.aposta:,} moedas."

            if retorno and not has_infinite_coins(self.owner_id):
                await ensure_user(self.guild_id, self.owner_id)
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute(
                        "UPDATE users SET wallet = wallet + ? WHERE guild_id = ? AND user_id = ?",
                        (retorno, self.guild_id, self.owner_id),
                    )
                    await db.commit()
                    cursor = await db.execute(
                        "SELECT wallet FROM users WHERE guild_id=? AND user_id=?",
                        (self.guild_id, self.owner_id),
                    )
                    row = await cursor.fetchone()
                    saldo = row[0] if row else 0
                self.result_text += f"\n💰 Carteira atual: {format_coins(self.owner_id, saldo)} {config.CURRENCY_NAME}"
            elif has_infinite_coins(self.owner_id):
                self.result_text += f"\n💰 Carteira atual: ∞ {config.CURRENCY_NAME}"

        self._build()
        await interaction.response.edit_message(view=self)
        self.stop()

    async def on_timeout(self):
        if self.done:
            return
        self.done = True
        self.result_text = "⌛ A partida expirou."
        if self.modo == "bet" and self.aposta > 0:
            await ensure_user(self.guild_id, self.owner_id)
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "UPDATE users SET wallet = wallet + ? WHERE guild_id = ? AND user_id = ?",
                    (self.aposta, self.guild_id, self.owner_id),
                )
                await db.commit()
            self.result_text += f" Sua aposta de {self.aposta:,} {config.CURRENCY_NAME} foi devolvida."
        self._build()
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class QuizView(discord.ui.LayoutView):
    def __init__(self, options, answer, owner_id, question):
        super().__init__(timeout=30)
        self.answer = answer
        self.owner_id = owner_id
        self.question = question
        self.done = False
        self.result_title = None
        self.result_description = None
        self.result_color = COR
        self._build_layout(options)

    def _build_layout(self, options=None):
        self.clear_items()
        panel = discord.ui.Container(accent_colour=self.result_color)
        if self.done:
            panel.add_item(discord.ui.TextDisplay(f"# ✦ SR.ALPHA • {self.result_title}"))
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
            "🃏 /21 — compre cartas ou pare; pode apostar a carteira toda\n"
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
            view=QuizView(opcoes, resposta, interaction.user.id, pergunta),
        )

    @app_commands.command(
        name="ppt",
        description="Pedra, papel e tesoura com o Sr.Alpha",
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
            resultado = "💨 O Sr.Alpha venceu!"

        await finalizar_jogo(
            interaction, modo.value, aposta, "✊ Pedra, papel e tesoura",
            f"Você: **{jogador.title()}**\n"
            f"Sr.Alpha: **{bot.title()}**\n{resultado}",
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

    @app_commands.command(name="dados", description="Desafie o Sr.Alpha nos dados")
    @app_commands.choices(modo=MODOS)
    async def dados(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 10000] = None,
    ):
        aposta = await aposta_efetiva(interaction, modo.value, aposta)
        seu = random.randint(1, 6)
        alpha = random.randint(1, 6)
        empate = seu == alpha
        venceu = seu > alpha
        premio = (aposta or 0) * 2 if venceu else (aposta or 0) if empate else 0

        await finalizar_jogo(
            interaction, modo.value, aposta, "🎲 Duelo de dados",
            f"Você: **{seu}**\nSr.Alpha: **{alpha}**\n"
            f"{'🏆 Você venceu!' if venceu else '🤝 Empate!' if empate else '💨 Sr.Alpha venceu!'}",
            premio, empate,
        )

    @app_commands.command(name="21", description="Jogue 21: compre cartas ou pare; pode apostar a carteira toda")
    @app_commands.choices(modo=MODOS)
    async def vinte_um(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 1000000000] = None,
    ):
        if interaction.guild is None:
            return await interaction.response.send_message(
                "Este jogo só funciona dentro do servidor.", ephemeral=True
            )

        valor_aposta = 0
        if modo.value == "bet":
            await ensure_user(interaction.guild.id, interaction.user.id)
            async with aiosqlite.connect(DB_PATH) as db:
                cursor = await db.execute(
                    "SELECT wallet FROM users WHERE guild_id=? AND user_id=?",
                    (interaction.guild.id, interaction.user.id),
                )
                row = await cursor.fetchone()
                saldo = row[0] if row else 0
                if aposta is None:
                    return await interaction.response.send_message(
                        "Informe o valor da aposta. Por segurança, o Sr.Alpha não aposta sua carteira inteira automaticamente.",
                        ephemeral=True,
                    )
                valor_aposta = aposta
                if valor_aposta < 1:
                    return await interaction.response.send_message(
                        "Informe uma aposta de pelo menos 1 Alpha Coin.", ephemeral=True
                    )
                infinite = has_infinite_coins(interaction.user.id)
                if not infinite and valor_aposta > saldo:
                    return await interaction.response.send_message(
                        f"Saldo insuficiente. Sua carteira tem {saldo:,} {config.CURRENCY_NAME}.",
                        ephemeral=True,
                    )
                if not infinite:
                    cursor = await db.execute(
                        "UPDATE users SET wallet=wallet-? WHERE guild_id=? AND user_id=? AND wallet>=?",
                        (valor_aposta, interaction.guild.id, interaction.user.id, valor_aposta),
                    )
                    if cursor.rowcount != 1:
                        await db.rollback()
                        return await interaction.response.send_message(
                            "Não consegui reservar sua aposta. Confira seu saldo e tente novamente.",
                            ephemeral=True,
                        )
                    await db.commit()

        partida = BlackjackView(
            owner_id=interaction.user.id,
            guild_id=interaction.guild.id,
            modo=modo.value,
            aposta=valor_aposta,
        )
        await interaction.response.send_message(view=partida)
        partida.message = await interaction.original_response()

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

    @app_commands.command(name="8ball", description="Consulte a bola mágica")
    async def oito_bola(self, interaction: discord.Interaction, pergunta: str):
        respostas = [
            "🔮 Com certeza!", "✨ As chances são boas.",
            "🌙 Talvez...", "💫 Pergunte novamente mais tarde.",
            "🌀 Não parece provável.", "⭐ Os sinais são positivos!",
        ]
        embed = embed_jogo(
            "🔮 Bola mágica",
            f"**Pergunta:** {pergunta}\n\n**Resposta:** {random.choice(respostas)}",
        )
        await interaction.response.send_message(view=embed)

    @app_commands.command(name="duelo", description="Desafie a sorte em um duelo")
    @app_commands.choices(modo=MODOS)
    async def duelo(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 10000] = None,
    ):
        aposta = await aposta_efetiva(interaction, modo.value, aposta)
        seu = random.randint(1, 100)
        alpha = random.randint(1, 100)
        empate = seu == alpha
        venceu = seu > alpha
        premio = (aposta or 0) * 2 if venceu else (aposta or 0) if empate else 0

        await finalizar_jogo(
            interaction, modo.value, aposta, "⚔️ Duelo Alpha",
            f"Seu poder: **{seu}**\nPoder do Sr.Alpha: **{alpha}**\n"
            f"{'🏆 Vitória!' if venceu else '🤝 Empate!' if empate else '💨 Derrota!'}",
            premio, empate,
        )


async def setup(bot):
    await bot.add_cog(Fun(bot))
