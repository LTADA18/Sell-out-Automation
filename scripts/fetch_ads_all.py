r"""ดึงรายงานโฆษณาทุกร้านที่ดึงได้ ทีละร้าน ห้ามซ้อน

    .\.venv\Scripts\python.exe scripts\fetch_ads_all.py --from 2026-08-01 --to 2026-08-21

⚠️ ทำทีละร้านโดยตั้งใจ ห้ามรันขนาน
   บทเรียน 2026-08-21: เปิด Chrome หลายตัวพร้อมกันทำให้ timeout สั้น ๆ
   ไม่พอ แล้วล้มด้วย "หาปุ่มไม่เจอ" ทั้งที่ปุ่มอยู่ครบ

⚠️ ร้านที่ล้มด้วย NO_PERMISSION จะไม่ลองซ้ำ — ยิงกี่ครั้งก็ไม่ผ่าน
   มีแต่เสี่ยงบัญชีโดนล็อก (กฎ error ที่ห้าม retry)
"""
from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.ads.parser import (parse_lazada_ads, parse_shopee_ads,   # noqa: E402
                            parse_tiktok_ads)
from src.core.config import load_config                          # noqa: E402
from src.core.logging_setup import setup_logging                 # noqa: E402
from src.core.models import AdapterError, ErrorType              # noqa: E402

OUT_DIR = PROJECT_ROOT / "output" / "_ads"


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def fetch_one(shop, d_from: date, d_to: date, timeout: int) -> tuple[str, int, str]:
    """คืน (สถานะ, จำนวนแถว, ข้อความ)"""
    sid = shop.shop_id
    if shop.platform == "shopee":
        from src.ads.shopee_ads import ShopeeAdsFetcher
        with ShopeeAdsFetcher(sid) as f:
            path = f.fetch(d_from, d_to, timeout_sec=timeout)
        rows = parse_shopee_ads(path, shop_id=sid)
    elif shop.platform == "tiktok":
        from src.ads.tiktok_ads import TikTokAdsFetcher
        with TikTokAdsFetcher(sid) as f:
            path = f.fetch(d_from, d_to)
        rows = parse_tiktok_ads(path, shop_id=sid)
    elif shop.platform == "lazada":
        from src.ads.lazada_ads import LazadaAdsFetcher
        with LazadaAdsFetcher(sid) as f:
            path = f.fetch(d_from, d_to)
        rows = parse_lazada_ads(path, shop_id=sid)
    else:
        return "SKIPPED", 0, f"ยังไม่รองรับ {shop.platform}"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{sid}_{d_from:%Y%m%d}_{d_to:%Y%m%d}.jsonl"
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    spend = sum(r["expense_thb"] for r in rows if r["expense_thb"])
    return "SUCCESS", len(rows), f"ค่าโฆษณา {spend:,.2f}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--platform", help="จำกัดแพลตฟอร์ม เช่น shopee")
    ap.add_argument("--timeout", type=int, default=600)
    args = ap.parse_args()

    setup_logging(PROJECT_ROOT / "logs", "ads_all")
    d_from, d_to = _d(args.d_from), _d(args.d_to)

    cfg = load_config()
    shops = [s for s in cfg.shops
             if s.enabled and s.platform in ("shopee", "tiktok", "lazada")
             and (not args.platform or s.platform == args.platform)]

    print(f"ดึงรายงานโฆษณา {len(shops)} ร้าน · ช่วง {d_from} ถึง {d_to}\n")
    results: list[tuple[str, str, int, str]] = []

    for i, s in enumerate(shops, 1):
        print(f"{'='*62}\n[{i}/{len(shops)}] {s.shop_id} {s.display_name} "
              f"({datetime.now():%H:%M:%S})\n{'='*62}", flush=True)
        try:
            status, n, msg = fetch_one(s, d_from, d_to, args.timeout)
        except AdapterError as exc:
            status, n = exc.error_type.value, 0
            msg = str(exc.message)[:110]
            print(f"   ❌ {status}: {msg}", flush=True)
        except Exception as exc:                         # noqa: BLE001
            status, n, msg = "ERROR", 0, f"{type(exc).__name__}: {str(exc)[:90]}"
            print(f"   ❌ {msg}", flush=True)
            traceback.print_exc(limit=2)
        else:
            print(f"   ✅ {n} แถว · {msg}", flush=True)
        results.append((s.shop_id, status, n, msg))

    print(f"\n{'='*62}\nสรุป\n{'='*62}")
    ok = [r for r in results if r[1] == "SUCCESS"]
    for sid, status, n, msg in results:
        icon = "✅" if status == "SUCCESS" else "❌"
        print(f"  {icon} {sid:<11} {status:<15} {n:>4} แถว  {msg[:60]}")
    print(f"\nสำเร็จ {len(ok)}/{len(results)} ร้าน · รวม {sum(r[2] for r in ok)} แถว")
    print(f"ไฟล์อยู่ที่ {OUT_DIR}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
