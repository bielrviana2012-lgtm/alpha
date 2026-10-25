"""Camada SQLite assíncrona do Rei Dado."""
import os
import aiosqlite
from pathlib import Path

# Railway: monte um Volume (ex.: /data) e defina DB_PATH=/data/alpha.db.
# Sem variável de ambiente, mantém o caminho padrão para desenvolvimento local.
DB_PATH = Path(
    os.getenv("DB_PATH", str(Path(__file__).parent / "data" / "alpha.db"))
).expanduser()

# Conta especial com moedas infinitas, identificada pelo ID do Discord.
INFINITE_USER_ID = 1340377944215785502

def has_infinite_coins(user_id: int) -> bool:
    return int(user_id) == INFINITE_USER_ID

def format_coins(user_id: int, amount: int) -> str:
    return "∞" if has_infinite_coins(user_id) else f"{amount:,}"

async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
            wallet INTEGER NOT NULL DEFAULT 0, bank INTEGER NOT NULL DEFAULT 0,
            xp INTEGER NOT NULL DEFAULT 0, level INTEGER NOT NULL DEFAULT 0,
            last_daily TEXT, last_work TEXT,
            PRIMARY KEY (guild_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS wallet_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            old_wallet INTEGER NOT NULL,
            new_wallet INTEGER NOT NULL,
            delta INTEGER NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TRIGGER IF NOT EXISTS audit_wallet_changes
        AFTER UPDATE OF wallet ON users
        WHEN OLD.wallet != NEW.wallet
        BEGIN
            INSERT INTO wallet_transactions
                (guild_id, user_id, old_wallet, new_wallet, delta)
            VALUES
                (NEW.guild_id, NEW.user_id, OLD.wallet, NEW.wallet, NEW.wallet - OLD.wallet);
        END;
        CREATE TABLE IF NOT EXISTS warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL, moderator_id INTEGER NOT NULL,
            reason TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL, text TEXT NOT NULL, message_id INTEGER, channel_id INTEGER,
            status TEXT NOT NULL DEFAULT 'Em análise', created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS suggestion_votes (
            suggestion_id INTEGER NOT NULL, user_id INTEGER NOT NULL, vote INTEGER NOT NULL,
            PRIMARY KEY(suggestion_id,user_id)
        );
        CREATE TABLE IF NOT EXISTS tickets (
            channel_id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'open'
        );
        CREATE TABLE IF NOT EXISTS inventory (
            guild_id INTEGER NOT NULL, user_id INTEGER NOT NULL, item TEXT NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(guild_id,user_id,item)
        );
        ''')
        await db.commit()

async def ensure_user(guild_id: int, user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users(guild_id,user_id) VALUES(?,?)", (guild_id,user_id))
        await db.commit()

async def get_user(guild_id: int, user_id: int):
    await ensure_user(guild_id, user_id)
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE guild_id=? AND user_id=?", (guild_id,user_id))
        return dict(await cur.fetchone())
