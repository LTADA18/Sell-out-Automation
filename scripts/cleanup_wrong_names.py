r"""ลบไฟล์ที่ตั้งชื่อร้านไม่ตรงมาตรฐาน — ค่าเริ่มต้นคือแค่แสดงรายการ ไม่ลบ

เกิดจาก reparse_raw.py รุ่นแรกใช้ display_name ดิบแทนชื่อมาตรฐาน
ชื่อไฟล์จึงไม่ตรงกับสายปกติ ไฟล์เก่าไม่ถูกทับ กลายเป็นมีสองชุดอยู่ด้วยกัน
ถ้าปล่อยไว้ ขั้นโหลดจะนับซ้ำ 6 ร้าน ยอดขายพองทันที

    .\.venv\Scripts\python.exe -u scripts\cleanup_wrong_names.py
    .\.venv\Scripts\python.exe -u scripts\cleanup_wrong_names.py --delete
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import load_config          # noqa: E402
from src.core.exporter import safe_name          # noqa: E402
from src.core.naming import canonical_name       # noqa: E402

DAY_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delete", action="store_true", help="ลบจริง ไม่ใส่ = แค่แสดงรายการ")
    args = ap.parse_args()

    cfg = load_config()
    # ชื่อไฟล์ที่ถูกต้องของแต่ละร้าน
    want = {s.shop_id: safe_name(canonical_name(s.shop_id, s.display_name))
            for s in cfg.shops}
    plat = {s.shop_id: s.platform for s in cfg.shops}

    doomed: list[Path] = []
    for day_dir in sorted(PROJECT_ROOT.joinpath("output").iterdir()):
        if not (day_dir.is_dir() and DAY_DIR.match(day_dir.name)):
            continue
        for folder in (day_dir, day_dir / "screened"):
            if not folder.is_dir():
                continue
            for f in folder.glob("*.xlsx"):
                m = re.match(r"(\w+)_((?:shopee|tiktok|lazada)_\d+)_(.+?)_\d{4}-\d{2}-\d{2}",
                             f.stem)
                if not m:
                    continue
                _, shop_id, name_part = m.groups()
                if shop_id not in want:
                    continue
                if name_part != want[shop_id]:
                    doomed.append(f)

    if not doomed:
        print("✅ ไม่มีไฟล์ชื่อผิด")
        return 0

    by_shop: dict[str, int] = {}
    for f in doomed:
        m = re.match(r"\w+_((?:shopee|tiktok|lazada)_\d+)_(.+?)_\d{4}-\d{2}-\d{2}", f.stem)
        key = f"{m.group(1)} : {m.group(2)}"
        by_shop[key] = by_shop.get(key, 0) + 1

    print(f"พบไฟล์ชื่อไม่ตรงมาตรฐาน {len(doomed)} ไฟล์\n")
    print(f"{'ร้าน : ชื่อที่ผิด':<58} {'ไฟล์':>5}   ชื่อที่ถูก")
    for key, n in sorted(by_shop.items()):
        shop_id = key.split(" : ")[0]
        print(f"  {key:<56} {n:>5}   {want[shop_id]}")

    if not args.delete:
        print("\n(ยังไม่ลบ — ใส่ --delete เพื่อลบจริง)")
        return 0

    for f in doomed:
        f.unlink()
    print(f"\n🗑️ ลบแล้ว {len(doomed)} ไฟล์")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
