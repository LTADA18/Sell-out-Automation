"""PDPA — ตัดข้อมูลส่วนบุคคลทิ้งก่อนเขียน Excel

ไฟล์ Export จากหลังบ้านมักแถมชื่อ-นามสกุล เบอร์โทร ที่อยู่เต็มมาให้หมด
ของพวกนี้ต้องไม่ไหลลง Excel ที่เอาไปส่งต่อ/เปิดบนเครื่องคนอื่น
ตัวดิบยังอยู่ใน data/raw/ (อยู่ใน .gitignore) เผื่อต้องย้อนตรวจ
"""

from __future__ import annotations

from src.core.models import Order

# field ที่ห้ามไหลลง Excel เมื่อ include_pii=false
# (ยังไม่มีใน schema กลางตอนนี้ ใส่ไว้กัน adapter อนาคตเผลอเพิ่มเข้ามา)
PII_FIELDS = ("buyer_name", "buyer_phone", "buyer_address", "postcode")


def mask_username(name: str | None) -> str | None:
    """เก็บตัวแรกกับตัวท้าย พอให้แยกลูกค้าซ้ำได้ แต่ระบุตัวตนไม่ได้"""
    if not name:
        return name
    if len(name) <= 2:
        return f"{name[0]}*"
    return f"{name[0]}{'*' * (len(name) - 2)}{name[-1]}"


def apply_privacy(orders: list[Order], include_pii: bool) -> list[Order]:
    """คืน list ใหม่ที่ mask แล้ว — ไม่แก้ของเดิม เผื่อ caller ยังต้องใช้ค่าจริง"""
    if include_pii:
        return orders

    cleaned: list[Order] = []
    for o in orders:
        c = o.model_copy(deep=True)
        c.buyer_username = mask_username(c.buyer_username)
        for field in PII_FIELDS:
            if hasattr(c, field):
                setattr(c, field, None)
        cleaned.append(c)
    return cleaned
