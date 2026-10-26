import sqlite3
import time
from typing import Optional, List, Dict, Any, Tuple

DB_PATH = "bot_database.db"

FREE_COOLDOWN_SECONDS = 3 * 3600  # 3 часа = 10800 секунд

CHAT_REWARD_STARS = 3
REFERRAL_REWARD_STARS = 2

def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_connection() as conn:
        cursor = conn.cursor()

        # Пользователи с колонкой причины бана
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                balance INTEGER DEFAULT 0,
                referrer_id INTEGER DEFAULT NULL,
                chat_reward_claimed INTEGER DEFAULT 0,
                is_banned INTEGER DEFAULT 0,
                ban_reason TEXT DEFAULT NULL
            )
        """)

        # Миграция ban_reason, если база данных уже существовала
        cursor.execute("PRAGMA table_info(users)")
        cols = [r["name"] for r in cursor.fetchall()]
        if "ban_reason" not in cols:
            cursor.execute("ALTER TABLE users ADD COLUMN ban_reason TEXT DEFAULT NULL")

        # Попытки для игр с таймером 3 часа
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_games (
                user_id INTEGER,
                game_key TEXT,
                last_free_time INTEGER DEFAULT 0,
                extra_attempts INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, game_key)
            )
        """)

        cursor.execute("PRAGMA table_info(user_games)")
        columns = [row["name"] for row in cursor.fetchall()]
        if "last_free_time" not in columns:
            cursor.execute("ALTER TABLE user_games ADD COLUMN last_free_time INTEGER DEFAULT 0")

        # Награжденные чаты
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS rewarded_chats (
                chat_id INTEGER PRIMARY KEY,
                user_id INTEGER
            )
        """)

        # Обязательные подписки на каналы
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS required_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_username TEXT NOT NULL,
                title TEXT NOT NULL,
                check_type TEXT NOT NULL,
                is_active INTEGER DEFAULT 1
            )
        """)

        # Таблица заявок на призы
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS prize_claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                game_title TEXT NOT NULL,
                prize_name TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL
            )
        """)

        conn.commit()

# --- Пользователи ---
def add_user(user_id: int, username: Optional[str], referrer_id: Optional[int] = None) -> bool:
    clean_username = username.lstrip("@").lower() if username else None
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row is None:
            cursor.execute(
                "INSERT INTO users (user_id, username, balance, referrer_id, chat_reward_claimed, is_banned, ban_reason) VALUES (?, ?, 0, ?, 0, 0, NULL)",
                (user_id, clean_username, referrer_id)
            )
            conn.commit()
            return True
        else:
            cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (clean_username, user_id))
            conn.commit()
            return False

def get_user(user_id: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return cursor.fetchone()

def get_user_by_query(query: str):
    query = query.strip().lstrip("@")
    with get_connection() as conn:
        cursor = conn.cursor()
        if query.isdigit():
            cursor.execute("SELECT * FROM users WHERE user_id = ?", (int(query),))
            row = cursor.fetchone()
            if row:
                return row
        cursor.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (query,))
        return cursor.fetchone()

def get_all_users() -> List[sqlite3.Row]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users")
        return cursor.fetchall()

def set_ban_status(user_id: int, is_banned: bool, reason: Optional[str] = None):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET is_banned = ?, ban_reason = ? WHERE user_id = ?",
            (1 if is_banned else 0, reason if is_banned else None, user_id)
        )
        conn.commit()

def get_ban_info(user_id: int) -> Tuple[bool, Optional[str]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT is_banned, ban_reason FROM users WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        if row and row["is_banned"]:
            return True, row["ban_reason"] or "Причина не указана"
        return False, None

def update_balance(user_id: int, amount: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET balance = MAX(0, balance + ?) WHERE user_id = ?", (amount, user_id))
        conn.commit()

def get_referrals_count(user_id: int) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
        row = cursor.fetchone()
        return row[0] if row else 0

# --- Игры и таймер 3 часа ---
def get_free_cooldown_left(user_id: int, game_key: str) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT last_free_time FROM user_games WHERE user_id = ? AND game_key = ?", (user_id, game_key))
        row = cursor.fetchone()
        if row is None:
            return 0
        last_time = row["last_free_time"] or 0
        elapsed = int(time.time()) - last_time
        if elapsed >= FREE_COOLDOWN_SECONDS:
            return 0
        return FREE_COOLDOWN_SECONDS - elapsed

def set_free_game_used_now(user_id: int, game_key: str):
    now = int(time.time())
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM user_games WHERE user_id = ? AND game_key = ?", (user_id, game_key))
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO user_games (user_id, game_key, last_free_time, extra_attempts) VALUES (?, ?, ?, 0)", (user_id, game_key, now))
        else:
            cursor.execute("UPDATE user_games SET last_free_time = ? WHERE user_id = ? AND game_key = ?", (now, user_id, game_key))
        conn.commit()

def get_extra_attempts(user_id: int, game_key: str) -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT extra_attempts FROM user_games WHERE user_id = ? AND game_key = ?", (user_id, game_key))
        row = cursor.fetchone()
        if row is None:
            cursor.execute("INSERT INTO user_games (user_id, game_key, last_free_time, extra_attempts) VALUES (?, ?, 0, 0)", (user_id, game_key))
            conn.commit()
            return 0
        return int(row["extra_attempts"])

def add_extra_attempts(user_id: int, game_key: str, count: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT extra_attempts FROM user_games WHERE user_id = ? AND game_key = ?", (user_id, game_key))
        row = cursor.fetchone()
        if row is None:
            cursor.execute("INSERT INTO user_games (user_id, game_key, last_free_time, extra_attempts) VALUES (?, ?, 0, ?)", (user_id, game_key, max(0, count)))
        else:
            cursor.execute("UPDATE user_games SET extra_attempts = MAX(0, extra_attempts + ?) WHERE user_id = ? AND game_key = ?", (count, user_id, game_key))
        conn.commit()

# --- Чаты ---
def can_claim_chat_reward(user_id: int, chat_id: int) -> bool:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT chat_reward_claimed FROM users WHERE user_id = ?", (user_id,))
        user_row = cursor.fetchone()
        if not user_row or user_row["chat_reward_claimed"] == 1:
            return False

        cursor.execute("SELECT chat_id FROM rewarded_chats WHERE chat_id = ?", (chat_id,))
        if cursor.fetchone() is not None:
            return False

        return True

def claim_chat_reward(user_id: int, chat_id: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET chat_reward_claimed = 1, balance = balance + ? WHERE user_id = ?", (CHAT_REWARD_STARS, user_id))
        cursor.execute("INSERT INTO rewarded_chats (chat_id, user_id) VALUES (?, ?)", (chat_id, user_id))
        conn.commit()

# --- Каналы для ОП ---
def add_channel(channel_username: str, title: str, check_type: str):
    clean_username = channel_username.strip().lstrip("@")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO required_channels (channel_username, title, check_type, is_active) VALUES (?, ?, ?, 1)",
            (clean_username, title, check_type)
        )
        conn.commit()

def get_channels(check_type: Optional[str] = None, active_only: bool = True) -> List[sqlite3.Row]:
    with get_connection() as conn:
        cursor = conn.cursor()
        query = "SELECT * FROM required_channels WHERE 1=1"
        params = []
        if check_type:
            query += " AND check_type = ?"
            params.append(check_type)
        if active_only:
            query += " AND is_active = 1"
        cursor.execute(query, params)
        return cursor.fetchall()

def toggle_channel_status(channel_pk: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE required_channels SET is_active = CASE WHEN is_active = 1 THEN 0 ELSE 1 END WHERE id = ?", (channel_pk,))
        conn.commit()

def delete_channel(channel_pk: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM required_channels WHERE id = ?", (channel_pk,))
        conn.commit()

# --- Заявки на призы ---
def create_prize_claim(user_id: int, username: Optional[str], game_title: str, prize_name: str) -> int:
    clean_username = username.lstrip("@") if username else "Без юзернейма"
    now_str = time.strftime("%Y-%m-%d %H:%M:%S")
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO prize_claims (user_id, username, game_title, prize_name, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
            (user_id, clean_username, game_title, prize_name, now_str)
        )
        conn.commit()
        return cursor.lastrowid

def get_claim_by_id(claim_id: int):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM prize_claims WHERE id = ?", (claim_id,))
        return cursor.fetchone()

def get_user_claims(user_id: int) -> List[sqlite3.Row]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM prize_claims WHERE user_id = ? ORDER BY id DESC", (user_id,))
        return cursor.fetchall()

def update_claim_status(claim_id: int, status: str):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE prize_claims SET status = ? WHERE id = ?", (status, claim_id))
        conn.commit()

def get_claims_page(page: int = 1, per_page: int = 8) -> Tuple[List[sqlite3.Row], int]:
    offset = (page - 1) * per_page
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM prize_claims")
        total = cursor.fetchone()[0]
        cursor.execute("SELECT * FROM prize_claims ORDER BY id DESC LIMIT ? OFFSET ?", (per_page, offset))
        return cursor.fetchall(), total

def get_pending_claims_count() -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM prize_claims WHERE status = 'pending'")
        return cursor.fetchone()[0]

def clear_all_claims():
    """Полностью удаляет все заявки и сбрасывает нумерацию в #1."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM prize_claims")
        cursor.execute("DELETE FROM sqlite_sequence WHERE name = 'prize_claims'")
        conn.commit()

def get_total_users_count() -> int:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        row = cursor.fetchone()
        return row[0] if row else 0