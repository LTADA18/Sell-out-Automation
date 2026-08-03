"""MockAdapter — ข้อมูลปลอมสำหรับ Phase 1-2 (ไม่แตะเน็ต ไม่แตะเบราว์เซอร์)

จงใจให้บางร้าน "พัง" คนละแบบ เพื่อให้ Dashboard มีของจริงให้ดู
ไม่ใช่เขียวหมด 15 ช่องจนมองไม่ออกว่า error แต่ละแบบหน้าตายังไง
"""

from __future__ import annotations

import hashlib
import random
from datetime import date, datetime, time, timedelta
from typing import Any

from src.adapters.base import BaseAdapter, HealthStatus
from src.core.models import AdapterError, ErrorType, Order, OrderStatus

# ── สคริปต์ความพังของแต่ละร้าน ───────────────────────────────
# shop_id -> (ErrorType, ล้มกี่ครั้งแรกก่อนจะสำเร็จ)  None = ล้มตลอด
FAILURE_SCRIPT: dict[str, tuple[ErrorType, int | None]] = {
    # ── ร้านที่มีจริงใน shops.yaml — ให้ Dashboard มีครบทุกสี ไม่ใช่เขียวหมด ──
    "tiktok_02": (ErrorType.AUTH_EXPIRED, None),   # ห้าม retry — ต้อง fail ทันที
    "tiktok_03": (ErrorType.RATE_LIMITED, 2),      # ล้ม 2 ครั้งแล้วผ่าน — ทดสอบ backoff
    "tiktok_04": (ErrorType.EMPTY_RESULT, None),   # ดึงได้แต่ไม่มีออเดอร์ → PARTIAL
    "tiktok_05": (ErrorType.TIMEOUT, None),        # retry ได้ แต่ครบ 3 ครั้งก็ยังไม่ผ่าน

    # ── id สมมติที่เทสใช้ (ไม่มีใน shops.yaml จึงไม่ถูกรันจริง) ──
    "shopee_03": (ErrorType.AUTH_EXPIRED, None),
    "lazada_02": (ErrorType.RATE_LIMITED, 2),
    "lazada_05": (ErrorType.NO_PERMISSION, None),  # เคสจริงที่เจอกับบัญชี Lazada
}

PRODUCTS = [
    ("สว่านไร้สาย 18V", "DRL-18V-001"),
    ("ชุดดอกสว่าน 40 ชิ้น", "BIT-SET-040"),
    ("เครื่องเจียร 4 นิ้ว", "GRD-100-004"),
    ("ไขควงไฟฟ้า 12V", "SCR-12V-002"),
    ("เลื่อยวงเดือน 7 นิ้ว", "SAW-185-007"),
    ("ตลับเมตร 5 เมตร", "TAP-5M-011"),
]

VARIATIONS = ["สีน้ำเงิน", "สีแดง", "ชุดมาตรฐาน", "ชุดพร้อมกระเป๋า"]
PROVINCES = ["กรุงเทพมหานคร", "นนทบุรี", "ชลบุรี", "เชียงใหม่", "ขอนแก่น", "สงขลา"]
CARRIERS = ["Flash Express", "Kerry Express", "J&T Express", "ไปรษณีย์ไทย"]
PAYMENTS = ["COD", "บัตรเครดิต", "โอนผ่านธนาคาร", "e-Wallet"]

# ค่าดิบของแต่ละแพลตฟอร์ม -> สถานะกลาง (ของจริงจะมาจาก column_maps ใน Phase 3)
STATUS_POOL: list[tuple[str, OrderStatus]] = [
    ("unpaid", OrderStatus.PENDING),
    ("ready_to_ship", OrderStatus.READY_TO_SHIP),
    ("shipped", OrderStatus.SHIPPED),
    ("delivered", OrderStatus.DELIVERED),
    ("delivered", OrderStatus.DELIVERED),      # ใส่ซ้ำให้ delivered มีน้ำหนักมากกว่า
    ("canceled", OrderStatus.CANCELLED),
    ("returned", OrderStatus.RETURNED),
]


