"""วนดึงทีละร้าน — ร้านหนึ่งพังต้องไม่ลามไปอีก 14 ร้าน"""

from __future__ import annotations

import os
import random
import sys
import time
import traceback
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterator

from src.adapters.registry import build_adapter
from src.core.config import PROJECT_ROOT, AppConfig, ShopConfig, rel_to_project
from src.core.exporter import export_shop
from src.core.logging_setup import get_logger
from src.core.models import (
    AdapterError,
    ErrorType,
    Order,
    RunResult,
    RunStatus,
)
from src.core.privacy import apply_privacy
from src.core.status_store import StatusStore

log = get_logger()


class AlreadyRunningError(RuntimeError):
    pass


def _pid_alive(pid: int) -> bool:
    """เช็คว่าโปรเซสนี้ยังอยู่ไหม

    ⚠️ ห้ามใช้ os.kill(pid, 0) บน Windows — Python จะเรียก TerminateProcess
    คือ **ฆ่าโปรเซสนั้นทิ้งจริง ๆ** ไม่ใช่แค่เช็ค (ต่างจากบน Linux)
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True          # มีอยู่จริงแต่เราไม่มีสิทธิ์ส่งสัญญาณ


def _lock_owner_pid(lock_path: Path) -> int:
    try:
        return int(lock_path.read_text(encoding="utf-8").split()[0])
    except Exception:                                    # noqa: BLE001
        return -1


@contextmanager
def run_lock(lock_path: Path) -> Iterator[None]:
    """กันรันซ้อน — รอบก่อนยังไม่จบ ห้ามเริ่มรอบใหม่

    ยึด lock คืนได้ 2 กรณี:
      1. โปรเซสเจ้าของ lock ตายไปแล้ว (เช่นถูกสั่งหยุด / เครื่องดับกลางรอบ)
      2. lock เก่าเกิน 6 ชม. (เผื่ออ่าน pid ไม่ได้ หรือ pid ถูกใช้ซ้ำ)

    ข้อ 1 สำคัญมากสำหรับรอบตี 6 — ถ้าไม่มี ไฟดับกลางรอบทีเดียว
    วันถัดไปจะรันไม่ได้เลยจนกว่าจะมีคนมาลบไฟล์เอง (เจอจริง 2026-08-04)
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        age = time.time() - lock_path.stat().st_mtime
        owner = _lock_owner_pid(lock_path)

        if not _pid_alive(owner):
            log.warning("stale_lock_taken_over", lock=str(lock_path),
                        dead_pid=owner, age_sec=round(age), reason="เจ้าของ lock ตายแล้ว")
        elif age < 6 * 3600:
            raise AlreadyRunningError(
                f"มีรอบที่กำลังรันอยู่จริง (pid {owner}, lock อายุ {age / 60:.0f} นาที) "
                f"— {lock_path}"
            )
        else:
            log.warning("stale_lock_taken_over", lock=str(lock_path),
                        dead_pid=owner, age_sec=round(age), reason="lock เก่าเกิน 6 ชม.")

    lock_path.write_text(f"{os.getpid()} {datetime.now().isoformat()}", encoding="utf-8")
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


# ⚠️ Playwright ไม่ได้โยน ConnectionError — มันโยน Error ของตัวเองที่มีข้อความ
#    net::ERR_* อยู่ข้างใน ถ้าไม่ดักด้วยข้อความจะกลายเป็น UNKNOWN ซึ่งอยู่นอก RETRYABLE
#    แล้วรอบตี 6 จะไม่ลองซ้ำให้ ทั้งที่เน็ตสะดุดแป๊บเดียวก็ผ่าน (เจอ 2 ครั้งใน 2026-08-04)
_NET_MARKERS = (
    "err_connection", "err_name_not_resolved", "err_internet_disconnected",
    "err_network_changed", "err_proxy", "err_address_unreachable",
    "err_socket_not_connected", "net::err_timed_out",
)


