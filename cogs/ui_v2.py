"""Utilitários visuais do Rei Dado usando Discord Components V2."""

import discord

PURPLE = discord.Color.from_rgb(145, 103, 255)


def make_v2_panel(
    title: str,
    description: str = "",
    *,
    sections: list[tuple[str, str]] | None = None,
    footer: str = "Rei Dado • Family Alpha",
    accent_color: discord.Color = PURPLE,
) -> discord.ui.LayoutView:
    """Monta um painel Components V2 sem usar discord.Embed."""
    layout = discord.ui.LayoutView(timeout=None)
    container = discord.ui.Container(accent_colour=accent_color)

    if title:
        container.add_item(discord.ui.TextDisplay(f"# {title}"))
    if description:
        container.add_item(discord.ui.TextDisplay(description))

    for heading, body in sections or []:
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(f"**{heading}**\n{body}"))

    if footer:
        container.add_item(discord.ui.Separator())
        container.add_item(discord.ui.TextDisplay(f"-# {footer}"))

    layout.add_item(container)
    return layout
