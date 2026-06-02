import sqlite3
import os
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fallguard.db")
SNAPSHOTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "fall_snapshots")


def get_db_path():
    return os.path.abspath(DB_PATH)


def ensure_snapshots_dir():
    os.makedirs(SNAPSHOTS_DIR, exist_ok=True)


def get_connection():
    """Get a SQLite connection with WAL mode for better concurrent reads."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    ensure_snapshots_dir()
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            google_id TEXT UNIQUE NOT NULL,
            email TEXT NOT NULL,
            name TEXT,
            picture TEXT,
            created_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS pairings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER REFERENCES users(id),
            system_id TEXT NOT NULL,
            pair_code TEXT,
            is_active INTEGER DEFAULT 0,
            created_at REAL NOT NULL,
            paired_at REAL,
            expires_at REAL
        );

        CREATE TABLE IF NOT EXISTS fall_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            camera_ip TEXT NOT NULL,
            camera_name TEXT,
            snapshot_filename TEXT,
            detected_at REAL NOT NULL,
            duration_seconds REAL,
            created_at REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_fall_events_detected_at ON fall_events(detected_at);
        CREATE INDEX IF NOT EXISTS idx_pairings_user_id ON pairings(user_id);
        CREATE INDEX IF NOT EXISTS idx_pairings_pair_code ON pairings(pair_code);
    """)

    conn.commit()
    conn.close()
    print(f"✅ Database initialized at {get_db_path()}")


# ── User CRUD ──

def upsert_user(google_id: str, email: str, name: str, picture: str) -> dict:
    """Create or update a user from Google OAuth data. Returns user dict."""
    conn = get_connection()
    cursor = conn.cursor()
    now = time.time()

    cursor.execute("SELECT * FROM users WHERE google_id = ?", (google_id,))
    existing = cursor.fetchone()

    if existing:
        cursor.execute(
            "UPDATE users SET email=?, name=?, picture=? WHERE google_id=?",
            (email, name, picture, google_id)
        )
        user_id = existing["id"]
    else:
        cursor.execute(
            "INSERT INTO users (google_id, email, name, picture, created_at) VALUES (?, ?, ?, ?, ?)",
            (google_id, email, name, picture, now)
        )
        user_id = cursor.lastrowid

    conn.commit()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    user = dict(cursor.fetchone())
    conn.close()
    return user


def get_user_by_id(user_id: int) -> dict | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


# ── Pairing CRUD ──

def create_pairing(system_id: str, pair_code: str, expires_in_seconds: int = 600) -> dict:
    """Create a new pairing entry (not yet linked to a user)."""
    conn = get_connection()
    cursor = conn.cursor()
    now = time.time()

    cursor.execute(
        "INSERT INTO pairings (system_id, pair_code, is_active, created_at, expires_at) VALUES (?, ?, 0, ?, ?)",
        (system_id, pair_code, now, now + expires_in_seconds)
    )
    pairing_id = cursor.lastrowid
    conn.commit()

    cursor.execute("SELECT * FROM pairings WHERE id = ?", (pairing_id,))
    pairing = dict(cursor.fetchone())
    conn.close()
    return pairing


def activate_pairing(pair_code: str, user_id: int) -> dict | None:
    """Activate a pairing by code — link it to a user."""
    conn = get_connection()
    cursor = conn.cursor()
    now = time.time()

    cursor.execute(
        "SELECT * FROM pairings WHERE pair_code = ? AND is_active = 0 AND expires_at > ?",
        (pair_code, now)
    )
    pairing = cursor.fetchone()

    if not pairing:
        conn.close()
        return None

    cursor.execute(
        "UPDATE pairings SET user_id = ?, is_active = 1, paired_at = ? WHERE id = ?",
        (user_id, now, pairing["id"])
    )
    conn.commit()

    cursor.execute("SELECT * FROM pairings WHERE id = ?", (pairing["id"],))
    result = dict(cursor.fetchone())
    conn.close()
    return result


def get_active_pairing(user_id: int) -> dict | None:
    """Check if a user has an active pairing."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM pairings WHERE user_id = ? AND is_active = 1 ORDER BY paired_at DESC LIMIT 1",
        (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None


def deactivate_pairing(user_id: int):
    """Deactivate all pairings for a user."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE pairings SET is_active = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


# ── Fall Events CRUD ──

def insert_fall_event(camera_ip: str, camera_name: str, snapshot_filename: str,
                      detected_at: float, duration_seconds: float = 0.0) -> dict:
    """Insert a new fall event."""
    conn = get_connection()
    cursor = conn.cursor()
    now = time.time()

    cursor.execute(
        """INSERT INTO fall_events 
           (camera_ip, camera_name, snapshot_filename, detected_at, duration_seconds, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (camera_ip, camera_name, snapshot_filename, detected_at, duration_seconds, now)
    )
    event_id = cursor.lastrowid
    conn.commit()

    cursor.execute("SELECT * FROM fall_events WHERE id = ?", (event_id,))
    event = dict(cursor.fetchone())
    conn.close()
    return event


def get_fall_events(limit: int = 50, offset: int = 0,
                    camera_ip: str | None = None,
                    date_from: float | None = None,
                    date_to: float | None = None) -> list[dict]:
    """Query fall events with optional filters."""
    conn = get_connection()
    cursor = conn.cursor()

    query = "SELECT * FROM fall_events WHERE 1=1"
    params: list = []

    if camera_ip:
        query += " AND camera_ip = ?"
        params.append(camera_ip)
    if date_from:
        query += " AND detected_at >= ?"
        params.append(date_from)
    if date_to:
        query += " AND detected_at <= ?"
        params.append(date_to)

    query += " ORDER BY detected_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_fall_event_by_id(event_id: int) -> dict | None:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM fall_events WHERE id = ?", (event_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None
