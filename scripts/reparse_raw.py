r"""แปลงไฟล์ดิบที่ดาวน์โหลดไว้แล้วเป็น Excel ใหม่ — ไม่ต้องไปดึงจากแพลตฟอร์มซ้ำ

ใช้ตอนที่ column map เปลี่ยน แล้วอยากได้ข้อมูลย้อนหลังตามรูปแบบใหม่
เช่นตอนเปิดใช้คอลัมน์การเงิน 2026-08-11 ข้อมูลอยู่ในไฟล์ดิบมาตลอด
แค่ตอนนั้นเราไม่ได้ map เข้ามา

ข้อดีกว่าการดึงใหม่
  ไม่กวนแพลตฟอร์ม ไม่เสี่ยงโดนตัด session ไม่ต้องรอคิว export
  ได้ข้อมูลชุดเดิมเป๊ะ ตัวเลขจึงเทียบกับของเดิมได้ตรง ๆ

⚠️ ได้เฉพาะคอลัมน์ที่ไฟล์ดิบมี ถ้าแพลตฟอร์มไม่เคยส่งมา แปลงกี่รอบก็ไม่มี

    .\.venv\Scripts\python.exe -u scripts\reparse_raw.py --from 2026-08-01 --to 2026-08-10
    .\.venv\Scripts\python.exe -u scripts\reparse_raw.py --from 2026-08-01 --to 2026-08-10 --shop shopee_06
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.config import load_config                  # noqa: E402
from src.core.exporter import export_shop                # noqa: E402
from src.core.naming import canonical_name               # noqa: E402
from src.core.privacy import apply_privacy               # noqa: E402

RAW = PROJECT_ROOT / "data" / "raw"


def order_day(o) -> str | None:
    d = o.order_created_at or getattr(o, "ordered_at", None)
    return d.date().isoformat() if d else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--shop", help="ทำร้านเดียว ไม่ใส่ = ทุกร้านที่เปิดใช้")
    args = ap.parse_args()

    d_from = date.fromisoformat(args.d_from)
    d_to = date.fromisoformat(args.d_to)
    want = {(d_from + timedelta(days=i)).isoformat()
            for i in range((d_to - d_from).days + 1)}

    cfg = load_config()
    shops = [s for s in cfg.shops if s.enabled and (not args.shop or s.shop_id == args.shop)]
    print(f"ช่วง {d_from} ถึง {d_to} · {len(shops)} ร้าน\n")

    grand = defaultdict(int)
    for shop in shops:
        shop_raw = RAW / shop.platform / shop.shop_id / "files"
        if not shop_raw.is_dir():
            print(f"  {shop.shop_id:<12} ไม่มีโฟลเดอร์ไฟล์ดิบ ข้าม")
            continue

        # เผื่อขอบ 2 วัน เพราะรอบรายวันดึงข้อมูลของเมื่อวาน
        lo = d_from - timedelta(days=1)
        hi = d_to + timedelta(days=2)
        files = [p for p in sorted(shop_raw.glob("*.xlsx"))
                 if lo <= date.fromtimestamp(p.stat().st_mtime) <= hi]
        if not files:
            print(f"  {shop.shop_id:<12} ไม่มีไฟล์ดิบในช่วงนี้ ข้าม")
            continue

        adapter = build_adapter(shop.model_copy(update={"adapter": "playwright"}),
                                cfg.settings)

        # ยุบซ้ำด้วยคีย์เดียวกับปลายทาง — ไฟล์ดิบหลายไฟล์ทับช่วงกันได้
        seen: dict[tuple, object] = {}
        bad = 0
        for f in files:
            try:
                orders = adapter.normalize(adapter.map.read_export(f))
            except Exception as exc:
                bad += 1
                print(f"      ⚠️ อ่านไม่ได้ {f.name[:52]} ({exc.__class__.__name__})")
                continue
            for o in orders:
                seen[(o.order_id, o.sku, o.variation, o.product_name)] = o

        orders = apply_privacy(list(seen.values()), cfg.settings.privacy.include_pii)

        by_day: dict[str, list] = defaultdict(list)
        for o in orders:
            day = order_day(o)
            if day in want:
                by_day[day].append(o)

        got = sum(len(v) for v in by_day.values())
        print(f"  {shop.shop_id:<12} ไฟล์ดิบ {len(files):>3} · แถวไม่ซ้ำ {len(orders):>6,} "
              f"· อยู่ในช่วง {got:>6,}" + (f" · เสีย {bad}" if bad else ""))

        for day, day_orders in sorted(by_day.items()):
            run_date = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
            export_shop(
                day_orders,
                shop_id=shop.shop_id,
                platform=shop.platform,
                # ⚠️ ต้องเป็นชื่อมาตรฐาน ไม่ใช่ display_name ดิบจากแพลตฟอร์ม
                #    ใช้ display_name แล้วชื่อไฟล์ไม่ตรงกับสายปกติ ไฟล์เก่าจึงไม่ถูกทับ
                #    กลายเป็นมีสองชุดอยู่ด้วยกัน แล้วขั้นโหลดนับซ้ำ 6 ร้าน
                shop_name=canonical_name(shop.shop_id, shop.display_name),
                run_date=run_date,
                date_from=day,
                date_to=day,
                output_dir=PROJECT_ROOT / "output",
                archive_dir=PROJECT_ROOT / "output" / "_archive",
                notes="แปลงใหม่จากไฟล์ดิบ เพื่อเติมคอลัมน์การเงินที่เดิมไม่ได้ map",
            )
            grand[day] += len(day_orders)

    print("\n=== สรุปรายวัน ===")
    for day in sorted(grand):
        print(f"  {day}  {grand[day]:>7,} แถว")
    print(f"  รวม        {sum(grand.values()):>7,} แถว")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
