import random
from datetime import date
import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
from database import DB_PATH, get_user, ensure_user
import config

SHOP = {"Caixa Misteriosa": 250, "Amuleto Alpha": 500, "Título VIP (cosmético)": 1000}

class Economy(commands.Cog):
    def __init__(self, bot): self.bot = bot

    @app_commands.command(name="saldo", description="Veja sua carteira e seu banco")
    async def saldo(self, interaction: discord.Interaction, membro: discord.Member | None = None):
        target = membro or interaction.user
        row = await get_user(interaction.guild_id, target.id)
        embed = discord.Embed(title=f"💰 Economia de {target.display_name}", color=discord.Color.gold())
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="👛 Carteira", value=f"{row['wallet']:,} {config.CURRENCY_NAME}")
        embed.add_field(name="🏦 Banco", value=f"{row['bank']:,} {config.CURRENCY_NAME}")
        embed.add_field(name="💎 Patrimônio", value=f"{row['wallet']+row['bank']:,} {config.CURRENCY_NAME}", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="setmoney", description="Define o saldo de um membro")
    @app_commands.describe(membro="Membro que receberá as moedas", valor="Novo saldo")
    async def setmoney(self, interaction: discord.Interaction, membro: discord.Member, valor: app_commands.Range[int, 0, 1000000000]):
        if interaction.user.id != 1340377944215785502:
            return await interaction.response.send_message(
                "❌ Você não tem permissão para usar este comando.",
                ephemeral=True
            )

        await ensure_user(interaction.guild_id, membro.id)

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE users SET wallet=? WHERE guild_id=? AND user_id=?",
                (valor, interaction.guild_id, membro.id)
            )
            await db.commit()

        await interaction.response.send_message(
            f"✅ O saldo de {membro.mention} foi definido para **{valor:,} {config.CURRENCY_NAME}**."
        )

    @app_commands.command(name="daily", description="Resgate sua recompensa diária")
    async def daily(self, interaction: discord.Interaction):
        row = await get_user(interaction.guild_id, interaction.user.id)
        today = date.today().isoformat()
        if row['last_daily'] == today:
            return await interaction.response.send_message("⏳ Você já resgatou sua recompensa hoje. Volte amanhã!", ephemeral=True)
        reward = random.randint(100, 250)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET wallet=wallet+?, last_daily=? WHERE guild_id=? AND user_id=?", (reward,today,interaction.guild_id,interaction.user.id)); await db.commit()
        await interaction.response.send_message(embed=discord.Embed(description=f"🎁 Você recebeu **{reward} {config.CURRENCY_NAME}**!", color=discord.Color.green()))

    @app_commands.command(name="trabalhar", description="Faça um trabalho e ganhe moedas (cooldown diário)")
    async def trabalhar(self, interaction: discord.Interaction):
        row = await get_user(interaction.guild_id, interaction.user.id)
        today = date.today().isoformat()
        if row['last_work'] == today:
            return await interaction.response.send_message("⏳ Você já trabalhou hoje. Volte amanhã!", ephemeral=True)
        reward = random.randint(60, 180)
        jobs = ["designer", "programador", "entregador", "streamer", "construtor de obbies"]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET wallet=wallet+?, last_work=? WHERE guild_id=? AND user_id=?", (reward,today,interaction.guild_id,interaction.user.id)); await db.commit()
        await interaction.response.send_message(f"🧰 Você trabalhou como **{random.choice(jobs)}** e ganhou **{reward} {config.CURRENCY_NAME}**!")

    async def move_money(self, interaction, amount, column_from, column_to):
        if amount <= 0: return await interaction.response.send_message("O valor precisa ser maior que zero.", ephemeral=True)
        row = await get_user(interaction.guild_id, interaction.user.id)
        if row[column_from] < amount: return await interaction.response.send_message("Você não tem saldo suficiente.", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(f"UPDATE users SET {column_from}={column_from}-?, {column_to}={column_to}+? WHERE guild_id=? AND user_id=?", (amount,amount,interaction.guild_id,interaction.user.id)); await db.commit()
        await interaction.response.send_message(f"✅ Transferência concluída: **{amount} {config.CURRENCY_NAME}**.")

    @app_commands.command(name="depositar", description="Deposite moedas no banco")
    async def depositar(self, interaction: discord.Interaction, valor: app_commands.Range[int, 1, 1000000000]): await self.move_money(interaction, valor, "wallet", "bank")

    @app_commands.command(name="sacar", description="Saque moedas do banco")
    async def sacar(self, interaction: discord.Interaction, valor: app_commands.Range[int, 1, 1000000000]): await self.move_money(interaction, valor, "bank", "wallet")

    @app_commands.command(name="transferir", description="Envie moedas para outro membro")
    async def transferir(self, interaction: discord.Interaction, membro: discord.Member, valor: app_commands.Range[int, 1, 1000000000]):
        if membro.bot or membro.id == interaction.user.id: return await interaction.response.send_message("Escolha outro membro que não seja um bot.", ephemeral=True)
        row = await get_user(interaction.guild_id, interaction.user.id); await ensure_user(interaction.guild_id, membro.id)
        if row['wallet'] < valor: return await interaction.response.send_message("Saldo insuficiente na carteira.", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET wallet=wallet-? WHERE guild_id=? AND user_id=?", (valor,interaction.guild_id,interaction.user.id))
            await db.execute("UPDATE users SET wallet=wallet+? WHERE guild_id=? AND user_id=?", (valor,interaction.guild_id,membro.id)); await db.commit()
        await interaction.response.send_message(f"💸 {interaction.user.mention} enviou **{valor} {config.CURRENCY_NAME}** para {membro.mention}.")

    @app_commands.command(name="ranking", description="Veja os membros mais ricos do servidor")
    async def ranking(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT user_id, wallet+bank AS total FROM users WHERE guild_id=? ORDER BY total DESC LIMIT 10", (interaction.guild_id,)); rows = await cur.fetchall()
        if not rows: return await interaction.response.send_message("Ainda não há dados de economia.", ephemeral=True)
        lines = [f"**{i}.** <@{uid}> — {total:,} {config.CURRENCY_NAME}" for i,(uid,total) in enumerate(rows,1)]
        await interaction.response.send_message(embed=discord.Embed(title="🏆 Ranking Alpha", description="\n".join(lines), color=discord.Color.gold()))

    @app_commands.command(name="loja", description="Veja os itens disponíveis na loja")
    async def loja(self, interaction: discord.Interaction):
        text = "\n".join(f"**{item}** — {price:,} {config.CURRENCY_NAME}" for item,price in SHOP.items())
        await interaction.response.send_message(embed=discord.Embed(title="🛍️ Loja Alpha", description=text+"\n\nCompre usando `/comprar`. Itens cosméticos não concedem permissões reais.", color=discord.Color.blurple()), ephemeral=True)

    @app_commands.command(name="comprar", description="Compre um item da loja")
    @app_commands.choices(item=[app_commands.Choice(name=k, value=k) for k in SHOP])
    async def comprar(self, interaction: discord.Interaction, item: app_commands.Choice[str]):
        price = SHOP[item.value]; row = await get_user(interaction.guild_id, interaction.user.id)
        if row['wallet'] < price: return await interaction.response.send_message("Você não tem moedas suficientes na carteira.", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET wallet=wallet-? WHERE guild_id=? AND user_id=?", (price,interaction.guild_id,interaction.user.id))
            await db.execute("INSERT INTO inventory(guild_id,user_id,item,quantity) VALUES(?,?,?,1) ON CONFLICT(guild_id,user_id,item) DO UPDATE SET quantity=quantity+1", (interaction.guild_id,interaction.user.id,item.value)); await db.commit()
        await interaction.response.send_message(f"🛍️ Compra concluída: **{item.value}**! Confira `/inventario` em uma próxima atualização.")

    @app_commands.command(name="inventario", description="Veja os itens que você comprou")
    async def inventario(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT item,quantity FROM inventory WHERE guild_id=? AND user_id=? AND quantity>0", (interaction.guild_id,interaction.user.id)); rows = await cur.fetchall()
        desc = "\n".join(f"• {name} × {qty}" for name,qty in rows) if rows else "Seu inventário está vazio. Visite `/loja`."
        await interaction.response.send_message(embed=discord.Embed(title=f"🎒 Inventário de {interaction.user.display_name}", description=desc, color=discord.Color.blurple()), ephemeral=True)

async def setup(bot): await bot.add_cog(Economy(bot))
