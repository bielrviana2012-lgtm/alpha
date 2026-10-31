from __future__ import annotations

import asyncio
import ctypes.util
import logging
import os
import queue
import threading
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, voice_recv
from google import genai
from google.genai import types

try:
    import audioop
except ImportError:  # Python 3.13+
    import audioop_lts as audioop

log = logging.getLogger("Rei Dado.Voz")

# discord-ext-voice-recv precisa do Opus nativo para decodificar o áudio
# recebido. O discord.py nem sempre carrega essa biblioteca automaticamente.
if not discord.opus.is_loaded():
    opus_library = ctypes.util.find_library("opus")
    if opus_library:
        discord.opus.load_opus(opus_library)
        log.info("Biblioteca Opus carregada: %s", opus_library)
    else:
        log.error("Biblioteca nativa libopus não encontrada; a recepção de voz não funcionará.")
FRAME_BYTES = 3840  # 20 ms, PCM16, 48 kHz, stereo
SILENCE = bytes(FRAME_BYTES)


class DiscordPCMSource(discord.AudioSource):
    """Lê áudio PCM 48 kHz estéreo para o player do discord.py."""

    def __init__(self):
        self.frames: queue.Queue[bytes] = queue.Queue()
        self.finished = threading.Event()
        self.closed = False

    def push(self, pcm: bytes):
        for offset in range(0, len(pcm), FRAME_BYTES):
            frame = pcm[offset:offset + FRAME_BYTES]
            if len(frame) == FRAME_BYTES:
                self.frames.put(frame)

    def read(self) -> bytes:
        if self.closed:
            return b""
        try:
            return self.frames.get(timeout=0.1)
        except queue.Empty:
            if self.finished.is_set():
                self.closed = True
                return b""
            return SILENCE

    def is_opus(self) -> bool:
        return False

    def cleanup(self):
        self.closed = True
        self.finished.set()


