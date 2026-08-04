r"""เปิดเบราว์เซอร์ด้วย "โปรไฟล์ที่ล็อกอินไว้แล้ว" ของร้านนั้น ให้กด Export เอง

ทำไมต้องใช้ตัวนี้แทนการเปิด Chrome ปกติ:
    session ที่ล็อกอินไว้อยู่ใน data/profiles/<ร้าน> ไม่ใช่ใน Chrome ปกติ
    เปิดจากที่อื่น Shopee เห็นเป็นอุปกรณ์ใหม่ → ขอ OTP ทุกครั้ง
    เปิดจากโปรไฟล์นี้จะเข้าหลังบ้านได้เลย ไม่ต้อง OTP

ต่างจาก `cli login` ตรงที่ตัวนั้นรอ input() กด Enter (ใช้กับ background ไม่ได้)
และไม่ได้จัดการเรื่องที่อยู่ไฟล์ดาวน์โหลด

⚠️ ไฟล์ที่กดดาวน์โหลดในหน้าต่างนี้ ปกติ Playwright จะเก็บไว้ในโฟลเดอร์ชั่วคราว
   แล้วลบทิ้งตอนปิด → ที่นี่ดัก event ไว้เซฟลง output/_manual_downloads/ เอง

รัน:
    .\.venv\Scripts\python.exe scripts\open_shop_browser.py --shop shopee_02
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.config import load_config                  # noqa: E402

DL_DIR = PROJECT_ROOT / "output" / "_manual_downloads"
MAX_MINUTES = 120


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", required=True)
    args = ap.parse_args()

    cfg = load_config()
    s = cfg.shop(args.shop)
    DL_DIR.mkdir(parents=True, exist_ok=True)

    adapter = build_adapter(s, cfg.settings)
    closed = {"v": False}

    def save_download(d) -> None:
        try:
            target = DL_DIR / d.suggested_filename
            n = 1
            while target.exists():                       # กันชื่อชนถ้าโหลดซ้ำ
                target = DL_DIR / f"{target.stem}_{n}{target.suffix}"
                n += 1
            d.save_as(str(target))
            print(f"  ⬇  เซฟแล้ว: {target.name}", flush=True)
        except Exception as exc:                         # noqa: BLE001
            print(f"  ⚠️ เซฟไฟล์ไม่สำเร็จ: {exc}", flush=True)

    def wire(page) -> None:
        page.on("download", save_download)

    try:
        page = adapter._open_page(headed=True)
        adapter._context.on("close", lambda *_: closed.__setitem__("v", True))
        adapter._context.on("page", wire)                # แท็บใหม่ก็ดักด้วย
        wire(page)

        page.goto(adapter.orders_url, wait_until="domcontentloaded")
        page.wait_for_timeout(8000)

        # ข้ามหน้า "เลือกร้านที่จะจัดการ" ให้เอง — 1 บัญชีดูแลหลายร้าน
        # ถ้าเลือกผิดร้านจะได้ข้อมูลผิดโดยไม่มีอะไรเตือน
        try:
            adapter._enter_shop(page)
            adapter._dismiss_onboarding(page)
        except Exception as exc:                         # noqa: BLE001
            print(f"  (ข้ามขั้นเลือกร้านไม่สำเร็จ ทำเองในหน้าต่างได้: {exc})")

        print()
        print(f"  ร้าน  : {s.display_name} ({s.shop_id})")
        print(f"  หน้า  : {adapter.orders_url}")
        print()
        print("  กด 'ดาวน์โหลด' → เลือกช่วง 1/1/2026 – 31/7/2026 → ยืนยัน")
        print("  ไฟล์จะไปอยู่ใน ประวัติการดาวน์โหลด รอสักพักแล้วกดโหลด")
        print(f"  ไฟล์ที่โหลดจะถูกเซฟไปที่ {DL_DIR.relative_to(PROJECT_ROOT)}")
        print()
        print("  ปิดหน้าต่างเบราว์เซอร์เมื่อเสร็จ (อย่าปิดด้วย Task Manager)")
        print()

        deadline = time.time() + MAX_MINUTES * 60
        while not closed["v"] and time.time() < deadline:
            time.sleep(2)
        print("  ปิดหน้าต่างแล้ว — เก็บ session เรียบร้อย")
    finally:
        # ต้องปิดผ่าน close() เสมอ ไม่งั้น cookie ที่ค้างในหน่วยความจำหาย
        adapter.close()

    files = sorted(DL_DIR.glob("*"))
    print(f"\n  ไฟล์ในโฟลเดอร์ตอนนี้ {len(files)} ไฟล์")
    for f in files:
        print(f"    {f.name}  ({f.stat().st_size / 1024 / 1024:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
