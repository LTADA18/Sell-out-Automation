r"""ไล่ทีละขั้นว่าเฟส "เก็บไฟล์" ของ Shopee ค้างตรงไหน

อาการ: Locator.click: Timeout 60000ms exceeded ซ้ำทุกรอบ
       แต่ไม่มีภาพหน้าจอ เพราะ error เกิดนอก _do_export ที่ถ่ายภาพให้

    python scripts\diag_collect_step.py --shop shopee_08
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.adapters.shopee import SEL, _click_first        # noqa: E402
from src.core.config import load_config                  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--shop", default="shopee_08")
args = ap.parse_args()

cfg = load_config()
s = cfg.shop(args.shop)
adapter = build_adapter(s, cfg.settings)
shot = PROJECT_ROOT / "logs" / "screenshots"
shot.mkdir(parents=True, exist_ok=True)

try:
    print("1) เปิดโปรไฟล์")
    page = adapter._open_page(headed=False)

    print("2) ไปหน้าคำสั่งซื้อ")
    page.goto(adapter.orders_url, wait_until="domcontentloaded")
    page.wait_for_timeout(9000)
    print(f"   URL: {page.url[:80]}")
    print(f"   ร้านที่เปิดอยู่: {adapter._current_shop_name(page)!r}  ต้องการ {s.web_name!r}")

    print("3) เลือกร้าน (_enter_shop)")
    adapter._enter_shop(page)
    print(f"   หลังเลือก URL: {page.url[:80]}")
    print(f"   ร้านที่เปิดอยู่: {adapter._current_shop_name(page)!r}")

    print("4) ตรวจ login")
    adapter._ensure_logged_in(page, adapter.orders_url)
    print("   ผ่าน")

    print("5) ปิดทัวร์แนะนำ")
    adapter._dismiss_onboarding(page)
    print("   ผ่าน")

    print("6) เปิดประวัติการดาวน์โหลด")
    ok = _click_first(page, SEL["history_btn"], 8000)
    print(f"   กดปุ่มประวัติ: {ok}")
    page.wait_for_timeout(3000)

    names = adapter._report_names(page)
    print(f"7) ไฟล์ในประวัติ {len(names)} รายการ")
    for n in sorted(names)[:12]:
        print(f"      {n[:70]}")

    print("8) หาปุ่มดาวน์โหลดของแต่ละแถว")
    for n in sorted(names)[:5]:
        btn = adapter._try_row_download_button(page, n)
        state = "ไม่เจอปุ่ม (ยังปั่นอยู่)"
        if btn is not None:
            try:
                state = f"visible={btn.is_visible(timeout=2000)} enabled={btn.is_enabled(timeout=2000)}"
            except Exception as e:                       # noqa: BLE001
                state = f"เจอปุ่มแต่เช็คสถานะไม่ได้: {str(e)[:40]}"
        print(f"      {n[:52]:<54} {state}")

    p = shot / f"{args.shop}_diag_collect.png"
    page.screenshot(path=str(p))
    print(f"\nถ่ายภาพไว้ที่ {p.name}")
finally:
    adapter.close()
