"""Private single-instance lifecycle journal. Never automatically retry ambiguous writes."""
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS notifications (
                po TEXT PRIMARY KEY, state TEXT NOT NULL, revision INTEGER NOT NULL,
                draft_id TEXT, thread_id TEXT, sent_id TEXT)""")
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.row_factory = sqlite3.Row
            with db:
                yield db
        finally:
            db.close()

    def get(self, po):
        with self.connect() as db:
            row = db.execute("SELECT * FROM notifications WHERE po=?", (po,)).fetchone()
            return dict(row) if row else {"po": po, "state": "new", "revision": 0}

    def known_thread(self, thread_id):
        with self.connect() as db:
            return bool(db.execute("SELECT 1 FROM notifications WHERE thread_id=?", (thread_id,)).fetchone())

    def claim(self, po, revision):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT OR IGNORE INTO notifications(po,state,revision) VALUES(?, 'new', 0)", (po,))
            row = dict(db.execute("SELECT * FROM notifications WHERE po=?", (po,)).fetchone())
            if row["revision"] != revision or row["state"] not in ("new", "draft"):
                raise ValueError("This notification changed or is locked. Reopen it; check Gmail if its outcome is uncertain.")
            db.execute("UPDATE notifications SET state='saving',revision=revision+1 WHERE po=?", (po,))
            return row

    def set(self, po, state, **values):
        if set(values) - {"draft_id", "thread_id", "sent_id"}:
            raise ValueError("Invalid journal field")
        with self.connect() as db:
            assignments = ", ".join(f"{k}=?" for k in values)
            db.execute("UPDATE notifications SET state=?" + (", " + assignments if values else "") +
                       " WHERE po=?", (state, *values.values(), po))
        return self.get(po)
