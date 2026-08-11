"""Schema กลางที่ทุกแพลตฟอร์มต้อง map มาลง — core ไม่รู้จักรูปแบบดิบของใครเลย"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ค่าที่ใช้แทน "ไม่มีข้อมูล" ตอนเขียน Excel
# ใช้ string ไม่ใช่ช่องว่าง เพื่อให้แยกออกว่า "ดึงมาแล้วไม่มี" กับ "ลืมดึง"
NULL = "Null"


class OrderStatus(str, Enum):
    """สถานะกลาง — ค่าดิบของแต่ละแพลตฟอร์มเก็บแยกไว้ที่ field `status_raw`"""

    PENDING = "PENDING"
    READY_TO_SHIP = "READY_TO_SHIP"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    RETURNED = "RETURNED"
    UNKNOWN = "UNKNOWN"


class RunStatus(str, Enum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class ErrorType(str, Enum):
    AUTH_EXPIRED = "AUTH_EXPIRED"      # cookie/token หมดอายุ — ห้าม retry
    AUTH_REQUIRED = "AUTH_REQUIRED"    # ยังไม่เคย login ร้านนี้ — ห้าม retry
    NO_PERMISSION = "NO_PERMISSION"    # login ได้ แต่บัญชีไม่มีสิทธิ์ดูคำสั่งซื้อ — ห้าม retry
    RATE_LIMITED = "RATE_LIMITED"
    TIMEOUT = "TIMEOUT"
    NETWORK = "NETWORK"
    PARSE_ERROR = "PARSE_ERROR"
    EMPTY_RESULT = "EMPTY_RESULT"
    UNKNOWN = "UNKNOWN"


# error ที่ยิงซ้ำแล้วมีโอกาสผ่าน — นอกจากนี้ให้ fail เร็ว
RETRYABLE: frozenset[ErrorType] = frozenset(
    {ErrorType.RATE_LIMITED, ErrorType.TIMEOUT, ErrorType.NETWORK}
)


class AdapterError(Exception):
    """error ที่ adapter โยนออกมา พร้อมบอก core ว่าควร retry ไหม"""

    def __init__(self, error_type: ErrorType, message: str) -> None:
        super().__init__(message)
        self.error_type = error_type
        self.message = message

    @property
    def retryable(self) -> bool:
        return self.error_type in RETRYABLE


class Order(BaseModel):
    """1 instance = 1 order line (ออเดอร์ที่มี 3 สินค้า = 3 instance)"""

    model_config = ConfigDict(str_strip_whitespace=True)

    # ── ตัวตน ────────────────────────────────────────────────
    order_id: str                       # text เสมอ — เลข 19 หลักของ TikTok ถ้าเป็น int จะเพี้ยน
    platform: str
    shop_id: str
    shop_name: str

    # ── เวลา (Asia/Bangkok ทุกตัว) ───────────────────────────
    order_created_at: datetime | None = None
    order_updated_at: datetime | None = None
    paid_at: datetime | None = None

    # ── สถานะ ────────────────────────────────────────────────
    status_raw: str | None = None       # ค่าดิบจากแพลตฟอร์ม เก็บไว้ debug map ผิด
    order_status: OrderStatus = OrderStatus.UNKNOWN
    payment_method: str | None = None

    # ── สินค้า ───────────────────────────────────────────────
    sku: str | None = None              # text เสมอ ด้วยเหตุผลเดียวกับ order_id
    product_name: str | None = None
    variation: str | None = None
    quantity: int | None = None

    # ── เงิน: ระดับสินค้า ────────────────────────────────────
    item_price: float | None = None
    item_subtotal_before_discount: float | None = None   # TikTok เท่านั้น
    item_discount: float | None = None
    seller_discount: float | None = None
    platform_discount: float | None = None
    payment_discount: float | None = None                # ส่วนลดจากช่องทางชำระเงิน
    tax_amount: float | None = None                      # ภาษีที่แพลตฟอร์มแจ้ง

    # ── ขนส่ง ────────────────────────────────────────────────
    shipping_fee: float | None = None
    shipping_fee_seller_discount: float | None = None    # ร้านออกค่าส่งให้เท่าไหร่
    shipping_fee_platform_discount: float | None = None  # แพลตฟอร์มออกให้เท่าไหร่
    shipping_carrier: str | None = None
    tracking_no: str | None = None

    # ── ค่าธรรมเนียม (อยู่คนละรายงานกับ order — ดู Phase 5) ──
    commission_fee: float | None = None
    transaction_fee: float | None = None
    service_fee: float | None = None

    # ── เงิน: ระดับออเดอร์ ───────────────────────────────────
    total_amount: float | None = None       # ยอดที่ลูกค้าจ่าย
    settlement_amount: float | None = None  # ยอดที่ร้านได้รับจริง

    # ── ผู้ซื้อ (ถูก mask เมื่อ include_pii=false) ───────────
    buyer_username: str | None = None
    province: str | None = None

    # ── ยกเลิก/คืน ───────────────────────────────────────────
    cancel_reason: str | None = None
    return_status: str | None = None

    # ── meta ─────────────────────────────────────────────────
    notes: str | None = None            # เหตุผลที่บาง field ว่าง — ห้ามเดาค่าแทน
    fetched_at: datetime = Field(default_factory=datetime.now)

    @field_validator("order_id", "sku", mode="before")
    @classmethod
    def _force_text(cls, v: object) -> str | None:
        """กันพลาดตั้งแต่ต้นทาง: ถ้า adapter เผลอส่ง int มา แปลงเป็น str ทันที"""
        if v is None:
            return None
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return str(v)


# ลำดับคอลัมน์ใน sheet Orders — แก้ที่นี่ที่เดียว exporter อ่านตามนี้
EXCEL_COLUMNS: tuple[str, ...] = (
    "order_id", "platform", "shop_id", "shop_name",
    "order_created_at", "order_updated_at", "paid_at",
    "status_raw", "order_status", "payment_method",
    "sku", "product_name", "variation", "quantity",
    "item_price", "item_subtotal_before_discount", "item_discount",
    "seller_discount", "platform_discount", "payment_discount", "tax_amount",
    "shipping_fee", "shipping_fee_seller_discount", "shipping_fee_platform_discount",
    "shipping_carrier", "tracking_no",
    "commission_fee", "transaction_fee", "service_fee",
    "total_amount", "settlement_amount",
    "buyer_username", "province",
    "cancel_reason", "return_status",
    "notes", "fetched_at",
)

# คอลัมน์ที่ต้องบังคับเป็น text ใน Excel ไม่งั้นเลขยาวกลายเป็น 1.23457E+18
TEXT_COLUMNS: frozenset[str] = frozenset({"order_id", "sku", "tracking_no"})

# คอลัมน์ที่จัดรูปแบบเป็นเงิน
MONEY_COLUMNS: frozenset[str] = frozenset({
    "item_price", "item_subtotal_before_discount", "item_discount",
    "seller_discount", "platform_discount", "payment_discount", "tax_amount",
    "shipping_fee", "shipping_fee_seller_discount", "shipping_fee_platform_discount",
    "commission_fee", "transaction_fee", "service_fee",
    "total_amount", "settlement_amount",
})


class RunResult(BaseModel):
    """ผลการดึงของ 1 ร้าน ใน 1 รอบ — บันทึกลง run_log แล้วโผล่บน Dashboard"""

    run_id: str
    run_date: str                       # YYYY-MM-DD
    shop_id: str
    platform: str
    shop_name: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None = None
    error_type: ErrorType | None = None
    error_message: str | None = None
    error_detail: str | None = None     # stack trace เต็ม สำหรับหน้า Error Detail
    retry_count: int = 0
    orders_fetched: int = 0
    rows_written: int = 0
    duration_sec: float | None = None
    output_file: str | None = None
    raw_file: str | None = None
    api_calls: int = 0
    http_status_last: int | None = None
