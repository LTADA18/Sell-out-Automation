r"""ดูหน้าเลือกร้านจริง ๆ ว่ามีอะไร ทำไม tr ถึงว่าง"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.config import load_config                  # noqa: E402

cfg = load_config()
s = cfg.shop("shopee_03")
a = build_adapter(s, cfg.settings)

try:
    p = a._open_page(headed=False)
    p.goto(a.orders_url, wait_until="domcontentloaded")
    p.wait_for_timeout(8000)
    print(f"1) หลัง goto orders : {p.url[:80]}")
    print(f"   ชื่อร้านที่อ่านได้ : {a._current_shop_name(p)!r}  (ต้องการ {s.web_name!r})")

    a._ensure_logged_in(p, a.orders_url)
    print(f"2) หลัง ensure_logged_in : {p.url[:80]}")
    print(f"   ชื่อร้านที่อ่านได้ : {a._current_shop_name(p)!r}")

    p.goto(f"{a.base_url}/portal/shop", wait_until="domcontentloaded")
    p.wait_for_timeout(10000)
    print(f"3) หน้าเลือกร้าน : {p.url[:80]}")
    print(f"   tr = {p.locator('tr').count()}  |  a = {p.locator('a').count()}")

    body = ""
    try:
        body = p.locator("body").inner_text()[:400].replace("\n", " | ")
    except Exception as e:                               # noqa: BLE001
        body = f"(อ่านไม่ได้ {e})"
    print(f"   ข้อความบนหน้า: {body}")

    print(f"\n   มีคำว่า {s.web_name!r} บนหน้าไหม: {s.web_name.lower() in body.lower()}")
    Path("logs/screenshots").mkdir(parents=True, exist_ok=True)
    p.screenshot(path="logs/screenshots/picker2.png")
    print("   ถ่ายภาพไว้ที่ logs/screenshots/picker2.png")
finally:
    a.close()
