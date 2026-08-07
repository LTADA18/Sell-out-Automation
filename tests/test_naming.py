"""ชื่อร้านมาตรฐาน — ร้านเดียวกันคนละแพลตฟอร์มต้องได้ชื่อเดียวกัน

กติกาที่เจ้าของงานกำหนด 2026-08-07:
  Excel = ชื่อมาตรฐานล้วน · อีเมล = "ชื่อมาตรฐาน (ชื่อจริง)"
"""
from __future__ import annotations

import pytest

from src.core.config import load_config
from src.core.naming import canonical_name, email_label


@pytest.mark.parametrize(
    ("shop_id", "expected"),
    [
        ("tiktok_01", "Powerstools"),                     # ชื่อจริง powerstool
        ("shopee_04", "Powerstools"),
        ("shopee_03", "TNLTOOLSTORE"),                    # ชื่อจริง Toolspartner
        ("shopee_08", "TNLTOOLSTORE"),
        ("tiktok_05", "เฮียเก๋า เครื่องมือช่างราคาถูก"),   # ชื่อจริงไม่มีเว้นวรรคตรงกลาง
        ("shopee_05", "เฮียเก๋า เครื่องมือช่างราคาถูก"),
        ("tiktok_04", "100อัน1000อย่าง"),                  # ชื่อจริงมี 88 ต่อท้าย
        ("lazada_01", "กัปตัน เอกสตีล"),
        ("shopee_06", "กัปตัน เอกสตีล"),
    ],
)
def test_canonical_name(shop_id: str, expected: str) -> None:
    assert canonical_name(shop_id) == expected


def test_shops_on_two_platforms_share_one_name() -> None:
    """ถ้าชื่อไม่ตรงกัน pivot ตามชื่อร้านจะแยกยอดของร้านเดียวเป็น 2 ก้อน"""
    for a, b in (("tiktok_01", "shopee_04"),
                 ("tiktok_05", "shopee_05"),
                 ("lazada_01", "shopee_06"),
                 ("shopee_03", "shopee_08")):
        assert canonical_name(a) == canonical_name(b), f"{a} กับ {b} ต้องได้ชื่อเดียวกัน"


def test_email_label_shows_real_name_in_brackets() -> None:
    assert email_label("tiktok_01", "powerstool") == "Powerstools (powerstool)"
    assert email_label("shopee_03", "Toolspartner") == "TNLTOOLSTORE (Toolspartner)"
    assert email_label("tiktok_04", "100อัน1000อย่าง88") == "100อัน1000อย่าง (100อัน1000อย่าง88)"


def test_email_label_no_brackets_when_names_match() -> None:
    """ชื่อตรงกันแล้วไม่ต้องใส่วงเล็บซ้ำ — จะรกเปล่า ๆ"""
    assert email_label("tiktok_02", "toolsdee1") == "toolsdee1"
    assert email_label("shopee_02", "Smarttooltech") == "Smarttooltech"


def test_unknown_shop_falls_back_to_real_name() -> None:
    """ร้านที่ยังไม่ประกาศใน brands.yaml ต้องไม่หายไปและต้องไม่ถูกเดาชื่อให้"""
    assert canonical_name("shopee_99", "ร้านใหม่") == "ร้านใหม่"
    assert email_label("shopee_99", "ร้านใหม่") == "ร้านใหม่"


def test_every_enabled_shop_has_canonical_name() -> None:
    """ทุกร้านที่เปิดอยู่ต้องอยู่ใน brands.yaml — ถ้าเพิ่มร้านใหม่แล้วลืมประกาศ เทสต์นี้จะจับได้"""
    cfg = load_config()
    missing = [s.shop_id for s in cfg.shops
               if s.enabled and canonical_name(s.shop_id) == s.shop_id
               and canonical_name(s.shop_id) != s.display_name]
    assert not missing, f"ร้านที่ยังไม่ได้ประกาศใน brands.yaml: {missing}"


def test_report_name_and_email_name_on_shop_config() -> None:
    cfg = load_config()
    tiktok_01 = cfg.shop("tiktok_01")
    assert tiktok_01.display_name == "powerstool"         # ชื่อจริงห้ามเปลี่ยน
    assert tiktok_01.report_name == "Powerstools"         # Excel ใช้ตัวนี้
    assert tiktok_01.email_name == "Powerstools (powerstool)"


def test_web_name_still_uses_real_name() -> None:
    """ชื่อที่ใช้จับคู่ร้านบนเว็บต้องเป็นชื่อจริง ไม่ใช่ชื่อมาตรฐาน

    ถ้าเผลอใช้ชื่อมาตรฐานตรงนี้ Shopee จะหาแถวร้านไม่เจอแล้วดึงข้อมูลไม่ได้เลย
    """
    cfg = load_config()
    assert cfg.shop("shopee_03").web_name == "Toolspartner"
    assert cfg.shop("shopee_08").web_name == "TNLTOOLSTORE"
