# -*- coding: utf-8 -*-
import sqlite3
import logging
from datetime import datetime, timedelta

DB_NAME = "database.db"
log = logging.getLogger("bot_logger")


def normalize_city(city_name: str) -> str:
    if not city_name or city_name == "Все города" or city_name == "🌍 Все города":
        return "Все города"
    return " ".join(city_name.strip().split()).capitalize()


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            city TEXT,
            is_blocked INTEGER DEFAULT 0
        )
    """)

    try:
        cursor.execute("SELECT is_blocked FROM users LIMIT 1")
    except sqlite3.OperationalError:
        log.info("[БАЗА ДАННЫХ] Колонка is_blocked не найдена. Добавление...")
        cursor.execute("ALTER TABLE users ADD COLUMN is_blocked INTEGER DEFAULT 0")
        conn.commit()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            ptype TEXT,
            category TEXT,
            specialty TEXT,
            city TEXT,
            text TEXT,
            created_at TEXT,
            expires_at TEXT,
            active INTEGER DEFAULT 1
        )
    """)

    try:
        cursor.execute("SELECT active FROM posts LIMIT 1")
    except sqlite3.OperationalError:
        log.info("[БАЗА ДАННЫХ] Колонка active не найдена. Добавление...")
        cursor.execute("ALTER TABLE posts ADD COLUMN active INTEGER DEFAULT 1")
        conn.commit()

    # Безопасное добавление колонки expires_at для существующих баз данных
    try:
        cursor.execute("SELECT expires_at FROM posts LIMIT 1")
    except sqlite3.OperationalError:
        log.info("[БАЗА ДАННЫХ] Колонка expires_at не найдена. Добавление...")
        cursor.execute("ALTER TABLE posts ADD COLUMN expires_at TEXT")
        conn.commit()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hidden_posts (
            user_id INTEGER,
            post_id INTEGER,
            PRIMARY KEY (user_id, post_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            city TEXT,
            category TEXT,
            specialty TEXT,
            ptype TEXT
        )
    """)

    # Безопасное обновление старой базы данных: добавляем колонку ptype, если ее нет
    try:
        cursor.execute("SELECT ptype FROM subscriptions LIMIT 1")
    except sqlite3.OperationalError:
        log.info("[БАЗА ДАННЫХ] Колонка ptype не найдена в subscriptions. Добавление...")
        cursor.execute("ALTER TABLE subscriptions ADD COLUMN ptype TEXT DEFAULT 'vacancy'")
        conn.commit()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            user_id INTEGER PRIMARY KEY,
            name TEXT UNIQUE COLLATE NOCASE,
            description TEXT
        )
    """)

    conn.commit()
    conn.close()


