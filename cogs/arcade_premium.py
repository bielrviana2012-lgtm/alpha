"""Arcade Premium do Rei Dado com modo grátis e apostas de moedas virtuais."""
import asyncio
import random
import discord
import aiosqlite
from discord import app_commands
from discord.ext import commands

from database import DB_PATH, ensure_user, has_infinite_coins
import config

PURPLE = discord.Colour.from_rgb(145, 103, 255)
GREEN = discord.Colour.from_rgb(46, 204, 113)
RED = discord.Colour.from_rgb(231, 76, 60)
GOLD = discord.Colour.from_rgb(241, 196, 15)
ACTIVE = set()
ACTIVE_VIEWS = {}


class ArcadeView(discord.ui.LayoutView):
    def __init__(self, game, owner_id, guild_id, mode, wager):
        super().__init__(timeout=90)
        self.game = game
        self.owner_id = owner_id
        self.guild_id = guild_id
        self.mode = mode
        self.wager = wager or 0
        self.settled = False
        self.done = False
        self.lock = asyncio.Lock()
        self.points = 0
        self.multiplier = 1.0
        self.floor = 0
        self.card = random.randint(2, 14)
        self.total = random.randint(12, 18)
        self.crash_at = random.uniform(1.25, 4.5)
        self.message = None
        self.crash_task = None
        # Registra o clique de saque antes de esperar pelo lock do temporizador.
        self.cashout_requested_at = None
        self.crash_at_time = None
        self.created_at = asyncio.get_running_loop().time()
        self._build("Partida iniciada! Escolha sua jogada.")

    def card_name(self, value):
        return {11: "Valete", 12: "Dama", 13: "Rei", 14: "Ás"}.get(value, str(value))

    def _build(self, extra="", colour=PURPLE):
        self.clear_items()
        box = discord.ui.Container(accent_colour=colour)
        box.add_item(discord.ui.TextDisplay(f"# ✦ REI DADO • {self.game}"))
        box.add_item(discord.ui.Separator())
        text = f"**Jogador:** <@{self.owner_id}>\n**Pontuação da rodada:** {self.points}"
        if self.game in ("Crash Alpha", "Torre Alpha", "Caça ao Dragão"):
            text += f"\n**Multiplicador:** {self.multiplier:.2f}x"
        if self.game == "Torre Alpha":
            text += f"\n**Andar:** {self.floor}"
        elif self.game == "Caça ao Dragão":
            text += f"\n**Etapa:** {self.floor}"
        elif self.game == "Blackjack Premium":
            text += f"\n**Sua mão:** {self.total}"
        elif self.game == "Maior ou Menor":
            text += f"\n**Carta atual:** {self.card_name(self.card)}"
        if self.mode == "bet":
            text += f"\n**Aposta:** {self.wager:,} {config.CURRENCY_NAME}"
            text += "\n🪙 **Modo aposta — moedas virtuais.**"
        else:
            text += "\n\n🎮 **Modo brincadeira — sem apostas ou moedas.**"
        if extra:
            text += "\n\n" + extra
        box.add_item(discord.ui.TextDisplay(text[:3900]))
        box.add_item(discord.ui.Separator())
        box.add_item(discord.ui.TextDisplay("-# Family Alpha • Arcade Premium"))
        self.add_item(box)
        if self.done:
            return

        row = discord.ui.ActionRow()
        if self.game == "Crash Alpha":
            b = discord.ui.Button(label="💰 Encerrar rodada", style=discord.ButtonStyle.success)
            b.callback = self.cashout
            row.add_item(b)
        elif self.game in ("Cofre Misterioso", "Caixa da Fortuna"):
            for label, choice in [("🎁 Opção A","a"),("💎 Opção B","b"),("👑 Opção C","c")]:
                b = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)
                b.callback = self.make_choice(choice)
                row.add_item(b)
        elif self.game == "Roleta Alpha 2.0":
            b = discord.ui.Button(label="🎡 Girar roleta", style=discord.ButtonStyle.primary)
            b.callback = self.spin
            row.add_item(b)
        elif self.game == "Blackjack Premium":
            hit = discord.ui.Button(label="🃏 Comprar", style=discord.ButtonStyle.primary)
            hit.callback = self.hit
            row.add_item(hit)
            stand = discord.ui.Button(label="✋ Parar", style=discord.ButtonStyle.success)
            stand.callback = self.stand
            row.add_item(stand)
        elif self.game == "Torre Alpha":
            for label, choice in [("🚪 Porta A","a"),("🚪 Porta B","b"),("🚪 Porta C","c")]:
                b = discord.ui.Button(label=label, style=discord.ButtonStyle.primary)
                b.callback = self.make_choice(choice)
                row.add_item(b)
            self.add_item(row)
            row2 = discord.ui.ActionRow()
            b = discord.ui.Button(label="⬆️ Encerrar", style=discord.ButtonStyle.success)
            b.callback = self.cashout
            row2.add_item(b)
            self.add_item(row2)
            return
        elif self.game == "Caça ao Dragão":
            b = discord.ui.Button(label="🐉 Avançar", style=discord.ButtonStyle.danger)
            b.callback = self.advance
            row.add_item(b)
            b = discord.ui.Button(label="🏆 Encerrar", style=discord.ButtonStyle.success)
            b.callback = self.cashout
            row.add_item(b)
        elif self.game == "Maior ou Menor":
            b = discord.ui.Button(label="📈 Maior", style=discord.ButtonStyle.primary)
            b.callback = self.make_highlow(True)
            row.add_item(b)
            b = discord.ui.Button(label="📉 Menor", style=discord.ButtonStyle.primary)
            b.callback = self.make_highlow(False)
            row.add_item(b)
        self.add_item(row)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("⛔ Esta partida pertence a outra pessoa.", ephemeral=True)
            return False
        return True

    def payout_amount(self):
        if self.game == "Crash Alpha":
            return int(self.wager * self.multiplier) if self.points > 0 else 0
        if self.game == "Torre Alpha":
            return int(self.wager * self.multiplier) if self.floor > 0 else 0
        if self.game == "Caça ao Dragão":
            return int(self.wager * self.multiplier) if self.floor > 0 else 0
        if self.game in ("Cofre Misterioso", "Caixa da Fortuna"):
            return int(self.wager * self.points / 100)
        if self.game == "Roleta Alpha 2.0":
            return int(self.wager * self.points / 100)
        if self.game == "Blackjack Premium":
            return self.wager * 2 if self.points >= 200 else self.wager if self.points >= 100 else 0
        if self.game == "Maior ou Menor":
            return self.wager * 2 if self.points >= 100 else self.wager if self.points >= 50 else 0
        return 0

    async def settle(self, crashed=False):
        if self.mode != "bet" or self.settled:
            return ""
        self.settled = True
        returned = 0 if crashed else self.payout_amount()
        infinite = has_infinite_coins(self.owner_id)
        if returned and not infinite:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("BEGIN IMMEDIATE")
                await db.execute(
                    "UPDATE users SET wallet = wallet + ? WHERE guild_id = ? AND user_id = ?",
                    (returned, self.guild_id, self.owner_id),
                )
                await db.commit()
        if infinite:
            balance = "∞"
        else:
            async with aiosqlite.connect(DB_PATH) as db:
                row = await (await db.execute(
                    "SELECT wallet FROM users WHERE guild_id = ? AND user_id = ?",
                    (self.guild_id, self.owner_id),
                )).fetchone()
            balance = f"{row[0]:,}" if row else "0"
        net = returned - self.wager
        return (f"\n\n🪙 **Aposta:** {self.wager:,} {config.CURRENCY_NAME}"
                f"\n**Retorno:** {returned:,} {config.CURRENCY_NAME}"
                f"\n**Resultado líquido:** {net:+,} {config.CURRENCY_NAME}"
                f"\n**Carteira:** {balance} {config.CURRENCY_NAME}")

    async def finish(self, interaction, message, colour=GREEN):
        if self.done:
            return await interaction.response.send_message("Esta partida já terminou.", ephemeral=True)
        self.done = True
        settlement = await self.settle()
        key = (self.guild_id, self.owner_id)
        ACTIVE.discard(key)
        if ACTIVE_VIEWS.get(key) is self:
            ACTIVE_VIEWS.pop(key, None)
        self._build(message + f"\n\n🏆 **Pontuação final:** {self.points}" + settlement, colour)
        self.stop()
        try:
            if interaction.response.is_done():
                await interaction.edit_original_response(view=self)
            else:
                await interaction.response.edit_message(view=self)
        except discord.HTTPException:
            # A liquidação já foi salva; tenta atualizar a mensagem do jogo diretamente.
            if self.message:
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    import logging
                    logging.getLogger(__name__).exception(
                        "Não foi possível atualizar a mensagem após finalizar a partida"
                    )

    async def cashout(self, interaction):
        # Reconhece o clique imediatamente: o temporizador do Crash também
        # usa este lock e pode estar terminando uma atualização de mensagem.
        is_crash = self.game == "Crash Alpha"
        if is_crash:
            # Marca o saque antes do defer e antes de esperar pelo lock. Assim,
            # o temporizador não declara crash se o clique já chegou primeiro.
            self.cashout_requested_at = asyncio.get_running_loop().time()
            await interaction.response.defer()

        async with self.lock:
            if self.done:
                if is_crash:
                    return await interaction.followup.send(
                        "Esta rodada já terminou; o Crash aconteceu antes do saque.",
                        ephemeral=True,
                    )
                return await interaction.response.send_message(
                    "Esta partida já terminou.", ephemeral=True
                )

            self.points += max(1, int(100 * self.multiplier))
            await self.finish(
                interaction,
                f"✨ Rodada encerrada em **{self.multiplier:.2f}x**!",
                GREEN,
            )

    async def make_choice(self, choice):
        async def callback(interaction):
            async with self.lock:
                if self.done:
                    return await interaction.response.send_message("Esta partida já terminou.", ephemeral=True)
                if self.game in ("Cofre Misterioso", "Caixa da Fortuna"):
                    mult = random.choice([0, .5, 1, 1.5, 2, 4])
                    self.points += int(100 * mult)
                    return await self.finish(interaction, f"🎁 A opção {choice.upper()} revelou **{mult:g}x** e rendeu {int(100*mult)} pontos!", GREEN if mult >= 1 else RED)
                safe = random.choice(("a", "b", "c"))
                if choice != safe:
                    return await self.finish(interaction, "💥 Porta perigosa! Fim da escalada.", RED)
                self.floor += 1
                self.multiplier *= 1.45
                self.points += int(25 * self.multiplier)
                self._build(f"✨ Porta segura! Você chegou ao andar **{self.floor}**.")
                await interaction.response.edit_message(view=self)
        return callback

    async def spin(self, interaction):
        async with self.lock:
            if self.done:
                return await interaction.response.send_message("Esta partida já terminou.", ephemeral=True)
            await interaction.response.defer()
            for frame in ["🎡 Girando... ◐", "🎡 Girando... ◓", "🎡 Girando... ◑", "🎡 Girando... ◒"]:
                self._build(frame)
                await interaction.edit_original_response(view=self)
                await asyncio.sleep(.3)
            mult = random.choice([0, .5, 1, 2, 3, 5])
            self.points += int(100 * mult)
            await self.finish(interaction, f"🎯 A roleta parou em **{mult:g}x**! Pontos ganhos: {int(100*mult)}.", GREEN if mult >= 1 else RED)

    async def hit(self, interaction):
        async with self.lock:
            self.total += random.randint(2, 11)
            if self.total > 21:
                return await self.finish(interaction, f"💥 Você passou de 21: **{self.total}**.", RED)
            self._build("🃏 Carta comprada! Compre outra ou pare.")
            await interaction.response.edit_message(view=self)

    async def stand(self, interaction):
        async with self.lock:
            dealer = random.randint(16, 23)
            if self.total > dealer or dealer > 21:
                self.points += 200
                msg, colour = f"🏆 Você: **{self.total}** • Dealer: **{dealer}**. Vitória!", GREEN
            elif self.total == dealer:
                self.points += 100
                msg, colour = f"🤝 Empate! Você: **{self.total}** • Dealer: **{dealer}**.", GOLD
            else:
                msg, colour = f"💨 Você: **{self.total}** • Dealer: **{dealer}**. O dealer venceu.", RED
            await self.finish(interaction, msg, colour)

    async def advance(self, interaction):
        async with self.lock:
            self.floor += 1
            if random.random() > .65:
                return await self.finish(interaction, f"🐉 O dragão bloqueou seu caminho na etapa {self.floor}.", RED)
            self.multiplier *= 1.5
            self.points += int(25 * self.multiplier)
            self._build(f"✨ Você passou pela etapa **{self.floor}**! Avance ou encerre.")
            await interaction.response.edit_message(view=self)

    def make_highlow(self, higher):
        async def callback(interaction):
            async with self.lock:
                nxt = random.randint(2, 14)
                win = nxt > self.card if higher else nxt < self.card
                if nxt == self.card:
                    self.points += 50
                    msg, colour = f"🤝 Empate: saiu **{self.card_name(nxt)}**.", GOLD
                elif win:
                    self.points += 100
                    msg, colour = f"🏆 Saiu **{self.card_name(nxt)}**. Você acertou!", GREEN
                else:
                    msg, colour = f"💨 Saiu **{self.card_name(nxt)}**. Você errou.", RED
                await self.finish(interaction, msg, colour)
        return callback

    async def on_timeout(self):
        async with self.lock:
            if self.done:
                key = (self.guild_id, self.owner_id)
                ACTIVE.discard(key)
                if ACTIVE_VIEWS.get(key) is self:
                    ACTIVE_VIEWS.pop(key, None)
                return
            self.done = True
            settlement = await self.settle()
            key = (self.guild_id, self.owner_id)
            ACTIVE.discard(key)
            if ACTIVE_VIEWS.get(key) is self:
                ACTIVE_VIEWS.pop(key, None)
            self._build("⌛ A partida expirou." + settlement, RED)
            self.stop()
            if self.message:
                try:
                    await self.message.edit(view=self)
                except discord.HTTPException:
                    pass


