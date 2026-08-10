r"""ดึงย้อนหลังแบบขนาน — แบ่งร้านเป็นสายตามโปรไฟล์เบราว์เซอร์

⚠️ ทำไมขนานได้:
   แต่ละร้านใช้โปรไฟล์ Chrome ของตัวเอง จึงเปิดพร้อมกันได้โดยไม่แย่ง session
   **ยกเว้นร้านที่ใช้ profile_key ร่วมกัน (เช่น shopee_03 กับ shopee_08)
   ต้องอยู่สายเดียวกันเสมอ** ไม่งั้นจะเปิดโปรไฟล์เดียวกัน 2 ที่พร้อมกันแล้วพัง

⚠️ สคริปต์นี้ **ไม่ใช้ run_lock** โดยตั้งใจ
   run_lock มีไว้กัน "รอบดึงซ้อนรอบดึง" ซึ่งถูกต้องสำหรับรอบรายวัน
   แต่ที่นี่เราตั้งใจให้หลายสายทำพร้อมกัน โดยแบ่งร้านไม่ให้ทับกัน
   ตัวเรียก (backfill_parallel.ps1 หรือคนสั่ง) ต้องรับผิดชอบว่าไม่ชนรอบรายวัน

    .\.venv\Scripts\python.exe -u scripts\backfill_parallel.py \
        --shops shopee_03,shopee_08,shopee_01 --from 2026-08-01 --to 2026-08-09
"""
from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import load_config                  # noqa: E402
from src.core.logging_setup import setup_logging         # noqa: E402
from src.core.models import RunStatus                    # noqa: E402
from src.core.runner import Runner                       # noqa: E402
from src.core.status_store import StatusStore            # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shops", required=True, help="รหัสร้าน คั่นด้วย ,")
    ap.add_argument("--from", dest="d_from", required=True)
    ap.add_argument("--to", dest="d_to", required=True)
    ap.add_argument("--tag", default="", help="ชื่อสาย ใช้แยกไฟล์ log")
    args = ap.parse_args()

    d_from = date.fromisoformat(args.d_from)
    d_to = date.fromisoformat(args.d_to)
    want = [s.strip() for s in args.shops.split(",") if s.strip()]

    cfg = load_config()
    cfg.settings.fetch.lookback_days = 1
    shops = [cfg.shop(sid) for sid in want]

    # กันพลาดร้ายแรง: ร้านที่ใช้โปรไฟล์ร่วมกันต้องอยู่สายเดียวกัน
    # ถ้าหลุดไปคนละสาย 2 โปรเซสจะเปิดโปรไฟล์เดียวกันพร้อมกัน = session พังทั้งคู่
    profiles = {s.profile_id for s in shops}
    for s in cfg.shops:
        if s.enabled and s.profile_id in profiles and s.shop_id not in want:
            print(f"❌ {s.shop_id} ใช้โปรไฟล์ {s.profile_id} ร่วมกับร้านในสายนี้ "
                  f"แต่ไม่ได้อยู่ในสายเดียวกัน — ต้องใส่มาด้วย")
            return 2

    tag = args.tag or want[0]
    setup_logging(PROJECT_ROOT / cfg.settings.paths.logs_dir, f"par_{tag}")

    n_days = (d_to - d_from).days + 1
    print(f"[{tag}] {len(shops)} ร้าน x {n_days} วัน = {len(shops) * n_days} รอบ", flush=True)

    lo, hi = cfg.settings.rate_limit.delay_between_shops
    ok = bad = 0
    with StatusStore(PROJECT_ROOT / cfg.settings.paths.db_path) as store:
        runner = Runner(cfg, store)
        day = d_from
        while day <= d_to:
            run_id = f"{day.isoformat()}_par_{tag}"
            for s in shops:
                res = runner.run_shop(s, run_id, day + timedelta(days=1))
                good = res.status is RunStatus.SUCCESS
                ok, bad = ok + good, bad + (not good)
                mark = "✅" if good else ("⚪" if res.status is RunStatus.SKIPPED else "❌")
                print(f"[{tag}] {day} {s.shop_id:<11} {mark} {res.orders_fetched or 0}",
                      flush=True)
                time.sleep(random.uniform(lo, hi))
            day += timedelta(days=1)

    print(f"[{tag}] จบ · สำเร็จ {ok} · ไม่สำเร็จ {bad}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