def upsert_user(user_id: int, username: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, username, city) VALUES (?, ?, '')
        ON CONFLICT(user_id) DO UPDATE SET username = excluded.username
    """, (user_id, username))
    conn.commit()
    conn.close()


def is_blocked(user_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return bool(row and row[0])


def block_user(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_blocked = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def unblock_user(user_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT is_blocked FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    if row and row[0] == 1:
        cursor.execute("UPDATE users SET is_blocked = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        conn.close()
        return True
    conn.close()
    return False


def get_city(user_id: int) -> str:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT city FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None


def set_city(user_id: int, city: str):
    norm_city = normalize_city(city)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET city = ? WHERE user_id = ?", (norm_city, user_id))
    conn.commit()
    conn.close()


def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE is_blocked = 0")
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]


def check_spam_and_limits(user_id: int, text: str) -> str:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now = datetime.now()
    one_day_ago = (now - timedelta(days=1)).isoformat()

    cursor.execute("SELECT COUNT(*) FROM posts WHERE user_id = ? AND created_at > ?", (user_id, one_day_ago))
    if cursor.fetchone()[0] >= 5:
        conn.close()
        return "⚠️ Превышен лимит: не более 5 публикаций в сутки."

    two_hours_ago = (now - timedelta(hours=2)).isoformat()
    cursor.execute("SELECT text FROM posts WHERE user_id = ? AND created_at > ?", (user_id, two_hours_ago))
    for (old_text,) in cursor.fetchall():
        if old_text.strip() == text.strip():
            conn.close()
            return "⚠️ Защита от спама: вы уже отправляли такое объявление недавно."

    conn.close()
    return None


def add_post(user_id: int, username: str, ptype: str, category: str, specialty: str, city: str, text: str) -> int:
    norm_city = normalize_city(city)
    now = datetime.now()
    expires = now + timedelta(days=30)

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO posts (user_id, username, ptype, category, specialty, city, text, created_at, expires_at, active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (user_id, username, ptype, category, specialty, norm_city, text, now.isoformat(), expires.isoformat()))
    post_id = cursor.lastrowid
    conn.commit()
    conn.close()
    log.info(f"[ОБЪЯВЛЕНИЕ] Пользователь {user_id} создал пост #{post_id}")
    return post_id


def get_post(post_id: int):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    cursor.execute("SELECT * FROM posts WHERE id = ? AND active = 1 AND expires_at > ?", (post_id, now_str))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def delete_post(post_id: int, user_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE posts SET active = 0 WHERE id = ? AND user_id = ?", (post_id, user_id))
    changes = conn.total_changes
    conn.commit()
    conn.close()
    if changes > 0:
        log.info(f"[УДАЛЕНИЕ] Пост #{post_id} удален автором {user_id}")
        return True
    return False


def get_my_posts(user_id: int, ptype: str):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    cursor.execute("SELECT * FROM posts WHERE user_id = ? AND ptype = ? AND active = 1 AND expires_at > ?",
                   (user_id, ptype, now_str))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_feed(ptype: str, city: str, category: str, specialty: str, exclude_user_id: int):
    norm_city = normalize_city(city)
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()

    query = "SELECT * FROM posts WHERE ptype = ? AND category = ? AND specialty = ? AND active = 1 AND expires_at > ? AND user_id != ?"
    params = [ptype, category, specialty, now_str, exclude_user_id]

    if norm_city != "Все города":
        query += " AND (city = ? OR city = 'Все города')"
        params.append(norm_city)

    query += " AND id NOT IN (SELECT post_id FROM hidden_posts WHERE user_id = ?) ORDER BY id DESC"
    params.append(exclude_user_id)

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def hide_post(user_id: int, post_id: int):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO hidden_posts (user_id, post_id) VALUES (?, ?)", (user_id, post_id))
    conn.commit()
    conn.close()
    log.info(f"[СКРЫТИЕ] Пост #{post_id} скрыт для {user_id}")


def add_subscription(user_id: int, city: str, category: str, specialty: str, ptype: str = "vacancy"):
    norm_city = normalize_city(city)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT INTO subscriptions (user_id, city, category, specialty, ptype) VALUES (?, ?, ?, ?, ?)",
                   (user_id, norm_city, category, specialty, ptype))
    conn.commit()
    conn.close()


def get_matching_subscriptions(city: str, category: str, specialty: str, ptype: str = "vacancy"):
    norm_city = normalize_city(city)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT DISTINCT user_id FROM subscriptions WHERE (city = ? OR city = 'Все города') AND category = ? AND specialty = ? AND ptype = ?",
        (norm_city, category, specialty, ptype))
    rows = cursor.fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_user_subscriptions(user_id: int, city: str, ptype: str):
    norm_city = normalize_city(city)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT category, specialty FROM subscriptions WHERE user_id = ? AND (city = ? OR city = 'Все города') AND ptype = ?",
        (user_id, norm_city, ptype)
    )
    rows = cursor.fetchall()
    conn.close()
    return rows


def remove_subscription(user_id: int, city: str, category: str, specialty: str, ptype: str):
    norm_city = normalize_city(city)
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM subscriptions WHERE user_id = ? AND (city = ? OR city = 'Все города') AND category = ? AND specialty = ? AND ptype = ?",
        (user_id, norm_city, category, specialty, ptype)
    )
    conn.commit()
    conn.close()


def get_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    cursor.execute("SELECT COUNT(*) FROM users")
    u = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM posts WHERE ptype = 'vacancy' AND active = 1 AND expires_at > ?", (now_str,))
    v = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM posts WHERE ptype = 'resume' AND active = 1 AND expires_at > ?", (now_str,))
    r = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1")
    b = cursor.fetchone()[0]
    conn.close()
    return {"users": u, "vacancies": v, "resumes": r, "blocked": b}


# --- ФУНКЦИИ ПРОФИЛЯ ---

def get_profile(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM profiles WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def get_profile_by_name(name: str):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM profiles WHERE name = ?", (name,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def is_name_taken(name: str, exclude_user_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM profiles WHERE name = ? AND user_id != ?", (name, exclude_user_id))
    row = cursor.fetchone()
    conn.close()
    return bool(row)


def upsert_profile(user_id: int, name: str, description: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO profiles (user_id, name, description) VALUES (?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET name = excluded.name, description = excluded.description
    """, (user_id, name, description))
    conn.commit()
    conn.close()


def update_profile_field(user_id: int, field: str, value: str):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    if field == "name":
        cursor.execute("UPDATE profiles SET name = ? WHERE user_id = ?", (value, user_id))
    elif field == "description":
        cursor.execute("UPDATE profiles SET description = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()


def get_user_all_active_posts(user_id: int):
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    cursor.execute("SELECT * FROM posts WHERE user_id = ? AND active = 1 AND expires_at > ? ORDER BY id DESC",
                   (user_id, now_str))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]
