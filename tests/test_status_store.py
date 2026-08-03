from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.core.models import ErrorType, RunResult, RunStatus
from src.core.status_store import StatusStore


@pytest.fixture
def store(tmp_path):
    with StatusStore(tmp_path / "status.db") as s:
        yield s


def make_result(**kw) -> RunResult:
    base = dict(
        run_id="r1", run_date="2026-08-03", shop_id="lazada_01",
        platform="lazada", shop_name="ร้านทดสอบ",
        status=RunStatus.SUCCESS, started_at=datetime(2026, 8, 3, 6, 0),
    )
    base.update(kw)
    return RunResult(**base)


def test_upsert_replaces_running_row(store):
    """เขียน RUNNING ตอนเริ่ม แล้วทับด้วยผลจริงตอนจบ — ต้องได้แถวเดียว"""
    store.upsert(make_result(status=RunStatus.RUNNING))
    store.upsert(make_result(status=RunStatus.SUCCESS, orders_fetched=42))

    rows = store.by_date("2026-08-03")
    assert len(rows) == 1
    assert rows[0]["status"] == "SUCCESS"
    assert rows[0]["orders_fetched"] == 42


def test_stale_running_becomes_failed(store):
    """process ตายกลางคัน = ไม่มีใครมาปิดแถว ต้องไม่ค้างโชว์ 'กำลังทำงาน' ตลอดไป"""
    store.upsert(make_result(
        status=RunStatus.RUNNING,
        started_at=datetime.now() - timedelta(hours=3),
    ))
    assert store.mark_stale_running(older_than_minutes=60) == 1

    row = store.by_date("2026-08-03")[0]
    assert row["status"] == "FAILED"
    assert row["error_type"] == ErrorType.UNKNOWN.value


def test_fresh_running_is_left_alone(store):
    """รอบที่กำลังรันอยู่จริงต้องไม่ถูกจับเป็นตาย"""
    store.upsert(make_result(status=RunStatus.RUNNING, started_at=datetime.now()))
    assert store.mark_stale_running(older_than_minutes=60) == 0
    assert store.by_date("2026-08-03")[0]["status"] == "RUNNING"


def test_by_date_returns_latest_run_per_shop(store):
    """กดปุ่ม Re-run แล้วต้องเห็นผลรอบใหม่ ไม่ใช่รอบเช้า"""
    store.upsert(make_result(run_id="morning", status=RunStatus.FAILED))
    store.upsert(make_result(run_id="rerun", status=RunStatus.SUCCESS, orders_fetched=7))

    rows = store.by_date("2026-08-03")
    assert len(rows) == 1
    assert rows[0]["status"] == "SUCCESS"
    assert rows[0]["orders_fetched"] == 7


def test_history_covers_multiple_days(store):
    for day in ("2026-08-01", "2026-08-02", "2026-08-03"):
        store.upsert(make_result(run_id=day, run_date=day))
    assert len({r["run_date"] for r in store.history(days=30)}) == 3


def test_has_successful_run_detects_missed_day(store):
    """ใช้ตอนเปิดเครื่อง: ถ้าเมื่อวาน 06:00 เครื่องปิด ต้องรู้ว่ายังไม่ได้รัน"""
    store.upsert(make_result(status=RunStatus.SUCCESS))
    assert store.has_successful_run("2026-08-03") is True
    assert store.has_successful_run("2026-08-04") is False


def test_failed_only_day_counts_as_not_run(store):
    store.upsert(make_result(run_date="2026-08-04", status=RunStatus.FAILED))
    assert store.has_successful_run("2026-08-04") is False


def test_error_detail_is_persisted(store):
    """หน้า Error Detail ต้องมี stack trace เต็มให้กด"""
    store.upsert(make_result(
        status=RunStatus.FAILED,
        error_type=ErrorType.PARSE_ERROR,
        error_message="คอลัมน์ orderNumber หายไป",
        error_detail="Traceback (most recent call last):\n  ...",
    ))
    row = store.by_date("2026-08-03")[0]
    assert row["error_type"] == "PARSE_ERROR"
    assert "Traceback" in row["error_detail"]
