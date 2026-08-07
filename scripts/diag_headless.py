r"""ทดสอบว่า headless เป็นเหตุให้ Shopee เด้งหน้า login หรือเปล่า

สังเกตจาก 2026-08-07: เปิดแบบ headed แล้วล็อกอินอยู่ แต่ headless เด้ง login
ทั้งที่ใช้โปรไฟล์เดียวกันและห่างกันไม่ถึงนาที

ถ้าจริง แปลว่ารอบดึงรายวัน (ซึ่งใช้ headless) จะพังกับร้านที่หลังบ้านคัดกรอง headless
    python scripts\diag_headless.py --shop shopee_03
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.config import load_config                  # noqa: E402

ORDERS = {"shopee": "/portal/sale/order", "tiktok": "/order",
          "lazada": "/apps/order/list?oldVersion=1"}

ap = argparse.ArgumentParser()
ap.add_argument("--shop", required=True)
args = ap.parse_args()

cfg = load_config()
s = cfg.shop(args.shop)
path = ORDERS.get(s.platform, "/")


def check(headed: bool) -> str:
    a = build_adapter(s, cfg.settings)
    try:
        p = a._open_page(headed=headed)
        p.goto(f"{a.base_url}{path}", wait_until="domcontentloaded")
        p.wait_for_timeout(9000)
        u = p.url
        ok = not any(h in u.lower() for h in ("login", "signin"))
        return f"{'✅ ล็อกอินอยู่' if ok else '🔴 เด้งหน้า login'}   {u[:70]}"
    finally:
        a.close()


print(f"=== {s.shop_id} — ทดสอบสลับโหมด 2 รอบเพื่อตัดเรื่องจังหวะเวลา ===")
print(f"1) headless : {check(False)}")
print(f"2) headed   : {check(True)}")
print(f"3) headless : {check(False)}")
print(f"4) headed   : {check(True)}")
