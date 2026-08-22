r"""ดึงรายงานโฆษณาแล้วแปลงเป็นแถวสำหรับ intel.mp_ads_raw

    .\.venv\Scripts\python.exe scripts\fetch_ads.py --shop shopee_02 ^
        --from 2026-07-01 --to 2026-07-31

    # แปลงไฟล์ที่โหลดมาแล้ว ไม่ต้องเปิดเบราว์เซอร์ (ใช้ตอนทดสอบตัวแปลง)
    .\.venv\Scripts\python.exe scripts\fetch_ads.py --shop shopee_02 --parse-only <ไฟล์>

⚠️ ยังไม่เขียนลงฐาน — ขั้นนี้ออกเป็น .jsonl ให้ตรวจก่อน
   เจ้าของงานสั่งไว้ว่าห้ามแก้ไขข้อมูลอะไรโดยเด็ดขาด การเขียนลง Postgres
   จึงต้องเป็นขั้นตอนแยกที่สั่งเองอีกที ไม่ใช่ผลข้างเคียงของการดึง
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.ads.parser import (parse_lazada_ads, parse_shopee_ads,   # noqa: E402
                            parse_tiktok_ads)
from src.core.config import load_config                     # noqa: E402
from src.core.logging_setup import setup_logging           # noqa: E402


def _d(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", required=True)
    ap.add_argument("--from", dest="d_from", help="YYYY-MM-DD")
    ap.add_argument("--to", dest="d_to", help="YYYY-MM-DD")
    ap.add_argument("--parse-only", help="ข้ามการดึง ใช้ไฟล์นี้แทน")
    ap.add_argument("--timeout", type=int, default=600,
                    help="รอ Shopee ปั่นไฟล์กี่วินาที (ค่าเริ่มต้น 600)")
    args = ap.parse_args()

    setup_logging(PROJECT_ROOT / "logs", f"ads_{args.shop}")

    platform = load_config().shop(args.shop).platform
    if platform not in ("shopee", "tiktok", "lazada"):
        ap.error(f"ยังไม่รองรับ {platform}")

    if args.parse_only:
        path = Path(args.parse_only)
    else:
        if not (args.d_from and args.d_to):
            ap.error("ต้องใส่ --from กับ --to (หรือใช้ --parse-only)")
        # import ตอนใช้จริง โมดูลพวกนี้เปิด Playwright ซึ่งหนัก
        if platform == "shopee":
            from src.ads.shopee_ads import ShopeeAdsFetcher
            with ShopeeAdsFetcher(args.shop) as f:
                path = f.fetch(_d(args.d_from), _d(args.d_to),
                               timeout_sec=args.timeout)
        elif platform == "tiktok":
            from src.ads.tiktok_ads import TikTokAdsFetcher
            with TikTokAdsFetcher(args.shop) as f:
                path = f.fetch(_d(args.d_from), _d(args.d_to))
        else:
            from src.ads.lazada_ads import LazadaAdsFetcher
            with LazadaAdsFetcher(args.shop) as f:
                path = f.fetch(_d(args.d_from), _d(args.d_to))
        print(f"✅ ได้ไฟล์: {path.name}")

    parse = {"shopee": parse_shopee_ads, "tiktok": parse_tiktok_ads,
             "lazada": parse_lazada_ads}[platform]
    rows = parse(path, shop_id=args.shop)
    print(f"แปลงได้ {len(rows)} แถว")

    spend = sum(r["expense_thb"] for r in rows if r["expense_thb"])
    gmv = sum(r["gmv_thb"] for r in rows if r["gmv_thb"])
    print(f"   ค่าโฆษณารวม {spend:,.2f} · ยอดขายรวม {gmv:,.2f}"
          f" · ROAS {gmv / spend:.2f}" if spend else "   (ไม่มียอดค่าโฆษณา)")

    out = PROJECT_ROOT / "output" / "_ads" / f"{args.shop}_{path.stem[:40]}.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    print(f"   เขียนผลไว้ที่ {out}")
    print("   (ยังไม่ได้เขียนลงฐาน — เป็นขั้นตอนแยกที่ต้องสั่งเอง)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
