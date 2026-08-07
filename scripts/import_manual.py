r"""นำไฟล์ Export ที่ดาวน์โหลดเองเข้าระบบ — บันทึกลง run_log + ออก Excel เหมือนดึงเอง

ใช้เมื่อ session ของร้านนั้นถูกเตะจนระบบดึงเองไม่ได้ แต่คนเปิดหน้าเว็บดาวน์โหลดได้

⚠️ ต้องระบุ --shop เอง เพราะไฟล์ Export ของ Shopee/TikTok ไม่มีคอลัมน์บอกชื่อร้าน
   ถ้าใส่ผิด ยอดขายจะถูกติดป้ายผิดร้านโดยไม่มีอะไรเตือน

    python scripts\import_manual.py --shop shopee_03 --file "C:\path\to\file.xlsx"
    python scripts\import_manual.py --shop shopee_03 --latest    # ใช้ไฟล์ล่าสุดใน Downloads
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.config import load_config                  # noqa: E402
from src.core.exporter import export_shop                # noqa: E402
from src.core.models import RunResult, RunStatus         # noqa: E402
from src.core.runner import date_range                   # noqa: E402
from src.core.status_store import StatusStore            # noqa: E402

SEARCH_DIRS = [
    Path.home() / "Downloads",
    PROJECT_ROOT / "output" / "_manual_downloads",
    Path.home() / "AppData" / "Local" / "Temp",
]


def newest_export() -> Path | None:
    cands: list[Path] = []
    for d in SEARCH_DIRS:
        if not d.exists():
            continue
        for p in d.glob("*"):
            if p.is_file() and p.stat().st_size > 3000:
                if p.suffix.lower() in (".xlsx", ".zip", ".csv") or not p.suffix:
                    cands.append(p)
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", required=True)
    ap.add_argument("--file")
    ap.add_argument("--latest", action="store_true", help="ใช้ไฟล์ที่ดาวน์โหลดล่าสุด")
    ap.add_argument("--date", help="วันที่ของข้อมูล (ไม่ใส่ = เมื่อวาน)")
    args = ap.parse_args()

    src = Path(args.file) if args.file else newest_export()
    if not src or not src.exists():
        print("ไม่พบไฟล์ — ระบุด้วย --file")
        return 1
    print(f"ไฟล์  : {src.name}  ({src.stat().st_size/1024:.0f} KB)")

    cfg = load_config()
    s = cfg.shop(args.shop)
    print(f"ร้าน  : {s.shop_id} — {s.display_name} ({s.platform})")

    run_date = date.fromisoformat(args.date) + date_range.__defaults__[0] if False else None
    run_date = date.today() if not args.date else date.fromisoformat(args.date)
    d_from, d_to = date_range(cfg, run_date)
    print(f"ถือเป็นข้อมูลของวันที่ {d_from} ถึง {d_to}")

    adapter = build_adapter(s, cfg.settings)
    try:
        # ⚠️ ถ้าเป็น .zip ให้แตกก่อน (Shopee ตัดไฟล์เป็นหลายส่วนเมื่อข้อมูลเยอะ)
        if src.suffix.lower() == ".zip":
            import zipfile
            out = PROJECT_ROOT / "output" / "_manual_downloads" / (src.stem + "_x")
            out.mkdir(parents=True, exist_ok=True)
            rows = []
            with zipfile.ZipFile(src) as zf:
                for n in sorted(x for x in zf.namelist()
                                if x.lower().endswith((".xlsx", ".xls", ".csv"))):
                    t = out / Path(n).name
                    t.write_bytes(zf.read(n))
                    rows.extend(adapter.map.read_export(t))
        else:
            rows = adapter.map.read_export(src)
        print(f"อ่านได้ {len(rows):,} แถว")

        orders = adapter.normalize(rows)
        print(f"ยุบเป็น {len(orders):,} ออเดอร์")
        if not orders:
            print("ไม่มีข้อมูล — ไม่บันทึก")
            return 1

        path = export_shop(
            orders,
            shop_id=s.shop_id, platform=s.platform, shop_name=s.display_name,
            run_date=run_date.isoformat(),
            date_from=d_from.isoformat(), date_to=d_to.isoformat(),
            output_dir=PROJECT_ROOT / cfg.settings.paths.output_dir,
            archive_dir=PROJECT_ROOT / cfg.settings.paths.output_dir / "_archive",
            notes=f"นำเข้าจากไฟล์ที่ดาวน์โหลดเอง ({src.name})",
        )
        print(f"Excel : {path.name}")

        now = datetime.now()
        with StatusStore(PROJECT_ROOT / cfg.settings.paths.db_path) as store:
            store.upsert(RunResult(
                run_id=f"manual_{now:%Y%m%d_%H%M%S}",
                run_date=run_date.isoformat(),
                shop_id=s.shop_id, platform=s.platform, shop_name=s.display_name,
                status=RunStatus.SUCCESS,
                started_at=now, finished_at=datetime.now(),
                orders_fetched=len(orders), rows_written=len(orders),
                output_file=str(path),
                notes="นำเข้าด้วยมือ",
            ))
        print(f"✅ บันทึกลง run_log แล้ว — {len(orders):,} ออเดอร์")
    finally:
        adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
