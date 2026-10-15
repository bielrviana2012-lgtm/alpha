            log.info("Não consegui enviar DM ao autor da sugestão #%s.", protocolo)
        await interaction.followup.send(f"✅ Sugestão `#{protocolo}` atualizada para **{status.value}**.", ephemeral=True)

    @app_commands.command(name="ticket_configurar", description="Define o canal onde as avaliações serão publicadas.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticket_configurar(self, interaction: discord.Interaction, canal_avaliacoes: discord.TextChannel):
        if interaction.guild is None:
            await interaction.response.send_message("Use este comando no servidor.", ephemeral=True)
            return
        await update_ticket_setting(interaction.guild.id, rating_channel_id=canal_avaliacoes.id)
        await interaction.response.send_message(f"⭐ As avaliações serão publicadas em {canal_avaliacoes.mention}.", ephemeral=True)

    @app_commands.command(name="ticket_categoria_adicionar", description="Cria uma categoria de atendimento com sua equipe.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(nome="Nome da categoria.", cargo="Cargo que atenderá os tickets.", emoji="Emoji mostrado nas mensagens.",
        descricao="Descrição curta no menu.", categoria_canais="Categoria do Discord onde criar os tickets.", mensagem_inicial="Mensagem ao abrir o ticket.")
    async def ticket_categoria_adicionar(self, interaction: discord.Interaction, nome: app_commands.Range[str, 2, 80],
        cargo: discord.Role, emoji: str = "🎫", descricao: str = "Fale com nossa equipe.",
        categoria_canais: Optional[discord.CategoryChannel] = None, mensagem_inicial: str = "Explique como podemos ajudar."):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Use este comando no servidor.", ephemeral=True)
            return
        nome = nome.strip()
        if not nome or cargo.is_default():
            await interaction.response.send_message("Informe um nome válido e um cargo específico.", ephemeral=True)
            return
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute("""INSERT INTO ticket_categories (guild_id,name,emoji,description,staff_role_id,discord_category_id,welcome_text)
                    VALUES (?,?,?,?,?,?,?)""", (guild.id, nome, (emoji or "🎫").strip()[:20] or "🎫", (descricao or nome).strip()[:100],
                    cargo.id, categoria_canais.id if categoria_canais else None, (mensagem_inicial or "Explique como podemos ajudar.").strip()[:1000]))
                await db.commit()
        except aiosqlite.IntegrityError:
            await interaction.response.send_message("Já existe uma categoria com esse nome.", ephemeral=True)
            return
        except Exception:
            log.exception("Erro ao adicionar categoria de ticket.")
            await interaction.response.send_message("Não consegui salvar a categoria. Consulte os logs do Railway.", ephemeral=True)
            return
        await interaction.response.send_message(embed=make_embed("✅ Categoria criada",
            f"**Categoria:** {(emoji or '🎫')} {nome}\n**Equipe:** {cargo.mention}\n**Categoria de canais:** {categoria_canais.name if categoria_canais else 'Não definida'}\n\nPublique novamente com `/painel_tickets`."), ephemeral=True)

    @app_commands.command(name="ticket_categoria_remover", description="Remove uma categoria de atendimento.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ticket_categoria_remover(self, interaction: discord.Interaction, nome: str):
        if interaction.guild is None:
            await interaction.response.send_message("Use este comando no servidor.", ephemeral=True)
            return
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("DELETE FROM ticket_categories WHERE guild_id=? AND name=?", (interaction.guild.id, nome.strip()))
            await db.commit()
        if not cur.rowcount:
            await interaction.response.send_message("Não encontrei uma categoria com esse nome.", ephemeral=True)
            return
        await interaction.response.send_message(f"✅ Categoria **{nome}** removida. Publique o painel novamente.", ephemeral=True)

    @app_commands.command(name="painel_tickets", description="Publica o painel de atendimento no canal escolhido.")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(canal="Canal onde publicar.", titulo="Título do painel.", descricao="Texto de apresentação.",
        cor="Cor hexadecimal, exemplo #9167FF.", imagem="URL de imagem opcional.", horarios="Horário de atendimento.", avisos="Informações importantes.")
    async def painel_tickets(self, interaction: discord.Interaction, canal: discord.TextChannel,
        titulo: str = "🎫 Central de Atendimento", descricao: str = "Selecione abaixo a categoria para abrir seu ticket.",
        cor: str = "#9167FF", imagem: str = "", horarios: str = "", avisos: str = ""):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Use este comando no servidor.", ephemeral=True)
            return
        categories = await get_ticket_categories(guild.id)
        if not categories:
            await interaction.response.send_message("Você ainda não criou categorias. Use `/ticket_categoria_adicionar` primeiro.", ephemeral=True)
            return
        parsed_color = parse_color(cor)
        if parsed_color is None:
            await interaction.response.send_message("Cor inválida. Use hexadecimal, como `#9167FF`.", ephemeral=True)
            return
        imagem = (imagem or "").strip()
        if imagem and not imagem.startswith(("https://", "http://")):
            await interaction.response.send_message("A imagem precisa ser uma URL começando com `https://`.", ephemeral=True)
            return
        titulo, descricao = (titulo or "🎫 Central de Atendimento").strip(), (descricao or "Selecione abaixo a categoria para abrir seu ticket.").strip()
        if not titulo or not descricao:
            await interaction.response.send_message("Título e descrição não podem ficar vazios.", ephemeral=True)
            return
        settings = {"panel_title": titulo[:256], "panel_description": descricao[:4000], "panel_color": parsed_color.value,
            "panel_image": imagem[:500], "hours_text": (horarios or "")[:1024], "notices_text": (avisos or "")[:1024], "panel_channel_id": canal.id}
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            message = await canal.send(embed=build_ticket_embed(settings), view=TicketPanelView(categories))
        except discord.Forbidden:
            log.exception("Sem permissão para publicar painel no canal %s.", canal.id)
            await interaction.followup.send("❌ Sem permissão para publicar nesse canal. Confira Ver canal, Enviar mensagens e Incorporar links.", ephemeral=True)
            return
        except discord.HTTPException as error:
            log.exception("Erro HTTP ao publicar painel de tickets.")
            await interaction.followup.send(f"❌ O Discord rejeitou o painel. Código `{error.code}` / HTTP `{error.status}`.", ephemeral=True)
            return
        await update_ticket_setting(guild.id, **settings, panel_message_id=message.id)
        await interaction.followup.send(f"✅ Painel publicado em {canal.mention}.", ephemeral=True)

    @app_commands.command(name="ticket", description="Mostra onde abrir um atendimento.")
    async def ticket(self, interaction: discord.Interaction):
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("Use este comando dentro do servidor.", ephemeral=True)
            return
        settings = await get_ticket_settings(guild.id)
        channel = guild.get_channel(settings.get("panel_channel_id")) if settings and settings.get("panel_channel_id") else None
        if isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(f"🎫 Para abrir um atendimento, acesse {channel.mention}.", ephemeral=True)
        else:
            await interaction.response.send_message("O painel ainda não foi publicado. Peça à administração para usar `/painel_tickets`.", ephemeral=True)


# =========================================================
# CARREGAMENTO DO MÓDULO
# =========================================================

async def setup(bot: commands.Bot):
    await init_community_tables()
    await bot.add_cog(Community(bot))
    bot.add_view(TicketCloseView())
    bot.add_view(SuggestionView())
    guild_id = int(getattr(config, "GUILD_ID", 0) or 0)
    if guild_id:
        categories = await get_ticket_categories(guild_id)
        if categories:
            bot.add_view(TicketPanelView(categories))
