
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from database import init_db


# =========================================================
# LOGS
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("Sr.Alpha")


# =========================================================
# MÓDULOS DO BOT
# =========================================================

EXTENSIONS = (
    "cogs.economy",
    "cogs.ping_roles",
    "cogs.color_roles",
    "cogs.premium",
    "cogs.moderation",
    "cogs.community",
    "cogs.fun",
    "cogs.levels",
    "cogs.updates",
    "cogs.embed_builder",
)


# =========================================================
# BOT PRINCIPAL
# =========================================================

class AlphaBot(commands.Bot):

    async def setup_hook(self):
        # Inicializa o banco de dados.
        try:
            await init_db()
            logger.info("Banco de dados inicializado.")
        except Exception:
            logger.exception("Falha ao inicializar o banco de dados.")
            raise

        # Carrega cada módulo individualmente.
        loaded_extensions = []
        failed_extensions = []

        logger.info("Iniciando carregamento dos módulos...")

        for extension in EXTENSIONS:
            try:
                await self.load_extension(extension)

                loaded_extensions.append(extension)
                logger.info("Módulo carregado: %s", extension)

            except Exception as error:
                failed_extensions.append(extension)

                logger.error(
                    "Falha ao carregar o módulo: %s | Erro: %s",
                    extension,
                    error,
                    exc_info=True,
                )

        # Resumo do carregamento.
        logger.info(
            "Resumo dos módulos: %s carregados, %s com falha.",
            len(loaded_extensions),
            len(failed_extensions),
        )

        if failed_extensions:
            logger.error(
                "Módulos que falharam: %s",
                ", ".join(failed_extensions),
            )
        else:
            logger.info("Todos os módulos foram carregados.")

        # Sincroniza os comandos com o servidor.
        try:
            guild_id = int(getattr(config, "GUILD_ID", 0) or 0)

            if guild_id <= 0:
                logger.error(
                    "GUILD_ID inválido ou não configurado. "
                    "Configure o ID do servidor Family Alpha no Railway."
                )
                return

            guild = discord.Object(id=guild_id)

            # Disponibiliza os comandos globais no servidor escolhido.
            self.tree.copy_global_to(guild=guild)

            synced = await self.tree.sync(guild=guild)

            command_names = sorted(command.name for command in synced)

            logger.info(
                "Comandos sincronizados no servidor %s: %s",
                guild_id,
                len(synced),
            )

            logger.info(
                "Comandos disponíveis: %s",
                ", ".join(command_names) or "Nenhum",
            )

            # Verifica comandos importantes.
            expected_commands = {
                "ajuda",
                "painel_tickets",
                "ticket",
                "ticket_categoria_adicionar",
                "ticket_categoria_editar",
                "ticket_categoria_remover",
                "ticket_configurar_avaliacoes",
                "fechar_ticket",
                "sugerir",
                "status_sugestao",
                "painel_pings",
                "adicionar_ping",
                "remover_ping",
                "listar_pings",
                "painel_cores",
                "criar_embed",
            }

            missing = expected_commands - set(command_names)

            if missing:
                logger.warning(
                    "Comandos esperados ausentes: %s",
                    ", ".join(sorted(missing)),
                )
                logger.warning(
                    "Verifique se os módulos responsáveis foram carregados "
                    "e se os comandos estão definidos neles."
                )
            else:
                logger.info(
                    "Todos os comandos principais foram encontrados."
                )

        except Exception:
            logger.exception(
                "Falha ao sincronizar os comandos do Discord."
            )


# =========================================================
# INTENTS E CONFIGURAÇÃO
# =========================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = AlphaBot(
    command_prefix="!",
    intents=intents,
    help_command=None,
)


# =========================================================
# EVENTO: BOT CONECTADO
# =========================================================

@bot.event
async def on_ready():
    logger.info(
        "Sr.Alpha conectado como %s (ID: %s)",
        bot.user,
        bot.user.id if bot.user else "desconhecido",
    )

    try:
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="a comunidade Alpha",
            )
        )
        logger.info("Presença do Sr.Alpha atualizada.")

    except discord.HTTPException:
        logger.exception("Não foi possível atualizar a presença.")


# =========================================================
# COMANDO /AJUDA — COMPONENTS V2
# =========================================================

@bot.tree.command(
    name="ajuda",
    description="Mostra os sistemas do Sr.Alpha",
)
async def ajuda(interaction: discord.Interaction):
    # Components V2 substitui embeds por componentes de layout.
    layout = discord.ui.LayoutView(timeout=None)
    painel = discord.ui.Container()

    painel.add_item(discord.ui.TextDisplay(
        "# 🤖 Sr.Alpha | Central de ajuda\n"
        "Seu bot geral para a comunidade Family Alpha.\n"
        "Confira abaixo os sistemas disponíveis."
    ))
    painel.add_item(discord.ui.Separator())

    secoes = [
        (
            "💰 Economia",
            "`/saldo` `/daily` `/trabalhar` `/depositar`\n"
            "`/sacar` `/transferir` `/ranking` `/loja` `/comprar`",
        ),
        (
            "🛡️ Moderação",
            "`/aviso` `/avisos` `/limpar` `/timeout`\n"
            "`/expulsar` `/banir`",
        ),
        (
            "💬 Comunidade e tickets",
            "`/sugerir` — enviar sugestão\n"
            "`/status_sugestao` — atualizar uma sugestão\n"
            "`/ticket` — publicar painel de atendimento\n"
            "`/painel_tickets` — publicar painel de tickets\n"
            "`/ticket_categoria_editar` — editar categoria\n"
            "`/ticket_categoria_adicionar` — criar categoria\n"
            "`/ticket_categoria_remover` — remover categoria\n"
            "`/ticket_configurar_avaliacoes` — configurar avaliações\n"
            "`/fechar_ticket` — fechar o ticket atual",
        ),
        (
            "🎨 Cargos e notificações",
            "`/painel_cores` — painel de cores\n"
            "`/painel_pings` — painel de notificações\n"
            "`/adicionar_ping` — cadastrar opção de ping\n"
            "`/remover_ping` — remover opção de ping\n"
            "`/listar_pings` — listar opções cadastradas",
        ),
        ("🎮 Diversão e níveis", "`/quiz` `/ppt` `/perfil` `/level`"),
        ("🚀 Atualizações", "`/anunciar_atualizacao` — anunciar novidades do bot"),
        ("🧩 Administração", "`/criar_embed` — criar um painel personalizado com Components V2"),
    ]

    for titulo, conteudo in secoes:
        painel.add_item(discord.ui.TextDisplay(f"**{titulo}**\n{conteudo}"))
        painel.add_item(discord.ui.Separator())

    painel.add_item(discord.ui.TextDisplay(
        "-# Sr.Alpha • Family Alpha | Alguns comandos exigem permissões."
    ))
    layout.add_item(painel)

    await interaction.response.send_message(
        view=layout,
        ephemeral=True,
    )


# =========================================================
# TRATAMENTO DE ERROS DOS COMANDOS
# =========================================================

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

    elif isinstance(error, app_commands.CheckFailure):
        message = "⛔ Você não pode usar este comando neste contexto."

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
        logger.exception(
            "Não foi possível enviar a mensagem de erro."
        )


# =========================================================
# INICIALIZAÇÃO
# =========================================================

if __name__ == "__main__":
    token = getattr(config, "DISCORD_TOKEN", None)

    if not token:
        raise SystemExit(
            "ERRO: configure DISCORD_TOKEN nas variáveis do Railway."
        )

    bot.run(
        token,
        log_handler=None,
    )
