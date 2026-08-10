r"""ตรวจความพร้อมก่อนรอบดึงรายวัน — ตอบว่า "พรุ่งนี้ 08:30 จะดึงได้ไหม"

ไล่ตรวจทุกอย่างที่เคยทำให้รอบรายวันพัง ไม่ใช่แค่ที่นึกออก
**เจอว่า session จะหมดอายุก่อนรอบดึง จะรัน keepalive ซ่อมให้เองทันที**
ไม่ใช่แค่บอกว่าเสี่ยงแล้วปล่อยให้ไปพังตอนเช้า

    .\.venv\Scripts\python.exe -u scripts\preflight.py
    .\.venv\Scripts\python.exe -u scripts\preflight.py --no-fix   # ตรวจอย่างเดียว
"""
from __future__ import annotations

import argparse
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

_ap = argparse.ArgumentParser()
_ap.add_argument("--no-fix", action="store_true",
                 help="ตรวจอย่างเดียว ไม่ต่ออายุ session ให้")
_ap.add_argument("--deadline", type=float, default=23.0,
                 help="เส้นตายอายุ session (ชม.) — ลดลงเพื่อทดสอบทางซ่อม")
ARGS = _ap.parse_args()

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
EXPECTED_SHOPS = 16                                       # 18 ร้าน ปิดไว้ 2 (lazada_02/03 ติดสิทธิ์)
if len(shops) != EXPECTED_SHOPS:
    warn(f"จำนวนร้านเปลี่ยนเป็น {len(shops)} (คาดไว้ {EXPECTED_SHOPS}) — เช็คว่าตั้งใจไหม "
         f"ถ้าตั้งใจให้แก้ EXPECTED_SHOPS ในไฟล์นี้")
else:
    ok(f"ครบ {EXPECTED_SHOPS} ร้านตามที่ตกลง")

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

# ── 3.1 อายุ session ตอนรอบดึงถัดไป — ตัวที่พลาดมาแล้ว 2 ครั้ง ──
#
# ⚠️ เช็ค "อายุตอนนี้" อย่างเดียวไม่พอ ต้องคิดไปถึงตอนรอบดึงจริง
#    2026-08-09 21:49 preflight บอก "พร้อมครบทุกจุด" ทั้งที่ TikTok ทุกร้าน
#    จะอายุ 24.0 ชม. พอดีตอน 08:30 ซึ่งคือเส้นตายที่วัดได้จริง
#    ถ้าเชื่อตามนั้นแล้วไปนอน เช้ามาก็พังเหมือนวันที่ 8
#
# เส้นตายจากการวัดจริง: 23.8 ชม. ตาย / 21.0 ชม. รอด
DEADLINE_H = ARGS.deadline
WARN_H = min(20.0, DEADLINE_H - 1)

head("3.1 อายุ session ตอนรอบดึงถัดไป")
_now = datetime.now()
_run = _now.replace(hour=8, minute=30, second=0, microsecond=0)
if _run <= _now:
    _run += timedelta(days=1)
print(f"  รอบดึงถัดไป {_run:%d/%m %H:%M}")

def _ages_at_run() -> dict[str, float]:
    """อายุ session ของแต่ละร้าน TikTok ณ เวลารอบดึงถัดไป"""
    out: dict[str, float] = {}
    for sh in shops:
        # เช็คเฉพาะ TikTok เพราะเป็นเจ้าเดียวที่ "อายุ session" ทำนายผลได้จริง
        #   TikTok  ~24 ชม. — วัดได้ชัด (23.8 ตาย / 21.0 รอด) จึงเตือนล่วงหน้าได้
        #   Lazada  ~85 นาที — สั้นจนอายุไม่มีความหมาย พึ่ง auto_relogin ตอนดึงแทน
        #   Shopee  ต่ออายุเองได้ด้วยหน้าเลือกบัญชี ไม่ต้องใช้รหัสผ่าน
        if sh.platform != "tiktok":
            continue
        p = sess_dir / f"{sh.profile_id}_state.json"
        if p.exists():
            out[sh.shop_id] = (
                _run - datetime.fromtimestamp(p.stat().st_mtime)).total_seconds() / 3600
    return out


ages = _ages_at_run()
risky = [sid for sid, a in ages.items() if a >= DEADLINE_H]
fixed: set[str] = set()

