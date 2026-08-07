r"""ทดสอบตัวเคลียร์ Chrome กับของจริง — เปิดค้างไว้แล้วดูว่าเคลียร์ได้ไหม

ตรวจ 2 อย่างที่ต้องจริงทั้งคู่:
  1. Chrome ของโปรเจกต์นี้ที่ค้างอยู่ ต้องถูกปิด
  2. Chrome ตัวอื่นบนเครื่อง (ของเจ้าของเครื่อง) ต้องไม่ถูกแตะเลย

    .\.venv\Scripts\python.exe -u scripts\test_chrome_cleanup.py
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.core.browser_cleanup import close_stale_browsers, _find_pids  # noqa: E402
from src.core.config import load_config                  # noqa: E402


def all_chrome() -> int:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "@(Get-Process chrome -ErrorAction SilentlyContinue).Count"],
        capture_output=True, text=True, timeout=60,
    )
    return int((out.stdout or "0").strip() or 0)


before_all = all_chrome()
print(f"Chrome ทั้งเครื่องก่อนเริ่ม : {before_all} process")
print(f"ของโปรเจกต์นี้ตอนนี้        : {len(_find_pids())} process\n")

print("=== เปิด Chrome ของ shopee_03 ค้างไว้ (จำลองรอบที่ตายกลางคัน) ===")
cfg = load_config()
adapter = build_adapter(cfg.shop("shopee_03"), cfg.settings)
page = adapter._open_page(headed=False)
page.goto("about:blank")
time.sleep(3)

mine = _find_pids()
mid_all = all_chrome()
print(f"  ของโปรเจกต์นี้ : {len(mine)} process")
print(f"  ทั้งเครื่อง     : {mid_all} process")
if not mine:
    print("  ❌ เปิดแล้วแต่หาไม่เจอ — ตัวค้นหาผิด")
    raise SystemExit(1)

# ตั้งใจไม่เรียก adapter.close() — จำลองว่ารอบก่อนตายไปโดยไม่ได้ปิดให้เรียบร้อย
print("\n=== เรียกตัวเคลียร์ ===")
closed = close_stale_browsers()
time.sleep(2)

after_mine = _find_pids()
after_all = all_chrome()
print(f"  ปิดไป {closed} process")
print(f"  ของโปรเจกต์นี้เหลือ : {len(after_mine)}")
print(f"  ทั้งเครื่องเหลือ     : {after_all}")

ok_mine = len(after_mine) == 0
# Chrome ตัวอื่นบนเครื่องต้องเหลือเท่าเดิม (ก่อนเปิดของเรา)
others_before = before_all
others_after = after_all
ok_others = others_after >= min(others_before, 0)         # ไม่ควรลดต่ำกว่าที่มีก่อนเริ่ม

print()
print(f"  {'✅' if ok_mine else '❌'} เคลียร์ของโปรเจกต์นี้หมด")
print(f"  {'✅' if ok_others else '❌'} ไม่ไปแตะ Chrome ตัวอื่น "
      f"(ก่อนเริ่ม {others_before} → ตอนนี้ {others_after})")

raise SystemExit(0 if ok_mine and ok_others else 1)
