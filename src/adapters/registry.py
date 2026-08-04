"""ทะเบียน adapter — ที่เดียวที่ core รู้ว่ามี adapter อะไรบ้าง

เพิ่มแพลตฟอร์มใหม่: import คลาสแล้วเติมใน _REGISTRY เท่านั้น
"""

from __future__ import annotations

from src.adapters.base import BaseAdapter
from src.adapters.lazada import LazadaAdapter
from src.adapters.mock import MockAdapter
from src.adapters.shopee import ShopeeAdapter
from src.adapters.tiktok import TiktokAdapter
from src.core.config import Settings, ShopConfig

# (adapter, platform) -> คลาส   ; platform "*" = ใช้ได้กับทุกแพลตฟอร์ม
_REGISTRY: dict[tuple[str, str], type[BaseAdapter]] = {
    ("mock", "*"): MockAdapter,
    ("playwright", "lazada"): LazadaAdapter,
    ("playwright", "tiktok"): TiktokAdapter,
    # ⚠️ Shopee ลงทะเบียนไว้เพื่อ "ล็อกอินเก็บ session" เท่านั้น ยังดึงข้อมูลไม่ได้
    #    _export/normalize โยน error ทันที จนกว่าจะมีไฟล์ Export จริงมาทำ column map
    ("playwright", "shopee"): ShopeeAdapter,
}


def build_adapter(shop: ShopConfig, settings: Settings) -> BaseAdapter:
    cls = _REGISTRY.get((shop.adapter, shop.platform)) or _REGISTRY.get((shop.adapter, "*"))
    if cls is None:
        available = sorted({a for a, _ in _REGISTRY})
        raise NotImplementedError(
            f"ยังไม่มี adapter '{shop.adapter}' สำหรับแพลตฟอร์ม '{shop.platform}' "
            f"(ร้าน {shop.shop_id}) — ที่ใช้ได้ตอนนี้: {available}"
        )
    return cls(shop, settings)