def _classify(exc: Exception) -> tuple[ErrorType, str]:
    if isinstance(exc, AdapterError):
        return exc.error_type, exc.message

    text = str(exc).lower()
    if any(k in text for k in _NET_MARKERS):
        return ErrorType.NETWORK, f"เน็ตสะดุด: {exc}"

    if isinstance(exc, TimeoutError):
        return ErrorType.TIMEOUT, str(exc) or "หมดเวลารอ"
    if isinstance(exc, (ConnectionError, OSError)):
        return ErrorType.NETWORK, str(exc)
    if isinstance(exc, (ValueError, KeyError, TypeError)):
        return ErrorType.PARSE_ERROR, f"{type(exc).__name__}: {exc}"
    return ErrorType.UNKNOWN, f"{type(exc).__name__}: {exc}"


def date_range(cfg: AppConfig, run_date: date) -> tuple[date, date]:
    """ช่วงวันที่ที่จะดึงในรอบนี้

    lookback_days=1 → ดึงเฉพาะ 'เมื่อวาน' (ข้อมูลของวันที่ปิดแล้วเท่านั้น)
    ดึงของ 'วันนี้' ไม่ได้เพราะวันยังไม่จบ ยอดจะไม่ครบ
    """
    date_to = run_date - timedelta(days=1)
    date_from = date_to - timedelta(days=cfg.settings.fetch.lookback_days - 1)
    return date_from, date_to


