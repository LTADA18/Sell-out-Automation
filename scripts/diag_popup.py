r"""หา selector ของป๊อปอัปโฆษณาที่บังปุ่มดาวน์โหลดในหน้าคำสั่งซื้อ Shopee

ใช้ครั้งเดียวเพื่อหา selector ที่ถูก แล้วเอาไปใส่ใน _dismiss_onboarding
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.adapters.shopee import SEL                      # noqa: E402
from src.core.config import load_config                  # noqa: E402

cfg = load_config()
s = cfg.shop("shopee_05")
adapter = build_adapter(s, cfg.settings)

try:
    page = adapter._open_page(headed=False)
    page.goto(adapter.orders_url, wait_until="domcontentloaded")
    page.wait_for_timeout(9000)
    adapter._enter_shop(page)
    adapter._ensure_logged_in(page, adapter.orders_url)
    adapter._dismiss_onboarding(page)
    page.wait_for_timeout(3000)

    print("=== ปุ่มเปิดกล่องดาวน์โหลดเจอไหม ===")
    print(f"  button.export-with-modal : {page.locator(SEL['open_modal'][0]).count()} ตัว")
    btn = page.locator(SEL["open_modal"][0]).first
    if btn.count():
        try:
            print(f"  visible={btn.is_visible()}  enabled={btn.is_enabled()}")
            print(f"  bounding_box={btn.bounding_box()}")
        except Exception as e:                           # noqa: BLE001
            print(f"  อ่านสถานะไม่ได้: {e}")

    print("\n=== element ที่ลอยทับ (fixed/absolute ขวาบน) ===")
    js = """
    () => {
      const out = [];
      document.querySelectorAll('div,section,aside').forEach(el => {
        const cs = getComputedStyle(el);
        if (cs.position !== 'fixed' && cs.position !== 'absolute') return;
        const r = el.getBoundingClientRect();
        if (r.width < 80 || r.height < 40) return;
        if (r.top > 400) return;
        if (r.right < window.innerWidth * 0.5) return;
        out.push({
          cls: (el.className || '').toString().slice(0, 90),
          id: el.id || '',
          z: cs.zIndex,
          rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
          text: (el.innerText || '').replace(/\\s+/g, ' ').slice(0, 70)
        });
      });
      return out.slice(0, 12);
    }
    """
    for it in page.evaluate(js):
        print(f"  class={it['cls']!r}")
        print(f"     id={it['id']!r} z={it['z']} rect={it['rect']} text={it['text']!r}")

    print("\n=== ปุ่มปิด (กากบาท) ที่หาเจอ ===")
    for sel in ("[class*='close']", "[class*='Close']", "i.eds-icon[class*='close']",
                "button[aria-label*='close']", "[class*='dismiss']"):
        n = page.locator(sel).count()
        if n:
            print(f"  {sel:<38} {n} ตัว")
            for i in range(min(n, 6)):
                el = page.locator(sel).nth(i)
                try:
                    if el.is_visible():
                        print(f"      nth({i}) visible box={el.bounding_box()} "
                              f"class={(el.get_attribute('class') or '')[:70]!r}")
                except Exception:                        # noqa: BLE001
                    continue
finally:
    adapter.close()
