import random
from datetime import datetime, date, timedelta, timezone
import aiosqlite
import discord
from discord import app_commands
from discord.ext import commands
from database import DB_PATH, get_user, has_infinite_coins
import config

class AlphaExpansion(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.executescript("""
            CREATE TABLE IF NOT EXISTS alpha_mission_claims(guild_id INTEGER,user_id INTEGER,mission_date TEXT,reward INTEGER,PRIMARY KEY(guild_id,user_id,mission_date));
            CREATE TABLE IF NOT EXISTS alpha_pets(guild_id INTEGER,user_id INTEGER,name TEXT,species TEXT,level INTEGER DEFAULT 1,xp INTEGER DEFAULT 0,fed_at TEXT,PRIMARY KEY(guild_id,user_id));
            CREATE TABLE IF NOT EXISTS alpha_reputation(guild_id INTEGER,giver_id INTEGER,target_id INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(guild_id,giver_id,target_id));
            CREATE TABLE IF NOT EXISTS alpha_achievements(guild_id INTEGER,user_id INTEGER,achievement_key TEXT,PRIMARY KEY(guild_id,user_id,achievement_key));
            CREATE TABLE IF NOT EXISTS alpha_identity(guild_id INTEGER,user_id INTEGER,title TEXT,badge TEXT,frame TEXT,PRIMARY KEY(guild_id,user_id));
            CREATE TABLE IF NOT EXISTS alpha_relationships(guild_id INTEGER,user_a INTEGER,user_b INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(guild_id,user_a,user_b));
            CREATE TABLE IF NOT EXISTS alpha_clans(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER,name TEXT,owner_id INTEGER,UNIQUE(guild_id,name));
            CREATE TABLE IF NOT EXISTS alpha_clan_members(guild_id INTEGER,clan_id INTEGER,user_id INTEGER,PRIMARY KEY(guild_id,user_id));
            CREATE TABLE IF NOT EXISTS alpha_events(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER,creator_id INTEGER,title TEXT,description TEXT,starts_at TEXT);
            CREATE TABLE IF NOT EXISTS alpha_giveaways(message_id INTEGER PRIMARY KEY,guild_id INTEGER,host_id INTEGER,prize TEXT,ends_at TEXT,ended INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS alpha_giveaway_entries(message_id INTEGER,user_id INTEGER,PRIMARY KEY(message_id,user_id));
            CREATE TABLE IF NOT EXISTS alpha_polls(message_id INTEGER PRIMARY KEY,guild_id INTEGER,question TEXT,options TEXT);
            CREATE TABLE IF NOT EXISTS alpha_poll_votes(message_id INTEGER,user_id INTEGER,option_index INTEGER,PRIMARY KEY(message_id,user_id));
            CREATE TABLE IF NOT EXISTS alpha_tournaments(id INTEGER PRIMARY KEY AUTOINCREMENT,guild_id INTEGER,title TEXT,host_id INTEGER);
            CREATE TABLE IF NOT EXISTS alpha_tournament_entries(tournament_id INTEGER,user_id INTEGER,PRIMARY KEY(tournament_id,user_id));
            """)
            await db.commit()


    @app_commands.command(name="presentear", description="Presenteie outro membro com Alpha Coins")
    async def presentear(self, interaction: discord.Interaction, membro: discord.Member, valor: app_commands.Range[int,1,1000000]):
        if membro.bot or membro.id == interaction.user.id:
            return await interaction.response.send_message("Escolha outro membro humano.", ephemeral=True)
        await get_user(interaction.guild_id, interaction.user.id)
        await get_user(interaction.guild_id, membro.id)
        infinite = has_infinite_coins(interaction.user.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("BEGIN IMMEDIATE")
            if not infinite:
                cur = await db.execute(
                    "UPDATE users SET wallet=wallet-? WHERE guild_id=? AND user_id=? AND wallet>=?",
                    (valor, interaction.guild_id, interaction.user.id, valor),
                )
                if cur.rowcount != 1:
                    await db.rollback()
                    return await interaction.response.send_message(
                        "Você não tem moedas suficientes na carteira. Nenhum presente foi enviado.",
                        ephemeral=True,
                    )
            await db.execute(
                "UPDATE users SET wallet=wallet+? WHERE guild_id=? AND user_id=?",
                (valor, interaction.guild_id, membro.id),
            )
            await db.commit()
        await interaction.response.send_message(f"🎁 {interaction.user.mention} presenteou {membro.mention} com **{valor:,} {config.CURRENCY_NAME}**!")

    @app_commands.command(name="enquete", description="Crie uma enquete com duas ou três opções")
    async def enquete(self, interaction: discord.Interaction, pergunta: str, opcao1: str, opcao2: str, opcao3: str | None = None):
        options=[opcao1,opcao2]+([opcao3] if opcao3 else [])
        if len({x.casefold() for x in options}) != len(options):
            return await interaction.response.send_message("As opções precisam ser diferentes.", ephemeral=True)
        view=ExpansionPollView(options)
        msg=await interaction.channel.send(f"## 📊 {discord.utils.escape_markdown(pergunta)}\\nCriada por {interaction.user.mention}\\n"+ "\\n".join(f"**{i+1}.** {discord.utils.escape_markdown(x)}" for i,x in enumerate(options)), view=view)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO alpha_polls(message_id,guild_id,question,options) VALUES(?,?,?,?)",(msg.id,interaction.guild_id,pergunta,"\\n".join(options)))
            await db.commit()
        await interaction.response.send_message(f"Enquete publicada: {msg.jump_url}", ephemeral=True)

    @app_commands.command(name="missao", description="Complete sua missão diária e ganhe Alpha Coins")
    async def missao(self, interaction: discord.Interaction):
        today=date.today().isoformat()
        missions=[
            ("Explorador Alpha","Use /masmorra para explorar uma aventura",100),
            ("Companheiro Alpha","Confira seu perfil com /perfil",80),
            ("Colecionador","Confira as conquistas com /conquistas",90),
        ]
        # Escolhe uma missão fixa por dia e limita a recompensa a um resgate diário.
        index=(date.today().toordinal()+interaction.user.id)%len(missions)
        title,description,reward=missions[index]
        async with aiosqlite.connect(DB_PATH) as db:
            row=await (await db.execute("SELECT reward FROM alpha_mission_claims WHERE guild_id=? AND user_id=? AND mission_date=?",(interaction.guild_id,interaction.user.id,today))).fetchone()
            if row:
                return await interaction.response.send_message(f"✅ Sua missão diária já foi resgatada hoje. Recompensa recebida: **{row[0]} {config.CURRENCY_NAME}**.",ephemeral=True)
            await db.execute("INSERT INTO alpha_mission_claims(guild_id,user_id,mission_date,reward) VALUES(?,?,?,?)",(interaction.guild_id,interaction.user.id,today,reward))
            await db.execute("INSERT OR IGNORE INTO users(guild_id,user_id) VALUES(?,?)",(interaction.guild_id,interaction.user.id))
            await db.execute("UPDATE users SET wallet=wallet+? WHERE guild_id=? AND user_id=?",(reward,interaction.guild_id,interaction.user.id))
            await db.commit()
        await interaction.response.send_message(f"## 🎯 Missão diária: {title}\n{description}\n\n🎁 Recompensa: **{reward} {config.CURRENCY_NAME}**\n-# Recompensa diária já creditada na sua carteira.")

    @app_commands.command(name="perfil", description="Mostra seu perfil da Family Alpha")
    async def perfil(self, interaction: discord.Interaction, membro: discord.Member | None = None):
        target=membro or interaction.user
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory=aiosqlite.Row
            row=await (await db.execute("SELECT wallet,xp,level FROM users WHERE guild_id=? AND user_id=?",(interaction.guild_id,target.id))).fetchone()
            pet=await (await db.execute("SELECT name,species,level FROM alpha_pets WHERE guild_id=? AND user_id=?",(interaction.guild_id,target.id))).fetchone()
            rep=await (await db.execute("SELECT COUNT(*) FROM alpha_reputation WHERE guild_id=? AND target_id=?",(interaction.guild_id,target.id))).fetchone()
            ach=await (await db.execute("SELECT COUNT(*) FROM alpha_achievements WHERE guild_id=? AND user_id=?",(interaction.guild_id,target.id))).fetchone()
            ident=await (await db.execute("SELECT title,badge,frame FROM alpha_identity WHERE guild_id=? AND user_id=?",(interaction.guild_id,target.id))).fetchone()
        if not row: wallet,xp,level=0,0,0
        else: wallet,xp,level=row["wallet"],row["xp"],row["level"]
        title,badge,frame=tuple(ident) if ident else ("Membro Alpha","💜","Padrão")
        pettext=f"{pet[1]} {pet[0]} (nível {pet[2]})" if pet else "Nenhum — use /pet_adotar"
        await interaction.response.send_message(f"## {badge} Perfil de {target.display_name}\n**Título:** {title} · **Moldura:** {frame}\n**Nível:** {level} · **XP:** {xp}\n**Alpha Coins:** {'∞' if has_infinite_coins(target.id) else format(wallet, ',')}\n**Reputação:** {rep[0]} · **Conquistas:** {ach[0]}\n**Pet:** {pettext}")

    @app_commands.command(name="conquistas", description="Veja suas conquistas")
    async def conquistas(self, interaction: discord.Interaction, membro: discord.Member | None = None):
        target=membro or interaction.user
        async with aiosqlite.connect(DB_PATH) as db:
            row=await (await db.execute("SELECT xp,level FROM users WHERE guild_id=? AND user_id=?",(interaction.guild_id,target.id))).fetchone()
            pet=await (await db.execute("SELECT 1 FROM alpha_pets WHERE guild_id=? AND user_id=?",(interaction.guild_id,target.id))).fetchone()
            rep=await (await db.execute("SELECT COUNT(*) FROM alpha_reputation WHERE guild_id=? AND target_id=?",(interaction.guild_id,target.id))).fetchone()
            checks=[("level",bool(row and row[1]>=1),"Alcançou o nível 1"),("xp",bool(row and row[0]>=100),"Acumulou 100 XP"),("pet",bool(pet),"Adotou um pet"),("rep",rep[0]>0,"Recebeu reputação")]
            for key,ok,label in checks:
                if ok: await db.execute("INSERT OR IGNORE INTO alpha_achievements(guild_id,user_id,achievement_key) VALUES(?,?,?)",(interaction.guild_id,target.id,key))
            await db.commit()
            existing={r[0] for r in await (await db.execute("SELECT achievement_key FROM alpha_achievements WHERE guild_id=? AND user_id=?",(interaction.guild_id,target.id))).fetchall()}
        await interaction.response.send_message(f"## 🏆 Conquistas de {target.display_name}\n"+ "\n".join(f"{'🏅' if key in existing else '🔒'} {label}" for key,_,label in checks),ephemeral=True)

    @app_commands.command(name="pet_adotar", description="Adote seu primeiro pet")
    @app_commands.choices(especie=[app_commands.Choice(name="Gato",value="🐈 Gato"),app_commands.Choice(name="Cachorro",value="🐕 Cachorro"),app_commands.Choice(name="Dragão Alpha",value="🐉 Dragão Alpha"),app_commands.Choice(name="Raposa",value="🦊 Raposa")])
    async def pet_adotar(self, interaction: discord.Interaction, nome: str, especie: app_commands.Choice[str]):
        async with aiosqlite.connect(DB_PATH) as db:
            row=await (await db.execute("SELECT 1 FROM alpha_pets WHERE guild_id=? AND user_id=?",(interaction.guild_id,interaction.user.id))).fetchone()
            if row: return await interaction.response.send_message("Você já tem um pet. Use /pet.",ephemeral=True)
            await db.execute("INSERT INTO alpha_pets(guild_id,user_id,name,species) VALUES(?,?,?,?)",(interaction.guild_id,interaction.user.id,nome,especie.value))
            await db.commit()
        await interaction.response.send_message(f"🎉 Você adotou {especie.value} chamado **{discord.utils.escape_markdown(nome)}**!")

    @app_commands.command(name="pet", description="Veja seu pet")
    async def pet(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            pet=await (await db.execute("SELECT name,species,level,xp,fed_at FROM alpha_pets WHERE guild_id=? AND user_id=?",(interaction.guild_id,interaction.user.id))).fetchone()
        if not pet: return await interaction.response.send_message("Você ainda não tem pet. Use /pet_adotar!",ephemeral=True)
        await interaction.response.send_message(f"## {pet[1]} {pet[0]}\nNível: **{pet[2]}** · XP: **{pet[3]}**\nÚltima alimentação: {pet[4] or 'nunca'}")

    @app_commands.command(name="pet_alimentar", description="Alimente seu pet uma vez por dia")
    async def pet_alimentar(self, interaction: discord.Interaction):
        today=date.today().isoformat()
        async with aiosqlite.connect(DB_PATH) as db:
            pet=await (await db.execute("SELECT level,xp,fed_at FROM alpha_pets WHERE guild_id=? AND user_id=?",(interaction.guild_id,interaction.user.id))).fetchone()
            if not pet: return await interaction.response.send_message("Adote um pet com /pet_adotar primeiro.",ephemeral=True)
            if pet[2]==today: return await interaction.response.send_message("Seu pet já comeu hoje.",ephemeral=True)
            xp=pet[1]+10; level=pet[0]
            if xp>=level*50: level+=1; xp=0
            await db.execute("UPDATE alpha_pets SET level=?,xp=?,fed_at=? WHERE guild_id=? AND user_id=?",(level,xp,today,interaction.guild_id,interaction.user.id))
            await db.commit()
        await interaction.response.send_message(f"🍖 Seu pet ganhou 10 XP! Nível: **{level}**.")

    @app_commands.command(name="reputacao", description="Dê reputação positiva a um membro")
    async def reputacao(self, interaction: discord.Interaction, membro: discord.Member):
        if membro.bot or membro.id==interaction.user.id: return await interaction.response.send_message("Escolha outro membro humano.",ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            try: await db.execute("INSERT INTO alpha_reputation(guild_id,giver_id,target_id) VALUES(?,?,?)",(interaction.guild_id,interaction.user.id,membro.id))
            except aiosqlite.IntegrityError: return await interaction.response.send_message("Você já deu reputação para esse membro.",ephemeral=True)
            await db.commit()
            count=await (await db.execute("SELECT COUNT(*) FROM alpha_reputation WHERE guild_id=? AND target_id=?",(interaction.guild_id,membro.id))).fetchone()
        await interaction.response.send_message(f"💜 {interaction.user.mention} deu reputação a {membro.mention}! Total: **{count[0]}**.")

    @app_commands.command(name="identidade", description="Personalize o título e emblema do perfil")
    @app_commands.choices(titulo=[app_commands.Choice(name="Membro Alpha",value="Membro Alpha"),app_commands.Choice(name="Lenda Alpha",value="Lenda Alpha"),app_commands.Choice(name="Guardião",value="Guardião"),app_commands.Choice(name="Arcade Master",value="Arcade Master")], emblema=[app_commands.Choice(name="💜 Roxo",value="💜"),app_commands.Choice(name="⚡ Raio",value="⚡"),app_commands.Choice(name="👑 Coroa",value="👑"),app_commands.Choice(name="🐉 Dragão",value="🐉")], moldura=[app_commands.Choice(name="Padrão",value="Padrão"),app_commands.Choice(name="Épica",value="Épica"),app_commands.Choice(name="Lendária",value="Lendária")])
    async def identidade(self, interaction: discord.Interaction, titulo: app_commands.Choice[str], emblema: app_commands.Choice[str], moldura: app_commands.Choice[str]):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO alpha_identity(guild_id,user_id,title,badge,frame) VALUES(?,?,?,?,?) ON CONFLICT(guild_id,user_id) DO UPDATE SET title=excluded.title,badge=excluded.badge,frame=excluded.frame",(interaction.guild_id,interaction.user.id,titulo.value,emblema.value,moldura.value))
            await db.commit()
        await interaction.response.send_message(f"✨ Perfil atualizado: {emblema.value} **{titulo.value}** · moldura **{moldura.value}**.")

    @app_commands.command(name="casamento", description="Registre uma dupla social opcional")
    async def casamento(self, interaction: discord.Interaction, membro: discord.Member):
        if membro.bot or membro.id==interaction.user.id: return await interaction.response.send_message("Escolha outro membro humano.",ephemeral=True)
        a,b=sorted([interaction.user.id,membro.id])
        async with aiosqlite.connect(DB_PATH) as db:
            row=await (await db.execute("SELECT 1 FROM alpha_relationships WHERE guild_id=? AND (user_a IN (?,?) OR user_b IN (?,?))",(interaction.guild_id,a,b,a,b))).fetchone()
            if row: return await interaction.response.send_message("Uma dessas pessoas já está em uma dupla registrada.",ephemeral=True)
            await db.execute("INSERT INTO alpha_relationships(guild_id,user_a,user_b) VALUES(?,?,?)",(interaction.guild_id,a,b)); await db.commit()
        await interaction.response.send_message(f"💞 Dupla social registrada: {interaction.user.mention} + {membro.mention}.")
    @app_commands.command(name="casamento_desfazer", description="Desfaça sua dupla social")
    async def casamento_desfazer(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            cur=await db.execute("DELETE FROM alpha_relationships WHERE guild_id=? AND (user_a=? OR user_b=?)",(interaction.guild_id,interaction.user.id,interaction.user.id)); await db.commit()
        await interaction.response.send_message("Dupla desfeita." if cur.rowcount else "Você não tem dupla registrada.",ephemeral=True)

    @app_commands.command(name="clan", description="Gerencie clãs da Family Alpha")
    @app_commands.choices(acao=[app_commands.Choice(name="Criar",value="criar"),app_commands.Choice(name="Entrar",value="entrar"),app_commands.Choice(name="Sair",value="sair"),app_commands.Choice(name="Meu clã",value="ver"),app_commands.Choice(name="Ranking",value="ranking")])
    async def clan(self, interaction: discord.Interaction, acao: app_commands.Choice[str], nome: str | None = None):
        async with aiosqlite.connect(DB_PATH) as db:
            if acao.value=="criar":
                if not nome: return await interaction.response.send_message("Informe o nome do clã.",ephemeral=True)
                row=await (await db.execute("SELECT 1 FROM alpha_clan_members WHERE guild_id=? AND user_id=?",(interaction.guild_id,interaction.user.id))).fetchone()
                if row: return await interaction.response.send_message("Você já está em um clã.",ephemeral=True)
                try:
                    cur=await db.execute("INSERT INTO alpha_clans(guild_id,name,owner_id) VALUES(?,?,?)",(interaction.guild_id,nome,interaction.user.id))
                    await db.execute("INSERT INTO alpha_clan_members(guild_id,clan_id,user_id) VALUES(?,?,?)",(interaction.guild_id,cur.lastrowid,interaction.user.id)); await db.commit()
                except aiosqlite.IntegrityError: return await interaction.response.send_message("Esse clã já existe.",ephemeral=True)
                return await interaction.response.send_message(f"🛡️ Clã **{discord.utils.escape_markdown(nome)}** criado!")
            if acao.value=="entrar":
                if not nome: return await interaction.response.send_message("Informe o nome do clã.",ephemeral=True)
                row=await (await db.execute("SELECT 1 FROM alpha_clan_members WHERE guild_id=? AND user_id=?",(interaction.guild_id,interaction.user.id))).fetchone()
                if row: return await interaction.response.send_message("Você já está em um clã.",ephemeral=True)
                clan=await (await db.execute("SELECT id,name FROM alpha_clans WHERE guild_id=? AND name=? COLLATE NOCASE",(interaction.guild_id,nome))).fetchone()
                if not clan: return await interaction.response.send_message("Clã não encontrado.",ephemeral=True)
                await db.execute("INSERT INTO alpha_clan_members(guild_id,clan_id,user_id) VALUES(?,?,?)",(interaction.guild_id,clan[0],interaction.user.id)); await db.commit()
                return await interaction.response.send_message(f"Bem-vindo ao clã **{clan[1]}**!")
            if acao.value=="sair":
                cur=await db.execute("DELETE FROM alpha_clan_members WHERE guild_id=? AND user_id=?",(interaction.guild_id,interaction.user.id)); await db.commit()
                return await interaction.response.send_message("Você saiu do clã." if cur.rowcount else "Você não está em um clã.",ephemeral=True)
            if acao.value=="ver":
                row=await (await db.execute("SELECT c.name,c.owner_id,COUNT(m.user_id) FROM alpha_clan_members m JOIN alpha_clans c ON c.id=m.clan_id WHERE m.guild_id=? AND m.user_id=? GROUP BY c.id",(interaction.guild_id,interaction.user.id))).fetchone()
                if not row: return await interaction.response.send_message("Você ainda não tem clã.",ephemeral=True)
                return await interaction.response.send_message(f"## 🛡️ {row[0]}\nLíder: <@{row[1]}> · Membros: {row[2]}")
            rows=await (await db.execute("SELECT c.name,COUNT(m.user_id) FROM alpha_clans c LEFT JOIN alpha_clan_members m ON m.clan_id=c.id AND m.guild_id=c.guild_id WHERE c.guild_id=? GROUP BY c.id ORDER BY COUNT(m.user_id) DESC LIMIT 10",(interaction.guild_id,))).fetchall()
        await interaction.response.send_message("## 🏆 Ranking de clãs\n"+("\n".join(f"{i}. {r[0]} — {r[1]} membros" for i,r in enumerate(rows,1)) if rows else "Nenhum clã criado."))

    @app_commands.command(name="masmorra", description="Enfrente uma criatura e tente ganhar moedas")
    async def masmorra(self, interaction: discord.Interaction):
        await get_user(interaction.guild_id, interaction.user.id)
        infinite = has_infinite_coins(interaction.user.id)
        win = random.random() < 0.58
        reward = random.randint(90, 220) if win else 0
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("BEGIN IMMEDIATE")
            if not infinite:
                cur = await db.execute(
                    "UPDATE users SET wallet=wallet-50 WHERE guild_id=? AND user_id=? AND wallet>=50",
                    (interaction.guild_id, interaction.user.id),
                )
                if cur.rowcount != 1:
                    await db.rollback()
                    return await interaction.response.send_message(
                        "Você precisa ter pelo menos 50 moedas para entrar. Nenhuma moeda foi retirada.",
                        ephemeral=True,
                    )
            if reward:
                await db.execute(
                    "UPDATE users SET wallet=wallet+? WHERE guild_id=? AND user_id=?",
                    (reward, interaction.guild_id, interaction.user.id),
                )
            await db.commit()
        await interaction.response.send_message(f"## 🏰 Masmorra Alpha\n{'🏆 Vitória! Você encontrou' if win else '👾 A criatura venceu. Você perdeu a entrada de'} **{reward if win else 50} {config.CURRENCY_NAME}**.")

    @app_commands.command(name="atividade", description="Veja XP, nível e advertências de um membro")
    async def atividade(self, interaction: discord.Interaction, membro: discord.Member | None = None):
        target=membro or interaction.user
        async with aiosqlite.connect(DB_PATH) as db:
            user=await (await db.execute("SELECT xp,level FROM users WHERE guild_id=? AND user_id=?",(interaction.guild_id,target.id))).fetchone()
            warnings=await (await db.execute("SELECT COUNT(*) FROM warnings WHERE guild_id=? AND user_id=?",(interaction.guild_id,target.id))).fetchone()
        xp,level=user if user else (0,0)
        await interaction.response.send_message(f"## 📊 Atividade de {target.display_name}\nNível: **{level}** · XP: **{xp}** · Advertências: **{warnings[0]}**")

    @app_commands.command(name="historico", description="Consulte advertências de um membro")
    @app_commands.default_permissions(moderate_members=True)
    async def historico(self, interaction: discord.Interaction, membro: discord.Member):
        async with aiosqlite.connect(DB_PATH) as db:
            rows=await (await db.execute("SELECT id,reason,moderator_id,created_at FROM warnings WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 10",(interaction.guild_id,membro.id))).fetchall()
        if not rows: return await interaction.response.send_message("Esse membro não tem advertências registradas.",ephemeral=True)
        await interaction.response.send_message(f"## 🧾 Histórico de {membro.display_name}\n"+"\n".join(f"**#{r[0]}** — {discord.utils.escape_markdown(r[1])} · Moderador <@{r[2]}> · {r[3]}" for r in rows),ephemeral=True)

    @app_commands.command(name="evento", description="Publique um evento da Family Alpha")
    @app_commands.default_permissions(manage_guild=True)
    async def evento(self, interaction: discord.Interaction, titulo: str, quando: str, descricao: str):
        await interaction.response.defer(ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT INTO alpha_events(guild_id,creator_id,title,description,starts_at) VALUES(?,?,?,?,?)",(interaction.guild_id,interaction.user.id,titulo,descricao,quando)); await db.commit()
        await interaction.channel.send(f"## 📅 {discord.utils.escape_markdown(titulo)}\n**Quando:** {discord.utils.escape_markdown(quando)}\n{discord.utils.escape_markdown(descricao)}\nOrganizador: {interaction.user.mention}")
        await interaction.followup.send("Evento publicado.",ephemeral=True)

    @app_commands.command(name="torneio", description="Crie, entre ou veja torneios")
    @app_commands.choices(acao=[app_commands.Choice(name="Criar",value="criar"),app_commands.Choice(name="Entrar",value="entrar"),app_commands.Choice(name="Participantes",value="ver"),app_commands.Choice(name="Finalizar e sortear campeão",value="finalizar")])
    async def torneio(self, interaction: discord.Interaction, acao: app_commands.Choice[str], titulo: str | None = None):
        async with aiosqlite.connect(DB_PATH) as db:
            if acao.value=="criar":
                if not titulo: return await interaction.response.send_message("Informe o título do torneio.",ephemeral=True)
                cur=await db.execute("INSERT INTO alpha_tournaments(guild_id,title,host_id) VALUES(?,?,?)",(interaction.guild_id,titulo,interaction.user.id)); tid=cur.lastrowid; await db.commit()
                return await interaction.response.send_message(f"🏆 Torneio **{discord.utils.escape_markdown(titulo)}** criado (ID {tid}).")
            row=await (await db.execute("SELECT id,title,host_id FROM alpha_tournaments WHERE guild_id=? ORDER BY id DESC LIMIT 1",(interaction.guild_id,))).fetchone()
            if not row: return await interaction.response.send_message("Nenhum torneio ativo.",ephemeral=True)
            tid,name,host=row
            if acao.value=="entrar":
                await db.execute("INSERT OR IGNORE INTO alpha_tournament_entries(tournament_id,user_id) VALUES(?,?)",(tid,interaction.user.id)); await db.commit()
                return await interaction.response.send_message(f"Você entrou no torneio **{name}**!")
            participants=await (await db.execute("SELECT user_id FROM alpha_tournament_entries WHERE tournament_id=?",(tid,))).fetchall()
            if acao.value=="finalizar":
                if interaction.user.id!=host and not interaction.user.guild_permissions.manage_guild: return await interaction.response.send_message("Só o organizador ou administrador pode finalizar.",ephemeral=True)
                if not participants: return await interaction.response.send_message("Nenhum participante inscrito.",ephemeral=True)
                winner=random.choice(participants)[0]
                await db.execute("DELETE FROM alpha_tournament_entries WHERE tournament_id=?",(tid,)); await db.execute("DELETE FROM alpha_tournaments WHERE id=?",(tid,)); await db.commit()
                return await interaction.response.send_message(f"🏆 Campeão do torneio **{name}**: <@{winner}>!")
        await interaction.response.send_message(f"## 🏆 Participantes de {name}\n"+("\n".join(f"• <@{r[0]}>" for r in participants) if participants else "Ninguém inscrito."))



class ExpansionPollView(discord.ui.View):
    def __init__(self, options):
        super().__init__(timeout=None)
        for index, option in enumerate(options):
            self.add_item(ExpansionPollButton(index, option[:80]))

class ExpansionPollButton(discord.ui.Button):
    def __init__(self, index, label):
        super().__init__(label=label, style=discord.ButtonStyle.primary, custom_id=f"alpha_exp_poll:{index}")
        self.index=index

    async def callback(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            row=await (await db.execute("SELECT options FROM alpha_polls WHERE message_id=?",(interaction.message.id,))).fetchone()
            if not row:
                return await interaction.response.send_message("Enquete não encontrada.",ephemeral=True)
            options=row[0].split("\\n")
            if self.index >= len(options):
                return await interaction.response.send_message("Opção inválida.",ephemeral=True)
            await db.execute("INSERT INTO alpha_poll_votes(message_id,user_id,option_index) VALUES(?,?,?) ON CONFLICT(message_id,user_id) DO UPDATE SET option_index=excluded.option_index",(interaction.message.id,interaction.user.id,self.index))
            await db.commit()
            counts=await (await db.execute("SELECT option_index,COUNT(*) FROM alpha_poll_votes WHERE message_id=? GROUP BY option_index",(interaction.message.id,))).fetchall()
        tally={x[0]:x[1] for x in counts}
        await interaction.response.send_message("🗳️ Voto registrado!\\n"+"\\n".join(f"**{i+1}. {x}** — {tally.get(i,0)} voto(s)" for i,x in enumerate(options)),ephemeral=True)

class ExpansionGiveawayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Participar", style=discord.ButtonStyle.success, emoji="🎉", custom_id="alpha_exp_giveaway:join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        async with aiosqlite.connect(DB_PATH) as db:
            row=await (await db.execute("SELECT ends_at,ended FROM alpha_giveaways WHERE message_id=?",(interaction.message.id,))).fetchone()
            if not row:
                return await interaction.response.send_message("Sorteio não encontrado.",ephemeral=True)
            if row[1] or datetime.fromisoformat(row[0]) <= datetime.now(timezone.utc):
                return await interaction.response.send_message("Esse sorteio já terminou.",ephemeral=True)
            try:
                await db.execute("INSERT INTO alpha_giveaway_entries(message_id,user_id) VALUES(?,?)",(interaction.message.id,interaction.user.id))
                message="Você está participando do sorteio! 🎉"
            except aiosqlite.IntegrityError:
                await db.execute("DELETE FROM alpha_giveaway_entries WHERE message_id=? AND user_id=?",(interaction.message.id,interaction.user.id))
                message="Sua participação foi cancelada."
            await db.commit()
        await interaction.response.send_message(message,ephemeral=True)

async def setup(bot):
    await bot.add_cog(AlphaExpansion(bot))
