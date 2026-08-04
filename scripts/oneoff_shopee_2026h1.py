r"""งานเฉพาะกิจ — ดึงออเดอร์ Shopee 4 ร้าน ย้อนหลัง 1 ม.ค. – 31 ก.ค. 2026

⚠️ ตั้งใจแยกจากรอบประจำวันโดยสิ้นเชิง ตามที่เจ้าของงานสั่ง:
   - ไม่เขียน status.db          → Dashboard กับอีเมลรายวันไม่เห็นงานนี้เลย
   - ไม่จับ run.lock             → ไม่บล็อกรอบ 09:00
   - ออกไฟล์ในโฟลเดอร์ของตัวเอง  → ไม่ปนกับ output/{วันที่}/ ที่อีเมลรายวันแนบ

   จึงไม่ใช้คำสั่ง `backfill` ที่มีอยู่ เพราะตัวนั้นวนดึงทีละวัน
   (212 วัน × 4 ร้าน = 848 รอบ) และเขียน run_log ลง status.db ทุกรอบ

Shopee ให้เลือกช่วงวันที่ได้ตรง ๆ จึงดึงทีเดียวจบต่อร้าน
ถ้าช่วงยาวเกินที่แพลตฟอร์มยอม จะถอยไปดึงทีละเดือนแล้วรวมกันเอง

รัน: .\.venv\Scripts\python.exe scripts\oneoff_shopee_2026h1.py
"""
from __future__ import annotations

import random
import sys
import time
import traceback
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.config import load_config                  # noqa: E402
from src.core.exporter import export_shop                # noqa: E402
from src.core.logging_setup import setup_logging         # noqa: E402
from src.core.models import AdapterError, Order          # noqa: E402

SHOP_IDS = ["shopee_02", "shopee_04", "shopee_05", "shopee_06"]
D_FROM = date(2026, 1, 1)
D_TO = date(2026, 7, 31)

TAG = "2026-01-01_ถึง_2026-07-31"
OUT_DIR = PROJECT_ROOT / "output" / "_oneoff_shopee_2026h1"


def month_chunks(d_from: date, d_to: date) -> list[tuple[date, date]]:
    """แบ่งเป็นช่วงรายเดือน — ใช้ตอนดึงยาวทีเดียวไม่ผ่าน"""
    out: list[tuple[date, date]] = []
    y, m = d_from.year, d_from.month
    cur = d_from
    while cur <= d_to:
        y2, m2 = (y + 1, 1) if m == 12 else (y, m + 1)
        last = date(y2, m2, 1).toordinal() - 1
        end = min(date.fromordinal(last), d_to)
        out.append((cur, end))
        cur = date.fromordinal(last + 1)
        y, m = y2, m2
    return out


def fetch_one(adapter, shop_id: str) -> tuple[list[Order], str]:
    """ลองดึงยาวทีเดียวก่อน ไม่ผ่านค่อยไล่ทีละเดือน — คืน (orders, วิธีที่ใช้)"""
    try:
        orders = adapter.fetch_orders(D_FROM, D_TO)
        return orders, "ช่วงเดียวจบ"
    except AdapterError as exc:
        print(f"   ดึงยาวทีเดียวไม่ผ่าน ({exc.error_type.value}) → ถอยไปดึงรายเดือน")

    merged: dict[str, Order] = {}
    for i, (a, b) in enumerate(month_chunks(D_FROM, D_TO), 1):
        print(f"   [{i}/7] {a} – {b} ...", flush=True)
        try:
            for o in adapter.fetch_orders(a, b):
                merged[f"{o.order_id}|{o.sku}"] = o      # กันซ้ำถ้าช่วงเหลื่อม
        except AdapterError as exc:
            print(f"      ⚠️ เดือนนี้ไม่ได้: {exc.error_type.value} — {exc}")
        time.sleep(3)
    return list(merged.values()), "รายเดือน"


def main() -> int:
    cfg = load_config()
    setup_logging(PROJECT_ROOT / cfg.settings.paths.logs_dir, "oneoff_shopee_2026h1")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    summary: list[tuple[str, str, int, str]] = []

    for shop_id in SHOP_IDS:
        s = cfg.shop(shop_id)
        print(f"\n=== {shop_id} — {s.display_name} ===", flush=True)
        adapter = build_adapter(s, cfg.settings)
        orders: list[Order] = []
        how = "-"
        try:
            orders, how = fetch_one(adapter, shop_id)
            print(f"   ได้ {len(orders):,} ออเดอร์ ({how})")
        except Exception as exc:                         # noqa: BLE001
            print(f"   ❌ ล้มเหลว: {type(exc).__name__}: {exc}")
            traceback.print_exc()
            summary.append((shop_id, s.display_name, 0, f"FAILED: {exc}"))
            continue
        finally:
            # ⚠️ ต้องปิดผ่าน close() เสมอ ไม่งั้น cookie ที่ค้างในหน่วยความจำหาย
            adapter.close()

        path = export_shop(
            orders,
            shop_id=shop_id,
            platform=s.platform,
            shop_name=s.display_name,
            run_date=TAG,
            date_from=D_FROM.isoformat(),
            date_to=D_TO.isoformat(),
            output_dir=OUT_DIR,
            archive_dir=OUT_DIR / "_archive",
        )
        print(f"   → {path.name}")
        summary.append((shop_id, s.display_name, len(orders), how))
        time.sleep(random.uniform(*cfg.settings.rate_limit.delay_between_shops))

    print("\n" + "=" * 60)
    total = 0
    for shop_id, name, n, how in summary:
        print(f"  {shop_id:<12} {name[:26]:<28} {n:>8,}  {how}")
        total += n
    print(f"  {'รวม':<12} {'':<28} {total:>8,}")
    print(f"\nไฟล์อยู่ที่ {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
