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
                self.client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
            except Exception:
                self.client = None
    @app_commands.command(name="perguntar", description="Converse com a IA do Alpha BOT")
    async def perguntar(self, interaction: discord.Interaction, pergunta: app_commands.Range[str, 1, 1500]):
        if not self.client:
            return await interaction.response.send_message("✨ A IA ainda não está configurada. Adicione OPENAI_API_KEY ao arquivo .env e reinicie o bot.", ephemeral=True)
        await interaction.response.defer(thinking=True)
        try:
            response = await self.client.chat.completions.create(
                model=config.OPENAI_MODEL,
                messages=[
                    {"role":"system","content":"Você é o Alpha BOT, assistente amigável de uma comunidade Discord. Responda em português brasileiro, com clareza e segurança. Não afirme que executou ações no servidor. Se não souber, admita."},
                    {"role":"user","content":pergunta}
                ], max_tokens=700, temperature=0.7
            )
            answer = response.choices[0].message.content or "Não consegui gerar uma resposta agora."
            if len(answer) > 1900: answer = answer[:1890] + "…"
            await interaction.followup.send(embed=discord.Embed(title="✨ Alpha AI", description=answer, color=discord.Color.blurple()))
        except Exception:
            await interaction.followup.send("Não consegui acessar a IA agora. Confira a chave, o modelo e os limites da API.", ephemeral=True)

async def setup(bot): await bot.add_cog(AIChat(bot))
