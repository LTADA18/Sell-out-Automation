"""ตัวตั้งค่าที่ต้องมีผลก่อนโค้ดอื่นทำงาน

⚠️ บังคับ stdout/stderr เป็น UTF-8 ตั้งแต่ import แรก

บน Windows ถ้า stdout ถูก redirect ลงไฟล์หรือ pipe Python จะใช้ codepage ของระบบ
(cp1252/cp874) ซึ่งเขียนภาษาไทยไม่ได้ พอ print ข้อความไทยก็โยน UnicodeEncodeError
แล้วโปรเซสตายทันที — ทั้งที่งานจริงสำเร็จไปแล้ว

เจอ 2 รอบในวันเดียว (2026-08-10):
  · `cli backfill` ดึงวันแรกครบแล้วตายตอนพิมพ์สรุป วันที่ 2-9 ไม่เคยถูกดึง
  · `screen_orders.py` กับ `merge_range.py` ตายตอนพิมพ์เหมือนกัน หลังดึงครบ 90 รอบ

รอบแรกผมไปแก้ไว้ที่ src/cli.py ที่เดียว ซึ่งไม่ครอบสคริปต์ใน scripts/
ย้ายมาไว้ตรงนี้เพราะทุกสคริปต์ import จาก src.core อยู่แล้ว — แก้ที่เดียวจบ
"""
from __future__ import annotations

import sys

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):                 # ไม่ใช่ TextIO ก็ปล่อยผ่าน
        pass
