"""ธงบอกว่า "มีงานยาวใช้เบราว์เซอร์อยู่" — กัน KeepAlive เข้ามาแทรก

⚠️ ทำไมใช้ธงแยก ไม่ใช้ run_lock
   run_lock เป็นล็อกตัวเดียวทั้งระบบ ถ้าให้ backfill จับ สายขนาน 3 สาย
   (Shopee / TikTok / Lazada) จะรันพร้อมกันไม่ได้เลย ซึ่งเสียประโยชน์ทั้งหมด
   ธงนี้ไม่ได้กันงานดึงด้วยกันเอง — คนละร้านคนละโปรไฟล์ ทำพร้อมกันได้อยู่แล้ว
   หน้าที่เดียวของมันคือบอก KeepAlive ว่า "อย่าเพิ่งเข้ามา"

⚠️ ทำไมต้องกัน KeepAlive เป็นพิเศษ
   keepalive.py เรียก close_stale_browsers() ตั้งแต่ก่อนจับ run_lock
   ถ้าเผลอรันคาบเกี่ยวงานยาว มันจะไล่ปิด Chrome ที่ backfill กำลังใช้อยู่
   cookie ที่ยังอยู่ในหน่วยความจำจะไม่ถูกเขียนลงดิสก์ = การล็อกอินหายทั้งดุ้น
   (กฎเหล็กข้อเดียวกับที่ห้าม Stop-Process -Force ใน CLAUDE.md)

⚠️ 1 งาน = 1 ไฟล์ ห้ามใช้ไฟล์เดียวร่วมกัน
   ของเดิมเป็นไฟล์เดียว พอรันขนาน 2 สาย สายที่เสร็จก่อนจะ clear_busy()
   ลบธงทิ้งทั้งที่อีกสายยังทำงานอยู่ KeepAlive รอบถัดไปจึงเข้ามาปิด Chrome
   ของสายที่ยังไม่เสร็จได้ — ซึ่งเป็นสิ่งที่ธงนี้มีไว้กันพอดี
   (แก้ 2026-08-18 ก่อนดึงย้อนหลัง lazada_02 + tiktok_06 ขนานกัน)

ธงเก่ากว่า MAX_AGE_HOURS ถือว่าเป็นของค้างจากงานที่ตายไปแล้ว ไม่นับ
ไม่งั้นงานที่พังกลางทางจะปิด KeepAlive ไว้ตลอดกาลโดยไม่มีใครรู้
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from src.core.config import PROJECT_ROOT

BUSY_DIR = PROJECT_ROOT / "data" / "browser_busy"
MAX_AGE_HOURS = 8.0


def _own_file() -> Path:
    return BUSY_DIR / f"{os.getpid()}.flag"


def _pid_alive(pid: int) -> bool:
    """process นี้ยังมีชีวิตอยู่ไหม

    ⚠️ ต้องเช็ค ไม่งั้นงานที่ถูกฆ่ากลางคันจะทิ้งธงค้างไว้บล็อก KeepAlive
       ยาวถึง 8 ชั่วโมง ทั้งที่ไม่มีอะไรใช้เบราว์เซอร์อยู่แล้ว
       (เจอจริง 2026-08-18: ธงค้าง 4 ใบจาก backfill ที่สั่งหยุดไป
        ทำให้ต่ออายุ session ไม่ได้เลยทั้งที่เครื่องว่าง)
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def mark_busy(what: str) -> None:
    BUSY_DIR.mkdir(parents=True, exist_ok=True)
    _own_file().write_text(f"{what}\npid={os.getpid()}\n{time.time()}\n",
                           encoding="utf-8")


def clear_busy() -> None:
    """ลบเฉพาะธงของตัวเอง — งานอื่นที่ยังทำอยู่ต้องไม่ถูกปลดธงไปด้วย"""
    _own_file().unlink(missing_ok=True)


def busy_reason() -> str | None:
    """คืนคำอธิบายถ้ามีงานยาวอยู่จริง / None ถ้าว่างหรือธงค้างเกินเวลา"""
    if not BUSY_DIR.exists():
        return None

    live: list[tuple[float, str]] = []
    for f in BUSY_DIR.glob("*.flag"):
        try:
            age_h = (time.time() - f.stat().st_mtime) / 3600
        except OSError:                      # ไฟล์หายระหว่างวน ถือว่าไม่มี
            continue
        if age_h > MAX_AGE_HOURS:
            f.unlink(missing_ok=True)        # ของค้างจากงานที่ตายไปแล้ว
            continue
        try:
            lines = f.read_text(encoding="utf-8").splitlines()
            what = lines[0]
            pid = int(lines[1].split("=", 1)[1]) if len(lines) > 1 else 0
        except (OSError, IndexError, ValueError):
            continue
        # ธงของ process ที่ตายไปแล้ว = ของค้าง ไม่ใช่งานที่ทำอยู่จริง
        if not _pid_alive(pid):
            f.unlink(missing_ok=True)
            continue
        live.append((age_h, what))

    if not live:
        return None
    live.sort(key=lambda x: -x[0])            # ตัวที่เริ่มมานานสุดขึ้นก่อน
    head = f"{live[0][1]} (เริ่มมาแล้ว {live[0][0]:.1f} ชม.)"
    if len(live) > 1:
        head += f" · และอีก {len(live) - 1} งาน"
    return head
