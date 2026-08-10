r"""เช็คว่าโปรไฟล์ Chrome ของแต่ละร้าน "มีรหัสผ่านบันทึกไว้ไหม"

⚠️ อ่านแค่ว่ามีกี่รายการและของเว็บไหน — ไม่อ่านค่ารหัสผ่าน ไม่ถอดรหัส ไม่แสดง
   คอลัมน์ password_value ถูกเข้ารหัสด้วย DPAPI อยู่แล้วและเราไม่แตะมัน

ใช้ตอบว่า auto_relogin จะทำงานได้ไหม — ถ้าไม่มีรหัสบันทึกไว้ ระบบจะเติมฟอร์มไม่ได้
แล้วต้องให้คนมาล็อกอินเองทุกครั้งที่ session หลุด

    .\.venv\Scripts\python.exe -u scripts\check_saved_password.py
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import load_config                   # noqa: E402

PROFILES = PROJECT_ROOT / "data" / "profiles"


def count_logins(profile: Path) -> tuple[int, list[str]]:
    """คืน (จำนวนรายการ, โดเมนที่มี) — ไม่แตะค่ารหัสผ่าน"""
    db = profile / "Default" / "Login Data"
    if not db.exists():
        db = profile / "Login Data"
    if not db.exists():
        return -1, []
    # ก๊อปก่อนอ่าน — Chrome ล็อกไฟล์ไว้ตอนเปิดอยู่
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "logindata"
        try:
            shutil.copy2(db, tmp)
            con = sqlite3.connect(f"file:{tmp}?mode=ro", uri=True)
            rows = con.execute(
                "select origin_url from logins order by origin_url").fetchall()
            con.close()
        except Exception:                                # noqa: BLE001
            return -2, []
    hosts = sorted({r[0].split("/")[2] for r in rows if "//" in r[0]})
    return len(rows), hosts


cfg = load_config()
shops = [s for s in cfg.shops if s.enabled and s.adapter == "playwright"]
seen: set[str] = set()

print(f"{'ร้าน':<12} {'โปรไฟล์':<12} {'รหัสที่บันทึกไว้':>16}   เว็บ")
print("-" * 76)
for s in shops:
    if s.profile_id in seen:
        continue
    seen.add(s.profile_id)
    n, hosts = count_logins(PROFILES / s.profile_id)
    if n == -1:
        state, extra = "ไม่มีไฟล์", ""
    elif n == -2:
        state, extra = "อ่านไม่ได้", "(Chrome เปิดอยู่?)"
    elif n == 0:
        state, extra = "❌ ไม่มีเลย", "ต้องล็อกอินมือทุกครั้งที่ session หลุด"
    else:
        state, extra = f"✅ {n} รายการ", ", ".join(hosts[:3])
    print(f"{s.shop_id:<12} {s.profile_id:<12} {state:>16}   {extra}")

print("\nหมายเหตุ: มีรหัสบันทึกไว้ = auto_relogin เติมฟอร์มเองได้")
print("          แต่ถ้าแพลตฟอร์มขอ OTP ซ้ำ ระบบจะหยุดและรายงาน ไม่พยายามผ่าน")
