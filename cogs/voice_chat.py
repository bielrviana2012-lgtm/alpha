from __future__ import annotations

import asyncio
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
                "Você é o Rei Dado, parceiro de conversa descontraído da Family Alpha. "
                "Fale sempre em português brasileiro, com energia, humor leve e jeito de resenha. "
                "Seja natural, breve e amigável; faça perguntas quando ajudar a conversa. "
                "Não invente fatos, não ofenda pessoas e admita quando não souber. "
                "Você está conversando por voz em um canal do Discord."
            ),
            "speech_config": {
                "voice_config": {
                    "prebuilt_voice_config": {"voice_name": "Kore"}
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
                asyncio.run_coroutine_threadsafe(self.send_audio(pcm16), self.loop)
            except Exception:
                log.exception("Falha ao converter áudio recebido do Discord.")

        self.voice.listen(voice_recv.BasicSink(receive_audio, decode=True))
        self.reader_task = asyncio.create_task(self.read_events())

    async def send_audio(self, pcm16: bytes):
        if self.closed or not self.gemini_session:
            return
        async with self.send_lock:
            await self.gemini_session.send_realtime_input(
                audio=types.Blob(data=pcm16, mime_type="audio/pcm;rate=16000")
            )

    async def read_events(self):
        try:
            async for response in self.gemini_session.receive():
                if self.closed:
                    break
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
                if getattr(server_content, "turn_complete", False) and self.output:
                    self.output.finished.set()
        except asyncio.CancelledError:
            raise
        except Exception:
            if not self.closed:
                log.exception("Conexão de voz com a Gemini foi interrompida.")

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
        if self.reader_task and self.reader_task is not asyncio.current_task():
            self.reader_task.cancel()
            await asyncio.gather(self.reader_task, return_exceptions=True)
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
