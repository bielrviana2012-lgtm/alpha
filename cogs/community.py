                (interaction.guild_id, interaction.user.id, texto, channel.id),
            )
            sid = cur.lastrowid
            await db.commit()
        embed = discord.Embed(title=f"💡 Sugestão #{sid}", description=texto, color=PURPLE)
        embed.add_field(name="👤 Sugerida por", value=f"{interaction.user.mention}\n`{interaction.user}`", inline=False)
        embed.add_field(name="📌 Status", value="🟡 Em análise", inline=True)
        embed.add_field(name="👍 Apoio", value="0", inline=True)
        embed.add_field(name="👎 Não apoio", value="0", inline=True)
        embed.set_footer(text="Sr.Alpha • Sistema de sugestões")
        msg = await channel.send(embed=embed, view=SuggestionView(sid))
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE suggestions SET message_id=? WHERE id=?", (msg.id, sid))
            await db.commit()
        await interaction.response.send_message(f"✅ Sua sugestão foi enviada em {channel.mention}!", ephemeral=True)

    @app_commands.command(name="status_sugestao", description="Atualize o status de uma sugestão")
    @app_commands.default_permissions(manage_messages=True)
    @app_commands.guild_only()
    @app_commands.choices(status=[app_commands.Choice(name=s, value=s) for s in ["Em análise", "Aprovada", "Recusada"]])
    async def status_sugestao(self, interaction: discord.Interaction, numero: app_commands.Range[int, 1, 1000000], status: app_commands.Choice[str], resposta: str = ""):
        if not interaction.user.guild_permissions.manage_messages:
            return await interaction.response.send_message("Você precisa da permissão Gerenciar mensagens para alterar sugestões.", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT message_id,channel_id FROM suggestions WHERE id=? AND guild_id=?", (numero, interaction.guild_id))
            row = await cur.fetchone()
            if not row:
                return await interaction.response.send_message("Sugestão não encontrada.", ephemeral=True)
            message_id, channel_id = row
            await db.execute("UPDATE suggestions SET status=? WHERE id=? AND guild_id=?", (status.value, numero, interaction.guild_id))
            await db.commit()
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                return await interaction.response.send_message("O canal da sugestão não está acessível ao bot.", ephemeral=True)
        try:
            msg = await channel.fetch_message(message_id)
        except discord.HTTPException:
            return await interaction.response.send_message("Não consegui encontrar a mensagem da sugestão.", ephemeral=True)
        embed = msg.embeds[0]
        emoji = {"Aprovada": "🟢", "Recusada": "🔴", "Em análise": "🟡"}[status.value]
        index = next((i for i, field in enumerate(embed.fields) if field.name == "📌 Status"), None)
        if index is None:
            embed.add_field(name="📌 Status", value=f"{emoji} {status.value}", inline=True)
        else:
            embed.set_field_at(index, name="📌 Status", value=f"{emoji} {status.value}", inline=True)
        decision = f"**Responsável:** {interaction.user.mention}\n**Resultado:** {status.value}"
        index = next((i for i, field in enumerate(embed.fields) if field.name == "🛡️ Decisão da equipe"), None)
        if index is None:
            embed.add_field(name="🛡️ Decisão da equipe", value=decision, inline=False)
        else:
            embed.set_field_at(index, name="🛡️ Decisão da equipe", value=decision, inline=False)
        response = resposta.strip()[:1024]
        index = next((i for i, field in enumerate(embed.fields) if field.name == "💬 Resposta da equipe"), None)
        if response:
            if index is None:
                embed.add_field(name="💬 Resposta da equipe", value=response, inline=False)
            else:
                embed.set_field_at(index, name="💬 Resposta da equipe", value=response, inline=False)
        await msg.edit(embed=embed, view=SuggestionView(numero))
        await interaction.response.send_message(f"✅ Sugestão #{numero} atualizada para **{status.value}** por {interaction.user.mention}.", ephemeral=True)

    @app_commands.command(name="ticket", description="Cria um painel de tickets com as configurações atuais")
    @app_commands.default_permissions(manage_channels=True)
    @app_commands.guild_only()
    async def ticket(self, interaction: discord.Interaction, canal: discord.TextChannel):
        # Compatibility alias: uses the same customizable panel system.
        settings = await get_ticket_settings(interaction.guild_id)
        if not settings:
            settings = {
                "panel_title": "🔔 Central de Atendimento",
                "panel_description": "Escolha no menu abaixo a categoria para a qual deseja atendimento.",
                "panel_color": PURPLE.value, "panel_image": "", "hours_text": "",
                "notices_text": "", "panel_channel_id": canal.id, "panel_message_id": None,
            }
            async with aiosqlite.connect(DB_PATH) as db:
                await db.execute(
                    "INSERT OR REPLACE INTO ticket_settings(guild_id,panel_channel_id,panel_title,panel_description,panel_color) VALUES(?,?,?,?,?)",
                    (interaction.guild_id, canal.id, settings["panel_title"], settings["panel_description"], settings["panel_color"]),
                )
                await db.commit()
        categories = await get_ticket_categories(interaction.guild_id)
        await interaction.response.defer(ephemeral=True)
        message = await canal.send(embed=ticket_panel_embed(settings, categories), view=TicketPanelView(interaction.guild_id, categories))
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE ticket_settings SET panel_channel_id=?,panel_message_id=? WHERE guild_id=?", (canal.id, message.id, interaction.guild_id))
            await db.commit()
        self.bot.add_view(TicketPanelView(interaction.guild_id, categories), message_id=message.id)
        await interaction.followup.send(f"✅ Painel de tickets publicado em {canal.mention}.", ephemeral=True)

    @app_commands.command(name="fechar_ticket", description="Feche o ticket atual")
    @app_commands.guild_only()
    async def fechar_ticket(self, interaction: discord.Interaction):
        await self.close_ticket(interaction)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if config.WELCOME_CHANNEL_ID:
            channel = member.guild.get_channel(config.WELCOME_CHANNEL_ID)
            if channel:
                embed = discord.Embed(
                    title="👋 Bem-vindo à comunidade!",
                    description=f"{member.mention}, seja bem-vindo ao **{member.guild.name}**!\nVocê é o membro **{member.guild.member_count}**.",
                    color=PURPLE,
                )
                embed.set_thumbnail(url=member.display_avatar.url)
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    log.exception("Não foi possível enviar mensagem de boas-vindas.")


async def setup(bot: commands.Bot):
    await init_community_tables()
    await bot.add_cog(Community(bot))
    bot.add_view(SuggestionView(0))
    bot.add_view(TicketControlView())
