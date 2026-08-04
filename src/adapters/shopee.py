"""Shopee Seller Centre — ⚠️ ตอนนี้รองรับแค่ "ล็อกอินเก็บ session" เท่านั้น

ทำไมมีไฟล์นี้ทั้งที่ยังดึงข้อมูลไม่ได้:
  การล็อกอินต้องทำด้วยมือทีละร้าน ซึ่งเป็นคอขวดที่ช้าที่สุดของงานนี้
  แยกให้ล็อกอินเก็บ session ไว้ก่อนได้ แล้วค่อยเขียนขั้นตอน Export ทีหลัง
  จะได้ไม่ต้องรอให้โค้ดเสร็จก่อนถึงจะเริ่มล็อกอิน

สิ่งที่ยังไม่มี — ต้องมี "ไฟล์ Export จริง" จากหลังบ้าน Shopee ก่อนถึงจะทำได้:
  1. config/column_maps/shopee.yaml  (ตอนนี้ fields ว่างเปล่า)
  2. _export()   — ขั้นตอนคลิกในหน้าคำสั่งซื้อ
  3. normalize() — จับคู่คอลัมน์ดิบเข้า schema กลาง

ห้ามเดาชื่อคอลัมน์แล้วเขียน normalize ล่วงหน้า — เดาผิดจะได้ Excel ที่หน้าตาถูก
แต่ตัวเลขผิด ซึ่งอันตรายกว่าไม่มีไฟล์เลย (กฎเหล็กข้อ 1)
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from src.adapters.playwright_base import PlaywrightAdapter
from src.core.logging_setup import get_logger
from src.core.models import AdapterError, ErrorType, Order

log = get_logger()

NOT_READY = (
    "Shopee ยังดึงข้อมูลไม่ได้ — มีแค่ส่วนล็อกอินเก็บ session เท่านั้น\n"
    "ต้องมีไฟล์ Export จริงจากหลังบ้าน Shopee มาทำ config/column_maps/shopee.yaml ก่อน\n"
    "ระหว่างนี้ให้ตั้ง enabled: false ใน shops.yaml (จะขึ้น ⚪ SKIPPED ไม่ใช่ 🔴 FAILED)"
)


class ShopeeAdapter(PlaywrightAdapter):
    name = "playwright"
    base_url_env = "SHOPEE_SELLER_URL"
    login_path = "/account/signin"

    def _export(self, page, date_from: date, date_to: date) -> Path:
        raise AdapterError(ErrorType.UNKNOWN, NOT_READY)

    def normalize(self, raw: Any) -> list[Order]:
        # กันไว้อีกชั้น เผื่อมีคนเผลอเปิดใช้ทั้งที่ column map ยังว่าง
        if not self.map.fields:
            raise AdapterError(ErrorType.UNKNOWN, NOT_READY)
        raise AdapterError(ErrorType.UNKNOWN, NOT_READY)