# ── ซ่อมเองถ้าเสี่ยง ──────────────────────────────────────────
# เจ้าของงานสั่งไว้: อย่ารอให้ปัญหาเกิด ให้ชิงแก้ก่อน
# ตรวจแล้วรู้ว่าจะพังแต่ปล่อยไว้ = ไร้ประโยชน์ เพราะเช้ามาก็พังอยู่ดี
if risky and not ARGS.no_fix:
    print(f"  ⚠️  {len(risky)} ร้านจะหมดอายุก่อนรอบดึง — ต่ออายุให้เลย")
    for sid in risky:
        print(f"       {sid} จะอายุ {ages[sid]:.1f} ชม.")
    try:
        # ⚠️ ต้องบังคับ UTF-8 ให้ทั้งฝั่งลูกและฝั่งอ่าน
        #    ไม่งั้น Python อ่าน stdout ภาษาไทยด้วย cp1252 แล้วโยน UnicodeDecodeError
        #    ในเธรดอ่านผลลัพธ์ ทำให้ทางซ่อมล้มทั้งที่ keepalive ทำงานได้ปกติ
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
        res = subprocess.run(
            # ⚠️ ต้องเป็น --max-age 0 (บังคับต่ออายุทุกร้าน)
            #    keepalive วัด "อายุตอนนี้" แต่ preflight ตัดสินจาก "อายุตอนรอบดึง"
            #    ถ้าส่งค่ามากกว่า 0 keepalive จะเห็นว่า session ยังใหม่แล้วข้ามทั้งหมด
            #    ทางซ่อมจะดูเหมือนทำงานแต่ไม่ได้ต่ออายุอะไรเลย (เจอตอนทดสอบ 2026-08-09)
            # --guard-min 0 : ปลดตัวกันชนกับรอบดึง
            #   ตัวกันนั้นมีไว้กัน keepalive "ที่ตั้งเวลาไว้" ไปคว้าล็อกตอนใกล้ 08:30
            #   แต่ตรงนี้ preflight เรียกเองแบบรอจนเสร็จ และตัว preflight เองก็เป็น
            #   ขั้นแรกของรอบดึง จึงไม่มีทางแย่งล็อกกับรอบดึง
            #   ถ้าไม่ปลด preflight ที่รันตอน 08:30 จะสั่งซ่อมไม่ได้เลย
            [sys.executable, "-u", str(PROJECT_ROOT / "scripts" / "keepalive.py"),
             "--platform", "tiktok", "--max-age", "0", "--guard-min", "0"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=900,
            encoding="utf-8", errors="replace", env=env,
        )
        for line in (res.stdout or "").splitlines():
            if any(k in line for k in ("✅", "❌", "ต่ออายุ", "ข้าม")):
                print(f"       {line.strip()}")
    except Exception as exc:                             # noqa: BLE001
        warn(f"รัน keepalive อัตโนมัติไม่สำเร็จ: {str(exc)[:80]}")

    before = dict(ages)
    ages = _ages_at_run()                                # วัดใหม่หลังซ่อม
    fixed = {sid for sid in before if ages.get(sid, 99) < before[sid] - 0.05}
    risky = [sid for sid, a in ages.items() if a >= DEADLINE_H]
    if not risky:
        print("  ✅ ต่ออายุแล้ว — ไม่เสี่ยงอีกต่อไป")

for sid, age_at_run in sorted(ages.items()):
    if age_at_run >= DEADLINE_H:
        # แยก 2 กรณีให้ชัด ไม่งั้นข้อความจะชี้ไปผิดทาง
        #   ต่ออายุไม่ติด = session ตายจริง ต้องมีคนล็อกอิน
        #   ต่ออายุติดแล้วแต่ยังเกิน = เส้นตายตั้งไว้สั้นกว่าระยะห่างถึงรอบดึง
        if sid in fixed:
            bad(f"{sid} ต่ออายุแล้วแต่ยังจะอายุ {age_at_run:.1f} ชม. ตอนรอบดึง "
                f"— รอบดึงอยู่ไกลเกินเส้นตาย {DEADLINE_H:.0f} ชม.")
        else:
            bad(f"{sid} จะอายุ {age_at_run:.1f} ชม. ตอนรอบดึง — เกินเส้นตาย "
                f"และต่ออายุเองไม่สำเร็จ ต้องล็อกอินร้านนี้")
    elif age_at_run >= WARN_H:
        warn(f"{sid} จะอายุ {age_at_run:.1f} ชม. ตอนรอบดึง — จ่อเส้น")
    else:
        print(f"     ✅ {sid:<11} จะอายุ {age_at_run:.1f} ชม.")

# keepalive ทำงานล่าสุดเมื่อไหร่ — ถ้าไม่ได้รันมาเกินวันครึ่งแปลว่ามันไม่ทำงาน
ka_log = PROJECT_ROOT / "logs" / "run_keepalive.jsonl"   # ชื่อจริงที่ setup_logging เขียน
if ka_log.exists():
    ka_age = (datetime.now()
              - datetime.fromtimestamp(ka_log.stat().st_mtime)).total_seconds() / 3600
    if ka_age > 36:
        warn(f"keepalive ไม่ได้ทำงานมา {ka_age:.0f} ชม. — ตัวตั้งเวลา 20:00 อาจไม่ยิง")
    else:
        print(f"     keepalive ทำงานล่าสุดเมื่อ {ka_age:.1f} ชม.ที่แล้ว")
else:
    warn("ยังไม่เคยมี log ของ keepalive")

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
