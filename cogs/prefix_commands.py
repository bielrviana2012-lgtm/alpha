import random
from datetime import date
import aiosqlite
import discord
from discord.ext import commands
import config
from database import DB_PATH, ensure_user, get_user, has_infinite_coins, format_coins
from cogs.ui_v2 import make_v2_panel

class PrefixCommands(commands.Cog):
    def __init__(self, bot): self.bot = bot
    async def guild_only(self, ctx):
        if ctx.guild is None:
            await ctx.reply('Este comando só funciona dentro do servidor.', mention_author=False); return False
        return True

    @commands.command(name='saldo', aliases=['carteira','balance'])
    async def saldo(self, ctx, membro: discord.Member = None):
        if not await self.guild_only(ctx): return
        alvo=membro or ctx.author; row=await get_user(ctx.guild.id,alvo.id)
        panel=make_v2_panel(f'💰 Economia de {alvo.display_name}',f'Patrimônio de {alvo.mention}.',sections=[('👛 Carteira',f"{format_coins(alvo.id,row['wallet'])} {config.CURRENCY_NAME}"),('🏦 Banco',f"{format_coins(alvo.id,row['bank'])} {config.CURRENCY_NAME}"),('💎 Patrimônio total',f"{format_coins(alvo.id,row['wallet']+row['bank'])} {config.CURRENCY_NAME}")])
        await ctx.send(view=panel,allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name='daily', aliases=['diario','recompensa'])
    async def daily(self,ctx):
        if not await self.guild_only(ctx): return
        await ensure_user(ctx.guild.id,ctx.author.id); today=date.today().isoformat(); reward=random.randint(100,250)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('BEGIN IMMEDIATE'); cur=await db.execute('SELECT last_daily FROM users WHERE guild_id=? AND user_id=?',(ctx.guild.id,ctx.author.id)); row=await cur.fetchone()
            if row and row[0]==today: await db.rollback(); return await ctx.reply('⏳ Você já resgatou sua recompensa hoje. Volte amanhã!',mention_author=False)
            cur=await db.execute('UPDATE users SET wallet=wallet+?,last_daily=? WHERE guild_id=? AND user_id=? AND (last_daily IS NULL OR last_daily != ?)',(reward,today,ctx.guild.id,ctx.author.id,today))
            if cur.rowcount!=1: await db.rollback(); return await ctx.reply('Não consegui confirmar seu resgate.',mention_author=False)
            cur=await db.execute('SELECT wallet FROM users WHERE guild_id=? AND user_id=?',(ctx.guild.id,ctx.author.id)); saldo=(await cur.fetchone())[0]; await db.commit()
        await ctx.send(view=make_v2_panel('🎁 Recompensa diária',f'Você recebeu **{reward:,} {config.CURRENCY_NAME}**. Carteira: **{format_coins(ctx.author.id,saldo)} {config.CURRENCY_NAME}**'))

    @commands.command(name='trabalhar', aliases=['work'])
    async def trabalhar(self,ctx):
        if not await self.guild_only(ctx): return
        await ensure_user(ctx.guild.id,ctx.author.id); today=date.today().isoformat(); reward=random.randint(60,180); job=random.choice(['designer','programador','entregador','streamer','construtor de obbies'])
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('BEGIN IMMEDIATE'); cur=await db.execute('SELECT last_work FROM users WHERE guild_id=? AND user_id=?',(ctx.guild.id,ctx.author.id)); row=await cur.fetchone()
            if row and row[0]==today: await db.rollback(); return await ctx.reply('⏳ Você já trabalhou hoje. Volte amanhã!',mention_author=False)
            cur=await db.execute('UPDATE users SET wallet=wallet+?,last_work=? WHERE guild_id=? AND user_id=? AND (last_work IS NULL OR last_work != ?)',(reward,today,ctx.guild.id,ctx.author.id,today))
            if cur.rowcount!=1: await db.rollback(); return await ctx.reply('Não consegui registrar seu trabalho.',mention_author=False)
            await db.commit()
        await ctx.reply(f'🧰 Você trabalhou como **{job}** e ganhou **{reward} {config.CURRENCY_NAME}**!',mention_author=False)

    async def mover(self,ctx,valor,origem,destino):
        if not await self.guild_only(ctx): return
        if valor<1: return await ctx.reply('Informe um valor maior que zero.',mention_author=False)
        await ensure_user(ctx.guild.id,ctx.author.id); infinite=has_infinite_coins(ctx.author.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('BEGIN IMMEDIATE')
            if infinite: await db.execute(f'UPDATE users SET {destino}={destino}+? WHERE guild_id=? AND user_id=?',(valor,ctx.guild.id,ctx.author.id))
            else:
                cur=await db.execute(f'UPDATE users SET {origem}={origem}-?,{destino}={destino}+? WHERE guild_id=? AND user_id=? AND {origem}>=?',(valor,valor,ctx.guild.id,ctx.author.id,valor))
                if cur.rowcount!=1: await db.rollback(); return await ctx.reply('Saldo insuficiente. Nenhuma moeda foi movimentada.',mention_author=False)
            await db.commit()
        await ctx.reply(f'✅ Movimentação concluída: **{valor:,} {config.CURRENCY_NAME}**.',mention_author=False)
    @commands.command(name='depositar',aliases=['deposito'])
    async def depositar(self,ctx,valor:int): await self.mover(ctx,valor,'wallet','bank')
    @commands.command(name='sacar',aliases=['retirar'])
    async def sacar(self,ctx,valor:int): await self.mover(ctx,valor,'bank','wallet')

    @commands.command(name='transferir',aliases=['pagar','enviar'])
    async def transferir(self,ctx,membro:discord.Member,valor:int):
        if not await self.guild_only(ctx): return
        if membro.bot or membro.id==ctx.author.id: return await ctx.reply('Escolha outro membro que não seja um bot.',mention_author=False)
        if valor<1: return await ctx.reply('O valor precisa ser maior que zero.',mention_author=False)
        await ensure_user(ctx.guild.id,ctx.author.id); await ensure_user(ctx.guild.id,membro.id); infinite=has_infinite_coins(ctx.author.id)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('BEGIN IMMEDIATE')
            if not infinite:
                cur=await db.execute('UPDATE users SET wallet=wallet-? WHERE guild_id=? AND user_id=? AND wallet>=?',(valor,ctx.guild.id,ctx.author.id,valor))
                if cur.rowcount!=1: await db.rollback(); return await ctx.reply('Saldo insuficiente. Nenhuma moeda foi transferida.',mention_author=False)
            await db.execute('UPDATE users SET wallet=wallet+? WHERE guild_id=? AND user_id=?',(valor,ctx.guild.id,membro.id)); await db.commit()
        await ctx.reply(f'💸 {ctx.author.mention} enviou **{valor:,} {config.CURRENCY_NAME}** para {membro.mention}.',mention_author=False,allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name='top',aliases=['ranking','leaderboard'])
    async def top(self,ctx,tipo='fortuna'):
        if not await self.guild_only(ctx): return
        mapping={'nivel':('level','NÍVEL'),'level':('level','NÍVEL'),'xp':('xp','XP'),'fortuna':('(wallet + bank)','FORTUNA'),'coins':('(wallet + bank)','FORTUNA'),'moedas':('(wallet + bank)','FORTUNA')}
        if tipo.lower() not in mapping: return await ctx.reply('Use !top fortuna, !top nivel ou !top xp.',mention_author=False)
        coluna,titulo=mapping[tipo.lower()]
        async with aiosqlite.connect(DB_PATH) as db:
            cur=await db.execute(f'SELECT user_id,wallet,bank,xp,level FROM users WHERE guild_id=? ORDER BY {coluna} DESC,xp DESC LIMIT 10',(ctx.guild.id,)); rows=await cur.fetchall()
        if not rows: return await ctx.reply('Ainda não existem dados para o ranking.',mention_author=False)
        medals=['🥇','🥈','🥉']; lines=[]
        for pos,(uid,wallet,bank,xp,level) in enumerate(rows,1):
            member=ctx.guild.get_member(uid); name=discord.utils.escape_markdown(member.display_name) if member else f'Usuário {uid}'
            value=f'Nível {level}' if titulo=='NÍVEL' else f'{xp:,} XP' if titulo=='XP' else f'{wallet+bank:,} {config.CURRENCY_NAME}'
            lines.append(f"{medals[pos-1] if pos<=3 else '#'+str(pos)} **{name}** — {value}")
        await ctx.send(view=make_v2_panel(f'🏆 RANKING ALPHA • {titulo}','\n'.join(lines),footer='Family Alpha • Top 10'),allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name='level',aliases=['nivel','xp'])
    async def level(self,ctx,membro:discord.Member=None):
        if not await self.guild_only(ctx): return
        alvo=membro or ctx.author; row=await get_user(ctx.guild.id,alvo.id)
        await ctx.send(view=make_v2_panel(f'🌟 Nível de {alvo.display_name}',f"**Nível:** {row['level']}\n**XP:** {row['xp']:,}"),allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name='perfil',aliases=['profile'])
    async def perfil(self,ctx,membro:discord.Member=None):
        if not await self.guild_only(ctx): return
        alvo=membro or ctx.author; row=await get_user(ctx.guild.id,alvo.id)
        await ctx.send(view=make_v2_panel(f'✦ PERFIL ALPHA • {alvo.display_name}',f"**Nível:** {row['level']}\n**XP:** {row['xp']:,}\n**Carteira:** {format_coins(alvo.id,row['wallet'])} {config.CURRENCY_NAME}\n**Banco:** {format_coins(alvo.id,row['bank'])} {config.CURRENCY_NAME}\n**Patrimônio:** {format_coins(alvo.id,row['wallet']+row['bank'])} {config.CURRENCY_NAME}"),allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name='loja')
    async def loja(self,ctx):
        if not await self.guild_only(ctx): return
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute('CREATE TABLE IF NOT EXISTS shop_products (guild_id INTEGER NOT NULL,name TEXT NOT NULL,price INTEGER NOT NULL,PRIMARY KEY(guild_id,name))'); await db.execute('CREATE TABLE IF NOT EXISTS shop_guilds (guild_id INTEGER PRIMARY KEY)')
            cur=await db.execute('SELECT 1 FROM shop_guilds WHERE guild_id=?',(ctx.guild.id,))
            if not await cur.fetchone():
                await db.executemany('INSERT OR IGNORE INTO shop_products(guild_id,name,price) VALUES(?,?,?)',[(ctx.guild.id,n,p) for n,p in [('Caixa Misteriosa',250),('Amuleto Alpha',500),('Título VIP (cosmético)',1000)]])
                await db.execute('INSERT OR IGNORE INTO shop_guilds(guild_id) VALUES(?)',(ctx.guild.id,)); await db.commit()
            cur=await db.execute('SELECT name,price FROM shop_products WHERE guild_id=? ORDER BY name',(ctx.guild.id,)); rows=await cur.fetchall()
        desc='\n'.join(f'**{n}** — {p:,} {config.CURRENCY_NAME}' for n,p in rows) or 'A loja está vazia.'
        await ctx.send(view=make_v2_panel('🛍️ Loja Alpha',desc+'\nPara comprar, use /comprar.'))

    @commands.command(name='inventario',aliases=['inv','mochila'])
    async def inventario(self,ctx):
        if not await self.guild_only(ctx): return
        async with aiosqlite.connect(DB_PATH) as db:
            cur=await db.execute('SELECT item,quantity FROM inventory WHERE guild_id=? AND user_id=? AND quantity>0',(ctx.guild.id,ctx.author.id)); rows=await cur.fetchall()
        desc='\n'.join(f'• {item} × {qty}' for item,qty in rows) if rows else 'Seu inventário está vazio. Visite !loja.'
        await ctx.send(view=make_v2_panel(f'🎒 Inventário de {ctx.author.display_name}',desc))

async def setup(bot): await bot.add_cog(PrefixCommands(bot))