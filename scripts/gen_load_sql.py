r"""สร้าง LOAD_day.sql จาก ALL_COLUMNS โดยตรง

⚠️ ทำไมต้องสร้างอัตโนมัติ ไม่เขียนมือ
   เคยพลาดมาแล้ว 2 รอบ: เพิ่มคอลัมน์ใน export แต่ลืมเพิ่มใน LOAD_day.sql
   ข้อมูลถูกดึงมาครบแต่หายตอนเข้าฐาน โดยไม่มีอะไรเตือน (ค่าธรรมเนียม Shopee
   หายทั้งเดือน ก.ค. ด้วยสาเหตุนี้) ตอนนี้ทั้งสองฝั่งอ่านลิสต์เดียวกัน
   เพิ่มคอลัมน์ที่ ALL_COLUMNS ที่เดียว แล้วรันสคริปต์นี้

    .\.venv\Scripts\python.exe -u scripts\gen_load_sql.py
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.export_pg_day import ALL_COLUMNS          # noqa: E402

PSQL_PATH = r"C:\Program Files\PostgreSQL\18\bin\psql.exe"
PGPASS_PATH = r"C:\Users\tada.p\Postgres\pgpass.conf"

OUT = Path(r"C:\Users\tada.p\Postgres\LOAD_day.sql")
OUT_RANGE = Path(r"C:\Users\tada.p\Postgres\LOAD_range.sql")

# คอลัมน์ที่ INSERT จัดการเป็นพิเศษ ไม่ใช่ nullif().cast ตรง ๆ
SPECIAL = {
    "platform":     "lower(b.platform)",
    "order_id":     "b.order_id",
    "shop_id":      "b.shop_id",
    "shop_name":    "b.shop_name",
    "sku":          "coalesce(b.sku, '')",
    "variation":    "coalesce(b.variation, '')",
    "product_name": "coalesce(b.product_name, '')",
    "status_raw":   "b.status_raw",
}

TS = {"ordered_at", "order_created_at", "order_updated_at", "extracted_at",
      "paid_at", "promised_ship_at", "shipped_at",
      "delivered_at", "completed_at", "cancelled_at", "settlement_date", "fetched_at"}
TEXT = {"osuka_sml_id", "osuka_model_code", "product_brand", "mapping_status",
        "match_method", "match_confidence", "payment_method", "province",
        "parent_sku", "shipping_method", "district", "postcode", "country",
        "order_type", "fulfilled_by_platform", "owned_by_platform", "in_bundle_deal",
        "hot_listing", "tax_invoice_requested", "tax_invoice_type", "seller_note",
        "shipping_carrier", "tracking_no", "buyer_username",
        "cancel_reason", "return_status", "notes"}


def db_types() -> dict[str, str]:
    """ถามชนิดคอลัมน์จริงจากฐาน — ห้ามเดาจากชื่อหรือจากลิสต์ที่เขียนค้างไว้

    ⚠️ ทำไมต้องถาม ไม่ใช้ลิสต์อย่างเดียว
       ตัวสร้างนี้ตั้งค่าเริ่มต้นให้คอลัมน์ที่ไม่รู้จักเป็น numeric
       เพิ่มคอลัมน์ข้อความใหม่แล้วลืมใส่ใน TEXT = ทั้งรอบล้มตอนซ้อม
       ด้วยข้อความ "invalid input syntax for type numeric" ซึ่งไม่บอกว่าคอลัมน์ไหน
       (เจอจริง 2026-08-19 ตอนเพิ่ม 19 คอลัมน์ผลการจับคู่)

       ฐานเป็นเจ้าของความจริงเรื่องชนิดคอลัมน์ ถามตรง ๆ จึงไม่มีวันหลุด
       หลักการเดียวกับ ask_db_uncovered() ใน export_pg_day.py

    คืน {} ถ้าต่อฐานไม่ได้ — ตอนนั้นถอยไปใช้ลิสต์ที่เขียนไว้ พร้อมเตือนดัง ๆ
    """
    if not Path(PSQL_PATH).exists():
        return {}
    sql = ("SELECT column_name || '|' || data_type FROM information_schema.columns "
           "WHERE table_schema='intel' AND table_name='mp_order_line'")
    env = dict(os.environ, PGPASSFILE=PGPASS_PATH, PGCLIENTENCODING="UTF8")
    try:
        r = subprocess.run([PSQL_PATH, "service=osuka", "-w", "-A", "-t", "-c", sql],
                           capture_output=True, env=env, timeout=40)
        if r.returncode != 0:
            return {}
        out: dict[str, str] = {}
        for ln in r.stdout.decode("utf-8", "replace").splitlines():
            if "|" in ln:
                c, t = ln.split("|", 1)
                out[c.strip()] = t.strip()
        return out
    except Exception:                                    # noqa: BLE001
        return {}


def apply_db_types(cols: list[str]) -> None:
    """ปรับชุด TS / TEXT / BOOL ให้ตรงกับชนิดจริงในฐาน"""
    types = db_types()
    if not types:
        print("⚠️ ต่อฐานไม่ได้ — ใช้ชนิดคอลัมน์จากลิสต์ที่เขียนไว้ อาจไม่ตรงกับฐานจริง")
        return
    moved = []
    for c in cols:
        t = types.get(c)
        if not t:
            continue
        if t.startswith("timestamp") or t == "date":
            tgt, cur = TS, (c in TS)
        elif t == "boolean":
            tgt, cur = BOOL, (c in BOOL)
        elif t in ("text", "character varying", "character"):
            tgt, cur = TEXT, (c in TEXT)
        else:
            continue                                     # ตัวเลข = ค่าเริ่มต้นอยู่แล้ว
        if not cur:
            tgt.add(c)
            moved.append(c + "(" + t + ")")
    if moved:
        print("   ปรับชนิดตามฐาน " + str(len(moved)) + " คอลัมน์: "
              + ", ".join(moved[:8]) + (" ..." if len(moved) > 8 else ""))


def check_types(cols: list[str]) -> None:
    """กันพลาดแบบที่เพิ่งเจอ — คอลัมน์ที่ลงท้าย _at / _date ต้องอยู่ในชุด TS

    ครั้งที่แล้ว fetched_at หลุดจาก TS แล้วถูก cast เป็น numeric ทำให้ทั้งรอบล้ม
    ตอนซ้อม ซึ่งดีกว่าเงียบ แต่ดีที่สุดคือจับตั้งแต่ตอนสร้างไฟล์
    """
    suspect = [c for c in cols
               if (c.endswith("_at") or c.endswith("_date")) and c not in TS]
    if suspect:
        raise SystemExit(f"❌ คอลัมน์เวลาที่ยังไม่ได้ประกาศใน TS: {suspect}")
BOOL = {"needs_review"}

# คอลัมน์ที่ห้ามอัปเดตตอนชนคีย์ — เป็นตัวตนของแถว ไม่ใช่ค่าที่เปลี่ยนได้
NO_UPDATE = {"platform", "order_id", "sku", "variation", "product_name", "shop_id",
             "shop_name", "order_month"}


def expr(c: str) -> str:
    if c in SPECIAL:
        return SPECIAL[c]
    if c in TS:
        return f"nullif(b.{c}, '')::timestamp"
    if c in BOOL:
        return (f"CASE upper(nullif(b.{c}, '')) WHEN 'TRUE' THEN true "
                f"WHEN 'FALSE' THEN false ELSE NULL END")
    if c in TEXT:
        return f"nullif(b.{c}, '')"
    return f"nullif(b.{c}, '')::numeric"


def build(range_mode: bool) -> str:
    cols = list(ALL_COLUMNS)
    apply_db_types(cols)
    check_types(cols)
    stg = ",\n".join(f"    {c:<34} text" for c in cols)

    # คอลัมน์ที่เขียนลงฐาน = ทุกตัวใน CSV + ที่คำนวณเพิ่ม
    ins = ["line_id"] + cols + ["order_status", "order_month", "source_file", "loaded_at"]
    sel = ["    b.new_line_id"] + [f"    {expr(c)}" for c in cols] + [
        "    intel.mp_order_state_v2(b.platform, b.status_raw, "
        "nullif(b.paid_at,'')::timestamp)",
        "    to_char(nullif(b.ordered_at, '')::timestamp, 'YYYY-MM')",
        "    '__CSVNAME__'",
        "    now()",
    ]
    upd = [c for c in cols if c not in NO_UPDATE] + [
        "order_status", "source_file", "loaded_at"]

    sql = f"""-- =====================================================================
