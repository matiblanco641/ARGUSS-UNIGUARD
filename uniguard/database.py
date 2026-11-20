import sqlite3
import hashlib
import json
import time
import os

from contextlib import contextmanager

from .config import settings


@contextmanager
def conn():
    db_path = settings.db_path

    if db_path != ":memory:":
        directory = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(directory, exist_ok=True)

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row

    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _column_exists(connection, table, column):
    columns = connection.execute(
        f"PRAGMA table_info({table})"
    ).fetchall()

    return any(row["name"] == column for row in columns)


def init():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS residents (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            unit TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS visits (
            id INTEGER PRIMARY KEY,
            unit TEXT,
            visitor TEXT,
            status TEXT,
            ts REAL
        );

        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY,
            ts REAL,
            event TEXT,
            data TEXT,
            prev TEXT,
            hash TEXT
        );
        """)

        if not _column_exists(c, "residents", "password_hash"):
            c.execute(
                "ALTER TABLE residents ADD COLUMN password_hash TEXT"
            )

        if not _column_exists(c, "residents", "face_embedding"):
            c.execute(
                "ALTER TABLE residents ADD COLUMN face_embedding BLOB"
            )

        if not _column_exists(c, "residents", "enabled"):
            c.execute(
                "ALTER TABLE residents ADD COLUMN enabled INTEGER DEFAULT 1"
            )

        if not c.execute(
            "SELECT 1 FROM residents LIMIT 1"
        ).fetchone():
            c.executemany(
                "INSERT INTO residents(name, unit) VALUES(?, ?)",
                [
                    ("Lucía Fernández", "1A"),
                    ("Martín Gómez", "2B"),
                    ("Carla Ruiz", "3C"),
                ],
            )


def log(event: str, data: dict):
    """Registra eventos mediante una cadena de hashes."""
    with conn() as c:
        row = c.execute(
            "SELECT hash FROM audit ORDER BY id DESC LIMIT 1"
        ).fetchone()

        previous_hash = row["hash"] if row else "GENESIS"

        timestamp = time.time()

        payload = json.dumps(
            data,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )

        current_hash = hashlib.sha256(
            f"{previous_hash}|{timestamp}|{event}|{payload}".encode("utf-8")
        ).hexdigest()

        c.execute(
            """
            INSERT INTO audit(ts, event, data, prev, hash)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                event,
                payload,
                previous_hash,
                current_hash,
            ),
        )


def find_residents(q: str):
    with conn() as c:
        like = f"%{q}%"

        rows = c.execute(
            """
            SELECT name, unit
            FROM residents
            WHERE name LIKE ? OR unit LIKE ?
            """,
            (like, like),
        ).fetchall()

        return [dict(row) for row in rows]


def get_face_templates():
    """
    Devuelve residentes habilitados que tienen
    plantilla facial y contraseña configuradas.
    """
    with conn() as c:
        rows = c.execute(
            """
            SELECT id, name, unit, face_embedding
            FROM residents
            WHERE enabled = 1
              AND face_embedding IS NOT NULL
              AND password_hash IS NOT NULL
            """
        ).fetchall()

        return [dict(row) for row in rows]


def get_resident_auth(resident_id: int):
    with conn() as c:
        row = c.execute(
            """
            SELECT id, name, unit, password_hash
            FROM residents
            WHERE id = ? AND enabled = 1
            """,
            (resident_id,),
        ).fetchone()

        return dict(row) if row else None


def create_visit(unit: str, visitor: str) -> int:
    with conn() as c:
        cursor = c.execute(
            """
            INSERT INTO visits(unit, visitor, status, ts)
            VALUES (?, ?, ?, ?)
            """,
            (unit, visitor, "PENDING", time.time()),
        )

        return cursor.lastrowid


def get_visit(visit_id: int):
    with conn() as c:
        row = c.execute(
            "SELECT * FROM visits WHERE id = ?",
            (visit_id,),
        ).fetchone()

        return dict(row) if row else None


def set_visit(visit_id: int, status: str):
    with conn() as c:
        c.execute(
            "UPDATE visits SET status = ? WHERE id = ?",
            (status, visit_id),
        )


def set_visit_if_pending(visit_id: int, status: str) -> bool:
    """
    Actualiza una visita únicamente si sigue pendiente.
    Devuelve True cuando se realizó la actualización.
    """
    with conn() as c:
        cursor = c.execute(
            """
            UPDATE visits
            SET status = ?
            WHERE id = ? AND status = ?
            """,
            (status, visit_id, "PENDING"),
        )

        return cursor.rowcount == 1
