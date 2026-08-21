r"""ส่องว่าจะเปิด "ประวัติการส่งออก" ของ Lazada ได้ทางไหน โดยไม่สร้างงานใหม่

    .\.venv\Scripts\python.exe scripts\diag_lazada_menu.py --shop lazada_02

⚠️ ไม่กดยืนยันสร้างงาน — แค่กางเมนูดูว่ามีรายการอะไรบ้าง
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.config import load_config                  # noqa: E402

DIAG = PROJECT_ROOT / "output" / "_diag"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", default="lazada_02")
    args = ap.parse_args()
    DIAG.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    adapter = build_adapter(cfg.shop(args.shop), cfg.settings)
    try:
        page = adapter._open_page(headed=True)
        page.goto(f"{adapter.base_url}/apps/order/list?oldVersion=1",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(7000)

        # ── 1. โครงของไอคอนแถบขวา ────────────────────────────────
        print("=== โครงรอบ #app_download_icon ===")
        info = page.evaluate("""
        () => {
          const el = document.querySelector('#app_download_icon');
          if (!el) return 'ไม่เจอ element';
          const r = el.getBoundingClientRect();
          return {
            outer: el.outerHTML.slice(0, 300),
            rect: {x: Math.round(r.x), y: Math.round(r.y),
                   w: Math.round(r.width), h: Math.round(r.height)},
            parent: el.parentElement ? el.parentElement.outerHTML.slice(0, 220) : '',
            children: el.innerHTML.slice(0, 220),
          };
        }
        """)
        print(f"  {info}")

        # ── 2. กดที่พิกัดจริงแทนการกด element ──────────────────────
        if isinstance(info, dict):
            r = info["rect"]
            cx, cy = r["x"] + r["w"] / 2, r["y"] + r["h"] / 2
            print(f"\nกดที่พิกัด ({cx:.0f}, {cy:.0f})")
            page.mouse.click(cx, cy)
            page.wait_for_timeout(4000)
            page.screenshot(path=str(DIAG / f"{args.shop}_after_icon_click.png"))
            has_dialog = page.evaluate(
                "() => !!document.querySelector('[data-spm=\"excel_export_dialog\"]')")
            print(f"  กล่อง excel_export_dialog เปิดไหม: {has_dialog}")

        # ── 3. กางเมนู "ส่งออก" ดูว่ามีรายการอะไร (ไม่กดยืนยัน) ────
        print("\n=== เมนูใต้ปุ่ม 'ส่งออก' ===")
        try:
            btn = page.locator('button[data-spm="d_button_order_import_export"]').first
            if btn.is_visible(timeout=4000):
                btn.click()
                page.wait_for_timeout(3000)
                items = page.evaluate("""
                () => Array.from(document.querySelectorAll(
                        '.next-menu-item, [role=menuitem], li'))
                       .map(e => (e.innerText || '').replace(/\\s+/g,' ').trim())
                       .filter(t => t && t.length < 60).slice(0, 20)
                """)
                for t in items:
                    print(f"  · {t}")
                page.screenshot(path=str(DIAG / f"{args.shop}_menu.png"))
            else:
                print("  ไม่เห็นปุ่มส่งออก")
        except Exception as exc:                         # noqa: BLE001
            print(f"  กางเมนูไม่ได้: {str(exc)[:90]}")

        print(f"\nภาพ: {DIAG}")
        page.wait_for_timeout(20_000)
    finally:
        adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
