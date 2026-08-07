r"""ดูของจริงในหน้าประวัติการดาวน์โหลด — ทำไมกดปุ่ม Download ไม่ได้

ใช้ตอบคำถามเดียว: แถวของแต่ละเดือน "สถานะอะไร" และ "มีปุ่มอะไรให้กด"
เดาไม่ได้ ต้องดู DOM จริง
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
a = build_adapter(s, cfg.settings)

try:
    p = a._open_page(headed=False)
    p.goto(a.orders_url, wait_until="domcontentloaded")
    p.wait_for_timeout(9000)
    a._ensure_logged_in(p, a.orders_url)
    a._enter_shop(p)
    a._dismiss_onboarding(p)
    print(f"ร้านที่เปิดอยู่: {a._current_shop_name(p)!r}  (ต้องการ {s.web_name!r})")

    _click_first(p, SEL["history_btn"], 8000)
    p.wait_for_timeout(4000)
    print(f"URL: {p.url[:90]}\n")

    js = """
    () => {
      const rows = [];
      document.querySelectorAll('tr').forEach(tr => {
        const tds = [...tr.querySelectorAll('td')].map(td => (td.innerText||'').trim());
        if (!tds.length) return;
        const btns = [...tr.querySelectorAll('button,a')].map(b => ({
          t: (b.innerText||'').trim().slice(0,24),
          cls: (b.className||'').toString().slice(0,55),
          dis: b.disabled === true || b.getAttribute('aria-disabled') === 'true'
        })).filter(b => b.t);
        rows.push({cells: tds.map(c => c.slice(0,46)), btns});
      });
      return rows.slice(0, 14);
    }
    """
    rows = p.evaluate(js)
    print(f"=== แถวในประวัติ {len(rows)} แถว ===")
    for i, r in enumerate(rows):
        print(f"\n[{i}] {' | '.join(r['cells'])}")
        if not r["btns"]:
            print("     ปุ่ม: (ไม่มีเลย)")
        for b in r["btns"]:
            print(f"     ปุ่ม {b['t']!r}  disabled={b['dis']}  class={b['cls']!r}")

    print("\n=== ทดสอบ _try_row_download_button กับชื่อไฟล์จริง ===")
    names = sorted(a._report_names(p))
    print(f"_report_names คืนมา {len(names)} ชื่อ")
    for name in names[:12]:
        btn = a._try_row_download_button(p, name)
        exact = p.locator(f'text="{name}"').count()
        print(f"  {name!r}")
        print(f"      text= exact เจอ {exact} node → "
              f"{'เจอปุ่ม' if btn is not None else '❌ ไม่เจอปุ่ม'}")

    Path("logs/screenshots").mkdir(parents=True, exist_ok=True)
    p.screenshot(path=f"logs/screenshots/history_{args.shop}.png", full_page=True)
    print(f"\nภาพ: logs/screenshots/history_{args.shop}.png")
finally:
    a.close()
