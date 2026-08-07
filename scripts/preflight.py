r"""ตรวจความพร้อมก่อนรอบดึงรายวัน — ตอบว่า "พรุ่งนี้ 08:30 จะดึงได้ไหม"

ไล่ตรวจทุกอย่างที่เคยทำให้รอบรายวันพัง ไม่ใช่แค่ที่นึกออก
เจอปัญหาแล้วบอกวิธีแก้ตรง ๆ ไม่ใช่แค่บอกว่าพัง

    .\.venv\Scripts\python.exe -u scripts\preflight.py
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.config import load_config                   # noqa: E402
from src.core.naming import canonical_name                # noqa: E402

problems: list[str] = []
warnings: list[str] = []


def head(t: str) -> None:
    print(f"\n=== {t} ===")


def ok(msg: str) -> None:
    print(f"  ✅ {msg}")


def bad(msg: str) -> None:
    print(f"  ❌ {msg}")
    problems.append(msg)


def warn(msg: str) -> None:
    print(f"  ⚠️  {msg}")
    warnings.append(msg)


cfg = load_config()
shops = [s for s in cfg.shops if s.enabled]

# ── 1. ร้านที่ต้องดึง ────────────────────────────────────────
head("1. รายชื่อร้าน")
print(f"  เปิดใช้งาน {len(shops)} ร้าน · ปิดไว้ {len(cfg.shops) - len(shops)} ร้าน")
if len(shops) != 13:
    warn(f"จำนวนร้านเปลี่ยนเป็น {len(shops)} (เดิม 13) — เช็คว่าตั้งใจไหม")
else:
    ok("ครบ 13 ร้านตามที่ตกลง")

# ── 2. ชื่อร้านมาตรฐาน ───────────────────────────────────────
head("2. ชื่อร้านมาตรฐาน (ของใหม่วันนี้)")
unnamed = [s.shop_id for s in shops
           if canonical_name(s.shop_id, s.display_name) == s.display_name
           and canonical_name(s.shop_id) == s.shop_id]
if unnamed:
    bad(f"ร้านที่ยังไม่ประกาศใน brands.yaml: {unnamed}")
else:
    ok("ทุกร้านมีชื่อมาตรฐานแล้ว")
for s in shops:
    if s.report_name != s.display_name:
        print(f"     {s.shop_id:<11} {s.display_name!r} → {s.report_name!r}")

# ── 3. session ของแต่ละร้าน ─────────────────────────────────
head("3. ไฟล์ session / โปรไฟล์เบราว์เซอร์")
sess_dir = PROJECT_ROOT / "data" / "sessions"
prof_dir = PROJECT_ROOT / "data" / "profiles"
missing_sess, old_sess = [], []
for s in shops:
    # ชื่อไฟล์จริงคือ <profile_id>_state.json — ร้านที่ใช้บัญชีร่วมกันใช้ไฟล์เดียวกัน
    # (shopee_08 ใช้ profile ของ shopee_03) จำนวนไฟล์จึงน้อยกว่าจำนวนร้านเป็นเรื่องปกติ
    f = sess_dir / f"{s.profile_id}_state.json"
    if not f.exists():
        missing_sess.append(s.shop_id)
        continue
    age_h = (datetime.now() - datetime.fromtimestamp(f.stat().st_mtime)).total_seconds() / 3600
    if age_h > 48:
        old_sess.append(f"{s.shop_id} ({age_h:.0f} ชม.)")
if missing_sess:
    warn(f"ไม่มีไฟล์ session: {missing_sess} — ระบบจะ auto_relogin ให้ ถ้าไม่ผ่านต้องล็อกอินมือ")
else:
    ok(f"มีไฟล์ session ครบ {len(shops)} ร้าน")
if old_sess:
    print(f"     เก่ากว่า 48 ชม.: {', '.join(old_sess)}")
n_prof = len([p for p in prof_dir.iterdir() if p.is_dir()]) if prof_dir.exists() else 0
print(f"     โปรไฟล์เบราว์เซอร์ {n_prof} ชุด")

# ── 4. Chrome ค้าง — ต้นเหตุที่ทำให้เช้านี้เสียเวลาเป็นชั่วโมง ──
head("4. Chrome ค้างจากรอบก่อน")
try:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "@(Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
         "Where-Object { $_.CommandLine -like '*data\\profiles*' }).Count"],
        capture_output=True, text=True, timeout=60,
    )
    n = int((out.stdout or "0").strip() or 0)
except Exception as exc:                                  # noqa: BLE001
    n = -1
    warn(f"เช็ค Chrome ไม่ได้: {exc}")
if n == 0:
    ok("ไม่มี Chrome ค้าง")
elif n > 0:
    bad(f"มี Chrome ค้าง {n} process — จะเปิด Chrome ตัวจริงไม่ได้ "
        f"ต้องถอยไปใช้ Chromium ที่เรนเดอร์หน้า Shopee ไม่ครบ")

# ── 5. run.lock ────────────────────────────────────────────
head("5. run.lock")
lock = PROJECT_ROOT / "data" / "run.lock"
if not lock.exists():
    ok("ไม่มี lock ค้าง")
else:
    try:
        info = json.loads(lock.read_text(encoding="utf-8-sig"))
        print(f"     {info}")
        warn("มี run.lock ค้าง — run_lock ยึดคืนเองได้ถ้าเจ้าของตาย แต่ควรดูให้แน่ใจ")
    except Exception:                                     # noqa: BLE001
        warn("มี run.lock ค้างและอ่านไม่ออก")

# ── 6. Task Scheduler ──────────────────────────────────────
head("6. งานตั้งเวลาใน Windows")
ps = (
    "Get-ScheduledTask -TaskName 'DealerMKP-*' | ForEach-Object { "
    "$i = $_ | Get-ScheduledTaskInfo; "
    "\"$($_.TaskName)|$($_.State)|$($i.NextRunTime)|$($i.LastTaskResult)\" }"
)
try:
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True, timeout=90)
    lines = [x.strip() for x in (out.stdout or "").splitlines() if "|" in x]
except Exception as exc:                                  # noqa: BLE001
    lines = []
    warn(f"อ่าน Task Scheduler ไม่ได้: {exc}")

if not lines:
    bad("ไม่พบงานตั้งเวลา DealerMKP-* เลย — พรุ่งนี้จะไม่มีอะไรรันอัตโนมัติ")
for ln in lines:
    name, state, nxt, last = (ln.split("|") + ["", "", ""])[:4]
    flag = "✅" if state == "Ready" else "❌"
    if state != "Ready":
        problems.append(f"งาน {name} สถานะ {state}")
    print(f"  {flag} {name:<26} {state:<9} รันครั้งถัดไป {nxt}")
    if last not in ("0", "", "267009"):
        warn(f"{name} รันครั้งล่าสุดจบด้วยรหัส {last} (0 = สำเร็จ)")

# ── 7. ผลรอบล่าสุด ──────────────────────────────────────────
head("7. ผลการดึงย้อนหลัง 3 วัน")
db = PROJECT_ROOT / "data" / "status.db"
if not db.exists():
    bad("ไม่มี data/status.db")
else:
    con = sqlite3.connect(db)
    for d in range(3):
        day = (date.today() - timedelta(days=d)).isoformat()
        # ⚠️ ต้องนับ "สถานะล่าสุดของแต่ละร้าน" ไม่ใช่ทุกครั้งที่ลอง
        #    วันที่ต้องรันซ้ำหลายรอบจะมี FAILED ค้างอยู่ในตาราง ทั้งที่สุดท้ายผ่านแล้ว
        #    ถ้านับดิบ ๆ จะอ่านเป็นว่าวันนั้นพังหนัก ทั้งที่จบครบ
        rows = con.execute(
            "select status, count(*) from ("
            "  select shop_id, status,"
            "         row_number() over (partition by shop_id order by rowid desc) rn"
            "  from run_log where run_date=?"
            ") where rn=1 group by status", (day,)
        ).fetchall()
        if not rows:
            print(f"  {day}  (ไม่มีข้อมูล)")
            continue
        m = dict(rows)
        line = " · ".join(f"{k} {v}" for k, v in sorted(m.items()))
        note = "" if m.get("FAILED") else "  ← จบครบ"
        print(f"  {day}  {line}{note}")
        if d == 0 and m.get("FAILED"):
            warn(f"วันนี้ยังมีร้าน FAILED ค้าง {m['FAILED']} ร้าน")
    con.close()

# ── 8. ปลายทางไฟล์ + เนื้อที่ ───────────────────────────────
head("8. ที่เก็บไฟล์")
out_dir = PROJECT_ROOT / "output"
out_dir.mkdir(exist_ok=True)
try:
    import shutil as _sh

    free_gb = _sh.disk_usage(PROJECT_ROOT).free / 1024**3
    if free_gb < 5:
        bad(f"เนื้อที่เหลือ {free_gb:.1f} GB — น้อยเกินไป")
    else:
        ok(f"เนื้อที่เหลือ {free_gb:.0f} GB")
except Exception as exc:                                  # noqa: BLE001
    warn(f"เช็คเนื้อที่ไม่ได้: {exc}")

# ── 9. อีเมล ───────────────────────────────────────────────
head("9. การส่งอีเมล")
try:
    import win32com.client  # noqa: F401

    ok("pywin32 พร้อม (ส่งผ่าน Outlook ที่เปิดอยู่)")
except Exception:                                         # noqa: BLE001
    bad("import win32com ไม่ได้ — ส่งอีเมลไม่ได้")

send_ps1 = PROJECT_ROOT / "send_report.ps1"
run_ps1 = PROJECT_ROOT / "run_daily.ps1"
for f in (send_ps1, run_ps1):
    if not f.exists():
        bad(f"ไม่มีไฟล์ {f.name}")
        continue
    bom = f.read_bytes()[:3] == b"\xef\xbb\xbf"
    if bom:
        ok(f"{f.name} เป็น UTF-8 with BOM ถูกต้อง")
    else:
        bad(f"{f.name} ไม่มี BOM — PowerShell 5.1 จะอ่านภาษาไทยเพี้ยนแล้ว parser พังทั้งไฟล์")

txt = run_ps1.read_text(encoding="utf-8-sig") if run_ps1.exists() else ""
if "--only-if-complete" in txt:
    ok("ตั้งกฎ 'ไม่ครบ 13 ร้าน ห้ามส่งเมล' ไว้แล้ว")
else:
    warn("ไม่เจอ --only-if-complete ใน run_daily.ps1")

# ── สรุป ───────────────────────────────────────────────────
print("\n" + "=" * 58)
if problems:
    print(f"❌ ต้องแก้ {len(problems)} ข้อก่อนพรุ่งนี้")
    for p in problems:
        print(f"   · {p}")
elif warnings:
    print(f"✅ พร้อมดึง — มีข้อสังเกต {len(warnings)} ข้อ ไม่บล็อก")
else:
    print("✅ พร้อมดึงครบทุกจุด")
raise SystemExit(1 if problems else 0)