class VoiceConversation:
    def __init__(self, bot: commands.Bot, guild_id: int, user_id: int):
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id
        self.loop = asyncio.get_running_loop()
        self.voice: Optional[voice_recv.VoiceRecvClient] = None
        self.client = None
        self.live_context = None
        self.gemini_session = None
        self.gemini_model = None
        self.gemini_config = None
        self.reader_task: Optional[asyncio.Task] = None
        self.closed = False
        self.resample_state = None
        self.output: Optional[DiscordPCMSource] = None
        self.send_lock = asyncio.Lock()
        # Agrupa os pacotes de 20 ms antes de enviá-los à Gemini.
        # Isso evita milhares de corrotinas pequenas acumuladas no loop do bot.
        self.audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        self.audio_sender_task: Optional[asyncio.Task] = None
        self.supervisor_task: Optional[asyncio.Task] = None

    async def start(self, channel: discord.VoiceChannel):
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY não está configurada no Railway.")

        # Recupera uma conexão antiga que tenha ficado no Discord após uma
        # interrupção/reinicialização, evitando tentar abrir uma segunda conexão.
        existing_voice = channel.guild.voice_client
        if existing_voice and existing_voice.is_connected():
            log.warning(
                "Já existe uma conexão de voz no servidor %s; encerrando a conexão antiga antes de entrar.",
                self.guild_id,
            )
            try:
                if isinstance(existing_voice, voice_recv.VoiceRecvClient) and existing_voice.is_listening():
                    existing_voice.stop_listening()
                existing_voice.stop()
                await existing_voice.disconnect(force=True)
            except Exception:
                log.exception("Não foi possível limpar a conexão de voz anterior.")
                raise RuntimeError("Já existe uma conexão de voz ativa e não consegui recuperá-la.")

        self.voice = await channel.connect(
            cls=voice_recv.VoiceRecvClient,
            timeout=30,
            reconnect=True,
            self_deaf=False,
        )

        self.client = genai.Client(api_key=api_key)
        self.gemini_model = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live").strip()
        self.gemini_config = {
            "response_modalities": ["AUDIO"],
            "system_instruction": (
                "Você é o Rei Dado, assistente de voz da Family Alpha. Sua personalidade é carismática, "
                "elegante, confiante e bem-humorada, com uma voz masculina madura, grave e aveludada, "
                "dicção clara e ritmo natural. Fale como um anfitrião simpático e inteligente, não como "
                "um narrador de jogos ou de espetáculo. "
                "REGRA PRINCIPAL DE TOM: converse de forma normal e espontânea sobre qualquer assunto. "
                "Não transforme respostas em falas sobre apostas, cassino, jogos de azar, sorte, roletas, "
                "cartas, fichas, dinheiro ou competição. Não use metáforas, bordões ou expressões desse tema. "
                "Não chame conversas comuns de rodada, aposta, jogada, prêmio ou vitória. Só fale desses "
                "assuntos se a pessoa perguntar diretamente sobre eles, e mesmo assim responda de forma "
                "informativa e neutra, sem incentivar apostas. "
                "Evite teatralidade excessiva, frases prontas e repetir o próprio nome. Seja natural, "
                "direto, prestativo e respeitoso. Ajuste o tamanho da resposta à pergunta: seja breve "
                "quando bastar e explique melhor quando necessário. "
                "Fale sempre em português brasileiro (pt-BR), mesmo se a pessoa usar palavras estrangeiras. "
                "Não mude para inglês nem diga que não consegue falar português. Se não entender, peça "
                "educadamente para repetir. Não invente fatos e admita quando não souber. "
                "IMPORTANTE: não existe limite de três perguntas, três respostas ou qualquer quantidade fixa. "
                "Continue conversando enquanto a pessoa quiser e enquanto a sessão estiver ativa. "
                "Responda a cada nova fala, sem encerrar a conversa por iniciativa própria. "
                "Você conversa por voz em um canal do Discord. Não diga que é o personagem original "
                "nem afirme ter a voz de um ator específico."
            ),
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {"voice_name": "Algieba"}
                }
            },
        }
        await self.connect_gemini_session()

    async def connect_gemini_session(self):
        """Abre uma sessão Live nova sem desconectar o bot do canal de voz."""
        context = self.client.aio.live.connect(
            model=self.gemini_model,
            config=self.gemini_config,
        )
        session = await context.__aenter__()
        async with self.send_lock:
            old_context = self.live_context
            self.live_context = context
            self.gemini_session = session
        if old_context:
            try:
                await old_context.__aexit__(None, None, None)
            except Exception:
                log.debug("Sessão Gemini anterior já estava encerrada.", exc_info=True)
        log.info("Sessão Gemini Live conectada/reconectada.")

        # A reconexão troca apenas a sessão Gemini. Não recria o listener do Discord
        # nem inicia workers duplicados enquanto a conversa de voz já está ativa.
        if self.audio_sender_task is not None:
            return

        def receive_audio(user, packet):
            # Responde a qualquer pessoa falando no canal, exceto outros bots.
            if self.closed or user is None or getattr(user, "bot", False) or not packet.pcm:
                return
            try:
                mono = audioop.tomono(packet.pcm, 2, 0.5, 0.5)
                pcm16, self.resample_state = audioop.ratecv(
                    mono, 2, 1, 48000, 16000, self.resample_state
                )
                self.loop.call_soon_threadsafe(self.enqueue_audio, pcm16)
            except Exception:
                log.exception("Falha ao converter áudio recebido do Discord.")

        if not discord.opus.is_loaded():
            raise RuntimeError(
                "A biblioteca Opus do sistema não está instalada/carregada no Railway; "
                "não consigo decodificar o áudio recebido do Discord."
            )
        self.audio_sender_task = asyncio.create_task(self.audio_sender(), name=f"rei-dado-audio-{self.guild_id}")
        self.voice.listen(voice_recv.BasicSink(receive_audio, decode=True))
        log.info("Recepção de áudio iniciada; aceitando todos os membros do canal.")
        self.reader_task = asyncio.create_task(self.read_events(), name=f"rei-dado-reader-{self.guild_id}")
        self.supervisor_task = asyncio.create_task(self.supervise_tasks(), name=f"rei-dado-supervisor-{self.guild_id}")

    def enqueue_audio(self, pcm16: bytes):
        if self.closed:
            return
        try:
            self.audio_queue.put_nowait(pcm16)
        except asyncio.QueueFull:
            # Prioriza áudio recente em vez de deixar a conversa atrasar.
            try:
                self.audio_queue.get_nowait()
                self.audio_queue.put_nowait(pcm16)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    async def audio_sender(self):
        # Envia os blocos continuamente. O fim da fala só é sinalizado depois
        # de um período real sem pacotes; nunca espera 1s após cada lote.
        speech_open = False
        silence_timeout = 0.65
        try:
            while not self.closed:
                try:
                    first = await asyncio.wait_for(
                        self.audio_queue.get(),
                        timeout=silence_timeout if speech_open else None,
                    )
                except asyncio.TimeoutError:
                    if speech_open and self.gemini_session and not self.closed:
                        async with self.send_lock:
                            await self.gemini_session.send_realtime_input(audio_stream_end=True)
                        log.info("Fim de fala enviado à Gemini após 650ms sem áudio.")
                    speech_open = False
                    continue

                chunks = [first]
                deadline = self.loop.time() + 0.06
                while len(chunks) < 8:
                    remaining = deadline - self.loop.time()
                    if remaining <= 0:
                        break
                    try:
                        chunks.append(
                            await asyncio.wait_for(self.audio_queue.get(), timeout=remaining)
                        )
                    except asyncio.TimeoutError:
                        break

                await self.send_audio(b"".join(chunks))
                speech_open = True
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self.closed:
                log.exception("Falha ao enviar áudio agrupado para a Gemini.")

    async def send_audio(self, pcm16: bytes):
        if self.closed or not self.gemini_session:
            return
        async with self.send_lock:
            await self.gemini_session.send_realtime_input(
                audio=types.Blob(data=pcm16, mime_type="audio/pcm;rate=16000")
            )

    async def read_events(self):
        # Mantém a leitura ativa e cria uma nova sessão se a conexão Live cair.
        retry_delay = 2
        while not self.closed:
            try:
                async for response in self.gemini_session.receive():
                    if self.closed:
                        return
                    server_content = getattr(response, "server_content", None)
                    if server_content is None:
                        continue
                    if getattr(server_content, "interrupted", False):
                        self.stop_output()
                    model_turn = getattr(server_content, "model_turn", None)
                    if model_turn:
                        for part in model_turn.parts or []:
                            inline_data = getattr(part, "inline_data", None)
                            if inline_data and inline_data.data:
                                self.play_delta(inline_data.data)
                    if getattr(server_content, "turn_complete", False):
                        if self.output:
                            self.output.finished.set()
                        log.info("Resposta concluída; conversa permanece aberta para novas perguntas.")
                if not self.closed:
                    # A Gemini encerra o iterador receive() ao concluir cada turno.
                    # Isso NÃO significa que a sessão caiu: abra outro iterador na
                    # mesma sessão para receber a próxima fala, sem reconectar.
                    log.info("Turno Gemini encerrado; aguardando a próxima fala na mesma sessão.")
                    await asyncio.sleep(0.05)
                    continue
            except asyncio.CancelledError:
                raise
            except Exception:
                if self.closed:
                    return
                log.exception("Conexão de leitura da Gemini caiu; tentando reconectar.")
                self.stop_output()
                while not self.closed:
                    try:
                        await asyncio.sleep(retry_delay)
                        await self.connect_gemini_session()
                        retry_delay = 2
                        log.info("Gemini reconectada; o bot continua na call do Discord.")
                        break
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        log.exception("Reconexão da Gemini falhou; nova tentativa em %ss.", retry_delay)
                        retry_delay = min(retry_delay * 2, 30)

    async def supervise_tasks(self):
        # Mantém os trabalhadores essenciais vivos enquanto a call estiver ativa.
        try:
            while not self.closed:
                await asyncio.sleep(2)
                if self.closed:
                    return

                if self.audio_sender_task and self.audio_sender_task.done():
                    try:
                        error = self.audio_sender_task.exception()
                    except asyncio.CancelledError:
                        error = None
                    if error:
                        log.error("Tarefa de envio de áudio terminou: %r", error)
                    else:
                        log.warning("Tarefa de envio de áudio terminou inesperadamente.")
                    self.audio_sender_task = asyncio.create_task(
                        self.audio_sender(), name=f"rei-dado-audio-restart-{self.guild_id}"
                    )

                if self.reader_task and self.reader_task.done():
                    try:
                        error = self.reader_task.exception()
                    except asyncio.CancelledError:
                        error = None
                    if error:
                        log.error("Tarefa de leitura da Gemini terminou: %r", error)
                    else:
                        log.warning("Tarefa de leitura da Gemini terminou inesperadamente.")
                    self.reader_task = asyncio.create_task(
                        self.read_events(), name=f"rei-dado-reader-restart-{self.guild_id}"
                    )
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self.closed:
                log.exception("Supervisor da conversa de voz falhou.")

    def play_delta(self, pcm24: bytes):
        if not self.voice or self.closed:
            return
        if self.output is None or self.output.finished.is_set():
            self.output = DiscordPCMSource()
            if self.voice.is_playing():
                self.voice.stop()
            self.voice.play(self.output)
        # Gemini: mono 24 kHz -> Discord: estéreo 48 kHz.
        upsampled, _ = audioop.ratecv(pcm24, 2, 1, 24000, 48000, None)
        stereo = audioop.tostereo(upsampled, 2, 1.0, 1.0)
        self.output.push(stereo)

    def stop_output(self):
        if self.output:
            self.output.finished.set()
        if self.voice and self.voice.is_playing():
            self.voice.stop()
        self.output = None

    async def close(self):
        if self.closed:
            return
        self.closed = True

        # A prioridade é liberar o canal do Discord. Não espere a Gemini
        # encerrar a sessão para começar a desconexão.
        self.stop_output()
        if self.voice:
            try:
                if self.voice.is_listening():
                    self.voice.stop_listening()
                self.voice.stop()
            except Exception:
                log.debug("A recepção de áudio já estava parada.", exc_info=True)

        if self.voice and self.voice.is_connected():
            try:
                await asyncio.wait_for(self.voice.disconnect(force=True), timeout=4)
                log.info("Rei Dado desconectado do canal de voz.")
            except asyncio.TimeoutError:
                log.warning("Desconexão do Discord excedeu 4s; encerramento seguirá em frente.")
            except Exception:
                log.exception("Falha ao desconectar o Rei Dado do canal de voz.")
                raise

        tasks = [
            task for task in (self.reader_task, self.audio_sender_task, self.supervisor_task)
            if task and task is not asyncio.current_task()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # A limpeza da Gemini tem limite de tempo para não bloquear /sair
        # nem impedir um novo /chamar.
        if self.live_context:
            try:
                await asyncio.wait_for(
                    self.live_context.__aexit__(None, None, None),
                    timeout=1.5,
                )
            except asyncio.TimeoutError:
                log.warning("Gemini demorou para fechar; seguindo sem bloquear o Discord.")
            except Exception:
                log.debug("Sessão Gemini já estava fechada.", exc_info=True)
            finally:
                self.live_context = None
                self.gemini_session = None


class VoiceChat(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.sessions: dict[int, VoiceConversation] = {}
        self.locks: dict[int, asyncio.Lock] = {}

    def lock_for(self, guild_id: int) -> asyncio.Lock:
        return self.locks.setdefault(guild_id, asyncio.Lock())

    @app_commands.command(name="chamar", description="Entra em um canal de voz e conversa com o Rei Dado")
    @app_commands.describe(canal="Escolha o canal de voz. Se deixar vazio, uso seu canal atual.")
    async def chamar(
        self,
        interaction: discord.Interaction,
        canal: Optional[discord.VoiceChannel] = None,
    ):
        # Reconhece a interação imediatamente; o Discord exige resposta em até 3 segundos.
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except discord.NotFound as error:
            interaction_age = (discord.utils.utcnow() - interaction.created_at).total_seconds()
            bot_app_id = getattr(self.bot, "application_id", None)
            log.error(
                "Discord rejeitou o defer de /chamar (10062/Unknown Interaction). "
                "interaction_id=%s; interaction_app_id=%s; bot_app_id=%s; "
                "idade_local=%.3fs; gateway_latency=%.3fs; guild=%s; user=%s; "
                "process_id=%s; código=%s. Verifique relógio do container, "
                "aplicação/comando instalado e se há mais de uma instância usando o token.",
                interaction.id,
                interaction.application_id,
                bot_app_id,
                interaction_age,
                getattr(self.bot, "latency", float("nan")),
                interaction.guild_id,
                interaction.user.id,
                os.getpid(),
                getattr(error, "code", "desconhecido"),
            )
            return

        interaction_age = (discord.utils.utcnow() - interaction.created_at).total_seconds()
        log.info(
            "Comando /chamar reconhecido; interaction_id=%s; idade_local=%.3fs; "
            "interaction_app_id=%s; bot_app_id=%s; gateway_latency=%.3fs; "
            "usuário=%s; guild=%s; process_id=%s",
            interaction.id,
            interaction_age,
            interaction.application_id,
            getattr(self.bot, "application_id", None),
            getattr(self.bot, "latency", float("nan")),
            interaction.user.id,
            interaction.guild_id,
            os.getpid(),
        )

        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            await interaction.followup.send("Use esse comando dentro de um servidor.", ephemeral=True)
            return

        member = interaction.user
        destino = canal
        if destino is None:
            if not member.voice or not isinstance(member.voice.channel, discord.VoiceChannel):
                await interaction.followup.send(
                    "Escolha um canal de voz no campo **canal** ou entre em um canal antes de usar /chamar.",
                    ephemeral=True,
                )
                return
            destino = member.voice.channel

        if destino.guild.id != interaction.guild.id:
            await interaction.followup.send("Escolha um canal de voz deste servidor.", ephemeral=True)
            return

        guild_id = interaction.guild.id
        async with self.lock_for(guild_id):
            if guild_id in self.sessions:
                await interaction.followup.send(
                    "Já estou em uma conversa de voz neste servidor. Use /sair para encerrar.",
                    ephemeral=True,
                )
                return

            session = VoiceConversation(self.bot, guild_id, member.id)
            try:
                await session.start(destino)
                self.sessions[guild_id] = session
                await interaction.followup.send(
                    f"🎙️ Entrei em **{destino.name}**! Pode falar comigo: vou ouvir e responder qualquer pessoa que falar neste canal, "
                    "não apenas quem usou /chamar. Não salvo gravações. Use /sair para encerrar a conversa.",
                    ephemeral=True,
                )
            except Exception as error:
                log.exception("Não foi possível iniciar a conversa de voz.")
                await session.close()
                await interaction.followup.send(
                    f"Não consegui iniciar a conversa de voz: {str(error)[:250]}",
                    ephemeral=True,
                )

    @app_commands.command(name="sair", description="Encerra a conversa e tira o Rei Dado da call")
    async def sair(self, interaction: discord.Interaction):
        # Reconhece o comando antes de esperar pelo lock ou desconectar da call.
        try:
            await interaction.response.defer(ephemeral=True, thinking=True)
        except discord.NotFound as error:
            log.warning(
                "Interação de /sair expirou antes do defer; idade=%.3fs; código=%s",
                (discord.utils.utcnow() - interaction.created_at).total_seconds(),
                getattr(error, "code", "desconhecido"),
            )
            return

        if not interaction.guild:
            await interaction.followup.send("Use esse comando dentro de um servidor.", ephemeral=True)
            return

        async with self.lock_for(interaction.guild.id):
            session = self.sessions.pop(interaction.guild.id, None)
            if session:
                await session.close()
            else:
                # Também limpa uma conexão órfã, caso o processo tenha perdido
                # o registro da conversa mas o Discord ainda mostre o bot na call.
                orphan_voice = interaction.guild.voice_client
                if orphan_voice and orphan_voice.is_connected():
                    try:
                        orphan_voice.stop()
                        if isinstance(orphan_voice, voice_recv.VoiceRecvClient) and orphan_voice.is_listening():
                            orphan_voice.stop_listening()
                        await orphan_voice.disconnect(force=True)
                    except Exception:
                        log.exception("Falha ao encerrar conexão de voz órfã.")
                        await interaction.followup.send(
                            "Encontrei uma conexão antiga, mas não consegui encerrá-la. Confira os logs do Railway.",
                            ephemeral=True,
                        )
                        return
                else:
                    await interaction.followup.send("Não estou em uma conversa de voz agora.", ephemeral=True)
                    return
        await interaction.followup.send("👋 Conversa encerrada. Até a próxima!", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceChat(bot))
