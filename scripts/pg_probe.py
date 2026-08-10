r"""สำรวจฐาน osuka_intel แบบอ่านอย่างเดียว — เตรียมก่อนโหลดข้อมูล

⚠️ สคริปต์นี้ไม่เขียนอะไรลงฐานเลย มีแต่ SELECT
   กฎของโปรเจกต์ Postgres: อ่านทำได้เลย เขียนต้องขออนุญาตเป็นรายครั้ง

⚠️ ไม่แสดงรหัสผ่าน ไม่อ่านไฟล์ pgpass — ใช้ service= ให้ libpq จัดการเอง

    .\.venv\Scripts\python.exe -u scripts\pg_probe.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

SERVICES = ("osuka", "osuka-build")
TABLE = ("intel", "mp_order_line")

# ⚠️ libpq ที่มากับ psycopg หาไฟล์ service เองไม่เจอบนเครื่องนี้
#    ของจริงอยู่ที่ %APPDATA%\postgresql\.pg_service.conf (มีจุดนำหน้า)
#    ชี้ด้วย PGSERVICEFILE ให้ชัด จะได้ไม่ต้องเดาว่า libpq มองที่ไหน
#    ⚠️ ไม่เปิดอ่านไฟล์นี้ — ปล่อยให้ libpq จัดการรหัสผ่านเอง
_svc_file = Path(os.environ.get("APPDATA", "")) / "postgresql" / ".pg_service.conf"
if _svc_file.exists() and not os.environ.get("PGSERVICEFILE"):
    os.environ["PGSERVICEFILE"] = str(_svc_file)


def connect() -> tuple[psycopg.Connection, str]:
    last = None
    for svc in SERVICES:
        try:
            con = psycopg.connect(f"service={svc}", connect_timeout=10)
            return con, svc
        except Exception as exc:                         # noqa: BLE001
            last = f"{svc}: {type(exc).__name__}: {str(exc)[:110]}"
    print(f"❌ ต่อไม่ได้ทุก service ที่ลอง {SERVICES}")
    print(f"   PGSERVICEFILE = {os.environ.get('PGSERVICEFILE', '(ไม่ได้ตั้ง)')}")
    print(f"   ล่าสุด: {last}")
    sys.exit(1)


con, svc = connect()
print(f"✅ ต่อได้ด้วย service={svc}")

with con:
    with con.cursor() as cur:
        cur.execute("select current_database(), current_user, version()")
        db, user, ver = cur.fetchone()
        print(f"   ฐาน {db} · ผู้ใช้ {user}")
        print(f"   {ver.split(',')[0]}")

        cur.execute("""
            select table_schema, table_name
            from information_schema.tables
            where table_schema='intel' and table_name like 'mp\\_%'
            order by table_name
        """)
        print("\n=== ตาราง intel.mp_* ที่มี ===")
        for s, t in cur.fetchall():
            print(f"   {s}.{t}")

        cur.execute("""
            select column_name, data_type, is_nullable, is_generated,
                   column_default is not null as has_default
            from information_schema.columns
            where table_schema=%s and table_name=%s
            order by ordinal_position
        """, TABLE)
        cols = cur.fetchall()
        if not cols:
            print(f"\n❌ ไม่พบตาราง {TABLE[0]}.{TABLE[1]}")
        else:
            print(f"\n=== {TABLE[0]}.{TABLE[1]} · {len(cols)} คอลัมน์ ===")
            for name, typ, nullable, gen, dflt in cols:
                flag = ""
                if gen and gen != "NEVER":
                    flag = "  ⛔ generated — ห้ามเขียน"
                elif dflt:
                    flag = "  (มีค่า default)"
                print(f"   {name:<26} {typ:<28}{flag}")

        cur.execute("""
            select p.proname, pg_get_function_identity_arguments(p.oid)
            from pg_proc p join pg_namespace n on n.oid=p.pronamespace
            where n.nspname='intel' and p.proname='mp_order_state'
        """)
        fn = cur.fetchall()
        print(f"\n=== ฟังก์ชัน intel.mp_order_state ===")
        print(f"   {fn if fn else '❌ ไม่พบ'}")

        cur.execute("""
            select count(*) from intel.mp_order_line
            where shop_id='shopee_08' and ordered_at::date = date '2026-08-01'
        """)
        print(f"\n=== มีข้อมูลของงานนี้อยู่แล้วไหม ===")
        print(f"   shopee_08 วันที่ 2026-08-01: {cur.fetchone()[0]} แถว")

        cur.execute("select count(*) from intel.mp_order_line")
        print(f"   ทั้งตาราง: {cur.fetchone()[0]:,} แถว")
