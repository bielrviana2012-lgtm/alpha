import random
from datetime import date
import discord
from discord import app_commands
from discord.ext import commands
import aiosqlite
from database import DB_PATH, get_user, ensure_user
import config
from cogs.ui_v2 import make_v2_panel

DEFAULT_SHOP = {"Caixa Misteriosa": 250, "Amuleto Alpha": 500, "Título VIP (cosmético)": 1000}

class Economy(commands.Cog):
    def __init__(self, bot): self.bot = bot

    async def cog_load(self):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS shop_products (
                    guild_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    price INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, name)
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS shop_guilds (
                    guild_id INTEGER PRIMARY KEY
                )
            """)
            await db.commit()

    async def ensure_shop(self, guild_id: int):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT 1 FROM shop_guilds WHERE guild_id=?", (guild_id,))
            initialized = await cur.fetchone()
            if not initialized:
                await db.executemany(
                    "INSERT OR IGNORE INTO shop_products(guild_id,name,price) VALUES(?,?,?)",
                    [(guild_id, name, price) for name, price in DEFAULT_SHOP.items()],
                )
                await db.execute("INSERT OR IGNORE INTO shop_guilds(guild_id) VALUES(?)", (guild_id,))
                await db.commit()

    async def get_products(self, guild_id: int):
        await self.ensure_shop(guild_id)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT name, price FROM shop_products WHERE guild_id=? ORDER BY name",
                (guild_id,),
            )
            return await cur.fetchall()

    @app_commands.command(name="saldo", description="Veja sua carteira e seu banco")
    async def saldo(self, interaction: discord.Interaction, membro: discord.Member | None = None):
        target = membro or interaction.user
        row = await get_user(interaction.guild_id, target.id)
        panel = make_v2_panel(
            f"💰 Economia de {target.display_name}",
            f"Confira o patrimônio de {target.mention}.",
            sections=[
                ("👛 Carteira", f"{row['wallet']:,} {config.CURRENCY_NAME}"),
                ("🏦 Banco", f"{row['bank']:,} {config.CURRENCY_NAME}"),
                ("💎 Patrimônio total", f"{row['wallet']+row['bank']:,} {config.CURRENCY_NAME}"),
            ],
        )
        await interaction.response.send_message(view=panel)

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
        await interaction.response.send_message(view=make_v2_panel(
            "🎁 Recompensa diária recebida",
            f"Você recebeu **{reward} {config.CURRENCY_NAME}**!",
        ))

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
        await interaction.response.send_message(view=make_v2_panel(
            "🏆 Ranking Alpha",
            "\n".join(lines),
            footer=f"Sr.Alpha • Ranking dos 10 membros mais ricos",
        ))

    @app_commands.command(name="produto_criar", description="Adiciona um produto personalizado à loja")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(nome="Nome do produto", preco="Preço em Alpha Coins")
    async def produto_criar(
        self,
        interaction: discord.Interaction,
        nome: app_commands.Range[str, 1, 100],
        preco: app_commands.Range[int, 1, 1000000000],
    ):
        if not interaction.guild_id:
            return await interaction.response.send_message("Use este comando dentro do servidor.", ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Apenas administradores podem gerenciar a loja.", ephemeral=True)
        nome = nome.strip()
        if not nome:
            return await interaction.response.send_message("O nome não pode ficar vazio.", ephemeral=True)
        await self.ensure_shop(interaction.guild_id)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "INSERT OR IGNORE INTO shop_products(guild_id,name,price) VALUES(?,?,?)",
                (interaction.guild_id, nome, preco),
            )
            await db.commit()
            if cur.rowcount == 0:
                return await interaction.response.send_message("Já existe um produto com esse nome. Escolha outro nome.", ephemeral=True)
        await interaction.response.send_message(f"✅ Produto **{nome}** adicionado à loja por **{preco:,} {config.CURRENCY_NAME}**.")

    @app_commands.command(name="produto_excluir", description="Remove um produto da loja")
    @app_commands.default_permissions(administrator=True)
    @app_commands.describe(nome="Nome do produto a remover")
    async def produto_excluir(self, interaction: discord.Interaction, nome: str):
        if not interaction.guild_id:
            return await interaction.response.send_message("Use este comando dentro do servidor.", ephemeral=True)
        if not interaction.user.guild_permissions.administrator:
            return await interaction.response.send_message("❌ Apenas administradores podem gerenciar a loja.", ephemeral=True)
        await self.ensure_shop(interaction.guild_id)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "DELETE FROM shop_products WHERE guild_id=? AND name=? COLLATE NOCASE",
                (interaction.guild_id, nome.strip()),
            )
            await db.commit()
        if cur.rowcount == 0:
            return await interaction.response.send_message("Não encontrei esse produto na loja.", ephemeral=True)
        await interaction.response.send_message(f"🗑️ Produto **{nome.strip()}** removido da loja.")

    @produto_excluir.autocomplete("nome")
    async def produto_excluir_autocomplete(self, interaction: discord.Interaction, current: str):
        if not interaction.guild_id:
            return []
        await self.ensure_shop(interaction.guild_id)
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute(
                "SELECT name FROM shop_products WHERE guild_id=? AND name LIKE ? ORDER BY name LIMIT 25",
                (interaction.guild_id, f"%{current}%"),
            )
            return [app_commands.Choice(name=row[0][:100], value=row[0]) for row in await cur.fetchall()]

    @app_commands.command(name="loja", description="Veja os itens disponíveis na loja")
    async def loja(self, interaction: discord.Interaction):
        products = await self.get_products(interaction.guild_id)
        text = "\\n".join(f"**{item}** — {price:,} {config.CURRENCY_NAME}" for item, price in products)
        await interaction.response.send_message(view=make_v2_panel(
            "🛍️ Loja Alpha",
            (text or "A loja está vazia. A equipe pode adicionar produtos usando `/produto_criar`.") +
            "\\n\\nCompre usando `/comprar`. Itens cosméticos não concedem permissões reais.",
        ), ephemeral=True)

    @app_commands.command(name="comprar", description="Compre um item da loja")
    @app_commands.describe(item="Produto que deseja comprar")
    async def comprar(self, interaction: discord.Interaction, item: str):
        products = await self.get_products(interaction.guild_id)
        match = next(((name, price) for name, price in products if name.casefold() == item.casefold()), None)
        if match is None:
            return await interaction.response.send_message("Esse produto não está mais disponível na loja.", ephemeral=True)
        product_name, price = match
        row = await get_user(interaction.guild_id, interaction.user.id)
        if row['wallet'] < price:
            return await interaction.response.send_message("Você não tem moedas suficientes na carteira.", ephemeral=True)
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE users SET wallet=wallet-? WHERE guild_id=? AND user_id=?", (price, interaction.guild_id, interaction.user.id))
            await db.execute("INSERT INTO inventory(guild_id,user_id,item,quantity) VALUES(?,?,?,1) ON CONFLICT(guild_id,user_id,item) DO UPDATE SET quantity=quantity+1", (interaction.guild_id, interaction.user.id, product_name))
            await db.commit()
        await interaction.response.send_message(f"🛍️ Compra concluída: **{product_name}**! Confira `/inventario`.")

    @comprar.autocomplete("item")
    async def comprar_autocomplete(self, interaction: discord.Interaction, current: str):
        if not interaction.guild_id:
            return []
        products = await self.get_products(interaction.guild_id)
        return [
            app_commands.Choice(name=name[:100], value=name)
            for name, price in products if current.casefold() in name.casefold()
        ][:25]

    @app_commands.command(name="inventario", description="Veja os itens que você comprou")
    async def inventario(self, interaction: discord.Interaction):
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT item,quantity FROM inventory WHERE guild_id=? AND user_id=? AND quantity>0", (interaction.guild_id,interaction.user.id)); rows = await cur.fetchall()
        desc = "\n".join(f"• {name} × {qty}" for name,qty in rows) if rows else "Seu inventário está vazio. Visite `/loja`."
        await interaction.response.send_message(view=make_v2_panel(
            f"🎒 Inventário de {interaction.user.display_name}",
            desc,
        ), ephemeral=True)

async def setup(bot): await bot.add_cog(Economy(bot))
