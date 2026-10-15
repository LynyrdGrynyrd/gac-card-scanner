import sqlite3, json, time, os, threading
from . import paths
DB = os.environ.get("GAC_DB") or paths.data("cards.db")   # audit 2026-10: GAC_DB was honoured by backup.py only
BUSY_MS = int(os.environ.get("GAC_DB_BUSY_MS", "30000"))   # wait this long for another writer instead of failing at once
CARDS_SQL = """CREATE TABLE IF NOT EXISTS cards(id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, status TEXT DEFAULT 'pending',
      engine TEXT, raw_text TEXT, fields TEXT, image TEXT, reviewer TEXT, note TEXT, decided REAL)"""
_READY: set = set(); _INIT_LOCK = threading.RLock(); _TX = threading.local()
def connect(path=None):
    """A connection with the settings every caller needs (row dicts, a busy wait). No schema work."""
    c = sqlite3.connect(path or DB, timeout=BUSY_MS / 1000); c.row_factory = sqlite3.Row
    c.execute(f"PRAGMA busy_timeout={BUSY_MS}")
    return c
def once(key, init):
    """Run init(conn) once per database file and key (schema set-up), not on every connection."""
    k = (os.path.abspath(DB), key)
    if k in _READY: return
    with _INIT_LOCK:
        if k in _READY: return
        t = getattr(_TX, "conn", None)
        if t is not None:   # inside tx(): a second connection would wait on our own write lock; use the tx's connection
            init(t._c); _READY.add(k); return
        c = connect()
        try:
            init(c); c.commit()
        finally: c.close()
        _READY.add(k)
def _init_cards(c):
    if c.execute("PRAGMA journal_mode").fetchone()[0].lower() != "wal":
        try: c.execute("PRAGMA journal_mode=WAL")   # readers no longer block the writer (and vice versa)
        except sqlite3.OperationalError: pass       # e.g. a file system without shared memory: stay on the default
    row = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='cards'").fetchone()
    if row and "AUTOINCREMENT" not in row[0].upper(): _autoincrement_cards(c)
    c.execute(CARDS_SQL)
def _autoincrement_cards(c):
    """Audit 2026-10 P0-6: card ids must never be reused after a permanent delete (history rows, past exports and undo
    snapshots refer to them). Rebuild the table with AUTOINCREMENT and start the counter above every id ever seen."""
    seen = [c.execute("SELECT COALESCE(MAX(id),0) FROM cards").fetchone()[0]]
    for t in ("card_meta", "card_history"):
        if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone():
            seen.append(c.execute(f"SELECT COALESCE(MAX(card_id),0) FROM {t}").fetchone()[0] or 0)
    c.execute("BEGIN IMMEDIATE")
    try:
        c.execute(CARDS_SQL.replace("IF NOT EXISTS cards(", "cards_new("))
        c.execute("INSERT INTO cards_new(id,created,status,engine,raw_text,fields,image,reviewer,note,decided) "
                  "SELECT id,created,status,engine,raw_text,fields,image,reviewer,note,decided FROM cards")
        c.execute("DROP TABLE cards"); c.execute("ALTER TABLE cards_new RENAME TO cards")
        c.execute("DELETE FROM sqlite_sequence WHERE name='cards'")
        c.execute("INSERT INTO sqlite_sequence(name,seq) VALUES('cards',?)", (max(seen),))
        c.execute("COMMIT")
    except Exception:
        c.execute("ROLLBACK"); raise
class _TxConn:
    """The connection of an open tx(): `with db() as c:` inside it neither commits nor closes (the tx does that)."""
    def __init__(self, c): self._c = c
    def __getattr__(self, k): return getattr(self._c, k)
    def __enter__(self): return self
    def __exit__(self, *exc): return False
    def commit(self): pass
    def close(self): pass
import contextlib
@contextlib.contextmanager
def tx():
    """Audit 2026-10 P2: one transaction for a whole request. Every db() call in this thread (store, ui, auth helpers) uses
    the same connection until the block ends; it commits at the end and rolls back if an exception escapes, so a save
    that fails half-way no longer leaves half its writes behind (a merge target updated, the source not rejected).
    Nested tx() blocks join the outer one."""
    if getattr(_TX, "conn", None) is not None:
        yield _TX.conn; return
    once("cards", _init_cards)
    c = connect(); c.execute("BEGIN IMMEDIATE"); _TX.conn = _TxConn(c)
    try:
        yield _TX.conn
        c.commit()
    except BaseException:
        c.rollback(); raise
    finally:
        _TX.conn = None; c.close()
def db():
    if getattr(_TX, "conn", None) is not None: return _TX.conn
    once("cards", _init_cards)
    return connect()
def add(engine, raw, fields, image):
    with db() as c:
        return c.execute("INSERT INTO cards(created,engine,raw_text,fields,image) VALUES(?,?,?,?,?)",
                         (time.time(), engine, raw, json.dumps(fields), image)).lastrowid
def get(i):
    r = db().execute("SELECT * FROM cards WHERE id=?", (i,)).fetchone()
    return _row(r) if r else None
def _row(r):
    d = dict(r); d["fields"] = json.loads(d["fields"]); return d
def all_(status=None):
    q = "SELECT * FROM cards" + (" WHERE status=?" if status else "") + " ORDER BY id DESC"
    return [_row(r) for r in db().execute(q, (status,) if status else ())]
def update(i, fields=None, status=None, reviewer=None, note=None):
    with db() as c:
        if fields is not None: c.execute("UPDATE cards SET fields=? WHERE id=?", (json.dumps(fields), i))
        if status: c.execute("UPDATE cards SET status=?,reviewer=?,note=?,decided=? WHERE id=?",
                             (status, reviewer, note, time.time(), i))
