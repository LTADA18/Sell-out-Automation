"""ชื่อร้านมาตรฐาน — ร้านเดียวกันบนคนละแพลตฟอร์มมักตั้งชื่อไม่ตรงกัน

ปัญหาที่แก้: `powerstool` (TikTok) กับ `Powerstools` (Shopee) เป็นร้านเดียวกัน
ถ้าปล่อยชื่อตามที่แต่ละแพลตฟอร์มตั้งไว้ เวลาทำ pivot หรือ group by ชื่อร้าน
ยอดของร้านเดียวจะถูกแยกเป็นคนละก้อนโดยไม่มีอะไรเตือน

กติกาที่เจ้าของงานกำหนด (2026-08-07):
  · ใน Excel — ใช้ชื่อมาตรฐานอย่างเดียว
  · ในอีเมล  — ใช้ "ชื่อมาตรฐาน (ชื่อจริงบนแพลตฟอร์ม)" เมื่อ 2 ชื่อไม่ตรงกัน
               จะได้ตรวจสอบย้อนได้ว่าดึงมาจากร้านไหนจริง ๆ

ชื่อมาตรฐานอ่านจาก `name` ของแต่ละแบรนด์ใน config/brands.yaml
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BRANDS_FILE = PROJECT_ROOT / "config" / "brands.yaml"


@lru_cache(maxsize=1)
def _canonical_map() -> dict[str, str]:
    """shop_id -> ชื่อมาตรฐาน

    ร้านที่ไม่ได้ประกาศใน brands.yaml จะไม่อยู่ใน map — ผู้เรียกต้อง fallback
    ไปใช้ display_name เอง (ดีกว่าเดาชื่อให้ ซึ่งอาจรวมยอดผิดร้าน)
    """
    if not BRANDS_FILE.exists():
        return {}
    data = yaml.safe_load(BRANDS_FILE.read_text(encoding="utf-8")) or {}
    out: dict[str, str] = {}
    for brand in data.get("brands", []):
        for shop_id in brand.get("shops", []):
            out[shop_id] = brand["name"]
    return out


def canonical_name(shop_id: str, fallback: str = "") -> str:
    """ชื่อที่ใช้ใน Excel — ชื่อเดียวต่อ 1 ร้านจริง ไม่ว่าจะขายกี่แพลตฟอร์ม"""
    return _canonical_map().get(shop_id) or fallback or shop_id


def email_label(shop_id: str, real_name: str) -> str:
    """ชื่อที่ใช้ในอีเมล — วงเล็บชื่อจริงไว้ถ้าไม่ตรงกับชื่อมาตรฐาน

    >>> email_label("tiktok_01", "powerstool")
    'Powerstools (powerstool)'
    >>> email_label("tiktok_02", "toolsdee1")
    'toolsdee1'
    """
    canon = canonical_name(shop_id, real_name)
    if real_name and canon != real_name:
        return f"{canon} ({real_name})"
    return canon


def reload() -> None:
    """ล้าง cache — ใช้ในเทสต์หรือหลังแก้ brands.yaml ระหว่างรัน"""
    _canonical_map.cache_clear()
