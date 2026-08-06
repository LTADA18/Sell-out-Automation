r"""สร้างไฟล์ย้อนหลังของ Lazada จากไฟล์ Export ที่โหลดมาแล้ว

⚠️ ทำไมต้องทำแบบนี้แทนการดึงรายเดือน:
   เมนูที่ Lazada ให้กดชื่อ "Export All" — มันส่งออก **ทุกออเดอร์** จริง ๆ
   ไม่สนตัวกรองวันที่ที่เลือกบนหน้าจอ (ยืนยัน 2026-08-06:
   ขอเดือน ก.พ. แต่ในไฟล์มีออเดอร์ของ 6 ส.ค. ปนมาด้วย และ
   ขอ ม.ค. กับ ก.พ. ได้ 38,490 ออเดอร์เท่ากันเป๊ะ = ไฟล์ชุดเดียวกัน)

   ดึงรายเดือนจึงเสียเวลา 14 นาที/เดือนเพื่อได้ไฟล์เดิมซ้ำ ๆ
   ใช้ไฟล์เดียวแล้วกรองเองในเครื่องเร็วกว่าและถูกต้องกว่า

   รอบดึงรายวันไม่ได้รับผลกระทบ เพราะใช้ปุ่ม "เมื่อวานนี้" คนละทางกัน
   (ยอดรายวันออกมา 38-48 ออเดอร์ ซึ่งสมเหตุสมผลกับ 1 วัน)

    python scripts\lazada_from_dump.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.config import load_config                  # noqa: E402
from src.core.exporter import export_shop                # noqa: E402

SHOP = "lazada_01"
D_FROM, D_TO = date(2026, 1, 1), date(2026, 7, 31)
OUT = PROJECT_ROOT / "output" / "_backfill_2026h1_all"
DUMPS = PROJECT_ROOT / "data" / "raw" / "lazada" / SHOP / "files"


def main() -> int:
    files = sorted(DUMPS.glob("*.xlsx"), key=lambda p: p.stat().st_size, reverse=True)
    if not files:
        print("ไม่พบไฟล์ Export ของ Lazada")
        return 1
    src = files[0]                       # เอาไฟล์ใหญ่สุด = ครบสุด
    print(f"ใช้ไฟล์ {src.name}  ({src.stat().st_size / 1024 / 1024:.1f} MB)")

    cfg = load_config()
    s = cfg.shop(SHOP)
    adapter = build_adapter(s, cfg.settings)
    try:
        rows = adapter.map.read_export(src)
        print(f"อ่านได้ {len(rows):,} แถว")
        orders = adapter.normalize(rows)
        print(f"ยุบเป็น {len(orders):,} ออเดอร์ (ก่อนกรองวันที่)")

        kept = []
        for o in orders:
            d = o.order_created_at
            if not d:
                continue
            day = d.date() if hasattr(d, "date") else date.fromisoformat(str(d)[:10])
            if D_FROM <= day <= D_TO:
                kept.append(o)

        print(f"อยู่ในช่วง {D_FROM} ถึง {D_TO}: {len(kept):,} ออเดอร์")
        if not kept:
            print("ไม่มีข้อมูลในช่วงที่ต้องการ")
            return 1

        days = sorted({(o.order_created_at.date() if hasattr(o.order_created_at, "date")
                        else date.fromisoformat(str(o.order_created_at)[:10]))
                       for o in kept})
        print(f"ครอบคลุม {days[0]} ถึง {days[-1]}  ({len(days)} วันที่มีออเดอร์)")

        path = export_shop(
            kept,
            shop_id=SHOP, platform=s.platform, shop_name=s.display_name,
            run_date="2026-01_ถึง_2026-07",
            date_from=D_FROM.isoformat(), date_to=D_TO.isoformat(),
            output_dir=OUT, archive_dir=OUT / "_archive",
            notes="กรองจากไฟล์ Export All ในเครื่อง — Lazada ไม่กรองตามช่วงวันที่ให้",
        )
        print(f"✅ {path.name}")
    finally:
        adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