-- LOAD_day.sql — โหลดข้อมูล 1 วัน ทุกร้านทุกแพลตฟอร์ม เข้า intel.mp_order_line
--
-- ⚠️ ไฟล์นี้ถูกสร้างโดย scripts/gen_load_sql.py — ห้ามแก้มือ
--    ต้องการเพิ่มคอลัมน์: เพิ่มที่ ALL_COLUMNS ใน export_pg_day.py แล้วรันตัวสร้างใหม่
--    เขียนมือเมื่อไหร่ export กับ load จะไม่ตรงกัน แล้วข้อมูลจะหายเงียบ ๆ
--
-- วิธีเรียก:
--   psql service=osuka-build -v day=2026-08-02 -v commit=1 -f LOAD_day.sql
--   ไม่ใส่ -v commit=1 = ซ้อมแล้ว ROLLBACK (ควรทำก่อนเสมอ)
-- =====================================================================
\\set ON_ERROR_STOP on
\\encoding UTF8

BEGIN;
SET LOCAL transaction_read_only = off;

CREATE TEMP TABLE stg (
{stg}
) ON COMMIT DROP;

-- CSV ใส่เครื่องหมายคำพูดทุกช่อง (QUOTE_ALL) ช่องว่างจึงเข้ามาเป็น '' ไม่ใช่ NULL
--
-- ⚠️ \\copy ไม่แทนค่าตัวแปร :'csv' ให้ (ต่างจากคำสั่ง SQL ปกติ) ตัวขับจึงต้อง
--    แทนคำว่า __CSV__ ด้วย path จริงก่อนส่งเข้า psql
\\copy stg FROM '__CSV__' WITH (FORMAT csv, HEADER true, QUOTE '"')

