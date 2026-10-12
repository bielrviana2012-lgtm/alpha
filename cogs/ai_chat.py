
import re

import discord
from discord import app_commands
from discord.ext import commands
import config


class AIChat(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.client = None

        if config.OPENAI_API_KEY:
            try:
                from openai import AsyncOpenAI
                self.client = AsyncOpenAI(
                    api_key=config.OPENAI_API_KEY
                )
            except Exception as e:
                print(f"Erro ao iniciar a IA: {e}")

    async def gerar_resposta(self, pergunta: str) -> str:
        response = await self.client.chat.completions.create(
            model=config.OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Seu nome é Sr.Alpha. Você é o assistente "
                        "inteligente e amigável da comunidade Family Alpha "
                        "no Discord. Converse naturalmente em português "
                        "brasileiro, como uma pessoa simpática e descontraída. "
                        "Seja criativo, use humor quando combinar e responda "
                        "de forma clara. Você pode usar emojis sem exagerar. "
                        "Lembre-se do contexto enviado nesta conversa, mas "
                        "não invente informações pessoais sobre os usuários. "
                        "Nunca diga que executou ações no servidor se não "
                        "executou."
                    )
                },
                {"role": "user", "content": pergunta}
            ],
            max_tokens=700,
            temperature=0.8
        )

        return (
            response.choices[0].message.content
            or "Hmm, não consegui pensar numa resposta agora 😅"
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # Ignora bots e mensagens sem menção ao Sr.Alpha.
        if message.author.bot:
            return

        if self.bot.user is None:
            return

        if self.bot.user not in message.mentions:
            return

        if not self.client:
            await message.reply(
                "Minha IA ainda não está configurada! 🤖",
                mention_author=False
            )
            return

        # Remove a marcação do próprio bot antes de enviar à IA.
        pergunta = re.sub(
            rf"<@!?{self.bot.user.id}>",
            "",
            message.content
        ).strip()

        if not pergunta:
            pergunta = "Cumprimente o usuário e pergunte como pode ajudar."

        try:
            async with message.channel.typing():
                resposta = await self.gerar_resposta(pergunta)

            if len(resposta) > 1800:
                resposta = resposta[:1790] + "…"

            await message.reply(
                f"{message.author.mention} {resposta}",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions(
                    users=[message.author],
                    replied_user=False
                )
            )

        except Exception as e:
            print(f"Erro na conversa com Sr.Alpha: {e}")

            await message.reply(
                f"{message.author.mention} Tive um probleminha para "
                "responder agora 😅 Tenta novamente daqui a pouco!",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions(
                    users=[message.author],
                    replied_user=False
                )
            )

    @app_commands.command(
        name="perguntar",
        description="Converse com a IA do Sr.Alpha"
    )
    @app_commands.describe(pergunta="O que você quer perguntar?")
    async def perguntar(
        self,
        interaction: discord.Interaction,
        pergunta: app_commands.Range[str, 1, 1500]
    ):
        if not self.client:
            return await interaction.response.send_message(
                "✨ A IA ainda não está configurada.",
                ephemeral=True
            )

        await interaction.response.defer(thinking=True)

        try:
            resposta = await self.gerar_resposta(pergunta)

            if len(resposta) > 4000:
                resposta = resposta[:3990] + "…"

            embed = discord.Embed(
                title="🐺 Sr.Alpha AI",
                description=resposta,
                color=discord.Color.blurple()
            )

            await interaction.followup.send(embed=embed)

        except Exception as e:
            print(f"Erro no comando /perguntar: {e}")

            await interaction.followup.send(
                "Não consegui acessar a IA agora. "
                "Confira a chave, o modelo e os limites da API.",
                ephemeral=True
            )


async def setup(bot):
    await bot.add_cog(AIChat(bot))
