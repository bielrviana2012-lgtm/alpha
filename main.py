
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from database import init_db


# ==========================================
# LOGS
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("Sr.Alpha")


# ==========================================
# MÓDULOS DO BOT
# ==========================================

EXTENSIONS = (
    "cogs.economy",
    "cogs.ping_roles",
    "cogs.color_roles",
    "cogs.premium",
    "cogs.moderation",
    "cogs.community",
    "cogs.fun",
    "cogs.ai_chat",
    "cogs.levels",
    "cogs.updates",
)


# ==========================================
# BOT PRINCIPAL
# ==========================================

class AlphaBot(commands.Bot):

    async def setup_hook(self):
        # Inicializa o banco de dados
        await init_db()
        logger.info("Banco de dados inicializado.")

        # Carrega os módulos
        for extension in EXTENSIONS:
            try:
                await self.load_extension(extension)
                logger.info("Módulo carregado: %s", extension)

            except Exception:
                logger.exception(
                    "Falha ao carregar o módulo: %s",
                    extension,
                )

        # Sincroniza os comandos slash
        try:
            guild_id = int(
                getattr(config, "GUILD_ID", 0) or 0
            )

            if guild_id > 0:
                guild = discord.Object(id=guild_id)

                # Copia os comandos globais para o servidor
                self.tree.copy_global_to(guild=guild)

                synced = await self.tree.sync(guild=guild)

                logger.info(
                    "Comandos sincronizados no servidor %s: %s",
                    guild_id,
                    len(synced),
                )

            else:
                synced = await self.tree.sync()

                logger.info(
                    "Comandos globais sincronizados: %s",
                    len(synced),
                )

            logger.info(
                "Comandos disponíveis: %s",
                ", ".join(command.name for command in synced)
                or "Nenhum comando registrado",
            )

        except Exception:
            logger.exception(
                "Falha ao sincronizar os comandos do Discord."
            )


# ==========================================
# INTENTS E CONFIGURAÇÃO
# ==========================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = AlphaBot(
    command_prefix="!",
    intents=intents,
    help_command=None,
)


# ==========================================
# EVENTO: BOT CONECTADO
# ==========================================

@bot.event
async def on_ready():
    logger.info(
        "Sr.Alpha conectado como %s (ID: %s)",
        bot.user,
        bot.user.id if bot.user else "desconhecido",
    )

    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="a comunidade Alpha",
        )
    )


# ==========================================
# COMANDO /AJUDA
# ==========================================

@bot.tree.command(
    name="ajuda",
    description="Mostra os sistemas do Sr.Alpha",
)
async def ajuda(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🤖 Sr.Alpha | Central de ajuda",
        description=(
            "Seu bot geral para a comunidade Family Alpha.\n\n"
            "Confira abaixo os sistemas disponíveis."
        ),
        color=discord.Color.from_rgb(145, 103, 255),
    )

    embed.add_field(
        name="💰 Economia",
        value=(
            "`/saldo` ` /daily` `/trabalhar` `/depositar`\n"
            "`/sacar` `/transferir` `/ranking` `/loja` `/comprar`"
        ).replace("` /daily`", "`/daily`"),
        inline=False,
    )

    embed.add_field(
        name="🛡️ Moderação",
        value=(
            "`/aviso` `/avisos` `/limpar` `/timeout`\n"
            "`/expulsar` `/banir`"
        ),
        inline=False,
    )

    embed.add_field(
        name="💬 Comunidade",
        value=(
            "`/sugerir` `/status_sugestao` `/ticket`\n"
            "`/fechar_ticket`"
        ),
        inline=False,
    )

    embed.add_field(
        name="🎨 Cargos e notificações",
        value=(
            "`/painel_cores` — painel de cores\n"
            "`/painel_pings` — painel de notificações\n"
            "`/adicionar_ping` — cadastrar opção de ping\n"
            "`/remover_ping` — remover opção de ping\n"
            "`/listar_pings` — listar opções cadastradas"
        ),
        inline=False,
    )

    embed.add_field(
        name="🎮 Diversão e níveis",
        value="`/quiz` `/ppt` `/perfil` `/level`",
        inline=False,
    )

    embed.add_field(
        name="✨ Inteligência Artificial",
        value="`/perguntar` — assistente de IA do Sr.Alpha",
        inline=False,
    )

    embed.add_field(
        name="🚀 Atualizações",
        value=(
            "`/anunciar_atualizacao` — anunciar novidades do bot"
        ),
        inline=False,
    )

    embed.set_footer(
        text="Sr.Alpha • Family Alpha | Alguns comandos exigem permissões."
    )

    await interaction.response.send_message(
        embed=embed,
        ephemeral=True,
    )


# ==========================================
# TRATAMENTO DE ERROS DOS COMANDOS
# ==========================================

@bot.tree.error
async def on_app_command_error(
    interaction: discord.Interaction,
    error: app_commands.AppCommandError,
):
    logger.error(
        "Erro em comando slash",
        exc_info=(
            type(error),
            error,
            error.__traceback__,
        ),
    )

    if isinstance(error, app_commands.MissingPermissions):
        message = "⛔ Você não tem permissão para usar este comando."

    elif isinstance(error, app_commands.BotMissingPermissions):
        message = (
            "⚠️ O Sr.Alpha não tem todas as permissões necessárias "
            "para executar este comando."
        )

    elif isinstance(error, app_commands.CommandOnCooldown):
        message = (
            f"⏳ Aguarde {error.retry_after:.1f} segundos "
            "antes de tentar novamente."
        )

    else:
        message = (
            "❌ Ocorreu um erro ao executar o comando. "
            "Tente novamente e confira os logs do bot."
        )

    try:
        if interaction.response.is_done():
            await interaction.followup.send(
                message,
                ephemeral=True,
            )
        else:
            await interaction.response.send_message(
                message,
                ephemeral=True,
            )

    except discord.HTTPException:
        logger.exception("Não foi possível enviar a mensagem de erro.")


# ==========================================
# INICIALIZAÇÃO
# ==========================================

if __name__ == "__main__":
    if not config.DISCORD_TOKEN:
        raise SystemExit(
            "ERRO: configure DISCORD_TOKEN nas variáveis do Railway."
        )

    bot.run(
        config.DISCORD_TOKEN,
        log_handler=None,
    )
