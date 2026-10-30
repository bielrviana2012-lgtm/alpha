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
        self.reader_task: Optional[asyncio.Task] = None
        self.closed = False
        self.resample_state = None
        self.output: Optional[DiscordPCMSource] = None
        self.send_lock = asyncio.Lock()
        # Agrupa os pacotes de 20 ms antes de enviá-los à Gemini.
        # Isso evita milhares de corrotinas pequenas acumuladas no loop do bot.
        self.audio_queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=100)
        self.audio_sender_task: Optional[asyncio.Task] = None

    async def start(self, channel: discord.VoiceChannel):
        api_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY não está configurada no Railway.")

        self.voice = await channel.connect(
            cls=voice_recv.VoiceRecvClient,
            timeout=30,
            reconnect=True,
            self_deaf=False,
        )

        self.client = genai.Client(api_key=api_key)
        model = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live").strip()
        config = {
            "response_modalities": ["AUDIO"],
            "system_instruction": (
                "Você é o Rei Dado, personagem inspirado no King Dice de Cuphead, adaptado como anfitrião "
                "carismático da Family Alpha. Fale sempre em português brasileiro. "
                "Sua interpretação deve lembrar um apresentador elegante de um espetáculo antigo: "
                "voz masculina madura, grave, aveludada e controlada; dicção clara; ritmo confiante; "
                "entonação teatral e refinada; humor irônico e provocador, sem ser grosseiro. "
                "Use frases naturais, respostas breves e comentários espirituosos. "
                "Às vezes use expressões de anfitrião e mestre de cerimônias, sem exagerar nem repetir bordões. "
                "Mantenha a personalidade mesmo em conversas comuns, mas seja prestativo e respeitoso. "
                "Não diga que é o personagem original nem afirme ter a voz de um ator específico. "
                "Não invente fatos e admita quando não souber. Você conversa por voz em um canal do Discord. "
                "REGRA DE IDIOMA OBRIGATÓRIA: entenda e responda sempre em português brasileiro (pt-BR), "
                "mesmo que a pessoa use palavras estrangeiras ou que o contexto anterior esteja em outro idioma. "
                "Nunca diga que não consegue falar português, nunca peça para trocar o idioma e nunca mude "
                "para inglês ou outro idioma. Se não entender uma frase, peça para a pessoa repetir em português. "
                "Responda de forma natural e completa, sem cortar a resposta no meio."
            ),
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {"voice_name": "Algieba"}
                }
            },
        }
        self.live_context = self.client.aio.live.connect(model=model, config=config)
        self.gemini_session = await self.live_context.__aenter__()

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
        self.audio_sender_task = asyncio.create_task(self.audio_sender())
        self.voice.listen(voice_recv.BasicSink(receive_audio, decode=True))
        log.info("Recepção de áudio iniciada; aceitando todos os membros do canal.")
        self.reader_task = asyncio.create_task(self.read_events())

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
        try:
            while not self.closed:
                first = await self.audio_queue.get()
                chunks = [first]
                deadline = self.loop.time() + 0.10
                while len(chunks) < 10:
                    remaining = deadline - self.loop.time()
                    if remaining <= 0:
                        break
                    try:
                        chunks.append(await asyncio.wait_for(self.audio_queue.get(), timeout=remaining))
                    except asyncio.TimeoutError:
                        break
                await self.send_audio(b"".join(chunks))

                # O voice-recv só entrega pacotes quando há voz. Se o fluxo
                # ficar sem novos pacotes por mais de 1 segundo, sinalizamos
                # o fim do áudio explicitamente conforme a API Gemini Live.
                # Não inventamos frames de silêncio: isso evita prolongar ou
                # fragmentar artificialmente as falas.
                try:
                    next_audio = await asyncio.wait_for(self.audio_queue.get(), timeout=1.1)
                except asyncio.TimeoutError:
                    if not self.closed and self.gemini_session:
                        await self.gemini_session.send_realtime_input(audio_stream_end=True)
                        log.info("Fim de fala enviado à Gemini (pausa de áudio > 1s).")
                    continue

                chunks = [next_audio]
                deadline = self.loop.time() + 0.10
                while len(chunks) < 10:
                    remaining = deadline - self.loop.time()
                    if remaining <= 0:
                        break
                    try:
                        chunks.append(await asyncio.wait_for(self.audio_queue.get(), timeout=remaining))
                    except asyncio.TimeoutError:
                        break
                await self.send_audio(b"".join(chunks))
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
        # session.receive() cria um iterador limitado a um único turno.
        # Recriá-lo repetidamente pode deixar mensagens de turnos seguintes
        # sem consumo. O loop interno _receive() mantém um único leitor ativo
        # durante toda a sessão Live (workaround para o comportamento do SDK).
        if not hasattr(self.gemini_session, "_receive"):
            log.error("Esta versão do google-genai não oferece o leitor Live esperado (_receive).")
            return

        log.info("Leitor contínuo da Gemini iniciado.")
        try:
            while not self.closed:
                response = await self.gemini_session._receive()
                if self.closed:
                    return
                if response is None:
                    log.warning("A conexão Live da Gemini encerrou o fluxo de respostas.")
                    return

                go_away = getattr(response, "go_away", None)
                if go_away is not None:
                    log.warning("Gemini avisou que encerrará a conexão Live: %s", go_away)

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
                    log.info("Turno da Gemini concluído; leitor contínuo permanece ativo.")
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self.closed:
                log.exception("Leitor contínuo da Gemini foi interrompido.")

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
        if self.voice:
            try:
                self.voice.stop()
                if self.voice.is_listening():
                    self.voice.stop_listening()
            except Exception:
                log.debug("A recepção de áudio já estava parada.", exc_info=True)
        tasks = [
            task for task in (self.reader_task, self.audio_sender_task)
            if task and task is not asyncio.current_task()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self.live_context:
            try:
                await self.live_context.__aexit__(None, None, None)
            except Exception:
                log.debug("Sessão Gemini já estava fechada.", exc_info=True)
        if self.voice and self.voice.is_connected():
            await self.voice.disconnect(force=True)


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
            if not session:
                await interaction.followup.send("Não estou em uma conversa de voz agora.", ephemeral=True)
                return
            await session.close()
        await interaction.followup.send("👋 Conversa encerrada. Até a próxima!", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceChat(bot))
