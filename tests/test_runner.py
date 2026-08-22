from __future__ import annotations

from datetime import date
from pathlib import Path

import os

import pytest

from src.core.models import ErrorType, RunStatus
from src.core.runner import AlreadyRunningError, Runner, date_range, run_lock, summarize
from src.core.status_store import StatusStore


@pytest.fixture
def runner(app_config, tmp_path):
    with StatusStore(Path(app_config.settings.paths.db_path)) as store:
        yield Runner(app_config, store), store


def _run(runner_pair, shop_id: str):
    runner, store = runner_pair
    shop = runner.cfg.shops[0].model_copy(update={"shop_id": shop_id})
    return runner.run_shop(shop, run_id="test", run_date=date(2026, 8, 3)), store


def test_auth_expired_fails_fast_without_retry(runner):
    """cookie หมดอายุแล้วยิงซ้ำก็ไม่ผ่าน มีแต่เสี่ยงโดนล็อกบัญชี"""
    result, _ = _run(runner, "shopee_03")
    assert result.status is RunStatus.FAILED
    assert result.error_type is ErrorType.AUTH_EXPIRED
    assert result.retry_count == 0, "ห้าม retry error กลุ่ม auth"


def test_no_permission_fails_fast(runner):
    result, _ = _run(runner, "lazada_05")
    assert result.status is RunStatus.FAILED
    assert result.error_type is ErrorType.NO_PERMISSION
    assert result.retry_count == 0


def test_rate_limited_recovers_after_backoff(runner):
    """โดน rate limit 2 ครั้งแรกแล้วผ่าน — ต้องได้ผลสำเร็จ ไม่ใช่ยอมแพ้"""
    result, _ = _run(runner, "lazada_02")
    assert result.status is RunStatus.SUCCESS
    assert result.retry_count == 2
    assert result.orders_fetched > 0


def test_timeout_gives_up_after_max_attempts(runner):
    result, _ = _run(runner, "tiktok_05")
    assert result.status is RunStatus.FAILED
    assert result.error_type is ErrorType.TIMEOUT
    assert result.retry_count == 3, "ต้องลองครบตามจำนวน backoff ก่อนยอมแพ้"


def test_empty_result_is_partial_not_failed(runner):
    """ไม่มีออเดอร์ ≠ ดึงไม่สำเร็จ — ต้องเป็นเหลือง และยังต้องได้ไฟล์"""
    result, _ = _run(runner, "tiktok_04")
    assert result.status is RunStatus.PARTIAL
    assert result.error_type is ErrorType.EMPTY_RESULT
    assert result.orders_fetched == 0
    assert result.output_file is not None, "ต้องยังออกไฟล์ Excel เปล่าให้ครบชุด"


def test_disabled_shop_is_skipped_not_failed(runner):
    """ร้านที่ปิดไว้ต้องเป็นสีเทา ไม่ใช่แดง ไม่งั้นสีแดงจะเฝือจนมองข้ามของจริง"""
    r, store = runner
    shop = r.cfg.shops[0].model_copy(
        update={"enabled": False, "skip_reason": "ยังไม่มีสิทธิ์ดูคำสั่งซื้อ"}
    )
    result = r.run_shop(shop, run_id="test", run_date=date(2026, 8, 3))
    assert result.status is RunStatus.SKIPPED
    assert "สิทธิ์" in (result.error_message or "")


def test_one_broken_shop_does_not_stop_the_rest(app_config, tmp_path):
    """หัวใจของ fail isolation — ร้านพัง 1 ร้านต้องไม่ทำให้ที่เหลือหยุด"""
    ids = ["shopee_01", "shopee_03", "shopee_04"]     # ตัวกลางพังแน่นอน
    shops = [app_config.shops[0].model_copy(update={"shop_id": i}) for i in ids]

    with StatusStore(Path(app_config.settings.paths.db_path)) as store:
        results = Runner(app_config, store).run_many(shops, date(2026, 8, 3))

    assert [r.status for r in results] == [
        RunStatus.SUCCESS, RunStatus.FAILED, RunStatus.SUCCESS,
    ]


def test_date_range_pulls_yesterday_only(app_config):
    """lookback_days=1 = ดึงเฉพาะเมื่อวาน (วันนี้ยังไม่จบ ยอดจะไม่ครบ)"""
    d_from, d_to = date_range(app_config, date(2026, 8, 3))
    assert d_from == d_to == date(2026, 8, 2)


def test_date_range_respects_lookback(app_config):
    app_config.settings.fetch.lookback_days = 7
    d_from, d_to = date_range(app_config, date(2026, 8, 3))
    assert d_to == date(2026, 8, 2)
    assert d_from == date(2026, 7, 27)


def test_lock_blocks_second_run(tmp_path):
    lock = tmp_path / "run.lock"
    with run_lock(lock):
        with pytest.raises(AlreadyRunningError):
            with run_lock(lock):
                pass
    assert not lock.exists(), "lock ต้องถูกลบเมื่อจบรอบ"


def test_lock_waits_instead_of_giving_up(tmp_path):
    """รอบดึงต้องรอล็อกได้ ไม่ใช่ยอมแพ้ทันที

    เจอจริง 2026-08-22: เครื่องตื่นสายตอน 08:58 รอบดึงกับ KeepAlive จึงยิง
    พร้อมกัน KeepAlive คว้าล็อกไปก่อน รอบดึงเจอล็อกไม่ว่างแล้วออกทันที
    ผลคือทั้งวันไม่ได้ดึงข้อมูลเลยสักร้าน ทั้งที่ตัวที่ถือล็อกจะปล่อยเองในไม่กี่นาที
    """
    import threading
    import time as _time

    lock = tmp_path / "run.lock"
    lock.write_text(f"{os.getpid()} holder", encoding="utf-8")   # เจ้าของยังมีชีวิต

    threading.Timer(1.0, lambda: lock.unlink(missing_ok=True)).start()

    started = _time.time()
    with run_lock(lock, wait_min=1):
        waited = _time.time() - started
    assert waited >= 1.0, "ต้องรอจริง ไม่ใช่ยึดทับตอนเจ้าของยังถืออยู่"


def test_lock_without_wait_still_fails_fast(tmp_path):
    """ค่าเริ่มต้นต้องไม่รอ — backfill ที่คนสั่งเองต้องรู้ทันทีว่ามีรอบอื่นรันอยู่
    ไม่ใช่ค้างเงียบให้คนนั่งงง
    """
    lock = tmp_path / "run.lock"
    lock.write_text(f"{os.getpid()} holder", encoding="utf-8")
    with pytest.raises(AlreadyRunningError):
        with run_lock(lock):
            pass


def test_lock_released_even_when_run_crashes(tmp_path):
    lock = tmp_path / "run.lock"
    with pytest.raises(ValueError):
        with run_lock(lock):
            raise ValueError("พังกลางรอบ")
    assert not lock.exists(), "ถ้าไม่ปลด lock ระบบจะค้างถาวรจนกว่าจะมีคนมาลบเอง"


def test_summary_line_lists_failed_shops(runner):
    r, _ = runner
    shops = [r.cfg.shops[0].model_copy(update={"shop_id": i})
             for i in ["shopee_01", "shopee_03"]]
    line = summarize(r.run_many(shops, date(2026, 8, 3)))
    assert "สำเร็จ 1/2" in line
    assert "shopee_03 (AUTH_EXPIRED)" in line
