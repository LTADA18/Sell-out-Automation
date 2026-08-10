r"""ต่ออายุ session ก่อนหมด — เข้าไปแตะหลังบ้านเบา ๆ แล้วเซฟ cookie ชุดใหม่

ทำไมต้องมี (วัดจากของจริง 2026-08-08):
  session ของ TikTok อยู่ได้ประมาณ 24 ชั่วโมง
  รอบรายวันรันเวลาเดิมทุกวัน = ห่างกัน 24 ชม. เป๊ะ → นั่งอยู่บนเส้นแบ่งพอดี
  วันนั้น tiktok_01/03/04/05 session อายุ 23.8-23.9 ชม. → ตายหมด
  ส่วน tiktok_02 อายุ 21 ชม. เพราะเพิ่งต่ออายุเมื่อวานสาย → รอด
  เป็นการโยนหัวก้อยทุกวัน ไม่ใช่ TikTok งอแง

ตัวนี้แตะทุก ๆ 12 ชั่วโมง อายุ session จึงไม่มีวันแตะ 24 ชม.
ผลคือไม่ต้องล็อกอินใหม่ → ไม่ต้องขอ OTP อีก

⚠️ ไม่ดึงข้อมูล ไม่กดปุ่มอะไร แค่เปิดหน้าคำสั่งซื้อแล้วเซฟ cookie
   ใช้ run_lock ตัวเดียวกับรอบดึง จะได้ไม่ชนกัน

    .\.venv\Scripts\python.exe -u scripts\keepalive.py
    .\.venv\Scripts\python.exe -u scripts\keepalive.py --platform tiktok
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.browser_cleanup import close_stale_browsers  # noqa: E402
from src.core.config import load_config                  # noqa: E402
from src.core.logging_setup import get_logger, setup_logging  # noqa: E402
from src.core.models import AdapterError                 # noqa: E402
from src.core.runner import AlreadyRunningError, run_lock  # noqa: E402

log = get_logger()


def session_age_hours(shop) -> float | None:
    f = PROJECT_ROOT / "data" / "sessions" / f"{shop.profile_id}_state.json"
    if not f.exists():
        return None
    return (datetime.now() - datetime.fromtimestamp(f.stat().st_mtime)).total_seconds() / 3600


def touch(shop, settings) -> tuple[bool, str]:
    """เปิดหน้าหลังบ้านแล้วเซฟ session คืน (สำเร็จไหม, ข้อความ)"""
    adapter = build_adapter(shop, settings)
    try:
        page = adapter._open_page(headed=False)
        page.goto(adapter.orders_url, wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        adapter._ensure_logged_in(page, adapter.orders_url)
        adapter._save_session_if_logged_in(page)
        return True, "ต่ออายุแล้ว"
    except AdapterError as exc:
        return False, f"{exc.error_type.value}: {exc.message[:70]}"
    except Exception as exc:                             # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:70]}"
    finally:
        adapter.close()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--platform",
                    help="จำกัดแพลตฟอร์ม คั่นหลายตัวด้วย , เช่น shopee,tiktok "
                         "(ไม่ใส่ = ทุกแพลตฟอร์ม)")
    ap.add_argument("--shop", help="เฉพาะร้านเดียว")
    ap.add_argument("--max-age", type=float, default=8.0,
                    help="แตะเฉพาะร้านที่ session เก่ากว่ากี่ชั่วโมง (ค่าเริ่มต้น 8)")
    ap.add_argument("--daily-at", default="08:30",
                    help="เวลารอบดึงรายวัน — ตัวนี้จะไม่รันช่วงใกล้เวลานั้น")
    ap.add_argument("--guard-min", type=int, default=45,
                    help="ห้ามรันภายในกี่นาทีก่อนรอบดึง (ค่าเริ่มต้น 45)")
    args = ap.parse_args()

    # ⚠️ กันชนกับรอบดึงรายวัน
    #    ถ้าเครื่องหลับตอน 20:00 งานนี้จะค้างไว้แล้ว StartWhenAvailable ตามเก็บ
    #    ทันทีที่เครื่องตื่น ถ้าบังเอิญตื่น 08:29 มันจะคว้า run_lock ไว้
    #    พอ 08:30 รอบดึงจะเจอล็อกแล้วออกทันทีโดยไม่ดึงอะไรเลย — เสียทั้งวัน
    #    (ยังไม่เคยเกิด แต่เป็นไปได้จริง จึงกันไว้ก่อน)
    try:
        hh, mm = (int(x) for x in args.daily_at.split(":"))
        now = datetime.now()
        daily = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        mins_to_daily = (daily - now).total_seconds() / 60
        if 0 <= mins_to_daily <= args.guard_min:
            print(f"อีก {mins_to_daily:.0f} นาทีจะถึงรอบดึง {args.daily_at} — "
                  f"ข้ามรอบนี้ ไม่ไปแย่งล็อก")
            return 0
    except ValueError:
        pass                                             # รูปแบบเวลาเพี้ยน ก็ทำงานต่อตามปกติ

    cfg = load_config()
    setup_logging(PROJECT_ROOT / cfg.settings.paths.logs_dir, "keepalive")

    shops = [s for s in cfg.shops if s.enabled and s.adapter == "playwright"]
    if args.platform:
        want = {p.strip() for p in args.platform.split(",") if p.strip()}
        shops = [s for s in shops if s.platform in want]
    if args.shop:
        shops = [s for s in shops if s.shop_id == args.shop]

    # ร้านที่ใช้โปรไฟล์ร่วมกันแตะครั้งเดียวพอ — session เป็นของบัญชี ไม่ใช่ของร้าน
    seen: set[str] = set()
    todo = []
    for s in shops:
        if s.profile_id in seen:
            continue
        seen.add(s.profile_id)
        age = session_age_hours(s)
        if age is None:
            print(f"  ⬜ {s.shop_id:<11} ยังไม่มี session — ต้องล็อกอินก่อน")
            continue
        if age < args.max_age:
            print(f"  ·  {s.shop_id:<11} อายุ {age:.1f} ชม. ยังใหม่ ข้าม")
            continue
        todo.append((s, age))

    if not todo:
        print("\nไม่มีร้านที่ต้องต่ออายุ")
        return 0

    print(f"\nต้องต่ออายุ {len(todo)} ร้าน")
    closed = close_stale_browsers()
    if closed:
        print(f"  เคลียร์ Chrome ค้าง {closed} process")

    ok = bad = 0
    try:
        with run_lock(PROJECT_ROOT / cfg.settings.paths.lock_file):
            for s, age in todo:
                good, msg = touch(s, cfg.settings)
                mark = "✅" if good else "❌"
                print(f"  {mark} {s.shop_id:<11} (อายุ {age:.1f} ชม.) {msg}", flush=True)
                log.info("keepalive", shop_id=s.shop_id, ok=good,
                         age_hours=round(age, 1), msg=msg)
                ok, bad = ok + good, bad + (not good)
                time.sleep(3)
    except AlreadyRunningError:
        print("มีรอบอื่นรันอยู่ — ข้ามรอบนี้ (ไม่ใช่ความผิดพลาด)")
        return 0

    print(f"\nต่ออายุสำเร็จ {ok} · ไม่สำเร็จ {bad}")
    # ไม่สำเร็จ = ต้องมีคนล็อกอิน แต่ไม่ควรทำให้ตัวตั้งเวลาขึ้นแดงทุกวัน
    # จึงคืน 0 เสมอ แล้วให้ดูรายละเอียดใน log แทน
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
