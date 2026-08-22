"""เทสต์ตัวแปลงรายงานโฆษณา Shopee

ตัวอย่างในไฟล์นี้ลอกโครงมาจากไฟล์จริงที่ดึงเมื่อ 2026-08-22
(ข้อมูล-Shopee-Ads-01/07/2026-31/07/2026.csv และ
 Shop+-Ads-Overall-Data-01/08/2026-21/08/2026.csv)
ตัวเลขย่อลงให้ตรวจด้วยตาได้ แต่รูปแบบ (หัวไฟล์ 7 บรรทัด, % , comma, "-")
เหมือนของจริงทุกอย่าง
"""
from __future__ import annotations

import pytest

from src.ads.parser import (find_header_row, parse_shopee_ads,
                            parse_tiktok_ads, to_number)

HEAD = (
    "รายงานโฆษณา CPC ทั้งหมด - Shopee ประเทศไทย\n"
    "User Name,smarttooltech\n"
    "ชื่อร้านค้า,Smarttooltech\n"
    "Shop ID,151330951\n"
    "รายงานถูกสร้างเมื่อ,04/08/2026 11:12\n"
    "ระยะเวลา,01/07/2026 - 31/07/2026\n"
    "\n"
)

ALL_ADS = HEAD + (
    "ลำดับ,ชื่อโฆษณา,สถานะ,ประเภทโฆษณา,รหัสสินค้า,การมองเห็น,จำนวนคลิก,"
    "อัตราการคลิก (CTR),การสั่งซื้อ,การสั่งซื้อโดยตรง,อัตราการสั่งซื้อ,"
    "ราคาต่อการสั่งซื้อ,สินค้าที่ขายแล้ว,ยอดขาย,ยอดขายโดยตรง,ค่าโฆษณา,"
    "ยอดขาย/รายจ่าย (ROAS),ACOS\n"
    "1,Shop GMV Max,กำลังดำเนินการ,,-,\"2,127,590\",\"91,472\",4.30%,"
    "\"3,180\",\"2,036\",3.48%,47.60,\"3,348\",\"7,936,274.00\","
    "\"6,402,603.00\",\"151,368.88\",52.43,1.91%\n"
    "2,รวมสินค้า Osuka,หยุดชั่วคราว,โฆษณาสินค้า,-,\"1,079,516\",\"45,532\",4.22%,"
    "\"1,359\",\"1,143\",2.98%,56.37,\"1,415\",\"3,373,916.60\","
    "\"2,900,000.00\",\"76,603.62\",44.04,2.27%\n"
)

KEYWORD_HEAD = HEAD.replace("รายงานโฆษณา CPC ทั้งหมด", "รายงานโฆษณาคำค้นหา")
KEYWORD = KEYWORD_HEAD + (
    "ลำดับ,ชื่อโฆษณา,สถานะ,การตั้งราคาประมูล,Keywords,ส่วนแบ่งการมองเห็น (SOV),"
    "การมองเห็น,จำนวนคลิก,อัตราการคลิก (CTR),การสั่งซื้อ,การสั่งซื้อโดยตรง,"
    "อัตราการสั่งซื้อ,ราคาต่อการสั่งซื้อ,สินค้าที่ขายแล้ว,ยอดขาย,ยอดขายโดยตรง,"
    "ค่าโฆษณา,ยอดขาย/รายจ่าย (ROAS),ACOS\n"
    "1,โฆษณาคำค้นหา A,กำลังดำเนินการ,ตั้งราคาเอง,ประแจ,12.5%,"
    "\"10,000\",500,5.00%,20,15,4.00%,25.00,22,\"50,000.00\","
    "\"40,000.00\",\"500.00\",100.00,1.00%\n"
)

KEYWORD_EMPTY = KEYWORD_HEAD + (
    "ลำดับ,ชื่อโฆษณา,สถานะ,การตั้งราคาประมูล,Keywords,ส่วนแบ่งการมองเห็น (SOV),"
    "การมองเห็น,จำนวนคลิก\n"
)


def _write(tmp_path, name: str, body: str):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8-sig")
    return p


# ── to_number ────────────────────────────────────────────────
@pytest.mark.parametrize("raw,want", [
    ("4.30%", 0.043),
    ("\"7,936,274.00\"".strip('"'), 7936274.0),
    ("151368.88", 151368.88),
    ("0", 0.0),
])
def test_to_number_parses_real_shapes(raw, want):
    assert to_number(raw) == pytest.approx(want)


@pytest.mark.parametrize("raw", ["-", "", "  ", "N/A", None])
def test_missing_value_is_none_not_zero(raw):
    """กฎเหล็กข้อ 1 — ไม่มีข้อมูลต้องเป็น None

    ถ้าคืน 0 จะแยกไม่ออกจาก "วัดได้ว่าเป็นศูนย์" แล้วค่าเฉลี่ยกับ ROAS
    ที่คำนวณต่อจะเพี้ยนโดยไม่มีอะไรเตือน
    """
    assert to_number(raw) is None


# ── โครงไฟล์ ─────────────────────────────────────────────────
def test_header_row_found_by_width_not_fixed_number():
    """หัวตารางต้องหาเจอแม้หัวไฟล์ยาวขึ้น — ห้ามฝังเลขแถวไว้ในโค้ด"""
    rows = [["หัวไฟล์"], ["a", "b"], [], ["c1", "c2", "c3", "c4", "c5", "c6"]]
    assert find_header_row(rows) == 3


