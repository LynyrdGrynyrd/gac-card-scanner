import sqlite3, json, time, os
from . import paths
DB = paths.data("cards.db")
def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row
    c.execute("""CREATE TABLE IF NOT EXISTS cards(id INTEGER PRIMARY KEY, created REAL, status TEXT DEFAULT 'pending',
      engine TEXT, raw_text TEXT, fields TEXT, image TEXT, reviewer TEXT, note TEXT, decided REAL)""")
    return c
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
