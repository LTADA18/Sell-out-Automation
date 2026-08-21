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
from src.core.busy import clear_busy, mark_busy          # noqa: E402
from src.core.config import load_config                  # noqa: E402
from src.core.exporter import export_shop                # noqa: E402
from src.core.logging_setup import setup_logging         # noqa: E402
from src.core.models import AdapterError, ErrorType, Order   # noqa: E402
from src.core.naming import canonical_name               # noqa: E402

D_FROM, D_TO = date(2026, 1, 1), date(2026, 7, 31)   # ค่าเริ่มต้น ทับได้ด้วย --from/--to
BASE = PROJECT_ROOT / "output" / "_backfill_2026h1_all"
STATE = BASE / "state_nonshopee.json"


def month_chunks(d_from: date, d_to: date) -> list[tuple[date, date]]:
    """ซอยช่วงเป็นรายเดือน — เดือนหัวกับเดือนท้ายถูกตัดตามวันที่จริงที่ขอ

    ⚠️ ของเดิมฝังไว้ว่าเดือน 1-7 เต็มเดือนเสมอ พอขอถึงกลางเดือน ส.ค.
       โหมด --monthly จะดึงเกินช่วงที่ขอโดยไม่มีอะไรเตือน
    """
    out: list[tuple[date, date]] = []
    y, m = d_from.year, d_from.month
    while (y, m) <= (d_to.year, d_to.month):
        first = date(y, m, 1)
        last = (date(y + 1, 1, 1) if m == 12 else date(y, m + 1, 1))
        last = date.fromordinal(last.toordinal() - 1)
        out.append((max(first, d_from), min(last, d_to)))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


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
    ap.add_argument("--from", dest="d_from", default=D_FROM.isoformat(),
                    help="วันเริ่ม YYYY-MM-DD")
    ap.add_argument("--to", dest="d_to", default=D_TO.isoformat(),
                    help="วันสุดท้าย YYYY-MM-DD")
    args = ap.parse_args()

    d_from = date.fromisoformat(args.d_from)
    d_to = date.fromisoformat(args.d_to)
    if d_from > d_to:
        print(f"❌ --from {d_from} มาหลัง --to {d_to}")
        return 2
    months = month_chunks(d_from, d_to)
    print(f"ช่วงที่ขอ {d_from} ถึง {d_to}"
          + (f" · ซอยเป็น {len(months)} เดือน" if args.monthly else ""))

    cfg = load_config()
    setup_logging(PROJECT_ROOT / cfg.settings.paths.logs_dir, "backfill_nonshopee")
    BASE.mkdir(parents=True, exist_ok=True)
    st = load_state()

    # ยกธงกัน KeepAlive เข้ามาไล่ปิด Chrome กลางคัน (ดู src/core/busy.py)
    mark_busy(f"backfill_nonshopee {args.shops}")
    try:
        return _run(cfg, st, args, d_from, d_to, months)
    finally:
        clear_busy()


def _run(cfg, st: dict, args, d_from: date, d_to: date,
         months: list[tuple[date, date]]) -> int:
    for shop_id in [s.strip() for s in args.shops.split(",") if s.strip()]:
        if shop_id in st["done"]:
            print(f"\n{shop_id}: ทำไปแล้ว ({st['done'][shop_id]} ออเดอร์) ข้าม", flush=True)
            continue

        s = cfg.shop(shop_id)
        print(f"\n=== {shop_id} — {s.display_name} ({s.platform}) ===", flush=True)
        adapter = build_adapter(s, cfg.settings)
        # ⚠️ คีย์กันซ้ำต้องครบ 5 ส่วน + ตัวนับลำดับซ้ำ ห้ามย่อเหลือ order_id|sku
        #    ย่อแล้วทิ้งบรรทัดที่ต่างกันแค่ variation หรือ product_name
        #    เคยพลาดมาแล้ว: หายไป 1,319 บรรทัด / 971 ออเดอร์ ตอนโหลด Postgres
        merged: dict[tuple, Order] = {}
        t0 = time.time()

        def keep(got: list[Order]) -> None:
            """เก็บออเดอร์เข้า merged โดยไม่ทับบรรทัดที่ซ้ำกันจริง"""
            occ: dict[tuple, int] = {}
            for o in got:
                base = (o.order_id, o.sku, o.variation, o.product_name)
                n = occ.get(base, 0)
                occ[base] = n + 1
                merged[(*base, n)] = o

        try:
            if args.monthly:
                failed: list[tuple[date, date]] = []
                for a, b in months:
                    try:
                        got = adapter.fetch_orders(a, b)
                        keep(got)
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
                            keep(got)
                            print(f"   {a:%Y-%m} (รอบ 2): {len(got):,} ออเดอร์", flush=True)
                        except AdapterError as exc:
                            print(f"   {a:%Y-%m} (รอบ 2): ยังไม่ผ่าน — {exc.error_type.value}",
                                  flush=True)
                        time.sleep(5)
            else:
                keep(adapter.fetch_orders(d_from, d_to))
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
            # ⚠️ ชื่อมาตรฐาน ไม่ใช่ชื่อดิบจากแพลตฟอร์ม ไม่งั้นร้านเดียวถูกหั่นเป็น 2 ชื่อ
            shop_id=shop_id, platform=s.platform,
            shop_name=canonical_name(shop_id, s.display_name),
            # ⚠️ ต้องสะท้อนช่วงที่ดึงจริง ของเดิมฝัง "2026-01_ถึง_2026-07" ไว้ตายตัว
            #    ดึงช่วงอื่นแล้วไฟล์จะถูกติดป้ายผิดช่วงโดยไม่มีอะไรเตือน
            run_date=f"{d_from:%Y-%m}_ถึง_{d_to:%Y-%m}",
            date_from=d_from.isoformat(), date_to=d_to.isoformat(),
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
