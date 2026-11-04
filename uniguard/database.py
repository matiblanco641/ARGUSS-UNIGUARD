import sqlite3, hashlib, json, time
from .config import settings

def conn():
    c = sqlite3.connect(settings.db_path); c.row_factory = sqlite3.Row; return c

def init():
    with conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS residents(id INTEGER PRIMARY KEY, name TEXT, unit TEXT);
        CREATE TABLE IF NOT EXISTS visits(id INTEGER PRIMARY KEY, unit TEXT, visitor TEXT, status TEXT, ts REAL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, ts REAL, event TEXT, data TEXT, prev TEXT, hash TEXT);
        """)
        if not c.execute("SELECT 1 FROM residents").fetchone():
            c.executemany("INSERT INTO residents(name,unit) VALUES(?,?)",
                [("Lucía Fernández", "1A"), ("Martín Gómez", "2B"), ("Carla Ruiz", "3C")])

def log(event: str, data: dict):
    """Log inmutable: cada fila encadena el hash de la anterior."""
    with conn() as c:
        row = c.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
        prev = row["hash"] if row else "GENESIS"
        ts, payload = time.time(), json.dumps(data, ensure_ascii=False, sort_keys=True)
        h = hashlib.sha256(f"{prev}|{ts}|{event}|{payload}".encode()).hexdigest()
        c.execute("INSERT INTO audit(ts,event,data,prev,hash) VALUES(?,?,?,?,?)", (ts, event, payload, prev, h))

def find_residents(q: str):
    with conn() as c:
        like = f"%{q}%"
        return [dict(r) for r in c.execute("SELECT name,unit FROM residents WHERE name LIKE ? OR unit LIKE ?", (like, like))]

def create_visit(unit: str, visitor: str) -> int:
    with conn() as c:
        cur = c.execute("INSERT INTO visits(unit,visitor,status,ts) VALUES(?,?,?,?)", (unit, visitor, "PENDING", time.time()))
        return cur.lastrowid

def get_visit(vid: int):
    with conn() as c:
        r = c.execute("SELECT * FROM visits WHERE id=?", (vid,)).fetchone()
        return dict(r) if r else None

def set_visit(vid: int, status: str):
    with conn() as c: c.execute("UPDATE visits SET status=? WHERE id=?", (status, vid))
