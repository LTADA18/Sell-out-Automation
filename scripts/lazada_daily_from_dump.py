r"""สร้างไฟล์ Lazada รายวันจากไฟล์ Export ที่โหลดมาแล้ว — ไม่ต้องดึงซ้ำ

⚠️ ทำไมต้องมี:
   เมนูของ Lazada มีแต่ "Export All" ซึ่งส่ง **ทุกออเดอร์** มาเสมอ
   ไม่สนตัวกรองวันที่ที่เลือกบนหน้าจอ (ยืนยันแล้ว 2026-08-06 และ 2026-08-10)
   ดึงย้อนหลัง 9 วันจึงเท่ากับรอ 14 นาที x 9 รอบ เพื่อได้ไฟล์เดิมซ้ำ ๆ = เสียเวลาเปล่า ~2 ชม.

   ตัวนี้อ่านไฟล์ที่โหลดมาแล้วครั้งเดียว แล้วแยกเป็นไฟล์รายวันให้ตรงรูปแบบเดียวกับรอบรายวัน
   (ชื่อไฟล์ · โฟลเดอร์ · 32 คอลัมน์) เพื่อให้ขั้นสกรีนใช้ต่อได้ทันที

⚠️ โฟลเดอร์ปลายทางใช้ "วันที่รัน" = วันของข้อมูล + 1 วัน
   ตรงกับที่ระบบทำอยู่ (รอบเช้าดึงข้อมูลของเมื่อวาน)

    .\.venv\Scripts\python.exe -u scripts\lazada_daily_from_dump.py --from 2026-08-01 --to 2026-08-09
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.config import load_config                  # noqa: E402
from src.core.exporter import export_shop                # noqa: E402
from src.core.privacy import apply_privacy               # noqa: E402

SHOP = "lazada_01"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--dump", help="ระบุไฟล์ export เอง (ไม่ใส่ = เอาไฟล์ใหญ่สุดที่มี)")
    ap.add_argument("--shop", default=SHOP, help="ร้านที่ไฟล์นี้เป็นของ")
    # ⚠️ แตกรายวันได้ไฟล์เยอะ (ช่วง 8 เดือน = 229 ไฟล์ = สกรีน 229 รอบ)
    #    โหมดนี้รวมเป็นไฟล์เดียวเหมือนที่ backfill_nonshopee ทำ สกรีนรอบเดียวจบ
    ap.add_argument("--single", action="store_true",
                    help="รวมทั้งช่วงเป็นไฟล์เดียว แทนการแตกรายวัน")
    args = ap.parse_args()

    d_from = date.fromisoformat(args.d_from)
    d_to = date.fromisoformat(args.d_to)

    cfg = load_config()
    shop_id = args.shop
    s = cfg.shop(shop_id)
    adapter = build_adapter(s, cfg.settings)

    if args.dump:
        src = Path(args.dump)
    else:
        dumps = PROJECT_ROOT / "data" / "raw" / "lazada" / shop_id / "files"
        files = sorted(dumps.glob("*.xlsx"), key=lambda p: p.stat().st_size, reverse=True)
        if not files:
            print(f"❌ ไม่พบไฟล์ Export ใน {dumps}")
            return 1
        src = files[0]                                    # ใหญ่สุด = ครบสุด
    print(f"ใช้ไฟล์ {src.name}  ({src.stat().st_size / 1024 / 1024:.1f} MB)")

    rows = adapter.map.read_export(src)
    print(f"อ่านได้ {len(rows):,} แถว")
    orders = adapter.normalize(rows)
    print(f"ยุบเป็น {len(orders):,} ออเดอร์ (ก่อนกรองวันที่)\n")

    def day_of(o) -> date | None:
        v = o.order_created_at
        if not v:
            return None
        return v.date() if hasattr(v, "date") else date.fromisoformat(str(v)[:10])

    out_dir = PROJECT_ROOT / cfg.settings.paths.output_dir
    arc_dir = PROJECT_ROOT / cfg.settings.paths.archive_dir

    # ── โหมดรวมไฟล์เดียว ────────────────────────────────────
    if args.single:
        picked = [o for o in orders if (dd := day_of(o)) and d_from <= dd <= d_to]
        picked = apply_privacy(picked, cfg.settings.privacy.include_pii)
        base = PROJECT_ROOT / "output" / "_backfill_2026h1_all"
        path = export_shop(
            picked, shop_id=shop_id, platform=s.platform, shop_name=s.report_name,
            run_date=f"{d_from:%Y-%m}_ถึง_{d_to:%Y-%m}",
            date_from=d_from.isoformat(), date_to=d_to.isoformat(),
            output_dir=base, archive_dir=base / "_archive",
        )
        print(f"✅ รวมเป็นไฟล์เดียว {len(picked):,} ออเดอร์ → {path}")
        return 0

    total = 0
    day = d_from
    while day <= d_to:
        picked = [o for o in orders if day_of(o) == day]
        # ปกปิด PII ให้เหมือนรอบดึงจริง — ห้ามให้ไฟล์จากทางลัดนี้หลุด PII
        picked = apply_privacy(picked, cfg.settings.privacy.include_pii)
        run_date = (day + timedelta(days=1)).isoformat()
        path = export_shop(
            picked,
            shop_id=shop_id,
            platform=s.platform,
            shop_name=s.report_name,
            run_date=run_date,
            date_from=day.isoformat(),
            date_to=day.isoformat(),
            output_dir=out_dir,
            archive_dir=arc_dir,
            status="SUCCESS" if picked else "PARTIAL",
            notes=None if picked else "ไม่มีออเดอร์ของวันนี้ในไฟล์ Export",
        )
        print(f"  {day}  →  {len(picked):>4} ออเดอร์  ·  {path.parent.name}/{path.name[:46]}")
        total += len(picked)
        day += timedelta(days=1)

    print(f"\n✅ รวม {total:,} ออเดอร์ ในช่วง {d_from} ถึง {d_to}")
    print("   ไม่ได้แตะเบราว์เซอร์เลย — ประหยัดการรอ export ไปหลายรอบ")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
