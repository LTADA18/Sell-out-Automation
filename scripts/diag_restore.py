r"""ทดสอบว่า _restore_session_cookies เป็นตัวทำให้หลุด login หรือเปล่า

สงสัย: โปรไฟล์ Chrome เก็บ cookie ที่ล็อกอินอยู่แล้ว แต่โค้ดยัด cookie จากไฟล์
state (ซึ่งอาจเป็นของรอบที่หลุดไปแล้ว) ทับเข้าไป ทำให้กลายเป็นไม่ได้ล็อกอิน

เทียบ 2 กรณีกับโปรไฟล์เดียวกัน:
  A) เปิดปกติ (ยัด cookie จาก state)
  B) เปิดโดยไม่ยัด cookie เลย ใช้แต่ของในโปรไฟล์

    python scripts\diag_restore.py --shop shopee_03
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
url_path = ORDERS.get(s.platform, "/")


def check(restore: bool) -> str:
    a = build_adapter(s, cfg.settings)
    if not restore:
        a._restore_session_cookies = lambda: None        # ปิดการยัด cookie
    try:
        p = a._open_page(headed=False)
        p.goto(f"{a.base_url}{url_path}", wait_until="domcontentloaded")
        p.wait_for_timeout(9000)
        u = p.url
        ok = not any(h in u.lower() for h in ("login", "signin"))
        return f"{'✅ ล็อกอินอยู่' if ok else '🔴 เด้งหน้า login'}  {u[:75]}"
    finally:
        a.close()


print(f"=== {s.shop_id} ===")
print(f"A) เปิดปกติ (ยัด cookie จาก state) : {check(True)}")
print(f"B) ไม่ยัด cookie เลย                : {check(False)}")
