r"""ดูหน้า login ของ TikTok Seller ว่ามีทางเข้าแบบไม่ใช้รหัสผ่านไหม

Shopee มีปุ่ม "เข้าสู่ระบบด้วยบัญชีหลัก/บัญชีย่อย" ที่พาไปหน้าเลือกบัญชี
เข้าได้โดยไม่ต้องพิมพ์รหัส — คำถามคือ TikTok มีอะไรแบบนั้นไหม

ห้ามเดา ต้องดู DOM จริง

    .\.venv\Scripts\python.exe -u scripts\diag_tiktok_login.py --shop tiktok_01
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.config import load_config                  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--shop", default="tiktok_01")
args = ap.parse_args()

cfg = load_config()
s = cfg.shop(args.shop)
a = build_adapter(s, cfg.settings)

try:
    p = a._open_page(headed=False)
    p.goto(f"{a.base_url}{a.login_path}", wait_until="domcontentloaded")
    p.wait_for_timeout(6000)
    print(f"URL: {p.url[:100]}\n")

    print("=== ช่องกรอก ===")
    for sel in ("input[type=password]", "input[type=text]", "input[type=email]"):
        n = p.locator(sel).count()
        val = 0
        if n:
            try:
                val = p.evaluate(
                    f"() => {{ const e = document.querySelector('{sel}');"
                    " return e ? e.value.length : 0; }}")
            except Exception:                            # noqa: BLE001
                val = -1
        print(f"  {sel:<26} จำนวน {n}  ความยาวค่าที่เติมไว้ {val}")

    print("\n=== ปุ่ม/ลิงก์ทั้งหมดบนหน้า (สูงสุด 30) ===")
    js = """
    () => [...document.querySelectorAll('button,a,div[role=button]')]
      .map(e => (e.innerText || '').trim())
      .filter(t => t && t.length < 60)
      .slice(0, 30)
    """
    for t in p.evaluate(js):
        print(f"  · {t}")

    print("\n=== มีร่องรอยทางเข้าแบบไม่ใช้รหัสไหม ===")
    HINTS = ("QR", "คิวอาร์", "บัญชี", "account", "Continue as", "ดำเนินการต่อ",
             "สลับ", "Switch", "จำ", "Remember", "อีเมล", "โทรศัพท์", "phone")
    body = ""
    try:
        body = p.locator("body").inner_text()[:3000]
    except Exception as e:                               # noqa: BLE001
        body = f"(อ่านไม่ได้ {e})"
    found = [h for h in HINTS if h.lower() in body.lower()]
    print(f"  คำที่เจอ: {found if found else 'ไม่เจอเลย'}")

    Path("logs/screenshots").mkdir(parents=True, exist_ok=True)
    out = f"logs/screenshots/tiktok_login_{args.shop}.png"
    p.screenshot(path=out, full_page=True)
    print(f"\nภาพ: {out}")
finally:
    a.close()
