r"""ดูว่าเปิดโปรไฟล์แล้วไปโผล่หน้าไหนจริง ๆ — หาสาเหตุที่ขึ้น 'session หมดอายุ'"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.config import load_config                  # noqa: E402

cfg = load_config()
s = cfg.shop("shopee_03")
adapter = build_adapter(s, cfg.settings)

try:
    page = adapter._open_page(headed=False)
    print(f"session file : {adapter.session_file}")
    print(f"  มีไฟล์ : {adapter.session_file.exists()}")

    page.goto(adapter.orders_url, wait_until="domcontentloaded")
    page.wait_for_timeout(10000)

    print(f"\nURL ที่ไปโผล่ : {page.url}")
    print(f"ชื่อร้านที่เปิดอยู่ : {adapter._current_shop_name(page)!r}")

    body = ""
    try:
        body = page.locator("body").inner_text()[:400].replace("\n", " | ")
    except Exception as e:                               # noqa: BLE001
        body = f"(อ่าน body ไม่ได้: {e})"
    print(f"\nข้อความบนหน้า (400 ตัวแรก):\n  {body}")

    print("\nสัญญาณหน้า login:")
    for kw in ("login", "signin", "เข้าสู่ระบบ", "รหัสผ่าน"):
        print(f"  {kw!r} ใน URL={kw in page.url.lower()}  ในหน้า={kw in body.lower()}")

    adapter._screenshot_on_error(page, "diag_session")
    print("\nถ่ายภาพหน้าจอไว้ใน logs/screenshots/ แล้ว")
finally:
    adapter.close()
