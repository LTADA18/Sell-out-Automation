"""เคลียร์ Chrome ที่ค้างจากรอบก่อน — ต้องทำก่อนเริ่มรอบใหม่เสมอ

ทำไมถึงต้องมี (เจอจริง 2026-08-07 เสียเวลาไปเกือบชั่วโมง):
  Chrome ที่ค้างอยู่ล็อกโฟลเดอร์โปรไฟล์ไว้ → Playwright เปิด Chrome ตัวจริงไม่ได้
  จึงถอยไปใช้ Chromium ที่มากับ Playwright (`chrome_channel_unavailable` ใน log)
  ตัวนั้นเรนเดอร์หน้า Shopee ไม่ครบ — หน้าเลือกร้านออกมาว่าง (tr=0)
  ระบบจึงรายงานผิดว่า "บัญชีนี้ไม่มีร้านชื่อนี้" (NO_PERMISSION)
  อาการชี้ไปผิดทางหมด ทำให้ไล่หาสาเหตุผิดจุดอยู่นาน

⚠️ กฎเหล็กข้อที่ว่า "ห้ามฆ่า Chrome ด้วย Stop-Process -Force" ยังใช้อยู่
   เหตุผลคือ cookie ที่ยังอยู่ในหน่วยความจำจะไม่ถูกเขียนลงดิสก์ การล็อกอินที่เพิ่งทำจะหาย
   ที่นี่จึง **ปิดแบบสุภาพก่อนเสมอ** (CloseMainWindow) แล้วรอให้เขียน cookie ลงดิสก์
   บังคับปิดเฉพาะตัวที่ยังไม่ยอมไปหลังหมดเวลา ซึ่งมักเป็น process ที่ค้างตายอยู่แล้ว

ขอบเขต: แตะเฉพาะ Chrome ที่ชี้ไปที่ data/profiles ของโปรเจกต์นี้เท่านั้น
        Chrome ส่วนตัวของเจ้าของเครื่องและของโปรเจกต์อื่นไม่ถูกแตะ
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from src.core.logging_setup import get_logger

log = get_logger()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILES_DIR = PROJECT_ROOT / "data" / "profiles"

# ปิดสุภาพแล้วรอเท่านี้ก่อนบังคับ — ให้เวลา Chrome flush cookie ลงดิสก์
GRACE_SEC = 8


def _ps(script: str, timeout: int = 90) -> str:
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, timeout=timeout,
    )
    return (out.stdout or "").strip()


def _find_pids() -> list[int]:
    """PID ของ Chrome ที่ใช้โปรไฟล์ของโปรเจกต์นี้"""
    # เทียบด้วย path เต็มของโฟลเดอร์โปรไฟล์ ไม่ใช่คำว่า "profiles" ลอย ๆ
    # ไม่งั้นจะไปโดน Chrome ของโปรเจกต์อื่นที่บังเอิญมีคำนี้ใน command line
    needle = str(PROFILES_DIR).replace("'", "''")
    script = (
        "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
        f"Where-Object {{ $_.CommandLine -like '*{needle}*' }} | "
        "ForEach-Object { $_.ProcessId }"
    )
    try:
        return [int(x) for x in _ps(script).split() if x.strip().isdigit()]
    except Exception as exc:                             # noqa: BLE001
        log.warning("chrome_scan_failed", err=str(exc)[:120])
        return []


def close_stale_browsers() -> int:
    """ปิด Chrome ค้างของโปรเจกต์นี้ คืนจำนวนที่ปิดไป

    ห้ามโยน exception ออกไป — งานหลักคือดึงข้อมูล ถ้าเคลียร์ไม่ได้ก็ควรลองดึงต่อ
    ไม่ใช่ล้มทั้งรอบเพราะขั้นตอนเสริม
    """
    pids = _find_pids()
    if not pids:
        return 0

    log.info("chrome_stale_found", count=len(pids), pids=pids[:12])
    ids = ",".join(str(p) for p in pids)
    try:
        # 1) ขอปิดสุภาพ แล้วรอให้เขียน cookie ลงดิสก์
        # 2) ตัวที่ยังไม่ไปค่อยบังคับ — ตรงนี้คือ process ที่ค้างตายแล้ว
        _ps(
            f"$ps = Get-Process -Id {ids} -ErrorAction SilentlyContinue; "
            "if ($ps) { $ps | ForEach-Object { $_.CloseMainWindow() | Out-Null } }; "
            f"Start-Sleep -Seconds {GRACE_SEC}; "
            f"Get-Process -Id {ids} -ErrorAction SilentlyContinue | "
            "Stop-Process -Force -ErrorAction SilentlyContinue",
            timeout=GRACE_SEC + 60,
        )
    except Exception as exc:                             # noqa: BLE001
        log.warning("chrome_cleanup_failed", err=str(exc)[:120])
        return 0

    left = _find_pids()
    closed = len(pids) - len(left)
    if left:
        log.warning("chrome_cleanup_partial", closed=closed, still_running=len(left))
    else:
        log.info("chrome_cleanup_ok", closed=closed)
    return closed