class MockAdapter(BaseAdapter):
    name = "mock"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._attempts = 0

    # ── สัญญาของ BaseAdapter ────────────────────────────────

    def authenticate(self) -> None:
        error_type, fail_times = FAILURE_SCRIPT.get(self.shop.shop_id, (None, None))
        # error กลุ่ม auth ต้องเด้งตั้งแต่ตอน authenticate ไม่ใช่ตอนดึงข้อมูล
        if error_type in (ErrorType.AUTH_EXPIRED, ErrorType.NO_PERMISSION):
            raise AdapterError(error_type, self._auth_message(error_type))

    def fetch_orders(self, date_from: date, date_to: date) -> list[Order]:
        self._attempts += 1
        self.api_calls += 1
        self._maybe_fail()

        raw = self._make_raw(date_from, date_to)
        self.save_raw(raw, date_to.isoformat())
        self.http_status_last = 200
        return self.normalize(raw)

    def normalize(self, raw: Any) -> list[Order]:
        orders: list[Order] = []
        for item in raw["items"]:
            orders.append(
                Order(
                    order_id=item["order_sn"],
                    platform=self.shop.platform,
                    shop_id=self.shop.shop_id,
                    shop_name=self.shop.display_name,
                    order_created_at=datetime.fromisoformat(item["create_time"]),
                    order_updated_at=datetime.fromisoformat(item["update_time"]),
                    paid_at=(
                        datetime.fromisoformat(item["pay_time"]) if item["pay_time"] else None
                    ),
                    status_raw=item["status_raw"],
                    order_status=OrderStatus(item["status_mapped"]),
                    payment_method=item["payment_method"],
                    sku=item["sku"],
                    product_name=item["product_name"],
                    variation=item["variation"],
                    quantity=item["quantity"],
                    item_price=item["item_price"],
                    item_discount=item["item_discount"],
                    seller_discount=item["seller_discount"],
                    platform_discount=item["platform_discount"],
                    shipping_fee=item["shipping_fee"],
                    shipping_carrier=item["carrier"],
                    tracking_no=item["tracking_no"],
                    # ค่าธรรมเนียม/settlement อยู่คนละรายงาน (Income report) — Phase 5
                    commission_fee=None,
                    transaction_fee=None,
                    service_fee=None,
                    total_amount=item["total_amount"],
                    settlement_amount=None,
                    buyer_username=item["buyer_username"],
                    province=item["province"],
                    cancel_reason=item["cancel_reason"],
                    return_status=item["return_status"],
                    notes="mock data — ค่าธรรมเนียม/settlement ยังไม่ดึง (อยู่ใน Income report)",
                )
            )
        return orders

    def health_check(self) -> HealthStatus:
        error_type, _ = FAILURE_SCRIPT.get(self.shop.shop_id, (None, None))
        if error_type in (ErrorType.AUTH_EXPIRED, ErrorType.NO_PERMISSION):
            return HealthStatus(
                shop_id=self.shop.shop_id,
                ok=False,
                message=self._auth_message(error_type),
            )
        # จำลองวันหมดอายุให้ต่างกัน จะได้เห็นแถบสีส้ม "เหลือ < 3 วัน" บน Dashboard
        days = 1 + (self._seed_int("expiry") % 30)
        return HealthStatus(
            shop_id=self.shop.shop_id,
            ok=True,
            message=f"mock session ใช้ได้ (เหลือ {days} วัน)",
            expires_at=datetime.now() + timedelta(days=days),
        )

    # ── ภายใน ───────────────────────────────────────────────

    @staticmethod
    def _auth_message(error_type: ErrorType) -> str:
        if error_type is ErrorType.NO_PERMISSION:
            return "บัญชีที่ล็อกอินไม่มีสิทธิ์ 'จัดการคำสั่งซื้อ' — ให้เจ้าของร้านเพิ่มสิทธิ์"
        return "cookie หมดอายุ — รัน `python -m src.cli login --shop <shop_id>` ใหม่"

    def _maybe_fail(self) -> None:
        error_type, fail_times = FAILURE_SCRIPT.get(self.shop.shop_id, (None, None))
        if error_type is None or error_type in (ErrorType.AUTH_EXPIRED, ErrorType.NO_PERMISSION):
            return
        if fail_times is not None and self._attempts > fail_times:
            return          # ผ่านช่วงที่สคริปต์ให้ล้มแล้ว ปล่อยผ่าน

        messages = {
            ErrorType.RATE_LIMITED: "โดนจำกัดอัตราการเรียก (ครั้งที่ {n}) — รอแล้วลองใหม่",
            ErrorType.TIMEOUT: "รอไฟล์ Export ถูก generate นานเกินกำหนด (ครั้งที่ {n})",
            ErrorType.EMPTY_RESULT: "ดึงสำเร็จแต่ไม่มีออเดอร์ในช่วงวันที่นี้",
            ErrorType.NETWORK: "เชื่อมต่อไม่ได้ (ครั้งที่ {n})",
        }
        self.http_status_last = 429 if error_type is ErrorType.RATE_LIMITED else 200
        raise AdapterError(
            error_type,
            messages.get(error_type, "mock error").format(n=self._attempts),
        )

    def _seed_int(self, salt: str = "") -> int:
        """seed จาก shop_id — ข้อมูลปลอมของร้านเดิมจะเหมือนเดิมทุกครั้งที่รัน
        (ถ้าสุ่มใหม่ทุกรอบ จะแยกไม่ออกว่า Excel เปลี่ยนเพราะโค้ดหรือเพราะสุ่ม)"""
        key = f"{self.shop.shop_id}|{salt}".encode()
        return int(hashlib.sha256(key).hexdigest()[:8], 16)

    def _make_raw(self, date_from: date, date_to: date) -> dict:
        items: list[dict] = []
        day = date_from
        while day <= date_to:
            rng = random.Random(self._seed_int(day.isoformat()))
            for _ in range(rng.randint(5, 25)):
                items.extend(self._make_order_lines(rng, day))
            day += timedelta(days=1)

        return {
            "shop_id": self.shop.shop_id,
            "platform": self.shop.platform,
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
            "fetched_at": datetime.now().isoformat(),
            "items": items,
        }

    def _make_order_lines(self, rng: random.Random, day: date) -> list[dict]:
        """1 ออเดอร์ → 1-3 แถว (order line) โดยค่าระดับออเดอร์ต้องเท่ากันทุกแถว"""
        order_sn = f"{day.strftime('%y%m%d')}{rng.randint(10**11, 10**12 - 1)}"
        status_raw, status = rng.choice(STATUS_POOL)
        created = datetime.combine(day, time(rng.randint(0, 23), rng.randint(0, 59)))
        updated = created + timedelta(hours=rng.randint(1, 48))
        paid = None if status is OrderStatus.PENDING else created + timedelta(minutes=rng.randint(1, 90))

        shipping_fee = round(rng.choice([0, 25, 35, 50]), 2)
        carrier = rng.choice(CARRIERS)
        tracking = (
            None if status in (OrderStatus.PENDING, OrderStatus.READY_TO_SHIP)
            else f"TH{rng.randint(10**14, 10**15 - 1)}"
        )

        lines: list[dict] = []
        subtotal = 0.0
        for _ in range(rng.randint(1, 3)):
            name, sku = rng.choice(PRODUCTS)
            qty = rng.randint(1, 4)
            price = round(rng.uniform(150, 4500), 2)
            seller_disc = round(price * qty * rng.choice([0, 0, 0.05, 0.10]), 2)
            plat_disc = round(price * qty * rng.choice([0, 0, 0.03]), 2)
            subtotal += price * qty - seller_disc - plat_disc

            lines.append({
                "order_sn": order_sn,
                "create_time": created.isoformat(),
                "update_time": updated.isoformat(),
                "pay_time": paid.isoformat() if paid else None,
                "status_raw": status_raw,
                "status_mapped": status.value,
                "payment_method": rng.choice(PAYMENTS),
                "sku": sku,
                "product_name": name,
                "variation": rng.choice(VARIATIONS),
                "quantity": qty,
                "item_price": price,
                "item_discount": round(seller_disc + plat_disc, 2),
                "seller_discount": seller_disc,
                "platform_discount": plat_disc,
                "shipping_fee": shipping_fee,
                "carrier": carrier,
                "tracking_no": tracking,
                "buyer_username": f"buyer{rng.randint(1000, 9999)}",
                "province": rng.choice(PROVINCES),
                "cancel_reason": "ลูกค้าเปลี่ยนใจ" if status is OrderStatus.CANCELLED else None,
                "return_status": "คืนสำเร็จ" if status is OrderStatus.RETURNED else None,
            })

        total = round(subtotal + shipping_fee, 2)
        for line in lines:
            line["total_amount"] = total       # ค่าระดับออเดอร์ ต้องเท่ากันทุกแถว
        return lines
