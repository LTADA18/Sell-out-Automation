from __future__ import annotations

from datetime import datetime

import pytest

from src.core.config import (
    AppConfig,
    FetchConfig,
    PathsConfig,
    PrivacyConfig,
    RateLimitConfig,
    RetryConfig,
    Settings,
    ShopConfig,
)
from src.core.models import Order, OrderStatus


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        fetch=FetchConfig(lookback_days=1),
        privacy=PrivacyConfig(include_pii=False),
        # backoff 0 วิ ในเทส ไม่งั้นเทส retry ตัวเดียวกิน 40 วินาที
        retry=RetryConfig(backoff_seconds=[0, 0, 0]),
        rate_limit=RateLimitConfig(delay_between_shops=(3.0, 3.0)),
        paths=PathsConfig(
            output_dir=str(tmp_path / "output"),
            archive_dir=str(tmp_path / "output" / "_archive"),
            db_path=str(tmp_path / "status.db"),
            raw_dir=str(tmp_path / "raw"),
            lock_file=str(tmp_path / "run.lock"),
            logs_dir=str(tmp_path / "logs"),
        ),
    )


@pytest.fixture
def shop() -> ShopConfig:
    return ShopConfig(
        shop_id="lazada_01", platform="lazada", adapter="mock",
        display_name="ร้านทดสอบ", enabled=True,
    )


@pytest.fixture
def app_config(settings, shop) -> AppConfig:
    return AppConfig(settings=settings, shops=[shop])


def make_order(order_id: str, **kw) -> Order:
    """ออเดอร์ตัวอย่างสำหรับเทส — ค่า default พอให้ผ่าน validate"""
    base = dict(
        order_id=order_id,
        platform="lazada",
        shop_id="lazada_01",
        shop_name="ร้านทดสอบ",
        order_created_at=datetime(2026, 8, 2, 10, 30),
        order_status=OrderStatus.DELIVERED,
        sku="SKU-001",
        quantity=1,
        item_price=100.0,
        total_amount=100.0,
    )
    base.update(kw)
    return Order(**base)
