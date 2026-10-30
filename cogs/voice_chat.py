from __future__ import annotations

import asyncio
import base64
import logging
import os
import queue
import threading
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, voice_recv
import websockets

try:
    import audioop
except ImportError:  # Python 3.13+
    import audioop_lts as audioop

log = logging.getLogger("Rei Dado.Voz")
LIVE_URL = "wss://api.openai.com/v1/realtime?model=gpt-realtime-2.1"
FRAME_BYTES = 3840  # 20 ms, PCM16, 48 kHz, stereo
SILENCE = bytes(FRAME_BYTES)


class DiscordPCMSource(discord.AudioSource):
    """Lê áudio PCM 48 kHz estéreo para o player do discord.py."""

    def __init__(self):
        self.frames: queue.Queue[bytes] = queue.Queue()
        self.finished = threading.Event()
        self.closed = False

    def push(self, pcm: bytes):
        # Divide em quadros de 20 ms exigidos pelo player de voz.
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
        self.ws = None
        self.reader_task: Optional[asyncio.Task] = None
        self.closed = False
        self.resample_state = None
        self.output: Optional[DiscordPCMSource] = None
        self.send_lock = asyncio.Lock()

    async def start(self, channel: discord.VoiceChannel):
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY não está configurada no Railway.")

        self.voice = await channel.connect(
            cls=voice_recv.VoiceRecvClient,
            timeout=30,
            reconnect=True,
            self_deaf=False,
        )
        headers = {"Authorization": f"Bearer {api_key}"}
        self.ws = await websockets.connect(
            LIVE_URL,
            additional_headers=headers,
            ping_interval=20,
            ping_timeout=20,
            max_size=8 * 1024 * 1024,
        )
        await self.ws.send(__import__("json").dumps({
            "type": "session.update",
            "session": {
                "type": "realtime",
                "instructions": (
                    "Você é o Rei Dado, parceiro de conversa descontraído da Family Alpha. "
                    "Fale sempre em português brasileiro, com energia, humor leve e jeito de resenha. "
                    "Seja natural, breve e amigável; faça perguntas quando ajudar a conversa. "
                    "Não invente fatos, não ofenda pessoas e admita quando não souber. "
                    "Você está conversando por voz em um canal do Discord."
                ),
                "output_modalities": ["audio"],
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "turn_detection": {"type": "server_vad", "create_response": True},
                    },
                    "output": {
                        "format": {"type": "audio/pcm", "rate": 24000},
                        "voice": "marin",
                    },
                },
            },
        }))
        ready = False
        # Aguarda a confirmação de configuração antes de começar a transmitir.
        for _ in range(20):
            event = await asyncio.wait_for(self.ws.recv(), timeout=10)
            data = __import__("json").loads(event)
            if data.get("type") == "session.updated":
                ready = True
                break
            if data.get("type") == "error":
                raise RuntimeError(data.get("error", {}).get("message", "Erro ao iniciar sessão de voz."))
        if not ready:
            raise RuntimeError("A API não confirmou a sessão de voz.")

        def receive_audio(user, packet):
            # Privacidade: somente o áudio de quem executou /chamar é processado.
            if self.closed or user is None or user.id != self.user_id or not packet.pcm:
                return
            try:
                mono = audioop.tomono(packet.pcm, 2, 0.5, 0.5)
                pcm24, self.resample_state = audioop.ratecv(
                    mono, 2, 1, 48000, 24000, self.resample_state
                )
                asyncio.run_coroutine_threadsafe(self.send_audio(pcm24), self.loop)
            except Exception:
                log.exception("Falha ao converter áudio recebido do Discord.")

        self.voice.listen(voice_recv.BasicSink(receive_audio, decode=True))
        self.reader_task = asyncio.create_task(self.read_events())

    async def send_audio(self, pcm24: bytes):
        if self.closed or not self.ws:
            return
        async with self.send_lock:
            await self.ws.send(__import__("json").dumps({
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(pcm24).decode("ascii"),
            }))

    async def read_events(self):
        try:
            async for raw in self.ws:
                if self.closed:
                    break
                event = __import__("json").loads(raw)
                kind = event.get("type")
                if kind == "input_audio_buffer.speech_started":
                    self.stop_output()
                elif kind == "response.output_audio.delta":
                    self.play_delta(base64.b64decode(event["delta"]))
                elif kind == "response.output_audio.done":
                    if self.output:
                        self.output.finished.set()
                elif kind == "error":
                    log.error("Erro da Realtime API: %s", event.get("error"))
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self.closed:
                log.exception("Conexão de voz com a OpenAI foi interrompida.")

    def play_delta(self, pcm24: bytes):
        if not self.voice or self.closed:
            return
        if self.output is None or self.output.finished.is_set():
            self.output = DiscordPCMSource()
            if self.voice.is_playing():
                self.voice.stop()
            self.voice.play(self.output)
        # OpenAI: mono 24 kHz -> Discord: estéreo 48 kHz.
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
        if self.reader_task and self.reader_task is not asyncio.current_task():
            self.reader_task.cancel()
            await asyncio.gather(self.reader_task, return_exceptions=True)
        if self.ws:
            try:
                await self.ws.close()
            except Exception:
                log.debug("WebSocket já estava fechado.", exc_info=True)
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
        # Reconhece a interação imediatamente: o Discord exige resposta inicial em poucos segundos.
        await interaction.response.defer(ephemeral=True, thinking=True)

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
                    f"🎙️ Entrei em **{destino.name}**! Pode falar comigo. Por privacidade, só vou processar "
                    "o áudio de quem usou /chamar. Não salvo gravações. Use /sair para encerrar a conversa.",
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
        if not interaction.guild:
            await interaction.response.send_message("Use esse comando dentro de um servidor.", ephemeral=True)
            return
        async with self.lock_for(interaction.guild.id):
            session = self.sessions.pop(interaction.guild.id, None)
            if not session:
                await interaction.response.send_message("Não estou em uma conversa de voz agora.", ephemeral=True)
                return
            await interaction.response.defer(ephemeral=True)
            await session.close()
            await interaction.followup.send("👋 Conversa encerrada. Até a próxima!", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(VoiceChat(bot))
