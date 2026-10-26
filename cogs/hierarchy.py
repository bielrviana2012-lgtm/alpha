import logging
import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("ReiDado.Hierarchy")
PURPLE = discord.Color.from_rgb(145, 103, 255)

# Somente cargos de equipe/gestão entram na hierarquia.
ROLE_KEYWORDS = (
    "criador", "fundador", "owner", "dono", "propriet",
    "subcriador", "co-owner", "coowner", "sub dono", "subdono",
    "administrador", "admin", "g adm", "gadm", "gerente",
    "moderador", "moderadora", "mod", "helper", "ajudante",
    "staff", "diretor", "coordenador", "supervisor",
)

ROLE_DESCRIPTIONS = {
    "criador": "Responsável principal pelo servidor, sua direção e decisões finais.",
    "fundador": "Fundou a comunidade e orienta seus objetivos e organização.",
    "owner": "Responsável principal pela administração e pelas decisões do servidor.",
    "dono": "Responsável principal pela administração e pelas decisões do servidor.",
    "subcriador": "Auxilia o criador e ajuda a coordenar a equipe e as decisões importantes.",
    "administrador": "Gerencia o servidor, configurações e equipe, ajudando a manter tudo organizado.",
    "admin": "Gerencia o servidor e auxilia na supervisão das equipes e das regras.",
    "g adm": "Gerencia e coordena a equipe administrativa e acompanha assuntos gerais do servidor.",
    "gadm": "Gerencia e coordena a equipe administrativa e acompanha assuntos gerais do servidor.",
    "gerente": "Coordena atividades e acompanha o trabalho das equipes.",
    "moderador": "Aplica as regras, acompanha conversas e ajuda a manter a comunidade segura.",
    "moderadora": "Aplica as regras, acompanha conversas e ajuda a manter a comunidade segura.",
    "mod": "Ajuda a moderar conversas e a manter o respeito às regras.",
    "helper": "Orienta membros e encaminha dúvidas ou problemas para a equipe responsável.",
    "ajudante": "Orienta membros e encaminha dúvidas ou problemas para a equipe responsável.",
    "staff": "Integra a equipe responsável pelo funcionamento e apoio à comunidade.",
    "diretor": "Coordena áreas e auxilia no planejamento e funcionamento do servidor.",
    "coordenador": "Organiza atividades e coordena a equipe de sua área.",
    "supervisor": "Acompanha a equipe e ajuda a garantir que os procedimentos sejam seguidos.",
}

def is_staff_role(role: discord.Role) -> bool:
    if role.is_default() or role.managed:
        return False
    name = role.name.casefold().strip()
    return any(keyword in name for keyword in ROLE_KEYWORDS)

def describe_role(role: discord.Role) -> str:
    name = role.name.casefold().strip()
    # Primeiro tenta correspondência específica, depois uma descrição segura genérica.
    for keyword in sorted(ROLE_DESCRIPTIONS, key=len, reverse=True):
        if keyword in name:
            return ROLE_DESCRIPTIONS[keyword]
    return "Faz parte da equipe de organização e apoio da comunidade."

def split_text(text: str, limit: int = 3800) -> list[str]:
    chunks = []
    current = ""
    for line in text.splitlines():
        addition = line if not current else "\n" + line
        if len(current) + len(addition) > limit:
            if current:
                chunks.append(current)
            current = line
        else:
            current += addition
    if current:
        chunks.append(current)
    return chunks

class Hierarchy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="hierarquia", description="Publica a hierarquia da equipe com descrições e nomes dos membros.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def hierarquia(self, interaction: discord.Interaction, canal: discord.TextChannel):
        guild = interaction.guild
        if guild is None:
            return await interaction.response.send_message("Este comando só funciona dentro de um servidor.", ephemeral=True)

        await interaction.response.defer(ephemeral=True, thinking=True)
        roles = sorted(
            (role for role in guild.roles if is_staff_role(role)),
            key=lambda role: role.position,
            reverse=True,
        )
        if not roles:
            return await interaction.followup.send(
                "Não encontrei cargos de equipe. Confira se os nomes incluem termos como Criador, Subcriador, Admin, G ADM ou Mod.",
                ephemeral=True,
            )

        # Atualiza o cache de membros quando a API permitir. Nomes são texto puro:
        # não usamos menções, IDs ou role.mention em nenhum ponto do painel.
        try:
            members = [member async for member in guild.fetch_members(limit=None)]
        except (discord.Forbidden, discord.HTTPException):
            members = list(guild.members)

        sections = []
        for role in roles:
            people = sorted(
                (member.display_name for member in members
                 if not member.bot and role in member.roles),
                key=str.casefold,
            )
            # Sem nomes de bots; se não houver ninguém, informa que o cargo está vago.
            member_text = "\n".join(f"• {discord.utils.escape_markdown(name)}" for name in people) if people else "• Nenhum membro"
            sections.append(
                f"## {discord.utils.escape_markdown(role.name)}\n"
                f"{describe_role(role)}\n"
                f"**Membros ({len(people)}):**\n{member_text}"
            )

        chunks = split_text("\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(sections))
        try:
            for index, chunk in enumerate(chunks, start=1):
                layout = discord.ui.LayoutView(timeout=None)
                panel = discord.ui.Container(accent_colour=PURPLE)
                if index == 1:
                    panel.add_item(discord.ui.TextDisplay(
                        f"# 🏛️ HIERARQUIA • {discord.utils.escape_markdown(guild.name)}\n"
                        "Estrutura da equipe, do cargo mais alto ao mais baixo.\n"
                        "Os nomes são exibidos sem marcar os membros."
                    ))
                    panel.add_item(discord.ui.Separator())
                panel.add_item(discord.ui.TextDisplay(chunk))
                if index == len(chunks):
                    panel.add_item(discord.ui.Separator())
                    panel.add_item(discord.ui.TextDisplay("-# Rei Dado • Hierarquia da equipe"))
                layout.add_item(panel)
                await canal.send(view=layout, allowed_mentions=discord.AllowedMentions.none())
        except discord.Forbidden:
            return await interaction.followup.send(
                "Não consegui publicar no canal escolhido. Dê ao Rei Dado as permissões de ver canal e enviar mensagens.",
                ephemeral=True,
            )
        except discord.HTTPException:
            log.exception("Falha ao publicar a hierarquia em %s.", canal.id)
            return await interaction.followup.send(
                "O Discord não aceitou a publicação. Verifique as permissões e tente novamente.",
                ephemeral=True,
            )

        await interaction.followup.send(f"✅ Hierarquia publicada em {canal.mention}. Os membros não foram marcados.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(Hierarchy(bot))
