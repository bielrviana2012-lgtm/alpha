"""Arcade Premium gratuito do Sr.Alpha: oito jogos interativos sem apostas."""
import asyncio
import random
import discord
from discord import app_commands
from discord.ext import commands

PURPLE = discord.Colour.from_rgb(145, 103, 255)
GREEN = discord.Colour.from_rgb(46, 204, 113)
RED = discord.Colour.from_rgb(231, 76, 60)
GOLD = discord.Colour.from_rgb(241, 196, 15)
ACTIVE = set()


class ArcadeView(discord.ui.LayoutView):
    def __init__(self, game, owner_id):
        super().__init__(timeout=90)
        self.game = game
        self.owner_id = owner_id
        self.done = False
        self.lock = asyncio.Lock()
        self.points = 0
        self.multiplier = 1.0
        self.floor = 0
        self.card = random.randint(2, 14)
        self.total = random.randint(12, 18)
        self.crash_at = random.uniform(1.25, 4.5)
        self.message = None
        self._build("Partida iniciada! Escolha sua jogada.")

    def card_name(self, value):
        return {11: "Valete", 12: "Dama", 13: "Rei", 14: "Ás"}.get(value, str(value))

    def _build(self, extra="", colour=PURPLE):
        self.clear_items()
        box = discord.ui.Container(accent_colour=colour)
        box.add_item(discord.ui.TextDisplay(f"# ✦ SR.ALPHA • {self.game}"))
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

    async def finish(self, interaction, message, colour=GREEN):
        if self.done:
            return await interaction.response.send_message("Esta partida já terminou.", ephemeral=True)
        self.done = True
        ACTIVE.discard((interaction.guild_id, self.owner_id))
        self._build(message + f"\n\n🏆 **Pontuação final:** {self.points}", colour)
        self.stop()
        if interaction.response.is_done():
            await interaction.edit_original_response(view=self)
        else:
            await interaction.response.edit_message(view=self)

    async def cashout(self, interaction):
        async with self.lock:
            self.points += max(1, int(100 * self.multiplier))
            await self.finish(interaction, f"✨ Rodada encerrada em **{self.multiplier:.2f}x**!", GREEN)

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
        ACTIVE.discard((getattr(self, "guild_id", None), self.owner_id))
        self.done = True
        self.stop()


class ArcadePremium(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def start(self, interaction, game):
        if interaction.guild_id is None:
            return await interaction.response.send_message("Este jogo só funciona dentro do servidor.", ephemeral=True)
        key = (interaction.guild_id, interaction.user.id)
        if key in ACTIVE:
            return await interaction.response.send_message("Você já tem uma partida do Arcade Premium em andamento.", ephemeral=True)
        ACTIVE.add(key)
        view = ArcadeView(game, interaction.user.id)
        view.guild_id = interaction.guild_id
        await interaction.response.send_message(view=view)
        view.message = await interaction.original_response()
        if game == "Crash Alpha":
            asyncio.create_task(self.crash_timer(view))

    async def crash_timer(self, view):
        try:
            while not view.done:
                await asyncio.sleep(0.5)
                async with view.lock:
                    if view.done:
                        return
                    view.multiplier = round(view.multiplier * 1.15, 2)
                    if view.multiplier >= view.crash_at:
                        view.done = True
                        ACTIVE.discard((view.guild_id, view.owner_id))
                        view._build(f"💥 Crash em **{view.crash_at:.2f}x**! Fim da rodada.", RED)
                        view.stop()
                    else:
                        view._build("🚀 O multiplicador está subindo! Saque antes do crash.")
                    if view.message:
                        await view.message.edit(view=view)
        except (discord.HTTPException, asyncio.CancelledError):
            return

    @app_commands.command(name="crash", description="Jogue Crash Alpha em modo gratuito")
    @app_commands.guild_only()
    async def crash(self, interaction: discord.Interaction):
        await self.start(interaction, "Crash Alpha")

    @app_commands.command(name="cofre", description="Escolha um cofre misterioso")
    @app_commands.guild_only()
    async def cofre(self, interaction: discord.Interaction):
        await self.start(interaction, "Cofre Misterioso")

    @app_commands.command(name="roleta2", description="Gire a Roleta Alpha 2.0")
    @app_commands.guild_only()
    async def roleta2(self, interaction: discord.Interaction):
        await self.start(interaction, "Roleta Alpha 2.0")

    @app_commands.command(name="blackjack", description="Jogue Blackjack Premium sem apostas")
    @app_commands.guild_only()
    async def blackjack(self, interaction: discord.Interaction):
        await self.start(interaction, "Blackjack Premium")

    @app_commands.command(name="torre", description="Suba a Torre Alpha")
    @app_commands.guild_only()
    async def torre(self, interaction: discord.Interaction):
        await self.start(interaction, "Torre Alpha")

    @app_commands.command(name="fortuna", description="Abra uma Caixa da Fortuna")
    @app_commands.guild_only()
    async def fortuna(self, interaction: discord.Interaction):
        await self.start(interaction, "Caixa da Fortuna")

    @app_commands.command(name="dragao", description="Enfrente as etapas da Caça ao Dragão")
    @app_commands.guild_only()
    async def dragao(self, interaction: discord.Interaction):
        await self.start(interaction, "Caça ao Dragão")

    @app_commands.command(name="maioroumenor", description="Adivinhe se a próxima carta será maior ou menor")
    @app_commands.guild_only()
    async def maioroumenor(self, interaction: discord.Interaction):
        await self.start(interaction, "Maior ou Menor")


async def setup(bot):
    await bot.add_cog(ArcadePremium(bot))
