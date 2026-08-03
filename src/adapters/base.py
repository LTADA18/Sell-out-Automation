"""สัญญากลางที่ทุกแพลตฟอร์มต้องทำตาม — core เรียกผ่านคลาสนี้เท่านั้น

เพิ่มแพลตฟอร์มที่ 4 = สร้างไฟล์ใหม่สืบทอด BaseAdapter แล้วลงทะเบียนใน registry.py
ไม่ต้องแก้ runner / exporter / dashboard เลยสักบรรทัด
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from src.core.config import PROJECT_ROOT, Settings, ShopConfig
from src.core.models import Order


class HealthStatus(BaseModel):
    """ผลของ health_check — ห้ามดึงข้อมูลจริง แค่เช็คว่า credential ยังใช้ได้"""

    shop_id: str
    ok: bool
    message: str
    expires_at: datetime | None = None      # cookie/token หมดอายุเมื่อไหร่ (ถ้ารู้)

    @property
    def days_left(self) -> int | None:
        if self.expires_at is None:
            return None
        return (self.expires_at - datetime.now()).days


class BaseAdapter(ABC):
    #: ชื่อที่ใช้ลงทะเบียนใน registry และเขียนลง log
    name: str = "base"

    def __init__(self, shop: ShopConfig, settings: Settings) -> None:
        self.shop = shop
        self.settings = settings
        self.api_calls = 0
        self.http_status_last: int | None = None

    # ── สัญญาที่คลาสลูกต้องเขียนเอง ─────────────────────────

    @abstractmethod
    def authenticate(self) -> None:
        """เตรียม session/token ให้พร้อมใช้ — โยน AdapterError(AUTH_*) ถ้าไม่ผ่าน"""

    @abstractmethod
    def fetch_orders(self, date_from: date, date_to: date) -> list[Order]:
        """ดึงออเดอร์ในช่วงวันที่ แล้วคืน Order ที่ normalize แล้ว"""

    @abstractmethod
    def normalize(self, raw: Any) -> list[Order]:
        """แปลงข้อมูลดิบเป็น schema กลาง — ไม่มีค่า = None ห้ามเดา"""

    @abstractmethod
    def health_check(self) -> HealthStatus:
        """เช็คว่า credential ยังใช้ได้ไหม โดยไม่ดึงข้อมูลจริง"""

    # ── ของกลางที่ทุก adapter ใช้ร่วมกัน ────────────────────

    def raw_path(self, run_date: str) -> Path:
        return (
            PROJECT_ROOT
            / self.settings.paths.raw_dir
            / self.shop.platform
            / self.shop.shop_id
            / f"{run_date}.json"
        )

    def save_raw(self, raw: Any, run_date: str) -> Path:
        """เก็บ response ดิบไว้ debug — ถ้า normalize ผิด จะย้อนดูได้โดยไม่ต้องยิงใหม่"""
        path = self.raw_path(run_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return path

    def close(self) -> None:
        """ปิด browser/session — คลาสลูกเขียนทับถ้ามีของต้องเก็บกวาด"""

    def __enter__(self) -> BaseAdapter:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
