import logging
import discord
from discord.ext import commands
import config
from database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(name)s | %(message)s")

class AlphaBot(commands.Bot):
    async def setup_hook(self):
        await init_db()
         for extension in (     "cogs.economy",     "cogs.moderation",     "cogs.community",     "cogs.fun",     "cogs.ai_chat",     "cogs.levels",     "cogs.updates", ):
            try:
                await self.load_extension(extension)
                logging.info("Módulo carregado: %s", extension)
            except Exception:
                logging.exception("Falha ao carregar %s", extension)
        if config.GUILD_ID:
            guild = discord.Object(id=config.GUILD_ID)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            logging.info("Comandos sincronizados no servidor de teste %s", config.GUILD_ID)
        else:
            await self.tree.sync()
            logging.info("Comandos globais sincronizados; podem levar algum tempo para aparecer.")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = AlphaBot(command_prefix="!", intents=intents, help_command=None)

@bot.event
async def on_ready():
    logging.info("Alpha BOT conectado como %s (ID %s)", bot.user, bot.user.id)
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="a comunidade Alpha"))

@bot.tree.command(name="ajuda", description="Mostra os sistemas do Alpha BOT")
async def ajuda(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 Alpha BOT | Central de ajuda", description="Seu bot geral para a comunidade.", color=discord.Color.blurple())
    embed.add_field(name="💰 Economia", value="`/saldo` `/daily` `/trabalhar` `/depositar` `/sacar` `/transferir` `/ranking` `/loja` `/comprar`", inline=False)
    embed.add_field(name="🛡️ Moderação", value="`/aviso` `/avisos` `/limpar` `/timeout` `/expulsar` `/banir`", inline=False)
    embed.add_field(name="💬 Comunidade", value="`/sugerir` `/status_sugestao` `/ticket` `/fechar_ticket`", inline=False)
    embed.add_field(name="🎮 Diversão", value="`/quiz` `/ppt` `/perfil` `/level`", inline=False)
    embed.add_field(name="✨ IA", value="`/perguntar` — requer OPENAI_API_KEY no arquivo .env", inline=False)
    embed.set_footer(text="Use os comandos com responsabilidade. Alguns exigem permissões específicas.")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: Exception):
    logging.exception("Erro em comando slash", exc_info=error)
    message = "Ocorreu um erro ao executar o comando. Confira as permissões e tente novamente."
    from discord import app_commands
    if isinstance(error, app_commands.MissingPermissions):
        message = "Você não tem permissão para usar este comando."
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


if __name__ == "__main__":
    if not config.DISCORD_TOKEN or config.DISCORD_TOKEN == "COLOQUE_SEU_TOKEN_AQUI":
        raise SystemExit("Configure DISCORD_TOKEN no arquivo .env antes de iniciar.")
    bot.run(config.DISCORD_TOKEN, log_handler=None)