class ArcadePremium(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def start(self, interaction, game, mode, wager=None):
        if interaction.guild_id is None:
            return await interaction.response.send_message("Este jogo só funciona dentro do servidor.", ephemeral=True)

        # Reconhece o slash command imediatamente. A resposta inicial do Discord
        # expira em poucos segundos; o banco ou a API podem ultrapassar esse prazo.
        await interaction.response.defer(thinking=True)

        async def start_error(message):
            # Remove o indicador público de carregamento e mostra o erro só ao jogador.
            try:
                await interaction.delete_original_response()
            except discord.HTTPException:
                pass
            return await interaction.followup.send(message, ephemeral=True)

        key = (interaction.guild_id, interaction.user.id)
        previous = ACTIVE_VIEWS.get(key)
        # Evita que uma view presa bloqueie novas partidas após o timeout.
        previous_age = (
            asyncio.get_running_loop().time() - getattr(previous, "created_at", 0)
            if previous is not None else 0
        )
        # O Crash tem um temporizador próprio. Se a tarefa morrer/cancelar sem
        # finalizar a view, não mantenha o jogador bloqueado até o limite de 95 s.
        crash_task_dead = (
            previous is not None
            and previous.game == "Crash Alpha"
            and previous.crash_task is not None
            and previous.crash_task.done()
        )
        previous_stale = (
            previous is not None
            and (
                previous.done
                or previous.is_finished()
                or previous_age > 95
                or crash_task_dead
            )
        )
        if previous is not None and not previous_stale:
            return await start_error(
                "Você já tem uma partida do Arcade Premium em andamento."
            )
        if previous is not None:
            previous.done = True
            previous.stop()
            ACTIVE_VIEWS.pop(key, None)
            ACTIVE.discard(key)
        if mode == "bet":
            if wager is None:
                return await start_error("Informe o valor da aposta.")
            await ensure_user(interaction.guild_id, interaction.user.id)
            if not has_infinite_coins(interaction.user.id):
                async with aiosqlite.connect(DB_PATH) as db:
                    await db.execute("BEGIN IMMEDIATE")
                    cur = await db.execute(
                        "UPDATE users SET wallet = wallet - ? WHERE guild_id = ? AND user_id = ? AND wallet >= ?",
                        (wager, interaction.guild_id, interaction.user.id, wager),
                    )
                    if cur.rowcount != 1:
                        row = await (await db.execute(
                            "SELECT wallet FROM users WHERE guild_id = ? AND user_id = ?",
                            (interaction.guild_id, interaction.user.id),
                        )).fetchone()
                        await db.rollback()
                        return await start_error(
                            f"Saldo insuficiente. Sua carteira tem {row[0] if row else 0:,} {config.CURRENCY_NAME}."
                        )
                    await db.commit()
        view = ArcadeView(game, interaction.user.id, interaction.guild_id, mode, wager)
        ACTIVE.add(key)
        ACTIVE_VIEWS[key] = view
        try:
            await interaction.edit_original_response(view=view)
            view.message = await interaction.original_response()
        except Exception:
            # Não deixe o jogador bloqueado se o envio inicial falhar.
            view.done = True
            view.stop()
            ACTIVE.discard(key)
            if ACTIVE_VIEWS.get(key) is view:
                ACTIVE_VIEWS.pop(key, None)
            raise
        if game == "Crash Alpha":
            view.crash_task = asyncio.create_task(self.crash_timer(view))

    async def crash_timer(self, view):
        try:
            while not view.done:
                await asyncio.sleep(0.5)
                async with view.lock:
                    if view.done:
                        return
                    # Se o jogador clicou em sacar antes deste tick, deixa o
                    # callback concluir o saque em vez de resolver como perda.
                    if view.cashout_requested_at is not None:
                        return
                    next_multiplier = round(view.multiplier * 1.15, 2)
                    if next_multiplier >= view.crash_at:
                        view.crash_at_time = asyncio.get_running_loop().time()
                        view.done = True
                        settlement = await view.settle(crashed=True)
                        key = (view.guild_id, view.owner_id)
                        ACTIVE.discard(key)
                        if ACTIVE_VIEWS.get(key) is view:
                            ACTIVE_VIEWS.pop(key, None)
                        view._build(f"💥 Crash em **{view.crash_at:.2f}x**! Fim da rodada." + settlement, RED)
                        view.stop()
                    else:
                        view.multiplier = next_multiplier
                        view._build("🚀 O multiplicador está subindo! Saque antes do crash.")
                    if view.message:
                        await view.message.edit(view=view)
        except asyncio.CancelledError:
            raise
        except Exception:
            import logging
            logging.getLogger(__name__).exception("Falha no temporizador do Crash Alpha")
            # Limpa o registro primeiro, mesmo se a liquidação ou a edição falhar.
            key = (view.guild_id, view.owner_id)
            view.done = True
            ACTIVE.discard(key)
            if ACTIVE_VIEWS.get(key) is view:
                ACTIVE_VIEWS.pop(key, None)
            view.stop()
            settlement = ""
            try:
                settlement = await view.settle(crashed=True)
            except Exception:
                logging.getLogger(__name__).exception("Falha ao encerrar a rodada do Crash Alpha")
            view._build("⚠️ A rodada foi encerrada por uma falha técnica." + settlement, RED)
            if view.message:
                try:
                    await view.message.edit(view=view)
                except discord.HTTPException:
                    pass

    @app_commands.command(name="crash", description="Jogue Crash Alpha grátis ou com aposta virtual")
    @app_commands.guild_only()
    @app_commands.choices(modo=[
        app_commands.Choice(name="🎮 Brincar grátis", value="free"),
        app_commands.Choice(name="🪙 Apostar Sr.Coins", value="bet"),
    ])
    @app_commands.describe(modo="Modo de jogo", aposta="Valor de Sr.Coins para apostar (obrigatório no modo aposta)")
    async def crash(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 1000000000] = None,
    ):
        await self.start(interaction, "Crash Alpha", modo.value, aposta)

    @app_commands.command(name="cofre", description="Escolha um cofre misterioso grátis ou com aposta virtual")
    @app_commands.guild_only()
    @app_commands.choices(modo=[
        app_commands.Choice(name="🎮 Brincar grátis", value="free"),
        app_commands.Choice(name="🪙 Apostar Sr.Coins", value="bet"),
    ])
    @app_commands.describe(modo="Modo de jogo", aposta="Valor de Sr.Coins para apostar (obrigatório no modo aposta)")
    async def cofre(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 1000000000] = None,
    ):
        await self.start(interaction, "Cofre Misterioso", modo.value, aposta)

    @app_commands.command(name="roleta2", description="Gire a Roleta Alpha 2.0 grátis ou com aposta virtual")
    @app_commands.guild_only()
    @app_commands.choices(modo=[
        app_commands.Choice(name="🎮 Brincar grátis", value="free"),
        app_commands.Choice(name="🪙 Apostar Sr.Coins", value="bet"),
    ])
    @app_commands.describe(modo="Modo de jogo", aposta="Valor de Sr.Coins para apostar (obrigatório no modo aposta)")
    async def roleta2(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 1000000000] = None,
    ):
        await self.start(interaction, "Roleta Alpha 2.0", modo.value, aposta)

    @app_commands.command(name="blackjack", description="Jogue Blackjack Premium grátis ou com aposta virtual")
    @app_commands.guild_only()
    @app_commands.choices(modo=[
        app_commands.Choice(name="🎮 Brincar grátis", value="free"),
        app_commands.Choice(name="🪙 Apostar Sr.Coins", value="bet"),
    ])
    @app_commands.describe(modo="Modo de jogo", aposta="Valor de Sr.Coins para apostar (obrigatório no modo aposta)")
    async def blackjack(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 1000000000] = None,
    ):
        await self.start(interaction, "Blackjack Premium", modo.value, aposta)

    @app_commands.command(name="torre", description="Suba a Torre Alpha grátis ou com aposta virtual")
    @app_commands.guild_only()
    @app_commands.choices(modo=[
        app_commands.Choice(name="🎮 Brincar grátis", value="free"),
        app_commands.Choice(name="🪙 Apostar Sr.Coins", value="bet"),
    ])
    @app_commands.describe(modo="Modo de jogo", aposta="Valor de Sr.Coins para apostar (obrigatório no modo aposta)")
    async def torre(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 1000000000] = None,
    ):
        await self.start(interaction, "Torre Alpha", modo.value, aposta)

    @app_commands.command(name="fortuna", description="Abra uma Caixa da Fortuna grátis ou com aposta virtual")
    @app_commands.guild_only()
    @app_commands.choices(modo=[
        app_commands.Choice(name="🎮 Brincar grátis", value="free"),
        app_commands.Choice(name="🪙 Apostar Sr.Coins", value="bet"),
    ])
    @app_commands.describe(modo="Modo de jogo", aposta="Valor de Sr.Coins para apostar (obrigatório no modo aposta)")
    async def fortuna(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 1000000000] = None,
    ):
        await self.start(interaction, "Caixa da Fortuna", modo.value, aposta)

    @app_commands.command(name="dragao", description="Enfrente as etapas da Caça ao Dragão grátis ou com aposta virtual")
    @app_commands.guild_only()
    @app_commands.choices(modo=[
        app_commands.Choice(name="🎮 Brincar grátis", value="free"),
        app_commands.Choice(name="🪙 Apostar Sr.Coins", value="bet"),
    ])
    @app_commands.describe(modo="Modo de jogo", aposta="Valor de Sr.Coins para apostar (obrigatório no modo aposta)")
    async def dragao(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 1000000000] = None,
    ):
        await self.start(interaction, "Caça ao Dragão", modo.value, aposta)

    @app_commands.command(name="maioroumenor", description="Adivinhe se a próxima carta será maior ou menor grátis ou com aposta virtual")
    @app_commands.guild_only()
    @app_commands.choices(modo=[
        app_commands.Choice(name="🎮 Brincar grátis", value="free"),
        app_commands.Choice(name="🪙 Apostar Sr.Coins", value="bet"),
    ])
    @app_commands.describe(modo="Modo de jogo", aposta="Valor de Sr.Coins para apostar (obrigatório no modo aposta)")
    async def maioroumenor(
        self,
        interaction: discord.Interaction,
        modo: app_commands.Choice[str],
        aposta: app_commands.Range[int, 1, 1000000000] = None,
    ):
        await self.start(interaction, "Maior ou Menor", modo.value, aposta)


async def setup(bot):
    await bot.add_cog(ArcadePremium(bot))
