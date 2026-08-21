"""รายชื่อผู้รับอีเมล — อ่านจาก config/recipients.yaml ที่ไม่ถูก commit

⚠️ ทำไมต้องแยกออกมาเป็นไฟล์ต่างหาก
   เดิมรายชื่ออีเมลพนักงานจริง 22 คนฝังอยู่ในโค้ด 3 ไฟล์
   (send_report.ps1 / mailer.py / keepalive.py) พอโปรเจกต์ขึ้น git
   ที่อยู่เหล่านั้นก็ติดขึ้นไปทั้งประวัติ เป็นข้อมูลของคนอื่นที่เราไม่ควร
   เผยแพร่แทนเขา และเป็นเป้าฟิชชิ่งถ้า repo เปลี่ยนเป็นสาธารณะวันหลัง

⚠️ ทำไมต้อง "ที่เดียว" ไม่ใช่ไฟล์ละชุด
   ของเดิม run_daily.ps1 มีรายชื่อ CC ของตัวเอง 4 คน แยกจาก send_report.ps1
   ที่มี 20 คน พอเจ้าของงานสั่งเพิ่มคนใหม่ ก็แก้แค่ไฟล์เดียว อีเมลรายวัน
   จึงส่งถึงแค่ 5 คนมาตลอดโดยไม่มีใครรู้ (เจอจริง 2026-08-19)
   ค่าเดียวกันเก็บ 2 ที่แล้วอัปเดตที่เดียว = บั๊กที่ไม่มีอะไรเตือน

⚠️ ไฟล์หายต้องพังแบบดัง ห้ามคืนรายชื่อว่างเงียบ ๆ
   ถ้าคืนลิสต์ว่าง อีเมลจะ "ส่งสำเร็จ" โดยไม่ถึงใครเลย ซึ่งแย่กว่าส่งไม่ออก
   เพราะไม่มีสัญญาณอะไรบอกว่าผิด ตรงกับกฎเหล็กข้อ 1 ห้ามเดาแทนข้อมูลที่ไม่มี

ใช้จาก Python:
    from src.core.recipients import report_to, report_cc, alert_to

ใช้จาก PowerShell (PS 5.1 อ่าน YAML เองไม่ได้ จึงเรียกผ่าน python):
    python -m src.core.recipients --group report --field cc
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = PROJECT_ROOT / "config" / "recipients.yaml"
EXAMPLE_FILE = PROJECT_ROOT / "config" / "recipients.example.yaml"


class RecipientsError(RuntimeError):
    """หารายชื่อผู้รับไม่ได้ — ห้ามส่งอีเมลต่อ"""


def _fail(msg: str) -> "RecipientsError":
    return RecipientsError(
        f"{msg}\n"
        f"  ไฟล์ที่ต้องมี : {CONFIG_FILE}\n"
        f"  ตัวอย่าง      : {EXAMPLE_FILE}\n"
        f"  วิธีแก้        : copy config\\recipients.example.yaml "
        f"config\\recipients.yaml แล้วเติมที่อยู่จริง\n"
        f"  (ไฟล์จริงอยู่ใน .gitignore โดยตั้งใจ — เป็นอีเมลของคนอื่น "
        f"ไม่ควรขึ้น git)"
    )


def load() -> dict:
    if not CONFIG_FILE.exists():
        raise _fail("ไม่พบไฟล์รายชื่อผู้รับอีเมล")
    try:
        data = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise _fail(f"ไฟล์รายชื่อผู้รับอ่านไม่ออก ({exc})") from exc
    if not isinstance(data, dict):
        raise _fail("ไฟล์รายชื่อผู้รับต้องเป็น mapping ของกลุ่มผู้รับ")
    return data


def get(group: str, field: str = "to") -> list[str]:
    """คืนรายชื่อของกลุ่มนั้น — ว่างไม่ได้ ยกเว้น field 'cc'"""
    data = load()
    block = data.get(group)
    if not isinstance(block, dict):
        raise _fail(f'ไม่มีกลุ่ม "{group}" ในไฟล์รายชื่อผู้รับ')

    raw = block.get(field) or []
    if isinstance(raw, str):                      # เขียนเป็นบรรทัดเดียวก็รับ
        raw = [x for x in raw.replace(";", ",").split(",")]
    addrs = [str(x).strip() for x in raw if str(x).strip()]

    # cc ว่างได้ (ส่งถึงคนเดียวก็ถูกต้อง) แต่ to ว่างไม่ได้เด็ดขาด
    if not addrs and field != "cc":
        raise _fail(f'กลุ่ม "{group}" ไม่มีที่อยู่ในช่อง "{field}" เลย')

    bad = [a for a in addrs if "@" not in a]
    if bad:
        raise _fail(f'กลุ่ม "{group}" มีที่อยู่ที่ไม่มี @ : {", ".join(bad)}')
    return addrs


def report_to() -> list[str]:
    """ผู้รับหลักของอีเมลรายงานยอดขายประจำวัน"""
    return get("report", "to")


def report_cc() -> list[str]:
    """สำเนาถึงของอีเมลรายงานยอดขายประจำวัน"""
    return get("report", "cc")


def alert_to() -> list[str]:
    """คนที่ต้องรู้เมื่อระบบดึงไม่ครบ หรือมีร้านต้องล็อกอินเอง

    คนละชุดกับผู้รับรายงานยอด — เตือนเป็นเรื่องของคนที่ลงมือแก้
    ไม่ใช่เรื่องของทุกคนที่ดูยอด
    """
    return get("alert", "to")


def main() -> int:
    ap = argparse.ArgumentParser(description="พิมพ์รายชื่อผู้รับให้สคริปต์อื่นใช้")
    ap.add_argument("--group", required=True, help="report | alert")
    ap.add_argument("--field", default="to", help="to | cc")
    ap.add_argument("--sep", default=",", help="ตัวคั่น (ค่าเริ่มต้น ,)")
    args = ap.parse_args()
    try:
        print(args.sep.join(get(args.group, args.field)))
    except RecipientsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
