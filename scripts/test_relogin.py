r"""ทดสอบว่า auto_relogin ใช้ได้จริงไหม — ตัวชี้ขาดว่าพรุ่งนี้ระบบจะกู้ตัวเองได้หรือไม่

ไม่ต้องรอให้ session ตายก่อน ทดสอบได้เลยเพราะ auto_relogin เริ่มจากไปหน้า login อยู่แล้ว

    python scripts\test_relogin.py --shop shopee_03
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
ap.add_argument("--shop", required=True)
args = ap.parse_args()

cfg = load_config()
s = cfg.shop(args.shop)
adapter = build_adapter(s, cfg.settings)

print(f"=== ทดสอบ auto_relogin: {s.shop_id} ({s.platform}) ===")
try:
    page = adapter._open_page(headed=False)
    ok = adapter.auto_relogin(page)
    print(f"\nผลลัพธ์ : {'✅ ต่ออายุเองได้' if ok else '🔴 ต่ออายุเองไม่ได้'}")
    print(f"URL ปลายทาง : {page.url[:90]}")
    if ok:
        # เซฟไว้เลย ได้ประโยชน์ทันที
        adapter._save_session_if_logged_in(page)
        print("เซฟ session แล้ว")
    else:
        print("\nสาเหตุที่เป็นไปได้:")
        print("  - Chrome ในโปรไฟล์นี้ไม่ได้จำรหัสผ่านไว้ (ต้องล็อกอินมือ 1 ครั้งแล้วกด 'บันทึก')")
        print("  - เจอ CAPTCHA/OTP (ระบบหยุดเองตามกฎ ไม่พยายามผ่าน)")
        print("  - ปุ่มล็อกอินเปลี่ยนชื่อ")
        print("  ดู log บรรทัด relogin_* ด้านบนเพื่อแยกสาเหตุ")
finally:
    adapter.close()
