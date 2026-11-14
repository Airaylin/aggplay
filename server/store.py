"""SQLite 队列：聚合条目 + 播放状态。"""
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "queue.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    kind TEXT DEFAULT '',
    title TEXT DEFAULT '',
    sub TEXT DEFAULT '',
    ref TEXT NOT NULL,             -- 源内唯一标识（bvid/songId/trackId/URL...）
    status TEXT DEFAULT 'pending', -- pending|playing|played|failed
    created_at REAL,
    played_at REAL
);
CREATE INDEX IF NOT EXISTS idx_items_status ON items(status);
CREATE UNIQUE INDEX IF NOT EXISTS idx_items_played ON items(source, ref)
    WHERE status = 'played';       -- 已听过的不再重复入队
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""


class Store:
    def __init__(self, path: Path = DB_PATH):
        path.parent.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self._lock:
            self.db.executescript(SCHEMA)
            self.db.commit()

    # ---- 队列操作 ----
    def add(self, source: str, ref: str, title: str = "", sub: str = "", kind: str = "") -> int | None:
        """入队（跳过已听过的；pending 中重复的忽略）。返回新条目 id 或 None。"""
        with self._lock:
            if self.db.execute(
                "SELECT 1 FROM items WHERE source=? AND ref=? AND status='played'",
                (source, ref),
            ).fetchone():
                return None
            if self.db.execute(
                "SELECT 1 FROM items WHERE source=? AND ref=? AND status IN ('pending','playing')",
                (source, ref),
            ).fetchone():
                return None
            cur = self.db.execute(
                "INSERT INTO items(source,kind,title,sub,ref,created_at) VALUES(?,?,?,?,?,?)",
                (source, kind, title, sub, ref, time.time()),
            )
            self.db.commit()
            return cur.lastrowid

    def replace_source(self, source: str, rows: list[dict]) -> int:
        """全量刷新某源：未播的删掉按新顺序重插（已听/在播保留）。返回新入队条数。"""
        added = 0
        with self._lock:
            self.db.execute(
                "DELETE FROM items WHERE source=? AND status IN ('pending','failed')", (source,)
            )
            for r in rows:
                if self.db.execute(
                    "SELECT 1 FROM items WHERE source=? AND ref=? AND status='played'",
                    (source, r["ref"]),
                ).fetchone():
                    continue
                self.db.execute(
                    "INSERT OR IGNORE INTO items(source,kind,title,sub,ref,created_at)"
                    " VALUES(?,?,?,?,?,?)",
                    (source, r.get("kind", ""), r.get("title", ""), r.get("sub", ""), r["ref"], time.time()),
                )
                added += 1
            self.db.commit()
        return added

    def list(self, source: str | None = None, statuses: tuple = ("pending", "playing", "failed")) -> list[dict]:
        q = f"SELECT * FROM items WHERE status IN ({','.join('?'*len(statuses))}"
        args = list(statuses)
        if source:
            q += " AND source=?"
            args.append(source)
        q += ") ORDER BY id"
        return [dict(r) for r in self.db.execute(q, args).fetchall()]

    def get(self, item_id: int) -> dict | None:
        r = self.db.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
        return dict(r) if r else None

    def set_status(self, item_id: int, status: str) -> None:
        with self._lock:
            self.db.execute(
                "UPDATE items SET status=?, played_at=? WHERE id=?",
                (status, time.time() if status == "played" else None, item_id),
            )
            self.db.commit()

    def clear(self, what: str, source: str | None = None) -> None:
        with self._lock:
            if what == "played":       # 重置已听（让已听条目可再次入队）
                self.db.execute(
                    "UPDATE items SET status='pending', played_at=NULL "
                    "WHERE status IN ('played','failed')"
                    + (" AND source=?" if source else ""),
                    (source,) if source else (),
                )
            elif what == "all":
                self.db.execute("DELETE FROM items" + (" WHERE source=?" if source else ""),
                                (source,) if source else ())
            elif what == "pending":
                self.db.execute(
                    "DELETE FROM items WHERE status IN ('pending','failed')"
                    + (" AND source=?" if source else ""),
                    (source,) if source else (),
                )
            self.db.commit()

    def counts(self) -> dict:
        out = {}
        for r in self.db.execute("SELECT source, status, COUNT(*) c FROM items GROUP BY source, status"):
            out.setdefault(r["source"], {})[r["status"]] = r["c"]
        return out

    # ---- 杂项 KV ----
    def kv_set(self, key: str, value: str) -> None:
        with self._lock:
            self.db.execute("INSERT OR REPLACE INTO kv(key,value) VALUES(?,?)", (key, value))
            self.db.commit()

    def kv_get(self, key: str, default: str = "") -> str:
        r = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default
