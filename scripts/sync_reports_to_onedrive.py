r"""ก๊อปรายงานขึ้นโฟลเดอร์ที่ OneDrive ซิงก์อยู่ แล้วลบไฟล์ชื่อเก่าที่ไม่ใช้แล้ว

ทำไมไม่อัปผ่าน Graph API: เครื่องมือ sharepoint_upload_file จำกัด 1 MB ต่อไฟล์
แต่รายงานของเราไฟล์ละ 8–145 MB จึงอัปตรงไม่ได้เลยสักไฟล์
วางในโฟลเดอร์ที่ OneDrive ซิงก์อยู่แทน ตัว OneDrive จัดการอัปเอง รองรับไฟล์ใหญ่

⚠️ ตัวนี้ "ลบไฟล์" ในโฟลเดอร์ปลายทาง — และการลบจะซิงก์ขึ้น SharePoint ด้วย
   จึงตรวจก่อนเสมอว่าต้นทางครบและไม่มีไฟล์ว่าง ถ้าไม่ครบจะไม่ยอมลบอะไรเลย
   (กันเคสที่รายงานสร้างไม่เสร็จแล้วเผลอลบของเดิมทิ้งจนไม่เหลืออะไร)

    .\.venv\Scripts\python.exe scripts\sync_reports_to_onedrive.py
    .\.venv\Scripts\python.exe scripts\sync_reports_to_onedrive.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

SRC = PROJECT_ROOT / "output" / "_report_2026h1"
DEST_NAME = "รายงานยอดขายย้อนหลัง 13 ร้าน 2026-01 ถึง 2026-07"
MIN_BYTES = 100_000                                       # ไฟล์จริงเล็กสุด ~8 MB


def onedrive_root() -> Path:
    for var in ("OneDriveCommercial", "OneDrive"):
        v = os.environ.get(var)
        if v and Path(v).is_dir():
            return Path(v)
    raise SystemExit("หาโฟลเดอร์ OneDrive ไม่เจอ — ตัวแปร OneDriveCommercial/OneDrive ว่าง")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="แสดงว่าจะทำอะไร แต่ไม่แตะไฟล์จริง")
    args = ap.parse_args()

    src_files = sorted(SRC.glob("*.xlsx"))
    if not src_files:
        print(f"❌ ไม่มีไฟล์ใน {SRC}")
        return 1

    empty = [f.name for f in src_files if f.stat().st_size < MIN_BYTES]
    if empty:
        print(f"❌ มีไฟล์ที่ยังเขียนไม่เสร็จ {empty} — หยุดไว้ก่อน ไม่ก๊อปและไม่ลบอะไร")
        return 1

    dest = onedrive_root() / DEST_NAME
    dest.mkdir(parents=True, exist_ok=True)
    keep = {f.name for f in src_files}

    print(f"ต้นทาง : {SRC}  ({len(src_files)} ไฟล์)")
    print(f"ปลายทาง: {dest}\n")

    print("=== ก๊อปทับ ===")
    for f in src_files:
        mb = f.stat().st_size / 1024 / 1024
        target = dest / f.name
        same = target.exists() and target.stat().st_size == f.stat().st_size
        action = "เท่าเดิม ข้าม" if same else ("ทับของเดิม" if target.exists() else "ไฟล์ใหม่")
        print(f"  {f.name[:52]:<54} {mb:>7.1f} MB  {action}")
        if not args.dry_run and not same:
            shutil.copy2(f, target)

    print("\n=== ลบไฟล์ชื่อเก่าที่ไม่ได้ใช้แล้ว ===")
    stale = [f for f in dest.glob("*.xlsx") if f.name not in keep]
    if not stale:
        print("  ไม่มี")
    for f in stale:
        print(f"  🗑  {f.name}")
        if not args.dry_run:
            f.unlink()

    if args.dry_run:
        print("\n(dry-run — ยังไม่ได้แตะไฟล์จริง)")
        return 0

    total = sum(f.stat().st_size for f in dest.glob("*.xlsx")) / 1024 / 1024
    print(f"\n✅ ปลายทางมี {len(list(dest.glob('*.xlsx')))} ไฟล์ รวม {total:.1f} MB")
    print("   OneDrive จะอัปขึ้น SharePoint ให้เอง — การลบก็จะซิงก์ขึ้นไปด้วย")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
