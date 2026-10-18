import asyncio
import random
import logging
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("Sr.Alpha.Giveaways")
PURPLE = discord.Color.from_rgb(145, 103, 255)


class GiveawayView(discord.ui.View):
    def __init__(self, prize: str, host_id: int):
        super().__init__(timeout=None)
        self.prize = prize
        self.host_id = host_id
        self.entries: set[int] = set()
        self.ended = False

    @discord.ui.button(label="Participar do sorteio", emoji="🎉", style=discord.ButtonStyle.primary, custom_id="alpha_giveaway_join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.ended:
            return await interaction.response.send_message("Este sorteio já terminou.", ephemeral=True)
        if interaction.user.bot:
            return await interaction.response.send_message("Bots não podem participar.", ephemeral=True)
        if interaction.user.id in self.entries:
            self.entries.remove(interaction.user.id)
            return await interaction.response.send_message("Você saiu do sorteio.", ephemeral=True)
        self.entries.add(interaction.user.id)
        await interaction.response.send_message("🎉 Você está participando do sorteio!", ephemeral=True)

    async def finish(self, message: discord.Message, winners_count: int):
        self.ended = True
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                child.disabled = True
        eligible = list(self.entries)
        winners = random.sample(eligible, min(winners_count, len(eligible))) if eligible else []
        result = (
            "🏆 **Vencedor(es):** " + ", ".join(f"<@{uid}>" for uid in winners)
            if winners else "😕 Ninguém participou, então não houve vencedor."
        )
        panel = discord.ui.LayoutView(timeout=None)
        container = discord.ui.Container(accent_colour=PURPLE)
        container.add_item(discord.ui.TextDisplay(f"# 🎉 Sorteio encerrado: {self.prize}"))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(result))
        container.add_item(discord.ui.TextDisplay(f"Participantes: **{len(eligible)}** • Organizado por <@{self.host_id}>"))
        panel.add_item(container)
        try:
            await message.edit(content=None, view=panel)
        except discord.HTTPException:
            log.exception("Não foi possível atualizar a mensagem do sorteio.")
        if winners:
            await message.reply(
                f"🎊 Parabéns {', '.join(f'<@{uid}>' for uid in winners)}! Você ganhou **{self.prize}**.",
                allowed_mentions=discord.AllowedMentions(users=True),
            )


class Giveaways(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tasks: set[asyncio.Task] = set()

    @app_commands.command(name="sorteio", description="Cria um sorteio com botão para participar")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(
        premio="Prêmio do sorteio",
        duracao_minutos="Duração em minutos (1 a 10080)",
        vencedores="Quantidade de vencedores",
        canal="Canal onde publicar (opcional)",
    )
    async def sorteio(
        self,
        interaction: discord.Interaction,
        premio: app_commands.Range[str, 1, 200],
        duracao_minutos: app_commands.Range[int, 1, 10080],
        vencedores: app_commands.Range[int, 1, 20] = 1,
        canal: discord.TextChannel = None,
    ):
        if not interaction.guild or not interaction.user.guild_permissions.manage_guild:
            return await interaction.response.send_message("❌ Você precisa da permissão Gerenciar servidor.", ephemeral=True)
        destination = canal or interaction.channel
        if not isinstance(destination, discord.TextChannel):
            return await interaction.response.send_message("Escolha um canal de texto.", ephemeral=True)
        bot_member = interaction.guild.me
        perms = destination.permissions_for(bot_member) if bot_member else None
        if not perms or not perms.view_channel or not perms.send_messages:
            return await interaction.response.send_message("Não tenho permissão para enviar mensagens nesse canal.", ephemeral=True)
        prize = premio.strip()
        ends_at = datetime.now(timezone.utc) + timedelta(minutes=duracao_minutos)
        view = GiveawayView(prize, interaction.user.id)
        layout = discord.ui.LayoutView(timeout=None)
        container = discord.ui.Container(accent_colour=PURPLE)
        container.add_item(discord.ui.TextDisplay(f"# 🎉 SORTEIO: {prize}"))
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(
            f"Organizado por {interaction.user.mention}\\n"
            f"🏆 Vencedores: **{vencedores}**\\n"
            f"⏳ Termina: <t:{int(ends_at.timestamp())}:R> (<t:{int(ends_at.timestamp())}:f>)\\n"
            f"👥 Clique no botão abaixo para participar!"
        ))
        layout.add_item(container)
        layout.add_item(view)
        try:
            message = await destination.send(view=layout, allowed_mentions=discord.AllowedMentions.none())
        except discord.HTTPException:
            log.exception("Erro ao publicar sorteio.")
            return await interaction.response.send_message("Não consegui publicar o sorteio nesse canal.", ephemeral=True)
        await interaction.response.send_message(f"✅ Sorteio criado em {destination.mention}!", ephemeral=True)

        async def end_later():
            await asyncio.sleep(duracao_minutos * 60)
            await view.finish(message, vencedores)

        task = asyncio.create_task(end_later())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)


async def setup(bot: commands.Bot):
    await bot.add_cog(Giveaways(bot))
