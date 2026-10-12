import random
import discord
from discord import app_commands
from discord.ext import commands

QUESTIONS = [
    ("Qual é o planeta conhecido como planeta vermelho?", ["Marte", "Vênus", "Júpiter", "Saturno"], 0),
    ("Quantos lados tem um hexágono?", ["5", "6", "7", "8"], 1),
    ("Qual é o maior oceano da Terra?", ["Atlântico", "Índico", "Pacífico", "Ártico"], 2),
    ("Qual linguagem é muito usada com discord.py?", ["Python", "CSS", "SQL apenas", "HTML apenas"], 0),
    ("Qual é o resultado de 9 × 7?", ["56", "63", "72", "79"], 1),
]

class QuizView(discord.ui.View):
    def __init__(self, question, options, answer, owner_id):
        super().__init__(timeout=30); self.answer = answer; self.owner_id = owner_id; self.done = False
        for i, option in enumerate(options):
            button = discord.ui.Button(label=option, style=discord.ButtonStyle.primary, custom_id=f"quiz_{i}")
            button.callback = self.make_callback(i)
            self.add_item(button)
    def make_callback(self, index):
        async def callback(interaction):
            if interaction.user.id != self.owner_id: return await interaction.response.send_message("Este quiz pertence a outra pessoa.", ephemeral=True)
            if self.done: return await interaction.response.send_message("Esta pergunta já foi respondida.", ephemeral=True)
            self.done = True
            for child in self.children: child.disabled = True
            await interaction.response.edit_message(content="✅ Resposta correta!" if index == self.answer else "❌ Não foi dessa vez! Tente novamente em outro quiz.", view=self)
        return callback

class Fun(commands.Cog):
    def __init__(self, bot): self.bot = bot
    @app_commands.command(name="quiz", description="Responda a uma pergunta de conhecimentos gerais")
    async def quiz(self, interaction: discord.Interaction):
        q, options, answer = random.choice(QUESTIONS)
        await interaction.response.send_message(embed=discord.Embed(title="🧠 Quiz Alpha", description=q, color=discord.Color.blurple()), view=QuizView(q, options, answer, interaction.user.id))
    @app_commands.command(name="ppt", description="Jogue pedra, papel e tesoura contra o bot")
    @app_commands.choices(escolha=[app_commands.Choice(name=x,value=x.lower()) for x in ["Pedra","Papel","Tesoura"]])
    async def ppt(self, interaction: discord.Interaction, escolha: app_commands.Choice[str]):
        bot = random.choice(["pedra","papel","tesoura"]); player = escolha.value
        result = "Empate!" if player == bot else "Você venceu! 🎉" if (player,bot) in [("pedra","tesoura"),("papel","pedra"),("tesoura","papel")] else "O bot venceu!"
        await interaction.response.send_message(embed=discord.Embed(title="✊ Pedra, papel e tesoura", description=f"Você: **{player.title()}**\nAlpha BOT: **{bot.title()}**\n\n**{result}**", color=discord.Color.green() if result.startswith("Você") else discord.Color.blurple()))
    @app_commands.command(name="moeda", description="Jogue uma moeda virtual")
    async def moeda(self, interaction: discord.Interaction): await interaction.response.send_message(f"🪙 Deu **{random.choice(['Cara','Coroa'])}**!")
    @app_commands.command(name="dado", description="Role um dado de seis lados")
    async def dado(self, interaction: discord.Interaction): await interaction.response.send_message(f"🎲 Você tirou **{random.randint(1,6)}**!")

async def setup(bot): await bot.add_cog(Fun(bot))
