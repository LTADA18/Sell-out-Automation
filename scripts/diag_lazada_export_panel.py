r"""ส่องหน้า "ข้อมูลการส่งออก" ของ Lazada ว่าปุ่มดาวน์โหลดคืออะไรกันแน่

    .\.venv\Scripts\python.exe scripts\diag_lazada_export_panel.py --shop lazada_02

⚠️ ทำไมต้องมี — ไล่แก้ selector ด้วยการเดามา 2 รอบแล้วยังไม่ตรง (2026-08-18)
   รอบแรกเดาว่าเวลารอไม่พอ รอบสองเดาว่าข้อความปุ่มไม่ตรง ทั้งคู่ผิด
   เสียเวลาไปรอบละ 30 นาที การอ่านโครงหน้าจริงครั้งเดียวถูกกว่าเดาสิบครั้ง

ตัวนี้ไม่กด Export ใหม่ — ประวัติการส่งออกที่ค้างอยู่มีแถวที่เสร็จแล้วอยู่ก่อน
จึงอ่านปุ่มของแถวที่เสร็จแล้วได้เลย ไม่ต้องรอปั่นไฟล์ 30 นาที
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.config import load_config                  # noqa: E402

OUT = PROJECT_ROOT / "output" / "_diag"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shop", default="lazada_02")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_config()
    s = cfg.shop(args.shop)
    adapter = build_adapter(s, cfg.settings)

    try:
        page = adapter._open_page(headed=True)
        page.goto(f"{adapter.base_url}/apps/order/list?oldVersion=1",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(6000)

        # ── 1. หน้านี้มีกี่ frame — ถ้าปุ่มอยู่ใน iframe การหาจาก page จะไม่มีวันเจอ
        print("\n=== frame ทั้งหมดในหน้า ===")
        for i, fr in enumerate(page.frames):
            print(f"  [{i}] name={fr.name!r} url={fr.url[:110]}")

        # ── 2. เปิดกล่องประวัติการส่งออก
        opened = False
        # ⚠️ ตัวเปิดคือไอคอนที่แถบขวามือ ไม่มีข้อความอยู่ข้างในเลย
        #    หาด้วย text= จึงไม่มีวันเจอ ต้องจับด้วย id / data-spm
        for sel in ('#app_download_icon',
                    '[data-spm="d_app_download_icon"]',
                    'text="ประวัติการส่งออก"', 'text="ข้อมูลการส่งออก"'):
            try:
                loc = page.locator(sel).first
                if loc.is_visible(timeout=2500):
                    print(f"\nกดเปิดด้วย {sel}")
                    loc.click()
                    page.wait_for_timeout(4000)
                    opened = True
                    break
            except Exception:                            # noqa: BLE001
                continue
        print(f"เปิดกล่องประวัติได้: {opened}")

        # ── 3. เก็บภาพไว้ดูด้วยตา
        shot = OUT / f"{args.shop}_export_panel.png"
        page.screenshot(path=str(shot), full_page=False)
        print(f"ภาพหน้าจอ: {shot}")

        # ── 4. ไล่ทุก frame หา element ที่มีคำว่า download / ดาวน์โหลด
        print("\n=== element ที่มีคำว่า download / ดาวน์โหลด (ทุก frame) ===")
        js = """
        () => {
          const out = [];
          const want = /download|ดาวน์โหลด/i;
          document.querySelectorAll('a,button,span,div,td').forEach(el => {
            const t = (el.innerText || '').trim();
            if (!t || t.length > 60 || !want.test(t)) return;
            if (el.querySelector('a,button')) return;      // เอาเฉพาะตัวในสุด
            const r = el.getBoundingClientRect();
            out.push({
              tag: el.tagName, text: t,
              cls: (el.className || '').toString().slice(0, 70),
              id: el.id || '', href: el.getAttribute('href') || '',
              visible: r.width > 0 && r.height > 0,
            });
          });
          return out.slice(0, 40);
        }
        """
        for i, fr in enumerate(page.frames):
            try:
                rows = fr.evaluate(js)
            except Exception as exc:                     # noqa: BLE001
                print(f"  [frame {i}] อ่านไม่ได้: {str(exc)[:60]}")
                continue
            if not rows:
                continue
            print(f"  [frame {i}] {fr.url[:80]}")
            for r in rows:
                print(f"      <{r['tag']}> {'เห็น ' if r['visible'] else 'ซ่อน'} "
                      f"{r['text']!r} class={r['cls']!r} href={r['href'][:50]!r}")

        # ── 5. เก็บ HTML ของกล่องไว้ดูละเอียด
        html = OUT / f"{args.shop}_export_panel.html"
        html.write_text(page.content(), encoding="utf-8")
        print(f"\nHTML เต็มหน้า: {html}")

        # ⚠️ ห้ามใช้ input() — สคริปต์นี้ถูกสั่งจาก background ที่ไม่มี stdin
        #    จะได้ EOFError แล้วปิดหน้าต่างทิ้งก่อนที่คนจะทันดู
        print("\nเปิดหน้าต่างค้างไว้ 3 นาทีให้ดูด้วยตา...")
        page.wait_for_timeout(180_000)
    finally:
        adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
