r"""ดึง Shopee เป็น "ช่วงวันที่ครั้งเดียวต่อร้าน" แล้วแยกเป็นไฟล์รายวันในเครื่อง

⚠️ ทำไมต้องมี:
   Shopee สั่ง export เป็นช่วงวันที่ได้ (งานย้อนหลัง 7 เดือนก็ขอทีละเดือน)
   การไล่ดึงทีละวันจึงเปลืองโดยไม่จำเป็น — 10 ร้าน x 9 วัน = 90 รอบเปิดเบราว์เซอร์
   ทั้งที่ขอเป็นช่วงครั้งเดียวต่อร้าน = 10 รอบ ได้ข้อมูลเท่ากัน

   หลักการเดียวกับ lazada_daily_from_dump.py: ดึงครั้งเดียว แยกเองในเครื่อง
   ผลลัพธ์เป็นไฟล์รายวันรูปแบบเดียวกับรอบรายวันเป๊ะ ขั้นสกรีนใช้ต่อได้ทันที

⚠️ ช่วงยาว Shopee อาจส่งมาเป็น .zip ที่ข้างในตัดเป็น part_1_of_N
   ตัว read_export ปกติอ่าน zip ไม่ได้ ต้องแตกก่อน ไม่งั้นข้อมูลหายเงียบ ๆ

    .\.venv\Scripts\python.exe -u scripts\shopee_range_to_daily.py --from 2026-08-01 --to 2026-08-09
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.browser_cleanup import close_stale_browsers  # noqa: E402
from src.core.config import load_config                  # noqa: E402
from src.core.exporter import export_shop                # noqa: E402
from src.core.logging_setup import get_logger, setup_logging  # noqa: E402
from src.core.privacy import apply_privacy               # noqa: E402
from src.core.runner import AlreadyRunningError, run_lock  # noqa: E402

log = get_logger()


def read_any(adapter, path: Path) -> list[dict]:
    """อ่าน .xlsx เดี่ยว หรือ .zip ที่ข้างในถูกตัดเป็นหลายส่วน"""
    if path.suffix.lower() != ".zip":
        return adapter.map.read_export(path)
    rows: list[dict] = []
    out = path.with_suffix("")
    out.mkdir(exist_ok=True)
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist()
                 if n.lower().endswith((".xlsx", ".xls", ".csv"))]
        for n in sorted(names):                          # part_1 ต้องมาก่อน part_2
            target = out / Path(n).name
            if not target.exists():
                with zf.open(n) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            rows.extend(adapter.map.read_export(target))
    return rows


def day_of(o) -> date | None:
    v = o.order_created_at
    if not v:
        return None
    return v.date() if hasattr(v, "date") else date.fromisoformat(str(v)[:10])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--shop", help="ทำร้านเดียว (ไม่ใส่ = ทุกร้าน Shopee ที่เปิดอยู่)")
    ap.add_argument("--wait", type=int, default=1200,
                    help="รอไฟล์ในประวัติการดาวน์โหลดนานสุดกี่วินาที (ค่าเริ่มต้น 1200)")
    args = ap.parse_args()

    d_from = date.fromisoformat(args.d_from)
    d_to = date.fromisoformat(args.d_to)

    cfg = load_config()
    setup_logging(PROJECT_ROOT / cfg.settings.paths.logs_dir,
                  f"shopee_range_{d_from}_{d_to}")

    shops = [s for s in cfg.shops
             if s.enabled and s.platform == "shopee"
             and (not args.shop or s.shop_id == args.shop)]
    if not shops:
        print("❌ ไม่มีร้าน Shopee ที่ตรงเงื่อนไข")
        return 1

    out_dir = PROJECT_ROOT / cfg.settings.paths.output_dir
    arc_dir = PROJECT_ROOT / cfg.settings.paths.archive_dir
    n_days = (d_to - d_from).days + 1

    print(f"ดึง {len(shops)} ร้าน x 1 รอบ (ช่วง {d_from} ถึง {d_to} = {n_days} วัน)")
    print(f"เทียบกับดึงทีละวัน {len(shops) * n_days} รอบ\n")

    closed = close_stale_browsers()
    if closed:
        print(f"เคลียร์ Chrome ค้าง {closed} process\n")

    ok = bad = 0
    try:
        with run_lock(PROJECT_ROOT / cfg.settings.paths.lock_file):
            for s in shops:
                print(f"--- {s.shop_id} ({s.report_name}) ---", flush=True)
                adapter = build_adapter(s, cfg.settings)
                # ช่วงยาว Shopee ปั่นไฟล์นานกว่ารอบรายวันมาก — ยืดเวลารอ
                adapter.report_timeout_sec = args.wait
                try:
                    adapter.authenticate()
                    orders = adapter.fetch_orders(d_from, d_to)
                    orders = apply_privacy(orders, cfg.settings.privacy.include_pii)
                    print(f"    ได้ {len(orders):,} ออเดอร์", flush=True)

                    day = d_from
                    while day <= d_to:
                        picked = [o for o in orders if day_of(o) == day]
                        run_date = (day + timedelta(days=1)).isoformat()
                        export_shop(
                            picked,
                            shop_id=s.shop_id, platform=s.platform,
                            shop_name=s.report_name, run_date=run_date,
                            date_from=day.isoformat(), date_to=day.isoformat(),
                            output_dir=out_dir, archive_dir=arc_dir,
                            status="SUCCESS" if picked else "PARTIAL",
                            notes=None if picked else "ไม่มีออเดอร์ของวันนี้ในไฟล์ Export",
                        )
                        print(f"      {day}  {len(picked):>4} ออเดอร์", flush=True)
                        day += timedelta(days=1)
                    ok += 1
                    log.info("shopee_range_done", shop_id=s.shop_id, orders=len(orders))
                except Exception as exc:                 # noqa: BLE001
                    bad += 1
                    print(f"    ❌ {type(exc).__name__}: {str(exc)[:110]}", flush=True)
                    log.error("shopee_range_failed", shop_id=s.shop_id,
                              err=str(exc)[:200])
                finally:
                    adapter.close()
                time.sleep(3)
    except AlreadyRunningError:
        print("❌ มีรอบอื่นรันอยู่ — หยุดก่อน")
        return 2

    print(f"\nสำเร็จ {ok} ร้าน · ล้มเหลว {bad} ร้าน")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
