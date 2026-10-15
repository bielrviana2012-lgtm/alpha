
import logging
import re

import discord
from discord import app_commands
from discord.ext import commands
from google import genai

import config
from cogs.ui_v2 import make_v2_panel

log = logging.getLogger(__name__)


class AIChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.client = None

        api_key = __import__("os").getenv("GEMINI_API_KEY", "").strip()

        if api_key:
            try:
                self.client = genai.Client(api_key=api_key)
            except Exception:
                log.exception("Não foi possível inicializar o Gemini")

    async def gerar_resposta(self, pergunta: str) -> str:
        if not self.client:
            return (
                "Minha IA ainda não está configurada! "
                "Confira a variável GEMINI_API_KEY no Railway."
            )

        response = await self.bot.loop.run_in_executor(
            None,
            lambda: self.client.models.generate_content(
                model="gemini-3.8-flash",
                contents=(
                    "Você é o Sr.Alpha, assistente amigável de uma "
                    "comunidade Discord. Responda em português brasileiro, "
                    "com clareza e segurança. Seja natural e amigável. "
                    "Não afirme que executou ações no servidor.\n\n"
                    f"Mensagem do usuário: {pergunta}"
                ),
            ),
        )

        return response.text or "Não consegui gerar uma resposta agora."

    @app_commands.command(
        name="perguntar",
        description="Converse com a IA do Sr.Alpha",
    )
    @app_commands.describe(pergunta="O que você quer perguntar?")
    async def perguntar(
        self,
        interaction: discord.Interaction,
        pergunta: app_commands.Range[str, 1, 1500],
    ):
        await interaction.response.defer(thinking=True)

        try:
            resposta = await self.gerar_resposta(pergunta)
            resposta = resposta[:1900]

            await interaction.followup.send(
                view=make_v2_panel("✨ Sr.Alpha AI", resposta)
            )
        except Exception:
            log.exception("Erro no comando /perguntar")
            await interaction.followup.send(
                "Tive um probleminha para acessar a IA. "
                "Confira os Logs do Railway.",
                ephemeral=True,
            )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not self.bot.user:
            return

        if self.bot.user not in message.mentions:
            return

        pergunta = re.sub(
            rf"<@!?{self.bot.user.id}>",
            "",
            message.content,
        ).strip()

        if not pergunta:
            pergunta = "Cumprimente a pessoa e pergunte como pode ajudar."

        try:
            resposta = await self.gerar_resposta(pergunta)
            resposta = resposta[:1800]

            await message.reply(
                f"{message.author.mention} {resposta}",
                mention_author=False,
            )
        except Exception:
            log.exception("Erro na conversa por menção")
            await message.reply(
                f"{message.author.mention} Tive um probleminha "
                "para responder agora 😅 Tenta novamente daqui a pouco!",
                mention_author=False,
            )


async def setup(bot):
    await bot.add_cog(AIChat(bot))
