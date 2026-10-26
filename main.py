
import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from database import DB_PATH, init_db


# =========================================================
# LOGS
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("Rei Dado")


# =========================================================
# MÓDULOS DO BOT
# =========================================================

EXTENSIONS = (
    "cogs.economy",
    "cogs.prefix_commands",
    "cogs.optional_betting",
    "cogs.ping_roles",
    "cogs.color_roles",
    "cogs.premium",
    "cogs.moderation",
    "cogs.community",
    "cogs.fun",
    "cogs.levels",
    "cogs.updates",
    "cogs.embed_builder",
    "cogs.expansion",
    "cogs.arcade_premium",
)


# =========================================================
# BOT PRINCIPAL
# =========================================================

class AlphaBot(commands.Bot):

    async def setup_hook(self):
        # Inicializa o banco de dados.
        try:
            await init_db()
            logger.info("Banco de dados inicializado. DB_PATH=%s", DB_PATH.resolve())
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

            # Copia os comandos carregados para o servidor escolhido.
            # Depois remove os comandos globais antigos para evitar que
            # os mesmos slash commands apareçam duplicados no Discord.
            self.tree.copy_global_to(guild=guild)

            self.tree.clear_commands(guild=None)
            await self.tree.sync()

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
                "apostar_ativar",
                "apostar_desativar",
                "apostar_cara_coroa",
                "apostar_sorte",
                "apostar_slots",
                "apostar_historico",
                "painel_tickets",
                "ticket",
                "ticket_categoria_adicionar",
                "ticket_categoria_editar",
                "ticket_categoria_equipes",
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
    command_prefix=commands.when_mentioned_or("!", "R", "r"),
    intents=intents,
    help_command=None,
)


# =========================================================
# EVENTO: BOT CONECTADO
# =========================================================

# Evita tentativas simultâneas de conexão quando o Discord dispara on_ready
# novamente após uma reconexão do Gateway.
_voice_connect_lock = asyncio.Lock()


async def connect_fixed_voice_channel():
    """Mantém o Rei Dado conectado ao canal de voz configurado no Railway."""
    channel_id = int(getattr(config, "VOICE_CHANNEL_ID", 0) or 0)

    if channel_id <= 0:
        logger.info(
            "VOICE_CHANNEL_ID não configurado; conexão automática à call desativada."
        )
        return

    async with _voice_connect_lock:
        try:
            channel = bot.get_channel(channel_id)
            if channel is None:
                channel = await bot.fetch_channel(channel_id)

            if not isinstance(channel, discord.VoiceChannel):
                logger.error(
                    "VOICE_CHANNEL_ID=%s não aponta para um canal de voz comum.",
                    channel_id,
                )
                return

            voice_client = discord.utils.get(
                bot.voice_clients, guild=channel.guild
            )

            if voice_client and voice_client.is_connected():
                if voice_client.channel and voice_client.channel.id == channel.id:
                    logger.info("Rei Dado já está conectado à call: %s.", channel.name)
                    return

                await voice_client.move_to(channel)
                logger.info("Rei Dado mudou para a call fixa: %s.", channel.name)
                return

            if voice_client:
                try:
                    await voice_client.disconnect(force=True)
                except discord.DiscordException:
                    logger.exception("Falha ao limpar a conexão de voz anterior.")

            await channel.connect(timeout=30, reconnect=True, self_deaf=True)
            logger.info("Rei Dado conectado à call fixa: %s (%s).", channel.name, channel.id)

        except discord.Forbidden:
            logger.error(
                "Sem permissão para entrar no canal de voz %s. "
                "Confira Ver canal e Conectar para o Rei Dado.",
                channel_id,
            )
        except discord.NotFound:
            logger.error(
                "Canal de voz %s não encontrado. Confira o VOICE_CHANNEL_ID no Railway.",
                channel_id,
            )
        except Exception:
            logger.exception("Não foi possível conectar o Rei Dado à call fixa.")


@bot.event
async def on_ready():
    logger.info(
        "Rei Dado conectado como %s (ID: %s)",
        bot.user,
        bot.user.id if bot.user else "desconhecido",
    )

    try:
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Family Alpha | Sempre na call",
            )
        )
        logger.info("Presença personalizada do Rei Dado atualizada.")

    except discord.HTTPException:
        logger.exception("Não foi possível atualizar a presença.")

    await connect_fixed_voice_channel()


# =========================================================
# COMANDO /AJUDA — COMPONENTS V2
# =========================================================