\\echo ''
\\echo '--- ตรวจไฟล์ก่อนเขียน ---'
SELECT count(*)                          AS บรรทัด,
       count(DISTINCT order_id)          AS ออเดอร์,
       sum(nullif(quantity,'')::numeric) AS ชิ้น,
       count(DISTINCT shop_id)           AS ร้าน,
       round(sum(nullif(revenue_thb,'')::numeric)) AS ยอดรวม
FROM   stg;

-- กันไฟล์ผิดวัน — เคยหยิบผิดเพราะโฟลเดอร์ตั้งชื่อตามวันรัน ไม่ใช่วันข้อมูล
\\echo ''
\\echo '--- ต้องได้ 0 แถว: บรรทัดที่ไม่ใช่วันที่สั่งโหลด ---'
SELECT count(*) AS แถวผิดวัน
FROM   stg WHERE nullif(ordered_at,'')::timestamp::date <> :'day'::date;

\\echo ''
\\echo '--- สถานะที่จะได้หลังแปลง ---'
SELECT intel.mp_order_state_v2(platform, status_raw,
                               nullif(paid_at,'')::timestamp) AS order_status,
       count(*) AS lines
FROM   stg GROUP BY 1 ORDER BY 2 DESC;

-- ---------------------------------------------------------------------
-- line_id ไม่มี default ต้องต่อจาก max เดิมเอง
-- counts_as_sale เป็น generated column ห้ามเขียน
-- ---------------------------------------------------------------------
WITH base AS (
    SELECT s.*,
           (SELECT coalesce(max(line_id),0) FROM intel.mp_order_line) +
           row_number() OVER (ORDER BY s.order_id, s.sku, s.variation, s.product_name)
               AS new_line_id
    FROM   stg s
)
INSERT INTO intel.mp_order_line (
{",".join(chr(10) + "    " + c for c in ins)}
)
SELECT
{",".join(chr(10) + s for s in sel)}
FROM base b
ON CONFLICT (platform, order_id, sku,
             COALESCE(variation, ''), COALESCE(product_name, ''))
DO UPDATE SET
{",".join(chr(10) + f"    {c:<34} = excluded.{c}" for c in upd)};
    -- ไม่แตะ line_id ตอน conflict — แถวเดิมต้องเก็บเลขเดิมไว้

\\echo ''
\\echo '--- ผลในฐานหลังโหลด (เทียบกับตัวเลขไฟล์ด้านบน) ---'
SELECT order_status, count(*) AS lines, round(sum(revenue_thb)) AS thb
FROM   intel.mp_order_line WHERE ordered_at::date = :'day'::date
GROUP  BY 1 ORDER BY 2 DESC;

SELECT count(*) AS บรรทัดรวม, count(DISTINCT order_id) AS ออเดอร์,
       sum(quantity) AS ชิ้น, count(DISTINCT shop_id) AS ร้าน,
       round(sum(revenue_thb)) AS ยอดรวม
FROM   intel.mp_order_line WHERE ordered_at::date = :'day'::date;

