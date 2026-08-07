r"""ล็อกอินแล้วเซฟ session — ตรวจด้วยการ "ลองเข้าหน้าจริง" ไม่ใช่แค่ดู URL

⚠️ ทำไมต้องมีตัวนี้ ทั้งที่มี cli login อยู่แล้ว:
   cli login เฝ้าดู page.url เฉย ๆ แต่ค่านั้นไม่อัปเดตตามที่ผู้ใช้เห็นบนจอ
   (2026-08-07: จอแสดง /portal/shop ล็อกอินเรียบร้อย แต่ page.url ยังค้างที่
    /account/signin ตัวตรวจจึงรอเก้อจนหมดเวลา ผู้ใช้ต้องล็อกอินซ้ำหลายรอบ)

   ตัวนี้ "นำทางไปหน้าคำสั่งซื้อจริง" ทุก 10 วินาที ถ้าไปถึงได้ = ล็อกอินแล้วแน่นอน
   แล้วเซฟทันทีขณะ context ยังเปิดอยู่ ไม่ต้องพึ่งการอ่าน URL

    python scripts\login_save.py --shop shopee_03
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.playwright_base import LOGIN_URL_HINTS   # noqa: E402
from src.adapters.registry import build_adapter            # noqa: E402
from src.core.config import load_config                    # noqa: E402

ORDERS = {
    "shopee": "/portal/sale/order",
    "tiktok": "/order",
    "lazada": "/apps/order/list?oldVersion=1",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", required=True)
    ap.add_argument("--wait", type=int, default=20, help="รอกี่นาที")
    args = ap.parse_args()

    cfg = load_config()
    s = cfg.shop(args.shop)
    adapter = build_adapter(s, cfg.settings)

    # ⚠️ ลบ state เก่าทิ้งก่อน — ถ้าเป็นของตอนหลุด login การยัดกลับเข้า context
    #    อาจไปทับ cookie ดีที่โปรไฟล์เพิ่งได้มา (สงสัยว่าเป็นเหตุหนึ่งของปัญหาวันนี้)
    if adapter.session_file.exists():
        bak = adapter.session_file.with_suffix(".json.bak")
        adapter.session_file.replace(bak)
        print(f"  ย้าย state เก่าไปเป็น {bak.name} (กันไปทับ cookie ใหม่)")

    url = f"{adapter.base_url}{ORDERS.get(s.platform, '/')}"
    ok = False
    try:
        page = adapter._open_page(headed=True)
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(5000)

        print()
        print(f"  ร้าน : {s.display_name} ({s.shop_id})")
        print(f"  ล็อกอินในหน้าต่างที่เปิดขึ้นมาได้เลย — ไม่ต้องกดอะไรอื่น")
        print(f"  ระบบจะลองเข้าหน้าคำสั่งซื้อทุก 10 วินาที พอเข้าได้จะเซฟให้เอง")
        print(f"  (รอสูงสุด {args.wait} นาที)")
        print()

        deadline = time.time() + args.wait * 60
        while time.time() < deadline:
            time.sleep(10)
            try:
                page.goto(url, wait_until="domcontentloaded")
                page.wait_for_timeout(4000)
                cur = page.url.lower()
            except Exception as exc:                     # noqa: BLE001
                print(f"  หน้าต่างถูกปิด — ยังไม่ได้เซฟ ({str(exc)[:50]})")
                return 1
            if any(h in cur for h in LOGIN_URL_HINTS):
                print(f"  ยังไม่ล็อกอิน ({page.url[:60]})", flush=True)
                continue
            print(f"  ✅ เข้าหน้าคำสั่งซื้อได้แล้ว: {page.url[:70]}")
            ok = True
            break

        if not ok:
            print("  หมดเวลารอ — ยังไม่ได้เซฟ")
            return 1

        # เซฟ 2 รอบ เผื่อ cookie ที่ตั้งหลัง redirect
        adapter._save_session()
        page.wait_for_timeout(4000)
        adapter._save_session()
        n = len(__import__("json").loads(
            adapter.session_file.read_text(encoding="utf-8")).get("cookies", []))
        print(f"  เก็บ session แล้ว {n} cookie → {adapter.session_file.name}")
    finally:
        adapter.close()                                  # ปิดแบบสะอาด cookie ไม่หาย
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