@bot.tree.command(
    name="ajuda",
    description="Mostra os sistemas do Rei Dado",
)
async def ajuda(interaction: discord.Interaction):
    # Components V2 substitui embeds por componentes de layout.
    layout = discord.ui.LayoutView(timeout=None)
    painel = discord.ui.Container()

    painel.add_item(discord.ui.TextDisplay(
        "# 🤖 Rei Dado | Central de ajuda\n"
        "Seu bot geral para a comunidade Family Alpha.\n"
        "**Prefixos de texto:** `!` • `R` • `r`\n"
        "**Exemplos:** `!jogos`, `Rjogos`, `rjogos`\n"
        "Também pode mencionar o bot antes do comando.\n"
        "Os comandos `/comando` continuam disponíveis por barra.\n"
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
            "`/ticket_categoria_equipes` — configurar até 5 equipes por categoria\n"
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
        ("🎮 Diversão e níveis", "`/quiz` `/ppt` `/moeda` `/dado` `/slots` `/roleta` `/dados`\n"
            "`/mines` `/caraoucoroa` `/bau` `/8ball` `/duelo` `/jogos`\n"
            "`/perfil` `/level`\n"
            "**Prefixos:** `!jogos` • `Rjogos` • `rjogos`"),
        ("🚀 Atualizações", "`/anunciar_atualizacao` — anunciar novidades do bot"),
        ("🧩 Administração", "`/criar_embed` — criar um painel personalizado com Components V2"),
    ]

    for titulo, conteudo in secoes:
        painel.add_item(discord.ui.TextDisplay(f"**{titulo}**\n{conteudo}"))
        painel.add_item(discord.ui.Separator())

    painel.add_item(discord.ui.TextDisplay(
        "-# Rei Dado • Family Alpha | Alguns comandos exigem permissões."
    ))
    layout.add_item(painel)

    await interaction.response.send_message(
        view=layout,
        ephemeral=True,
    )



# =========================================================
# COMANDO DE PREFIXO !AJUDA / RAJUDA / rajuda
# =========================================================

@bot.command(name="ajuda", aliases=["help", "comandos"])
async def ajuda_prefixo(ctx: commands.Context):
    """Central de ajuda em Discord Components V2."""
    layout = discord.ui.LayoutView(timeout=120)
    painel = discord.ui.Container(accent_colour=discord.Colour.from_rgb(145, 103, 255))
    painel.add_item(discord.ui.TextDisplay(
        "# 🎲 REI DADO • CENTRAL DE AJUDA\n"
        "Jogos, economia e ferramentas da Family Alpha.\n"
        "**Prefixos:** `!`, `R` e `r`\n"
        "**Exemplos:** `!ajuda`, `!moeda`, `Rjogos`, `rjogos`\n"
        "Os comandos de barra continuam disponíveis."
    ))
    painel.add_item(discord.ui.Separator())
    secoes = [
        ("🎮 JOGOS E ARCADE", "`!jogos` — lista de jogos\n"
         "`!moeda`, `!caraoucoroa`, `!dado`, `!dados`, `!ppt`, `!quiz`, `!slots`, `!roleta`, `!bau`, `!duelo`\n"
         "Os prefixos de jogo iniciam uma escolha entre modo grátis e aposta quando disponível.\n"
         "Arcade premium: `/crash`, `/blackjack`, `/torre`, `/fortuna`, `/dragao`, `/maioroumenor`, `/mines`, `/8ball`."),
        ("💰 ECONOMIA", "`/saldo`, `/daily`, `/trabalhar`, `/depositar`, `/sacar`, `/transferir`, `/loja`, `/comprar`, `/inventario`, `/historico_moedas`."),
        ("👤 PERFIL E SOCIAL", "`/perfil`, `/perfil_alpha`, `/level`, `/top`, `/conquistas`, `/identidade`, `/reputacao`, `/pet`, `/clan`, `/atividade`."),
        ("🛡️ MODERAÇÃO", "`/aviso`, `/avisos`, `/limpar`, `/timeout`, `/expulsar`, `/banir` — exigem permissões."),
        ("🎫 COMUNIDADE", "`/ticket`, `/painel_tickets`, `/fechar_ticket`, `/sugerir`, `/status_sugestao`, `/relatar_bug`."),
        ("🎨 PAINÉIS", "`/painel_cores`, `/adicionar_cor`, `/remover_cor`, `/listar_cores`, `/painel_pings`, `/adicionar_ping`, `/remover_ping`, `/listar_pings`, `/criar_embed`."),
        ("⚙️ ADMINISTRAÇÃO E EVENTOS", "`/setmoney`, `/produto_criar`, `/produto_excluir`, `/sorteio`, `/encerrar_sorteio`, `/enquete`, `/evento`, `/torneio`, `/anunciar_atualizacao`. Alguns comandos são restritos à equipe.")
    ]
    for titulo, texto in secoes:
        painel.add_item(discord.ui.TextDisplay(f"**{titulo}**\n{texto}"))
        painel.add_item(discord.ui.Separator())
    painel.add_item(discord.ui.TextDisplay("-# Rei Dado • Family Alpha"))
    layout.add_item(painel)
    await ctx.send(view=layout, allowed_mentions=discord.AllowedMentions.none())


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    if isinstance(error, commands.CommandNotFound):
        # Evita traceback para palavras comuns enviadas como se fossem comandos.
        return
    if isinstance(error, commands.CommandOnCooldown):
        await ctx.reply(
            f"⏳ Aguarde {error.retry_after:.1f} segundos antes de tentar novamente.",
            mention_author=False,
        )
        return
    if isinstance(error, commands.MissingPermissions):
        await ctx.reply("⛔ Você não tem permissão para usar esse comando.", mention_author=False)
        return
    logger.error(
        "Erro em comando de prefixo %s",
        getattr(ctx.command, "qualified_name", "desconhecido"),
        exc_info=(type(error), error, error.__traceback__),
    )
    await ctx.reply("❌ Ocorreu um erro ao executar esse comando. Confira os logs do bot.", mention_author=False)


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
            "⚠️ O Rei Dado não tem todas as permissões necessárias "
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

    except discord.NotFound as send_error:
        # Interações expiradas (10062) não aceitam novas respostas.
        logger.warning(
            "A interação do comando %s expirou antes de a resposta de erro ser enviada (código %s).",
            interaction.command.name if interaction.command else "desconhecido",
            getattr(send_error, "code", "desconhecido"),
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

# Commit de gatilho para novo deploy no Railway.