\\echo ''
\\echo '--- ต้องได้ 0 ทุกข้อ ---'
SELECT count(*) AS คีย์ซ้ำ FROM (
  SELECT 1 FROM intel.mp_order_line WHERE ordered_at::date = :'day'::date
  GROUP BY platform, order_id, sku, COALESCE(variation,''), COALESCE(product_name,'')
  HAVING count(*) > 1) d;

SELECT count(*) AS สถานะไม่ตรง
FROM   intel.mp_order_line
WHERE  ordered_at::date = :'day'::date
  AND  order_status IS DISTINCT FROM
       intel.mp_order_state_v2(platform, status_raw, paid_at);

-- Dashboard วัดความสดของร้านจาก fetched_at ถ้าว่างหน้าเว็บจะขึ้นว่าร้านค้าง
SELECT count(*) AS fetched_at_ว่าง
FROM   intel.mp_order_line
WHERE  ordered_at::date = :'day'::date AND fetched_at IS NULL;

-- ยอดรายบรรทัดต้องรวมกันได้เท่ายอดออเดอร์ที่แพลตฟอร์มแจ้ง
-- ถ้าไม่เท่า แปลว่าการเฉลี่ยใน export_pg_day.py เพี้ยน
\\echo ''
\\echo '--- ออเดอร์ที่ผลรวมรายบรรทัดไม่เท่ายอดออเดอร์ (ต้องได้ 0) ---'
SELECT count(*) AS ออเดอร์ที่ยอดไม่ตรง FROM (
  SELECT order_id
  FROM   intel.mp_order_line
  WHERE  ordered_at::date = :'day'::date AND total_amount IS NOT NULL
  GROUP  BY platform, order_id
  HAVING abs(sum(revenue_thb) - max(total_amount)) > 1) d;

\\if :{{?commit}}
COMMIT;
\\else
ROLLBACK;
\\echo ''
\\echo '*** ROLLBACK — ยังไม่ได้เขียนจริง ส่ง -v commit=1 เมื่อพร้อม ***'
\\endif
"""
    if range_mode:
        # โหมดช่วง: เปลี่ยนเงื่อนไขวันเดียวเป็นช่วง แล้วรับตัวแปร d_from/d_to แทน day
        #
        # ⚠️ ทำไมต้องมีโหมดนี้ — งานย้อนหลัง 212 วัน ถ้าโหลดทีละวันต้องเปิด/ปิด
        #    transaction 424 รอบ (ซ้อม+เขียนจริง วันละ 2 รอบ) ทั้งที่ข้อมูลจริง
        #    แค่ราว 60,000 แถว เวลาเกือบทั้งหมดหมดไปกับ overhead ไม่ใช่การเขียน
        #    รวบเป็นรอบเดียวเหลือราว 5 นาที จาก 55 นาที
        #    ด่านตรวจทุกตัวยังอยู่ครบ แค่เปลี่ยนขอบเขตจาก "วันนั้น" เป็น "ช่วงนั้น"
        s = sql
        s = s.replace("ordered_at::date = :'day'::date",
                      "ordered_at::date BETWEEN :'d_from'::date AND :'d_to'::date")
        s = s.replace("nullif(ordered_at,'')::timestamp::date <> :'day'::date",
                      "nullif(ordered_at,'')::timestamp::date "
                      "NOT BETWEEN :'d_from'::date AND :'d_to'::date")
        s = s.replace("-- LOAD_day.sql — โหลดข้อมูล 1 วัน",
                      "-- LOAD_range.sql — โหลดข้อมูลหลายวันรวดเดียว")
        s = s.replace("psql service=osuka-build -v day=2026-08-02 -v commit=1 -f LOAD_day.sql",
                      "psql service=osuka-build -v d_from=2026-01-01 -v d_to=2026-07-31 "
                      "-v commit=1 -f LOAD_range.sql")
        s = s.replace("บรรทัดที่ไม่ใช่วันที่สั่งโหลด", "บรรทัดที่อยู่นอกช่วงที่สั่งโหลด")
        assert ":'day'" not in s, "ยังมี :'day' ค้างอยู่ในโหมดช่วง"
        return s
    return sql


def main() -> int:
    for path, rng in ((OUT, False), (OUT_RANGE, True)):
        path.write_text(build(rng), encoding="utf-8")
        print(f"✅ เขียน {path.name}" + ("  (โหมดช่วงวัน)" if rng else ""))
    print(f"   คอลัมน์จาก CSV {len(ALL_COLUMNS)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
