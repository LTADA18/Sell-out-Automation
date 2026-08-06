"""อีเมลต้องบอก 'วันของข้อมูล' ไม่ใช่ 'วันที่ส่ง'

เจ้าของงานสั่งไว้ 2026-08-05: ส่งวันที่ 6/8 แต่ข้อมูลเป็นของวันที่ 5/8
ต้องเขียนให้ชัดว่าเป็นยอดของวันที่ 5/8 ไม่งั้นคนอ่านเข้าใจผิด
"""
from __future__ import annotations

from datetime import date

from src.core.mailer import build_html, build_subject, data_period
from src.core.runner import date_range

ROWS = [
    {"status": "SUCCESS", "orders_fetched": 100, "rows_written": 100,
     "shop_id": "a", "shop_name": "ร้าน ก", "platform": "shopee", "error_message": None},
    {"status": "SUCCESS", "orders_fetched": 3592, "rows_written": 3600,
     "shop_id": "b", "shop_name": "ร้าน ข", "platform": "tiktok", "error_message": None},
]


def test_data_period_single_day() -> None:
    assert data_period("2026-08-05", "2026-08-05") == "5 ส.ค. 2026"


def test_data_period_same_month_range() -> None:
    assert data_period("2026-08-03", "2026-08-05") == "3–5 ส.ค. 2026"


def test_data_period_across_months() -> None:
    assert data_period("2026-07-30", "2026-08-02") == "30 ก.ค. – 2 ส.ค. 2026"


def test_data_period_missing_is_blank() -> None:
    """ไม่มีช่วงวันก็ต้องไม่ระเบิด — ถอยไปใช้รูปแบบเดิมแทน"""
    assert data_period(None, None) == ""
    assert data_period("ไม่ใช่วันที่", "ก็ไม่ใช่") == ""


def test_subject_shows_data_date_not_send_date() -> None:
    """หัวข้อต้องขึ้นวันของข้อมูล (5 ส.ค.) ไม่ใช่วันที่รัน (6 ส.ค.)"""
    subject = build_subject("2026-08-06", ROWS, "2026-08-05", "2026-08-05")
    assert "ยอดขายวันที่ 5 ส.ค. 2026" in subject
    assert "2026-08-06" not in subject
    assert "3,692 ออเดอร์" in subject


def test_html_separates_data_date_from_run_date() -> None:
    """เนื้ออีเมลต้องแยกให้เห็นทั้งสองวัน จะได้ไม่สับสน"""
    html = build_html("2026-08-06", ROWS, "2026-08-05", "2026-08-05")
    assert "ข้อมูลของวันที่" in html
    assert "5 ส.ค. 2026" in html
    assert "ดึงเมื่อ 2026-08-06" in html


def test_period_follows_lookback_setting(app_config) -> None:
    """ช่วงวันต้องมาจาก date_range เดียวกับที่ runner ใช้ดึงจริง

    ⚠️ กันไม่ให้ใครมาเขียนสูตร 'run_date - 1 วัน' ทับ
       ถ้า lookback_days เปลี่ยนเป็น 3 อีเมลต้องบอกช่วง 3 วัน ไม่ใช่วันเดียว
    """
    app_config.settings.fetch.lookback_days = 3
    d_from, d_to = date_range(app_config, date(2026, 8, 6))
    assert d_to == date(2026, 8, 5)
    assert d_from == date(2026, 8, 3)

    subject = build_subject("2026-08-06", ROWS, d_from.isoformat(), d_to.isoformat())
    assert "3–5 ส.ค. 2026" in subject
