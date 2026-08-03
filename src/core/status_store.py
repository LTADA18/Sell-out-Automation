"""run_log บน SQLite — แหล่งข้อมูลเดียวของ Dashboard (Dashboard ห้ามยิงเว็บเอง)"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from src.core.models import ErrorType, RunResult, RunStatus

SCHEMA = """
CREATE TABLE IF NOT EXISTS run_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id           TEXT NOT NULL,
    run_date         TEXT NOT NULL,
    shop_id          TEXT NOT NULL,
    platform         TEXT NOT NULL,
    shop_name        TEXT NOT NULL,
    status           TEXT NOT NULL,
    started_at       TEXT NOT NULL,
    finished_at      TEXT,
    error_type       TEXT,
    error_message    TEXT,
    error_detail     TEXT,
    retry_count      INTEGER NOT NULL DEFAULT 0,
    orders_fetched   INTEGER NOT NULL DEFAULT 0,
    rows_written     INTEGER NOT NULL DEFAULT 0,
    duration_sec     REAL,
    output_file      TEXT,
    raw_file         TEXT,
    api_calls        INTEGER NOT NULL DEFAULT 0,
    http_status_last INTEGER,
    UNIQUE (run_id, shop_id)
);
CREATE INDEX IF NOT EXISTS idx_run_date ON run_log (run_date);
CREATE INDEX IF NOT EXISTS idx_shop_date ON run_log (shop_id, run_date);
"""

_COLUMNS = (
    "run_id", "run_date", "shop_id", "platform", "shop_name", "status",
    "started_at", "finished_at", "error_type", "error_message", "error_detail",
    "retry_count", "orders_fetched", "rows_written", "duration_sec",
    "output_file", "raw_file", "api_calls", "http_status_last",
)


def _to_row(r: RunResult) -> dict:
    d = r.model_dump()
    for k in ("started_at", "finished_at"):
        d[k] = d[k].isoformat() if d[k] else None
    d["status"] = r.status.value
    d["error_type"] = r.error_type.value if r.error_type else None
    return {k: d[k] for k in _COLUMNS}


class StatusStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> StatusStore:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ── เขียน ────────────────────────────────────────────────

    def upsert(self, result: RunResult) -> None:
        """เขียนทับด้วยคู่ (run_id, shop_id) — เรียกตอนเริ่ม (RUNNING) แล้วเรียกซ้ำตอนจบ

        เขียน RUNNING ทันทีที่เริ่มร้านนั้น เพื่อให้ถ้า process ตายกลางคัน
        แถวจะค้างอยู่ที่ RUNNING แล้ว mark_stale_running() จับได้ว่าไม่ปกติ
        """
        row = _to_row(result)
        cols = ", ".join(row)
        placeholders = ", ".join(f":{c}" for c in row)
        updates = ", ".join(f"{c}=excluded.{c}" for c in row if c not in ("run_id", "shop_id"))
        self._conn.execute(
            f"INSERT INTO run_log ({cols}) VALUES ({placeholders}) "
            f"ON CONFLICT (run_id, shop_id) DO UPDATE SET {updates}",
            row,
        )
        self._conn.commit()

    def mark_stale_running(self, older_than_minutes: int = 60) -> int:
        """แถวที่ค้าง RUNNING เกินเวลา = process ตายไปแล้ว ไม่มีใครมาปิดให้

        ถ้าไม่ทำขั้นนี้ Dashboard จะโชว์ 'กำลังทำงาน' ค้างตลอดไป
        แล้วคุณจะไม่รู้เลยว่าจริง ๆ มันตายไปตั้งแต่เมื่อวาน
        """
        cutoff = (datetime.now() - timedelta(minutes=older_than_minutes)).isoformat()
        cur = self._conn.execute(
            "UPDATE run_log SET status=?, error_type=?, error_message=? "
            "WHERE status=? AND started_at < ?",
            (
                RunStatus.FAILED.value,
                ErrorType.UNKNOWN.value,
                "ค้างสถานะ RUNNING เกินกำหนด — โปรเซสน่าจะถูกปิด/เครื่องดับกลางรอบ",
                RunStatus.RUNNING.value,
                cutoff,
            ),
        )
        self._conn.commit()
        return cur.rowcount

    # ── อ่าน (Dashboard ใช้) ─────────────────────────────────

    def by_date(self, run_date: str) -> list[dict]:
        """สถานะล่าสุดของแต่ละร้านในวันนั้น (รันซ้ำหลายรอบ = เอารอบล่าสุด)"""
        cur = self._conn.execute(
            "SELECT * FROM run_log WHERE run_date=? "
            "AND id IN (SELECT MAX(id) FROM run_log WHERE run_date=? GROUP BY shop_id) "
            "ORDER BY platform, shop_id",
            (run_date, run_date),
        )
        return [dict(r) for r in cur.fetchall()]

    def history(self, days: int = 30) -> list[dict]:
        """ข้อมูลสำหรับ heatmap ย้อนหลัง"""
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        cur = self._conn.execute(
            "SELECT * FROM run_log WHERE run_date >= ? "
            "AND id IN (SELECT MAX(id) FROM run_log WHERE run_date >= ? GROUP BY shop_id, run_date) "
            "ORDER BY run_date DESC, platform, shop_id",
            (since, since),
        )
        return [dict(r) for r in cur.fetchall()]

    def shop_runs(self, shop_id: str, limit: int = 50) -> list[dict]:
        cur = self._conn.execute(
            "SELECT * FROM run_log WHERE shop_id=? ORDER BY id DESC LIMIT ?",
            (shop_id, limit),
        )
        return [dict(r) for r in cur.fetchall()]

    def latest_run_date(self) -> str | None:
        cur = self._conn.execute("SELECT MAX(run_date) AS d FROM run_log")
        row = cur.fetchone()
        return row["d"] if row and row["d"] else None

    def has_successful_run(self, run_date: str) -> bool:
        """ใช้ตอนเปิดเครื่อง: วันนี้รันไปหรือยัง ถ้ายังให้รันย้อนหลังให้"""
        cur = self._conn.execute(
            "SELECT COUNT(*) AS n FROM run_log WHERE run_date=? AND status IN (?, ?)",
            (run_date, RunStatus.SUCCESS.value, RunStatus.PARTIAL.value),
        )
        return cur.fetchone()["n"] > 0
