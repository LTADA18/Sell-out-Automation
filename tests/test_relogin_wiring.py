"""กันบั๊ก "เขียน auto_relogin ไว้แต่ลืมต่อสาย"

เจอจริง 2026-08-08: tiktok.py เรียก _assert_logged_in ตรง ๆ ซึ่งโยน AUTH_EXPIRED ทันที
auto_relogin ที่เขียนไว้จึงไม่เคยถูกเรียก ร้าน TikTok พังทุกครั้งที่ cookie หมดอายุ
Lazada กับ Shopee เรียก _ensure_logged_in ถูกมาตลอด มีแต่ TikTok ที่พลาด

อาการหลอกมาก: มีเมธอด auto_relogin อยู่ในไฟล์ อ่านโค้ดผ่าน ๆ แล้วนึกว่าใช้งานได้
"""
from __future__ import annotations

import inspect
import re

import pytest

from src.adapters.lazada import LazadaAdapter
from src.adapters.playwright_base import PlaywrightAdapter
from src.adapters.shopee import ShopeeAdapter
from src.adapters.tiktok import TiktokAdapter

ADAPTERS = [LazadaAdapter, ShopeeAdapter, TiktokAdapter]


@pytest.mark.parametrize("cls", ADAPTERS, ids=lambda c: c.__name__)
def test_adapter_has_auto_relogin(cls: type) -> None:
    """ทุก adapter ต้องต่ออายุ session เองได้ ไม่งั้นรอบเช้าพังแล้วต้องรอคนมาแก้"""
    assert "auto_relogin" in cls.__dict__, f"{cls.__name__} ไม่มี auto_relogin เป็นของตัวเอง"


@pytest.mark.parametrize("cls", ADAPTERS, ids=lambda c: c.__name__)
def test_export_goes_through_ensure_logged_in(cls: type) -> None:
    """เส้นทางดึงข้อมูลต้องผ่าน _ensure_logged_in ซึ่งเป็นตัวเดียวที่เรียก auto_relogin

    ถ้าเรียก _assert_logged_in ตรง ๆ = ยอมแพ้ทันทีที่ session หมด
    """
    src = inspect.getsource(cls)
    assert "_ensure_logged_in" in src, (
        f"{cls.__name__} ไม่ได้เรียก _ensure_logged_in เลย — "
        f"session หมดอายุแล้วจะพังทันทีโดยไม่ลองต่ออายุ"
    )


@pytest.mark.parametrize("cls", ADAPTERS, ids=lambda c: c.__name__)
def test_no_bare_assert_logged_in_in_export_path(cls: type) -> None:
    """ห้ามเรียก _assert_logged_in ตรง ๆ ใน _export

    _assert_logged_in มีไว้ให้ _ensure_logged_in เรียกภายในเท่านั้น
    """
    try:
        src = inspect.getsource(cls._export)
    except (AttributeError, TypeError):
        pytest.skip(f"{cls.__name__} ไม่มี _export")

    # ตัดคอมเมนต์ออกก่อน จะได้ไม่ไปจับข้อความในคำอธิบาย
    code = "\n".join(re.sub(r"#.*$", "", ln) for ln in src.splitlines())
    assert "_assert_logged_in" not in code, (
        f"{cls.__name__}._export เรียก _assert_logged_in ตรง ๆ — "
        f"ต้องใช้ _ensure_logged_in เพื่อให้ auto_relogin ได้ทำงาน"
    )


@pytest.mark.parametrize("cls", ADAPTERS, ids=lambda c: c.__name__)
def test_adapter_exposes_orders_url(cls: type) -> None:
    """ทุก adapter ต้องบอกได้ว่าหน้าคำสั่งซื้ออยู่ที่ไหน

    keepalive กับตัวเช็ค login ใช้ค่านี้ ถ้าขาดจะพังตอนรันจริงเท่านั้น
    (เจอจริง 2026-08-08: keepalive ล้มทั้ง 5 ร้านเพราะ TiktokAdapter ไม่มี orders_url)
    """
    assert isinstance(getattr(cls, "orders_url", None), property), (
        f"{cls.__name__} ไม่มี property orders_url"
    )


def test_ensure_logged_in_actually_calls_auto_relogin() -> None:
    """ตัวจริงที่เป็นหัวใจ — ถ้าวันหนึ่งมีคนแก้ _ensure_logged_in จนไม่เรียก relogin แล้ว
    เทสต์ข้างบนทั้งหมดจะผ่านแต่ระบบพังเงียบ ๆ"""
    src = inspect.getsource(PlaywrightAdapter._ensure_logged_in)
    assert "auto_relogin" in src
