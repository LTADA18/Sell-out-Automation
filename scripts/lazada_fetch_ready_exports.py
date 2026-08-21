r"""ไปเก็บไฟล์ Export ของ Lazada ที่ "ปั่นเสร็จแล้ว" ในประวัติ — ไม่สั่งงานใหม่

    .\.venv\Scripts\python.exe -u scripts\lazada_fetch_ready_exports.py --shop lazada_02

⚠️ ทำไมต้องมี — เจ้าของงานสั่ง Export เองจากหน้าเว็บได้ แล้วไฟล์ไปรออยู่ในประวัติ
   ระบบเดิมสั่งใหม่อย่างเดียว ไม่เคยไปหยิบของที่พร้อมอยู่แล้วมาใช้
   ยิ่งสั่งใหม่ถี่ ๆ ยิ่งโดน Lazada กัน ("การสร้างงานล้มเหลว")

⚠️ ตัวนี้ "ห้ามสร้างงานใหม่" เด็ดขาด — เปิดกล่องประวัติแล้วโหลดของที่เสร็จแล้วเท่านั้น
   ปุ่มสร้างงานคือ d_button_order_import_export ซึ่งจะไม่ถูกกดในสคริปต์นี้

ไฟล์ที่โหลดได้จะไปอยู่ output/_manual_downloads/
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.config import load_config                  # noqa: E402

DL_DIR = PROJECT_ROOT / "output" / "_manual_downloads"
DIAG = PROJECT_ROOT / "output" / "_diag"

# ⚠️ ทางเปิดประวัติคือ เมนูปุ่ม "ส่งออก" -> รายการ "Export History"
#    ไม่ใช่ไอคอนดาวน์โหลดที่แถบขวา (#app_download_icon) — กดแล้วไม่มีอะไรเกิดขึ้น
#    และรายการในเมนูเป็นภาษาอังกฤษ ทั้งที่หน้าอื่นเป็นไทยหมด
EXPORT_MENU_BTN = 'button[data-spm="d_button_order_import_export"]'
HISTORY_ITEM = [
    'text="Export History"',
    'text="ประวัติการส่งออก"',
]
SHOW_HISTORY = [
    '[data-spm="d_show_history_btn"]',
    'button:has-text("ดูประวัติ")',
]
DL_LINK = 'Download Result File'


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", default="lazada_02")
    ap.add_argument("--max", type=int, default=10, help="โหลดมากสุดกี่ไฟล์")
    args = ap.parse_args()

    DL_DIR.mkdir(parents=True, exist_ok=True)
    DIAG.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    s = cfg.shop(args.shop)
    adapter = build_adapter(s, cfg.settings)
    got = 0

    try:
        page = adapter._open_page(headed=True)
        page.goto(f"{adapter.base_url}/apps/order/list?oldVersion=1",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(7000)

        # ── เปิดประวัติ: กางเมนู "ส่งออก" แล้วเลือก Export History ──
        #    ⚠️ ห้ามกด "Export All" — นั่นคือการสร้างงานใหม่
        try:
            page.locator(EXPORT_MENU_BTN).first.click(timeout=8000)
            page.wait_for_timeout(2500)
        except Exception as exc:                         # noqa: BLE001
            print(f"กางเมนูส่งออกไม่ได้: {str(exc)[:80]}")

        opened = False
        for sel in HISTORY_ITEM:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=2500):
                    loc.click()
                    page.wait_for_timeout(5000)
                    opened = True
                    break
            except Exception:                            # noqa: BLE001
                continue
        print(f"เปิดประวัติได้: {opened}")

        # ── กาง "ดูประวัติ" ถ้ายังไม่กาง ────────────────────────────
        for sel in SHOW_HISTORY:
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=2500):
                    loc.click()
                    page.wait_for_timeout(3500)
                    break
            except Exception:                            # noqa: BLE001
                continue

        page.screenshot(path=str(DIAG / f"{args.shop}_history.png"))
        print(f"ภาพหน้าจอ: {DIAG / (args.shop + '_history.png')}")

        # ── อ่านตารางประวัติออกมาดูก่อนว่ามีอะไรบ้าง ─────────────────
        rows = page.evaluate("""
        () => {
          const out = [];
          document.querySelectorAll('tr').forEach(tr => {
            const t = (tr.innerText || '').replace(/\\s+/g, ' ').trim();
            if (!t) return;
            if (/\\d{4}-\\d{2}-\\d{2}/.test(t) || /Download Result File/i.test(t))
              out.push(t.slice(0, 160));
          });
          return out.slice(0, 25);
        }
        """)
        print(f"\n=== แถวในประวัติ {len(rows)} แถว ===")
        for r in rows:
            print("  " + r)

        links = page.get_by_text(DL_LINK)
        n = links.count()
        print(f"\n=== ไฟล์ที่พร้อมโหลด {n} ไฟล์ ===")
        if n == 0:
            print("  ไม่มีไฟล์ที่เสร็จแล้วในประวัติ")
            return 0

        for i in range(min(n, args.max)):
            try:
                with page.expect_download(timeout=120_000) as dl:
                    links.nth(i).click()
                d = dl.value
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                dest = DL_DIR / f"{args.shop}_ready_{stamp}_{i}_{d.suggested_filename}"
                d.save_as(str(dest))
                size = dest.stat().st_size / 1024 / 1024
                print(f"  ✅ [{i+1}/{min(n, args.max)}] {dest.name}  ({size:,.1f} MB)")
                got += 1
                page.wait_for_timeout(2500)
            except Exception as exc:                     # noqa: BLE001
                print(f"  ❌ [{i+1}] โหลดไม่ได้: {type(exc).__name__}: {str(exc)[:90]}")

        print(f"\nโหลดได้ {got} ไฟล์ → {DL_DIR}")
    finally:
        adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