def test_parses_all_ads_variant(tmp_path):
    rows = parse_shopee_ads(_write(tmp_path, "all.csv", ALL_ADS), shop_id="shopee_02")
    assert len(rows) == 2
    r = rows[0]
    assert r["ad_name"] == "Shop GMV Max"
    assert r["impressions"] == 2127590
    assert r["ctr"] == pytest.approx(0.043)
    assert r["expense_thb"] == pytest.approx(151368.88)
    assert r["roas"] == pytest.approx(52.43)
    assert r["acos"] == pytest.approx(0.0191)
    assert str(r["period_from"]) == "2026-07-01"
    assert str(r["period_to"]) == "2026-07-31"
    assert r["date_collection_method"].endswith("all_ads")
    # ไฟล์แบบนี้ไม่มีคีย์เวิร์ด ต้องเป็น None และบอกไว้ใน dq_flags
    assert r["keyword"] is None
    assert any("keyword" in f for f in r["dq_flags"])


def test_parses_keyword_variant(tmp_path):
    rows = parse_shopee_ads(_write(tmp_path, "kw.csv", KEYWORD), shop_id="shopee_02")
    assert len(rows) == 1
    r = rows[0]
    assert r["keyword"] == "ประแจ"
    assert r["date_collection_method"].endswith("keyword")
    assert r["clicks"] == 500
    assert r["roas"] == pytest.approx(100.0)


def test_empty_keyword_report_is_zero_rows_not_error(tmp_path):
    """ร้านที่ไม่ได้ยิงโฆษณาคำค้นหาจะได้ไฟล์ที่มีแต่หัวตาราง

    ต้องคืน 0 แถวเงียบ ๆ ไม่ใช่โยน error — "ไม่มีโฆษณาแบบนั้น"
    คนละเรื่องกับ "ดึงพัง" (เจอจริงกับ shopee_02 ช่วง 01-21/08/2026)
    """
    rows = parse_shopee_ads(_write(tmp_path, "empty.csv", KEYWORD_EMPTY),
                            shop_id="shopee_02")
    assert rows == []


def test_gmv_max_row_is_kept(tmp_path):
    """แถว Shop GMV Max ไม่มีประเภทโฆษณา แต่ห้ามทิ้ง — ยอดใหญ่สุดในไฟล์"""
    rows = parse_shopee_ads(_write(tmp_path, "all.csv", ALL_ADS), shop_id="shopee_02")
    gmv_max = [r for r in rows if r["ad_name"] == "Shop GMV Max"]
    assert len(gmv_max) == 1
    assert gmv_max[0]["ads_type"] is None
    assert gmv_max[0]["expense_thb"] > 0


# ── TikTok ───────────────────────────────────────────────────
TIKTOK_ROWS = [
    ["ตามวัน", "ต้นทุน", "คำสั่งซื้อ SKU (ร้านค้าปัจจุบัน)",
     "ค่าใช้จ่ายต่อคำสั่งซื้อ (ร้านค้าปัจจุบัน)",
     "รายได้ขั้นต้น (ร้านค้าปัจจุบัน)", "ROI (ร้านค้าปัจจุบัน)", "สกุลเงิน"],
    ["2026-08-15 00:00:00", "667.81", 26, "25.68", "6805.94", "10.19", "THB"],
    ["2026-08-16 00:00:00", "400.00", 32, "12.50", "25938.11", "64.85", "THB"],
    # แถวรวมทั้งช่วง — ใช้ "-" ในช่องวันที่ ต้องถูกทิ้ง
    ["-", "1067.81", 58, "18.41", "32744.05", "30.66", "THB"],
]


def _tiktok_xlsx(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    for r in TIKTOK_ROWS:
        ws.append(r)
    p = tmp_path / "Campaign overview data 20260815 - 20260816.xlsx"
    wb.save(p)
    return p


def test_tiktok_drops_the_grand_total_row(tmp_path):
    """แถวรวมท้ายไฟล์ต้องถูกทิ้ง ไม่งั้นยอดเบิ้ล

    เจอจริง 2026-08-22: ไฟล์ 8 วันมี 9 แถว แถวที่ 9 คือยอดรวม
    บวกทั้งไฟล์ได้ 10,058.70 ซึ่งเป็น 2 เท่าของจริง (5,029.35)
    นี่คือบั๊กที่ไม่มีอะไรเตือน ตัวเลขดูสมเหตุสมผลทุกอย่าง
    """
    rows = parse_tiktok_ads(_tiktok_xlsx(tmp_path), shop_id="tiktok_01")
    assert len(rows) == 2, "แถวรวมต้องไม่หลุดเข้ามา"
    total = sum(r["expense_thb"] for r in rows)
    assert total == pytest.approx(1067.81), "ยอดต้องเท่ากับแถวรวมที่ไฟล์บอก ไม่ใช่ 2 เท่า"


def test_tiktok_parses_datetime_string_dates(tmp_path):
    """วันที่มาเป็นสตริง "2026-08-15 00:00:00" ไม่ใช่ชนิดวันที่ของ Excel"""
    rows = parse_tiktok_ads(_tiktok_xlsx(tmp_path), shop_id="tiktok_01")
    assert str(rows[0]["period_from"]) == "2026-08-15"
    # 1 แถว = 1 วัน ช่วงต้องเป็นวันเดียว ไม่ใช่ช่วงที่ขอทั้งก้อน
    assert rows[0]["period_from"] == rows[0]["period_to"]


def test_tiktok_missing_columns_are_none_with_reason(tmp_path):
    """impression/คลิก/คีย์เวิร์ด ไม่มีในรายงานนี้ ต้องเป็น None พร้อมเหตุผล"""
    r = parse_tiktok_ads(_tiktok_xlsx(tmp_path), shop_id="tiktok_01")[0]
    for f in ("impressions", "clicks", "keyword", "ad_name"):
        assert r[f] is None
    assert any("impressions" in f for f in r["dq_flags"])
