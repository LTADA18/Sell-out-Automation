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
from src.core import mailer                              # noqa: E402
from src.core.browser_cleanup import close_stale_browsers  # noqa: E402
from src.core.config import load_config                  # noqa: E402
from src.core.logging_setup import get_logger, setup_logging  # noqa: E402
from src.core.models import AdapterError                 # noqa: E402
from src.core.busy import busy_reason                      # noqa: E402
from src.core.runner import AlreadyRunningError, run_lock  # noqa: E402

log = get_logger()

# ผู้รับอีเมลเตือน — อยู่ใน config/recipients.yaml กลุ่ม alert
# ⚠️ อ่านตอนใช้จริง ไม่ใช่ตอน import เพราะสคริปต์นี้ทำงานหลักคือต่ออายุ session
#    ซึ่งไม่ควรพังทั้งตัวเพียงเพราะไฟล์รายชื่ออีเมลหาย


def send_login_alert(need_login: list[str], to: str, draft: bool = False) -> None:
    """เตือนทางอีเมลว่ามีร้านต้องล็อกอินเอง

    ⚠️ ทำไมต้องมี — ตัวตรวจเจอปัญหาได้ล่วงหน้าครึ่งวัน แต่เขียนลงล็อกที่ไม่มีใครอ่าน
       2026-08-11 เวลา 20:00 keepalive เจอ 6 ร้านพังแล้วรายงานไว้ในล็อก
       ไม่มีใครเห็น เช้า 2026-08-12 รอบดึงเลยตกไป 6 ร้านเหมือนเดิม
       การตรวจเจอที่ไม่มีใครรู้ ไม่ต่างอะไรกับไม่ได้ตรวจ

    ส่งไม่สำเร็จก็ไม่ทำให้ keepalive ล้ม — งานหลักคือต่ออายุ session
    """
    rows = "".join(
        f"<tr><td style='padding:6px 14px;border:1px solid #ddd'>{sid}</td>"
        f"<td style='padding:6px 14px;border:1px solid #ddd;font-family:Consolas'>"
        f".\\.venv\\Scripts\\python.exe scripts\\login_save.py --shop {sid}</td></tr>"
        for sid in need_login
    )
    html = (
        f"<div style='font-family:Segoe UI,Tahoma'>"
        f"<h3 style='color:#C00000'>ต้องล็อกอินใหม่ {len(need_login)} ร้าน</h3>"
        f"<p>ต่ออายุ session อัตโนมัติไม่สำเร็จ ถ้าไม่ล็อกอินก่อนรอบถัดไป "
        f"ร้านเหล่านี้จะดึงข้อมูลไม่ได้</p>"
        f"<table style='border-collapse:collapse'>"
        f"<tr><th style='padding:6px 14px;border:1px solid #ddd'>ร้าน</th>"
        f"<th style='padding:6px 14px;border:1px solid #ddd'>คำสั่ง</th></tr>"
        f"{rows}</table>"
        f"<p style='color:#666;font-size:12px'>ตอนล็อกอิน ถ้า Chrome ถามว่าจะบันทึก"
        f"รหัสผ่านไหม ให้กดบันทึก ครั้งหน้าระบบจะต่ออายุเองได้โดยไม่ต้องเรียกคน</p>"
        f"<p style='color:#888;font-size:11px'>ส่งอัตโนมัติจาก keepalive · "
        f"{datetime.now():%Y-%m-%d %H:%M}</p></div>"
    )
    try:
        mailer.send(
            subject=f"⚠️ ต้องล็อกอินใหม่ {len(need_login)} ร้าน — {', '.join(need_login)}",
            html=html, to=[t.strip() for t in to.split(",") if t.strip()],
            send_now=not draft,
        )
        print(f"  📧 ส่งอีเมลเตือนไปที่ {to} แล้ว")
        log.info("keepalive_alert_sent", shops=need_login, to=to)
    except Exception as exc:                                   # noqa: BLE001
        print(f"  ⚠️ ส่งอีเมลเตือนไม่สำเร็จ: {type(exc).__name__}: {exc}")
        log.warning("keepalive_alert_failed", err=str(exc)[:200])


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
    ap.add_argument("--alert-to", default=None,
                    help="อีเมลที่จะเตือนเมื่อมีร้านต้องล็อกอินเอง คั่นหลายคนด้วย , "
                         "(ไม่ใส่ = ใช้กลุ่ม alert ใน config/recipients.yaml)")
    ap.add_argument("--no-alert", action="store_true",
                    help="ไม่ต้องส่งอีเมลเตือน (ใช้ตอนทดสอบ)")
    ap.add_argument("--draft-alert", action="store_true",
                    help="เปิดหน้าต่างร่างแทนการส่งจริง ใช้ตรวจหน้าตาอีเมล")
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

    # ⚠️ ต้องเช็คก่อน close_stale_browsers() — ไม่ใช่หลัง
    #    ถ้าปล่อยให้มันไล่ปิด Chrome ของงาน backfill ที่กำลังรัน cookie ในหน่วยความจำ
    #    จะไม่ถูกเขียนลงดิสก์ การล็อกอินหายทั้งดุ้น แล้วต้องให้คนมานั่งล็อกอินใหม่
    busy = busy_reason()
    if busy:
        print(f"มีงานยาวใช้เบราว์เซอร์อยู่ — ข้ามรอบนี้ (ไม่ใช่ความผิดพลาด)\n  {busy}")
        log.info("keepalive_skipped_busy", reason=busy)
        return 0

    print(f"\nต้องต่ออายุ {len(todo)} ร้าน")
    closed = close_stale_browsers()
    if closed:
        print(f"  เคลียร์ Chrome ค้าง {closed} process")

    ok = bad = 0
    need_login: list[str] = []
    try:
        with run_lock(PROJECT_ROOT / cfg.settings.paths.lock_file):
            for s, age in todo:
                good, msg = touch(s, cfg.settings)
                mark = "✅" if good else "❌"
                print(f"  {mark} {s.shop_id:<11} (อายุ {age:.1f} ชม.) {msg}", flush=True)
                log.info("keepalive", shop_id=s.shop_id, ok=good,
                         age_hours=round(age, 1), msg=msg)
                if not good and "AUTH" in msg:
                    need_login.append(s.shop_id)
                ok, bad = ok + good, bad + (not good)
                time.sleep(3)
    except AlreadyRunningError:
        print("มีรอบอื่นรันอยู่ — ข้ามรอบนี้ (ไม่ใช่ความผิดพลาด)")
        return 0

    print(f"\nต่ออายุสำเร็จ {ok} · ไม่สำเร็จ {bad}")
    if need_login:
        # บอกให้ชัดว่าต้องทำอะไรกับร้านไหน ไม่ใช่แค่ตัวเลข
        # ถ้าเห็นตั้งแต่กลางวัน จะได้ล็อกอินตอนสะดวก ไม่ใช่มารู้ตอน 08:30
        print(f"\n⚠️  ต้องล็อกอินเอง {len(need_login)} ร้าน: {', '.join(need_login)}")
        for sid in need_login:
            print(f"    .\\.venv\\Scripts\\python.exe scripts\\login_save.py --shop {sid}")
        # ⚠️ พิมพ์ลงจอกับล็อกอย่างเดียวไม่พอ ไม่มีใครเปิดอ่าน — ต้องเด้งหาคน
        if not args.no_alert:
            to = args.alert_to
            if not to:
                from src.core.recipients import RecipientsError, alert_to as _alert_to
                try:
                    to = ",".join(_alert_to())
                except RecipientsError as exc:
                    # งานหลัก (ต่ออายุ session) ทำเสร็จไปแล้ว ตัวเตือนพัง
                    # ไม่ควรลากให้ทั้งรอบขึ้นแดง แต่ต้องดังพอให้เห็นใน log
                    log.error("alert_recipients_missing", err=str(exc)[:200])
                    print(f"\n⚠️  ส่งเมลเตือนไม่ได้ — {exc}")
                    to = ""
            if to:
                send_login_alert(need_login, to, draft=args.draft_alert)
    # ไม่สำเร็จ = ต้องมีคนล็อกอิน แต่ไม่ควรทำให้ตัวตั้งเวลาขึ้นแดงทุกวัน
    # จึงคืน 0 เสมอ แล้วให้ดูรายละเอียดใน log แทน
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
