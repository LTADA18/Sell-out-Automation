r"""ดึงย้อนหลัง 1 ม.ค. – 31 ก.ค. 2026 สำหรับ Lazada / TikTok

ต่างจาก Shopee ตรงที่ 2 เจ้านี้ยอมให้เลือกช่วงยาวทีเดียว
(ยืนยันแล้ว: tiktok_01 ดึง 7 เดือนรวด 9,933 ออเดอร์ ใช้เวลา 180 วินาที)
จึงไม่ต้องแยกรายเดือนแบบ Shopee

⚠️ Lazada ช่วงยาวเจอ TIMEOUT (รอไฟล์เกิน 120 วิ) → มีโหมดถอยไปดึงรายเดือน

    python scripts\backfill_nonshopee.py --shops tiktok_01,tiktok_02
    python scripts\backfill_nonshopee.py --shops lazada_01 --monthly
"""
from __future__ import annotations

import argparse
import json
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
from src.core.models import AdapterError, ErrorType, Order   # noqa: E402

D_FROM, D_TO = date(2026, 1, 1), date(2026, 7, 31)
BASE = PROJECT_ROOT / "output" / "_backfill_2026h1_all"
STATE = BASE / "state_nonshopee.json"

MONTHS = [(date(2026, m, 1),
           date.fromordinal(date(2026, m + 1, 1).toordinal() - 1) if m < 12
           else date(2026, 12, 31))
          for m in range(1, 8)]


def load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding="utf-8-sig"))
    return {"done": {}}


def save_state(st: dict) -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shops", required=True, help="รหัสร้าน คั่นด้วย ,")
    ap.add_argument("--monthly", action="store_true",
                    help="ดึงทีละเดือนแล้วรวม (ใช้เมื่อช่วงยาวไม่ผ่าน)")
    args = ap.parse_args()

    cfg = load_config()
    setup_logging(PROJECT_ROOT / cfg.settings.paths.logs_dir, "backfill_nonshopee")
    BASE.mkdir(parents=True, exist_ok=True)
    st = load_state()

    for shop_id in [s.strip() for s in args.shops.split(",") if s.strip()]:
        if shop_id in st["done"]:
            print(f"\n{shop_id}: ทำไปแล้ว ({st['done'][shop_id]} ออเดอร์) ข้าม", flush=True)
            continue

        s = cfg.shop(shop_id)
        print(f"\n=== {shop_id} — {s.display_name} ({s.platform}) ===", flush=True)
        adapter = build_adapter(s, cfg.settings)
        merged: dict[str, Order] = {}
        t0 = time.time()

        try:
            if args.monthly:
                failed: list[tuple[date, date]] = []
                for a, b in MONTHS:
                    try:
                        got = adapter.fetch_orders(a, b)
                        for o in got:
                            merged[f"{o.order_id}|{o.sku}"] = o
                        print(f"   {a:%Y-%m}: {len(got):,} ออเดอร์", flush=True)
                    except AdapterError as exc:
                        # EMPTY_RESULT = เดือนนั้นไม่มีออเดอร์จริง ไม่ใช่ความพัง ไม่ต้องลองซ้ำ
                        print(f"   {a:%Y-%m}: {exc.error_type.value} — {str(exc)[:60]}",
                              flush=True)
                        if exc.error_type is not ErrorType.EMPTY_RESULT:
                            failed.append((a, b))
                    time.sleep(3)

                # ลองซ้ำเดือนที่พลาด — TIMEOUT ของแพลตฟอร์มมักเป็นอาการชั่วคราว
                # และรอบสองคิวฝั่งเขามักโล่งกว่าเพราะงานแรกปั่นเสร็จไปแล้ว
                if failed:
                    print(f"   -- ลองซ้ำ {len(failed)} เดือนที่พลาด --", flush=True)
                    for a, b in failed:
                        try:
                            got = adapter.fetch_orders(a, b)
                            for o in got:
                                merged[f"{o.order_id}|{o.sku}"] = o
                            print(f"   {a:%Y-%m} (รอบ 2): {len(got):,} ออเดอร์", flush=True)
                        except AdapterError as exc:
                            print(f"   {a:%Y-%m} (รอบ 2): ยังไม่ผ่าน — {exc.error_type.value}",
                                  flush=True)
                        time.sleep(5)
            else:
                for o in adapter.fetch_orders(D_FROM, D_TO):
                    merged[f"{o.order_id}|{o.sku}"] = o
        except Exception as exc:                         # noqa: BLE001
            print(f"   ❌ {type(exc).__name__}: {str(exc)[:110]}", flush=True)
            traceback.print_exc()
            adapter.close()
            continue
        finally:
            adapter.close()

        if not merged:
            print("   ไม่ได้ข้อมูลเลย ข้าม", flush=True)
            continue

        path = export_shop(
            list(merged.values()),
            shop_id=shop_id, platform=s.platform, shop_name=s.display_name,
            run_date="2026-01_ถึง_2026-07",
            date_from=D_FROM.isoformat(), date_to=D_TO.isoformat(),
            output_dir=BASE, archive_dir=BASE / "_archive",
        )
        st["done"][shop_id] = len(merged)
        save_state(st)
        print(f"   ✅ {len(merged):,} ออเดอร์ · {time.time() - t0:.0f} วินาที → {path.name}",
              flush=True)

    print(f"\nสรุป: ทำไปแล้ว {len(st['done'])} ร้าน")
    for k, v in st["done"].items():
        print(f"  {k:<12} {v:>8,} ออเดอร์")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
