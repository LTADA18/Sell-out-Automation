r"""ดู DOM หน้า login ของ Shopee — หาว่าปุ่ม "เข้าสู่ระบบด้วยบัญชีหลัก/บัญชีย่อย" คือ element ไหน"""
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
    p.goto(f"{a.base_url}{a.login_path}", wait_until="domcontentloaded")
    p.wait_for_timeout(8000)
    print(f"URL: {p.url[:90]}\n")

    js = """
    () => {
      const out = [];
      document.querySelectorAll('a,button,div,span,li').forEach(el => {
        const t = (el.innerText || '').trim();
        if (!t || t.length > 60) return;
        if (!/บัญชีหลัก|บัญชีย่อย|Main Account|Sub.?Account/i.test(t)) return;
        if (el.children.length > 2) return;          // เอาตัวในสุด
        const r = el.getBoundingClientRect();
        out.push({tag: el.tagName, cls: (el.className||'').toString().slice(0,70),
                  text: t.slice(0,55), rect: [Math.round(r.x), Math.round(r.y),
                  Math.round(r.width), Math.round(r.height)]});
      });
      return out.slice(0, 8);
    }
    """
    hits = p.evaluate(js)
    print(f"=== element ที่มีคำว่า 'บัญชีหลัก/บัญชีย่อย' : {len(hits)} ===")
    for h in hits:
        print(f"  <{h['tag']}> class={h['cls']!r}")
        print(f"      text={h['text']!r}  rect={h['rect']}")

    print("\n=== ลองนับด้วย locator แบบต่าง ๆ ===")
    for sel in ('text=/เข้าสู่ระบบด้วยบัญชีหลัก/',
                'text=/บัญชีหลัก/',
                ':text("บัญชีหลัก")',
                'text=/บัญชีย่อย/'):
        try:
            print(f"  {sel:<42} {p.locator(sel).count()}")
        except Exception as e:                           # noqa: BLE001
            print(f"  {sel:<42} error {str(e)[:40]}")

    Path("logs/screenshots").mkdir(parents=True, exist_ok=True)
    p.screenshot(path="logs/screenshots/shopee_loginpage.png")
    print("\nถ่ายภาพไว้ที่ logs/screenshots/shopee_loginpage.png")
finally:
    a.close()
