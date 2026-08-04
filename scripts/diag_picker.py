r"""ดู DOM จริงของหัวปฏิทิน Shopee — หาว่าปุ่มย้อน "เดือน" ชื่อ class อะไร

ใช้ครั้งเดียวเพื่อหา selector ที่ถูก ไม่เกี่ยวกับรอบรายวัน
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.adapters.shopee import SEL, _click_first        # noqa: E402
from src.core.config import load_config                  # noqa: E402

cfg = load_config()
s = cfg.shop("shopee_02")
adapter = build_adapter(s, cfg.settings)

try:
    page = adapter._open_page(headed=False)
    page.goto(adapter.orders_url, wait_until="domcontentloaded")
    page.wait_for_timeout(9000)
    adapter._enter_shop(page)
    adapter._ensure_logged_in(page, adapter.orders_url)
    adapter._dismiss_onboarding(page)

    _click_first(page, SEL["open_modal"], 15000)
    page.wait_for_timeout(3000)
    page.locator(SEL["range_input"][0]).first.click()
    page.wait_for_timeout(2000)

    print("\n=== HTML ของหัวปฏิทิน ===")
    for side in ("left", "right"):
        hdr = page.locator(f".eds-daterange-picker-panel__body-{side} .eds-picker-header").first
        if hdr.count():
            html = hdr.inner_html()
            print(f"\n--- {side} ---")
            print(html[:1500])

    print("\n=== ปุ่มทั้งหมดในแผงปฏิทิน (class + ข้อความ) ===")
    seen = set()
    for el in page.locator(".eds-daterange-picker-panel button, "
                           ".eds-daterange-picker-panel [class*='prev'], "
                           ".eds-daterange-picker-panel [class*='next']").all():
        try:
            cls = (el.get_attribute("class") or "").strip()
            txt = (el.inner_text() or "").strip()[:20]
            key = f"{cls}|{txt}"
            if cls and key not in seen:
                seen.add(key)
                print(f"  class={cls!r}  text={txt!r}")
        except Exception:                                # noqa: BLE001
            continue

    print("\n=== นับจำนวนที่แต่ละ selector เจอ ===")
    for sel in (".eds-picker-header__prev", ".eds-picker-header__next",
                ".eds-picker-header__prev-month", ".eds-picker-header__super-prev",
                "[class*='picker-header'] [class*='prev']"):
        print(f"  {sel:<45} {page.locator(sel).count()}")
finally:
    adapter.close()
