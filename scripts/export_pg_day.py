r"""เตรียมข้อมูล "ทั้งวัน ทุกร้าน ทุกแพลตฟอร์ม" ส่งให้ฝั่ง Postgres โหลด

ต่างจาก `export_pg_handoff.py` ที่ทำทีละร้าน ตัวนี้รวมทุกร้านของวันนั้นเป็นไฟล์เดียว
เพื่อให้ Dashboard โชว์ได้ทั้งวันจริง ไม่ใช่ร้านเดียวโดด ๆ

⚠️ ตัวที่กัดแน่ถ้าไม่ระวัง — `intel.mp_order_state()` ฉบับที่อยู่ในฐานตอนนี้
   รู้จักเฉพาะคำของ Shopee พอเจอคำของ Lazada/TikTok จะ RAISE แล้วทั้งทรานแซกชันล้ม
   สคริปต์นี้จึงไล่เช็คคำสถานะให้ก่อน แล้วบอกว่าตัวไหนยังไม่มีในบันได

    .\.venv\Scripts\python.exe -u scripts\export_pg_day.py --date 2026-08-01
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from openpyxl import load_workbook

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

BLANKS = {"null", "none", "nan", "n/a", "na", "-", "nil", ""}

# คอลัมน์ที่ส่งให้ปลายทาง — ตรงกับที่ LOAD_revised.sql ฝั่ง Postgres เขียนจริง
# เพิ่ม shop_name จากของเดิม เพราะทำหลายร้านจะ hardcode ชื่อเดียวไม่ได้
COLUMNS = [
    "platform", "order_id", "shop_id", "shop_name",
    "sku", "variation", "product_name",
    "quantity", "item_price", "revenue_thb", "total_amount",
    "ordered_at", "order_created_at", "paid_at", "status_raw",
    "osuka_sml_id", "osuka_model_code", "product_brand", "mapping_status",
    "match_method", "match_confidence", "needs_review",
]

# ── คอลัมน์ที่มีก็เอา ไม่มีก็ปล่อยว่าง ─────────────────────────
# แยกจาก COLUMNS เพราะไฟล์สกรีนรุ่นเก่ายังไม่มีคอลัมน์การเงินชุดใหม่
# ถ้าใส่รวมใน COLUMNS สคริปต์จะ error แล้วโหลดข้อมูลย้อนหลังไม่ได้เลย
#
# ⚠️ เดิม CSV ที่ส่งเข้าฐานไม่มีคอลัมน์การเงินสักตัว แม้แต่ของ Shopee
#    ที่เปิดใช้ไปแล้ว ข้อมูลจึงตกหล่นตั้งแต่ขั้นส่งเข้าฐาน ไม่ใช่ขั้นดึง
OPTIONAL_COLUMNS = [
    "item_discount", "seller_discount", "platform_discount",
    "shipping_fee", "commission_fee", "transaction_fee", "service_fee",
    "settlement_amount", "payment_method", "province",
    # 5 ตัวใหม่ของ TikTok เปิดใช้ 2026-08-11
    "item_subtotal_before_discount", "payment_discount", "tax_amount",
    "shipping_fee_seller_discount", "shipping_fee_platform_discount",
]

# บันไดที่ mp_order_state() ในฐานรู้จักตอนนี้ (Shopee ล้วน)
SHOPEE_PREFIX = "ผู้ซื้อได้รับสินค้าแล้ว"
SHOPEE_KNOWN = {
    "สำเร็จแล้ว", "จัดส่งสำเร็จแล้ว", "การจัดส่ง",
    "ที่ต้องจัดส่ง", "คำขอยกเลิก", "ยกเลิกแล้ว",
}


ALL_COLUMNS = COLUMNS + OPTIONAL_COLUMNS

I_SKU, I_VAR, I_NAME = (ALL_COLUMNS.index("sku"), ALL_COLUMNS.index("variation"),
                        ALL_COLUMNS.index("product_name"))
I_QTY, I_REV = ALL_COLUMNS.index("quantity"), ALL_COLUMNS.index("revenue_thb")
I_ORDERED, I_STATUS = ALL_COLUMNS.index("ordered_at"), ALL_COLUMNS.index("status_raw")


# ยุบช่องว่างทุกชนิดที่ติดกันให้เหลือช่องว่างเดียว
#
# ⚠️ ทำไมต้องยุบ: sku / variation / product_name เป็น 3 ใน 5 คอลัมน์ของคีย์
#    ไฟล์ Export ส่งค่าเดิมมาไม่เหมือนกันทุกครั้ง เจอทั้งอักขระขึ้นบรรทัดใหม่
#    ฝังกลาง sku และช่องว่างซ้อน เช่น 'OCMC537-M1 +  OCMC2536'
#    ถ้าไม่ยุบ ครั้งหน้าที่ต้นทางส่งมาต่างไปนิดเดียว คีย์จะเปลี่ยน แล้ว
#    ON CONFLICT DO UPDATE จะหาแถวเดิมไม่เจอ กลายเป็นแถวใหม่ซ้อนเข้ามาแทน
#
# กฎนี้ต้องตรงกับฝั่งฐานเป๊ะ: btrim(regexp_replace(col, '\s+', ' ', 'g'))
# \s ของ Python ครอบ \xa0 (non-breaking space) ด้วย ส่วนของ Postgres ไม่ครอบ
# จึงแปลง \xa0 เป็นช่องว่างธรรมดาก่อน ทั้งสองฝั่งจะได้ผลลัพธ์เดียวกัน
_WS = re.compile(r"\s+")


def clean(v: object) -> str:
    if v is None:
        return ""
    s = _WS.sub(" ", str(v).replace("\xa0", " ")).strip()
    return "" if s.lower() in BLANKS else s


def num(s: str) -> float:
    try:
        return float(s or 0)
    except ValueError:
        return 0.0


def fmt(x: float) -> str:
    """คืนเป็นจำนวนเต็มถ้าลงตัว — กัน quantity กลายเป็น 2.0 ใน CSV"""
    return str(int(x)) if x == int(x) else repr(x)


def merge(keep: list[str], extra: list[str]) -> None:
    """รวม 2 บรรทัดที่มีคีย์ 5 คอลัมน์เดียวกันให้เหลือบรรทัดเดียว

    บวกเฉพาะ quantity กับ revenue_thb — สองตัวนี้เป็นค่าราย "บรรทัด" จริง
    ห้ามบวก total_amount เด็ดขาด เพราะเป็นค่าระดับ "ออเดอร์" ที่ซ้ำอยู่ทุกบรรทัด
    ของตะกร้าเดียวกัน บวกแล้วยอดจะพองตามจำนวนสินค้าในตะกร้า
    item_price เป็นราคาต่อชิ้น ก็ไม่บวกเช่นกัน
    """
    keep[I_QTY] = fmt(num(keep[I_QTY]) + num(extra[I_QTY]))
    keep[I_REV] = fmt(num(keep[I_REV]) + num(extra[I_REV]))


def covered(status: str) -> bool:
    """ฟังก์ชันในฐานตอนนี้แปลงค่านี้ได้ไหม"""
    return status.startswith(SHOPEE_PREFIX) or status in SHOPEE_KNOWN


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-08-01")
    args = ap.parse_args()

    d = date.fromisoformat(args.date)
    run_date = (d + timedelta(days=1)).isoformat()
    src_dir = PROJECT_ROOT / "output" / run_date / "screened"
    # glob นี้ตัดไฟล์สรุป (brand_summary / data_issues / missing_models) ออกเองอยู่แล้ว
    files = sorted(src_dir.glob("*_matched.xlsx"))
    if not files:
        print(f"❌ ไม่พบไฟล์สกรีนของวันที่ {d} ใน {src_dir}")
        return 1
    print(f"ไฟล์ต้นทาง {len(files)} ไฟล์ จาก {src_dir.relative_to(PROJECT_ROOT)}\n")

    out_dir = PROJECT_ROOT / "output" / f"_pg_day_{d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / f"all_shops_{d}.csv"

    staged: dict[tuple, list[str]] = {}
    keys: Counter = Counter()
    uncovered: Counter = Counter()
    off_day: Counter = Counter()
    merged_rows = 0
    raw_qty = 0

    for src in files:
        wb = load_workbook(src, read_only=True, data_only=True)
        try:
            ws = wb["data"]
            it = ws.iter_rows(values_only=True)
            hdr = [str(c) if c is not None else "" for c in next(it)]
            missing = [c for c in COLUMNS if c not in hdr]
            if missing:
                print(f"❌ {src.name} ขาดคอลัมน์ {missing}")
                return 1
            # คอลัมน์ทางเลือก: ไม่มีก็ไม่เป็นไร ปล่อยเป็นค่าว่าง ไม่ทำให้ทั้งรอบล้ม
            idx = {c: hdr.index(c) for c in COLUMNS}
            idx.update({c: hdr.index(c) for c in OPTIONAL_COLUMNS if c in hdr})

            for r in it:
                if not any(v is not None for v in r):
                    continue
                vals = [clean(r[idx[c]]) if c in idx else ""
                        for c in ALL_COLUMNS]
                vals[0] = vals[0].lower()

                # กันไฟล์ปนวัน — เคยโดนมาแล้วตอนสกรีน ไฟล์ค้างทำยอดเฟ้อ 18%
                day = vals[I_ORDERED][:10]
                if day != args.date:
                    off_day[day] += 1
                    continue

                raw_qty += num(vals[I_QTY])

                k = (vals[0], vals[1], vals[I_SKU], vals[I_VAR], vals[I_NAME])
                keys[k] += 1
                if k in staged:
                    # ⚠️ ยุบรวม ห้ามทิ้ง — Shopee ส่งสินค้าเดียวกันในออเดอร์เดียว
                    #    มาเป็น 2 บรรทัดได้จริง ถ้าปล่อยไปชนกันที่ปลายทาง
                    #    ON CONFLICT DO UPDATE จะทับทิ้ง ทำให้จำนวนชิ้นกับยอดเงินหายเงียบ ๆ
                    #    (Lazada ยุบแบบนี้อยู่แล้วตั้งแต่ต้นทาง Shopee เพิ่งเจอ)
                    merge(staged[k], vals)
                    merged_rows += 1
                    continue
                staged[k] = vals
        finally:
            wb.close()

    with csv_path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, quoting=csv.QUOTE_ALL, lineterminator="\n")
        w.writerow(ALL_COLUMNS)
        for vals in staged.values():
            w.writerow(vals)

    per_shop: dict[str, list] = defaultdict(lambda: [0, set()])
    per_platform: Counter = Counter()
    orders: set[str] = set()
    qty = 0
    for vals in staged.values():
        orders.add(vals[1])
        qty += num(vals[I_QTY])
        per_shop[vals[2]][0] += 1
        per_shop[vals[2]][1].add(vals[1])
        per_platform[vals[0]] += 1
        st = vals[I_STATUS]
        if not covered(st):
            uncovered[f"{vals[0]} · {st}"] += 1

    n = len(staged)
    dup_keys = {k: c for k, c in keys.items() if c > 1}

    print("=== ตัวเลขจากไฟล์ต้นทาง (ใช้กระทบยอด ไม่ได้นับจากฐาน) ===")
    print(f"  บรรทัดสินค้า   {n:,}")
    print(f"  ออเดอร์ไม่ซ้ำ  {len(orders):,}")
    print(f"  ผลรวม quantity {qty:,.0f}")
    if merged_rows:
        print(f"  ยุบรวม {len(dup_keys)} คีย์ · {merged_rows} แถว "
              f"— quantity ก่อนยุบ {raw_qty:,.0f} หลังยุบ {qty:,.0f} "
              f"({'ครบ ไม่หาย' if raw_qty == qty else f'⚠️ หาย {raw_qty - qty:,.0f}'})")
    if off_day:
        print(f"  ⚠️ ตัดแถวที่ไม่ใช่วันที่ {args.date} ออก {sum(off_day.values()):,} แถว "
              f"({dict(list(off_day.items())[:4])})")

    print("\n=== แยกตามแพลตฟอร์ม ===")
    for p, c in per_platform.most_common():
        print(f"  {p:<10} {c:>7,}")

    print("\n=== แยกตามร้าน ===")
    for shop in sorted(per_shop):
        rows, ords = per_shop[shop]
        print(f"  {shop:<12} {rows:>6,} บรรทัด · {len(ords):>5,} ออเดอร์")

    print(f"\n✅ {csv_path.relative_to(PROJECT_ROOT)}  ({csv_path.stat().st_size/1024:,.0f} KB)")

    if uncovered:
        print(f"\n⛔ คำสถานะที่ mp_order_state() ฉบับปัจจุบันแปลงไม่ได้ "
              f"— รวม {sum(uncovered.values()):,} แถว")
        print("   ถ้าโหลดตอนนี้ ฟังก์ชันจะ RAISE แล้วทรานแซกชันล้มทั้งก้อน")
        for k, c in uncovered.most_common():
            print(f"   {c:>6,}  {k}")
    else:
        print("\n✅ คำสถานะทุกค่าอยู่ในบันไดที่ฐานรู้จักแล้ว")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