class Runner:
    def __init__(self, cfg: AppConfig, store: StatusStore) -> None:
        self.cfg = cfg
        self.store = store

    def run_shop(self, shop: ShopConfig, run_id: str, run_date: date) -> RunResult:
        started = datetime.now()
        run_date_s = run_date.isoformat()
        result = RunResult(
            run_id=run_id,
            run_date=run_date_s,
            shop_id=shop.shop_id,
            platform=shop.platform,
            shop_name=shop.display_name,
            status=RunStatus.RUNNING,
            started_at=started,
        )

        if not shop.enabled:
            # ปิดไว้เอง ≠ พัง — ต้องเป็นสีเทาไม่ใช่สีแดง ไม่งั้นสีแดงจะเฝือ
            result.status = RunStatus.SKIPPED
            result.finished_at = datetime.now()
            result.duration_sec = 0.0
            result.error_message = shop.skip_reason or "ปิดไว้ใน shops.yaml"
            self.store.upsert(result)
            log.info("shop_skipped", shop_id=shop.shop_id, reason=result.error_message)
            return result

        # เขียน RUNNING ทันที — ถ้าโปรเซสตายกลางคัน แถวนี้จะค้างให้ Dashboard จับได้
        self.store.upsert(result)

        date_from, date_to = date_range(self.cfg, run_date)
        backoff = self.cfg.settings.retry.backoff_seconds
        adapter = None

        try:
            adapter = build_adapter(shop, self.cfg.settings)
            empty_note: str | None = None

            try:
                orders = self._fetch_with_retry(adapter, shop, date_from, date_to, backoff, result)
            except AdapterError as exc:
                if exc.error_type is not ErrorType.EMPTY_RESULT:
                    raise
                # "วันนั้นไม่มีออเดอร์" ไม่ใช่ความพัง — ร้านเล็กมีสิทธิ์ขายไม่ได้เลยสักชิ้น
                # ให้เป็นเหลือง (PARTIAL) ไม่ใช่แดง แล้วยังออกไฟล์เปล่าให้ครบ 15 ไฟล์
                # จะได้แยกออกจาก 'ดึงไม่สำเร็จ' ซึ่งต้องลงมือแก้
                orders = []
                empty_note = exc.message
                log.warning("shop_empty", shop_id=shop.shop_id, msg=exc.message)

            orders = apply_privacy(orders, self.cfg.settings.privacy.include_pii)

            out_path = export_shop(
                orders,
                shop_id=shop.shop_id,
                platform=shop.platform,
                shop_name=shop.display_name,
                run_date=run_date_s,
                date_from=date_from.isoformat(),
                date_to=date_to.isoformat(),
                output_dir=PROJECT_ROOT / self.cfg.settings.paths.output_dir,
                archive_dir=PROJECT_ROOT / self.cfg.settings.paths.archive_dir,
                status="PARTIAL" if empty_note else "SUCCESS",
                notes=empty_note,
            )

            if empty_note:
                result.status = RunStatus.PARTIAL
                result.error_type = ErrorType.EMPTY_RESULT
                result.error_message = empty_note
            else:
                result.status = RunStatus.SUCCESS
            result.orders_fetched = len({o.order_id for o in orders})
            result.rows_written = len(orders)
            result.output_file = rel_to_project(out_path)
            log.info(
                "shop_done",
                shop_id=shop.shop_id,
                orders=result.orders_fetched,
                rows=result.rows_written,
            )

        except Exception as exc:                       # noqa: BLE001 — ตั้งใจจับทุกอย่าง
            error_type, message = _classify(exc)
            result.status = RunStatus.FAILED
            result.error_type = error_type
            result.error_message = message
            result.error_detail = traceback.format_exc()
            log.error("shop_failed", shop_id=shop.shop_id, error_type=error_type.value, msg=message)

        finally:
            if adapter is not None:
                result.api_calls = adapter.api_calls
                result.http_status_last = adapter.http_status_last
                raw = adapter.raw_path(date_to.isoformat())
                if raw.exists():
                    result.raw_file = rel_to_project(raw)
                adapter.close()

            result.finished_at = datetime.now()
            result.duration_sec = round((result.finished_at - started).total_seconds(), 2)
            self.store.upsert(result)

        return result

    def _fetch_with_retry(
        self,
        adapter,
        shop: ShopConfig,
        date_from: date,
        date_to: date,
        backoff: list[float],
        result: RunResult,
    ) -> list[Order]:
        last_exc: Exception | None = None

        for attempt in range(len(backoff) + 1):
            result.retry_count = attempt
            try:
                adapter.authenticate()
                return adapter.fetch_orders(date_from, date_to)

            except AdapterError as exc:
                last_exc = exc
                # AUTH_* / NO_PERMISSION ยิงซ้ำก็ไม่ผ่าน มีแต่เสี่ยงโดนล็อกบัญชี → fail ทันที
                if not exc.retryable or attempt >= len(backoff):
                    raise
                wait = backoff[attempt]
                log.warning(
                    "retry",
                    shop_id=shop.shop_id,
                    attempt=attempt + 1,
                    wait_sec=wait,
                    error_type=exc.error_type.value,
                )
                time.sleep(wait)

        raise last_exc if last_exc else RuntimeError("retry loop จบแบบไม่ควรเกิด")

    def run_many(self, shops: list[ShopConfig], run_date: date) -> list[RunResult]:
        run_id = f"{run_date.isoformat()}_{uuid.uuid4().hex[:6]}"
        lo, hi = self.cfg.settings.rate_limit.delay_between_shops
        results: list[RunResult] = []

        log.info("run_start", run_id=run_id, run_date=run_date.isoformat(), shops=len(shops))

        for i, shop in enumerate(shops):
            results.append(self.run_shop(shop, run_id, run_date))
            if i < len(shops) - 1:
                # หน่วงสุ่มระหว่างร้าน — จังหวะเป๊ะ ๆ ทุกครั้งดูเป็นบอทชัดเจน
                time.sleep(random.uniform(lo, hi))

        ok = sum(1 for r in results if r.status is RunStatus.SUCCESS)
        log.info("run_finished", run_id=run_id, success=ok, total=len(results))
        return results


def summarize(results: list[RunResult]) -> str:
    """บรรทัดสรุปท้ายรอบ — โผล่ทั้งใน log และบนหน้าจอ"""
    ok = [r for r in results if r.status is RunStatus.SUCCESS]
    failed = [r for r in results if r.status is RunStatus.FAILED]
    skipped = [r for r in results if r.status is RunStatus.SKIPPED]

    parts = [f"สำเร็จ {len(ok)}/{len(results)}"]
    if failed:
        detail = ", ".join(
            f"{r.shop_id} ({r.error_type.value if r.error_type else 'UNKNOWN'})" for r in failed
        )
        parts.append(f"ล้มเหลว {len(failed)}: {detail}")
    if skipped:
        parts.append(f"ข้าม {len(skipped)}: " + ", ".join(r.shop_id for r in skipped))
    return " | ".join(parts)
