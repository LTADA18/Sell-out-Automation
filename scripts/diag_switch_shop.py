r"""หาวิธีสลับร้านเมื่อโปรไฟล์จำร้านล่าสุดไว้แล้ว

ปัญหา: /portal/shop?next=... เด้งกลับหน้าคำสั่งซื้อของร้านเดิม
        ทำให้สลับไปร้านที่ 2 ของบัญชีเดียวกันไม่ได้ (shopee_08)

ลองหลายวิธีแล้ววัดผลจริงว่าวิธีไหนพาไปหน้าเลือกร้านได้
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.config import load_config                  # noqa: E402

cfg = load_config()
s = cfg.shop("shopee_08")
adapter = build_adapter(s, cfg.settings)
want = s.web_name

try:
    page = adapter._open_page(headed=False)
    page.goto(adapter.orders_url, wait_until="domcontentloaded")
    page.wait_for_timeout(9000)
    print(f"เริ่มที่ : {page.url[:90]}")
    print(f"ร้านที่เปิดอยู่ : {adapter._current_shop_name(page)!r}   ต้องการ {want!r}\n")

    attempts = [
        ("goto /portal/shop เปล่า ๆ", lambda: page.goto(
            f"{adapter.base_url}/portal/shop", wait_until="domcontentloaded")),
        ("goto /portal/shop?next=%2Fportal%2Fsale%2Forder", lambda: page.goto(
            f"{adapter.base_url}/portal/shop?next=%2Fportal%2Fsale%2Forder",
            wait_until="domcontentloaded")),
        ("goto /portal/shop/select", lambda: page.goto(
            f"{adapter.base_url}/portal/shop/select", wait_until="domcontentloaded")),
    ]

    for name, act in attempts:
        try:
            act()
            page.wait_for_timeout(6000)
            ok = "/portal/shop" in page.url
            rows = page.locator("tr").count()
            print(f"{'✅' if ok else '❌'} {name}")
            print(f"     -> {page.url[:90]}  (แถวในตาราง {rows})")
            if ok and rows > 1:
                found = page.locator(f'tr:has-text("{want}")').count()
                print(f"     เจอแถวของ {want!r}: {found}")
                if found:
                    print("     *** วิธีนี้ใช้ได้ ***")
                    break
        except Exception as e:                           # noqa: BLE001
            print(f"❌ {name} -> {type(e).__name__}: {str(e)[:70]}")
        # กลับไปหน้าคำสั่งซื้อก่อนลองวิธีถัดไป ให้สภาพเริ่มต้นเหมือนกัน
        try:
            page.goto(adapter.orders_url, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
        except Exception:                                # noqa: BLE001
            pass

    print("\n=== เมนูบัญชีมุมขวาบน มีตัวเลือกสลับร้านไหม ===")
    try:
        page.goto(adapter.orders_url, wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        for sel in (".shopee-header-bar [class*='account']", "[class*='account-info']",
                    ".shopee-header-bar__user", "[class*='header'] [class*='user']"):
            loc = page.locator(sel).first
            if loc.count():
                loc.hover()
                page.wait_for_timeout(2000)
                txt = page.locator("body").inner_text()
                for kw in ("สลับร้าน", "เปลี่ยนร้าน", "เลือกร้าน", "Switch", "ร้านค้าของฉัน"):
                    if kw in txt:
                        print(f"  เจอคำว่า {kw!r} หลัง hover {sel}")
                break
    except Exception as e:                               # noqa: BLE001
        print(f"  ลองไม่ได้: {e}")
finally:
    adapter.close()
