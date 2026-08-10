r"""ต่อท่อ: เอาไฟล์ที่ดึงมาเข้าระบบสกรีน SKU แล้วเก็บผลไว้ให้อีเมลแนบ

ไปป์ไลน์เต็ม
    ดึงยอด (โปรเจกต์นี้)  ->  Excel 32 คอลัมน์  ->  สกรีน  ->  Excel 63 คอลัมน์
                                 ของกลาง                        ของส่งมอบจริง

ไฟล์ 32 คอลัมน์ยังต้องมีอยู่เพราะเป็น input ของตัวสกรีน แต่ไม่ใช่ของที่ส่งออกแล้ว
เจ้าของงานยืนยัน 2026-08-10 ว่าอีเมลต้องแนบไฟล์ 63 คอลัมน์แทน

⚠️ ไม่แตะโปรเจกต์ Clean data เลย — ก๊อปไฟล์เข้า input/ แล้วเรียกสคริปต์ของเขา
   ผลลัพธ์ถูกก๊อปกลับมาไว้ที่ output/<วันที่>/screened/ ของเรา
   ทำแบบนี้เพื่อให้ 2 โปรเจกต์แยกกันเหมือนเดิม ย้ายโฟลเดอร์ทีหลังก็ยังได้

    .\.venv\Scripts\python.exe -u scripts\screen_orders.py
    .\.venv\Scripts\python.exe -u scripts\screen_orders.py --date 2026-08-10
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import load_config                   # noqa: E402
from src.core.logging_setup import get_logger, setup_logging  # noqa: E402

log = get_logger()

# โปรเจกต์สกรีน — อยู่คนละที่ ตั้งใจไม่รวมโฟลเดอร์กัน
SCREENER = Path(os.environ.get(
    "OSUKA_SKU_DIR", r"C:\Users\tada.p\Clean data\osuka-sku"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="วันที่ของรอบดึง (ไม่ใส่ = วันนี้)")
    ap.add_argument("--screener", help="ที่อยู่ของโปรเจกต์สกรีน")
    args = ap.parse_args()

    screener = Path(args.screener) if args.screener else SCREENER
    cfg = load_config()
    setup_logging(PROJECT_ROOT / cfg.settings.paths.logs_dir, "screen")

    run_date = args.date or date.today().isoformat()
    src_dir = PROJECT_ROOT / cfg.settings.paths.output_dir / run_date
    if not src_dir.exists():
        print(f"❌ ไม่มีโฟลเดอร์ {src_dir} — ยังไม่ได้ดึงข้อมูลของวันนี้?")
        return 1

    raw = sorted(p for p in src_dir.glob("*.xlsx") if not p.name.startswith("~"))
    if not raw:
        print(f"❌ ไม่มีไฟล์ Excel ใน {src_dir}")
        return 1

    match_py = screener / "scripts" / "match_sku.py"
    if not match_py.exists():
        print(f"❌ ไม่พบตัวสกรีนที่ {match_py}")
        print("   ระบุที่อยู่ด้วย --screener หรือตั้งตัวแปร OSUKA_SKU_DIR")
        return 1

    inbox = screener / "input"
    outbox = screener / "output"
    inbox.mkdir(parents=True, exist_ok=True)

    print(f"=== ส่งไฟล์เข้าระบบสกรีน {len(raw)} ไฟล์ ===")
    for f in raw:
        shutil.copy2(f, inbox / f.name)
        print(f"  → {f.name}")

    print(f"\n=== รันตัวสกรีน ===")
    # ใช้ python ตัวเดียวกับโปรเจกต์นี้ — ตรวจแล้วว่ามี pandas + openpyxl ครบ
    # โปรเจกต์สกรีนไม่มี venv ของตัวเอง จึงไม่มีอะไรให้ชนกัน
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    res = subprocess.run(
        [sys.executable, "-u", str(match_py), "--input", "input/", "--out", "output/"],
        cwd=screener, capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=env, timeout=3600,
    )
    tail = [ln for ln in (res.stdout or "").splitlines() if ln.strip()][-12:]
    for ln in tail:
        print(f"  {ln}")
    if res.returncode != 0:
        print(f"\n❌ ตัวสกรีนจบด้วย exit {res.returncode}")
        for ln in (res.stderr or "").splitlines()[-8:]:
            print(f"  {ln}")
        log.error("screen_failed", rc=res.returncode)
        return 1

    # เก็บผลกลับมาไว้ฝั่งเรา — อีเมลจะแนบจากตรงนี้
    dest = src_dir / "screened"
    dest.mkdir(exist_ok=True)
    got = 0
    for f in raw:
        matched = outbox / f"{f.stem}_matched.xlsx"
        if matched.exists():
            shutil.copy2(matched, dest / matched.name)
            got += 1
        else:
            print(f"  ⚠️ ไม่พบผลของ {f.name}")

    # รายงานสรุปที่ตัวสกรีนออกให้ — แนบไปด้วยจะได้เห็นภาพรวม
    for extra in ("brand_summary.xlsx", "data_issues.xlsx", "missing_models.xlsx"):
        p = outbox / extra
        if p.exists():
            shutil.copy2(p, dest / extra)

    print(f"\n✅ สกรีนแล้ว {got}/{len(raw)} ไฟล์ → {dest.relative_to(PROJECT_ROOT)}")
    log.info("screen_done", files_in=len(raw), files_out=got, date=run_date)

    if got < len(raw):
        # ไม่ครบ = ต้องรู้ ไม่ใช่ปล่อยผ่านแล้วส่งอีเมลไปแบบขาด ๆ
        print(f"❌ ขาด {len(raw) - got} ไฟล์")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
