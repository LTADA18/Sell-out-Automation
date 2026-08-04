from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from src.adapters.mock import MockAdapter
from src.adapters.registry import build_adapter
from src.core.logging_setup import mask
from src.core.models import AdapterError, Order, OrderStatus
from src.core.privacy import apply_privacy, mask_username
from tests.conftest import make_order

RANGE = (date(2026, 8, 2), date(2026, 8, 2))


def test_normalize_produces_valid_orders(shop, settings):
    adapter = MockAdapter(shop, settings)
    orders = adapter.fetch_orders(*RANGE)

    assert orders and all(isinstance(o, Order) for o in orders)
    assert all(isinstance(o.order_id, str) for o in orders)
    assert all(o.shop_id == shop.shop_id for o in orders)
    assert all(isinstance(o.order_status, OrderStatus) for o in orders)


def test_order_level_fields_consistent_across_lines(shop, settings):
    """ทุกแถวของออเดอร์เดียวกันต้องมี total_amount/สถานะเท่ากัน"""
    orders = MockAdapter(shop, settings).fetch_orders(*RANGE)
    by_order: dict[str, list[Order]] = {}
    for o in orders:
        by_order.setdefault(o.order_id, []).append(o)

    for lines in by_order.values():
        assert len({l.total_amount for l in lines}) == 1
        assert len({l.order_status for l in lines}) == 1


def test_same_input_gives_same_output(shop, settings):
    """ข้อมูลปลอมต้องคงที่ ไม่งั้นแยกไม่ออกว่า Excel เปลี่ยนเพราะโค้ดหรือเพราะสุ่ม"""
    a = MockAdapter(shop, settings).fetch_orders(*RANGE)
    b = MockAdapter(shop, settings).fetch_orders(*RANGE)
    assert [o.order_id for o in a] == [o.order_id for o in b]
    assert [o.total_amount for o in a] == [o.total_amount for o in b]


def test_raw_response_is_saved_for_debugging(shop, settings):
    adapter = MockAdapter(shop, settings)
    adapter.fetch_orders(*RANGE)
    assert adapter.raw_path("2026-08-02").exists()


def test_registry_rejects_unknown_platform(shop, settings):
    """แพลตฟอร์มที่ไม่มี adapter ต้องบอกให้ชัดตอน build ไม่ใช่ไปพังกลางรอบ"""
    broken = shop.model_copy(update={"adapter": "playwright", "platform": "kaidee"})
    with pytest.raises(NotImplementedError, match="kaidee"):
        build_adapter(broken, settings)


def test_shopee_column_map_is_wired(shop, settings):
    """Shopee ต้อง normalize ได้แล้ว และ order_id ต้องเป็น string"""
    s = shop.model_copy(update={"adapter": "playwright", "platform": "shopee"})
    adapter = build_adapter(s, settings)

    assert adapter.map.fields, "shopee.yaml ต้องมี fields แล้ว"
    orders = adapter.normalize([{
        "หมายเลขคำสั่งซื้อ": "260803BAG8EKQP",
        "สถานะการสั่งซื้อ": "ยกเลิกแล้ว",
        "วันที่ทำการสั่งซื้อ": "2026-08-03 00:00",
        "จำนวน": "2",
        "จำนวนเงินทั้งหมด": "2016.00",
        "จังหวัด": "จังหวัดชัยภูมิ",
    }])
    assert len(orders) == 1
    o = orders[0]
    assert isinstance(o.order_id, str) and o.order_id == "260803BAG8EKQP"
    assert o.order_status is OrderStatus.CANCELLED
    assert o.quantity == 2
    assert o.province == "จังหวัดชัยภูมิ"


def test_shopee_status_with_trailing_text_still_maps(shop, settings):
    """ค่าสถานะจริงบางตัวยาวกว่าคีย์ใน status_map — ต้องยังจับได้

    ของจริง: "ผู้ซื้อได้รับสินค้าแล้ว โปรดทราบว่าผู้ซื้อ..." ถ้าจับไม่ได้จะกลายเป็น UNKNOWN
    """
    s = shop.model_copy(update={"adapter": "playwright", "platform": "shopee"})
    adapter = build_adapter(s, settings)
    orders = adapter.normalize([{
        "หมายเลขคำสั่งซื้อ": "260803X",
        "สถานะการสั่งซื้อ": "ผู้ซื้อได้รับสินค้าแล้ว โปรดทราบว่าผู้ซื้อยังขอคืนได้",
    }])
    assert orders[0].order_status is OrderStatus.DELIVERED


def test_shopee_does_not_map_financial_columns(shop, settings):
    """เจ้าของงานสั่งไม่ให้ยุ่งกับข้อมูลการเงิน (2026-08-04)

    ไฟล์ Export ของ Shopee "มี" ค่าคอมมิชชั่น/Transaction Fee/ค่าบริการ อยู่จริง
    เทสต์นี้กันไม่ให้มีใครเผลอ map เข้ามาโดยไม่ได้ขออนุญาตก่อน
    """
    s = shop.model_copy(update={"adapter": "playwright", "platform": "shopee"})
    adapter = build_adapter(s, settings)

    for field in ("commission_fee", "transaction_fee", "service_fee", "settlement_amount"):
        assert field not in adapter.map.fields, (
            f"{field} ถูก map เข้ามาแล้ว — ต้องขออนุญาตเจ้าของงานก่อนแตะข้อมูลการเงิน"
        )


def test_registered_platforms_have_column_maps(shop, settings):
    """adapter ที่ลงทะเบียนไว้ต้องมีไฟล์ column map คู่กัน ไม่งั้นพังตอนรันจริง"""
    for platform in ("lazada", "tiktok"):
        s = shop.model_copy(update={"adapter": "playwright", "platform": platform})
        adapter = build_adapter(s, settings)          # โหลด PlatformMap ตอน __init__
        assert adapter.map.fields, f"{platform}.yaml ไม่มี fields"
        assert adapter.map.flow, f"{platform}.yaml ไม่มี export_flow"


def test_health_check_does_not_fetch(shop, settings):
    adapter = MockAdapter(shop, settings)
    status = adapter.health_check()
    assert status.ok is True
    assert adapter.api_calls == 0, "health_check ห้ามยิงขอข้อมูลจริง"


def test_health_check_reports_broken_credential(shop, settings):
    broken = shop.model_copy(update={"shop_id": "shopee_03"})
    assert MockAdapter(broken, settings).health_check().ok is False


# ── แปลงไฟล์ Export ของจริง ──────────────────────────────────
# ไฟล์จริงมี PII จึง commit ลง repo ไม่ได้ — เทสจะข้ามถ้าไม่มีไฟล์บนเครื่อง

DOWNLOADS = Path.home() / "Downloads"
REAL_FILES = {
    "lazada": sorted(DOWNLOADS.glob("????????????????????????????????.xlsx")),
    "tiktok": sorted(DOWNLOADS.glob("*คำสั่งซื้อ-*.xlsx")),
}


@pytest.mark.parametrize("platform", ["lazada", "tiktok"])
def test_real_export_file_parses(platform, shop, settings):
    files = REAL_FILES[platform]
    if not files:
        pytest.skip(f"ไม่มีไฟล์ Export ของ {platform} ใน Downloads")

    s = shop.model_copy(update={"adapter": "playwright", "platform": platform})
    adapter = build_adapter(s, settings)
    rows = adapter.map.read_export(files[-1])
    assert rows, "อ่านไฟล์แล้วไม่ได้สักแถว"

    orders = adapter.normalize(rows)
    assert orders, "normalize แล้วไม่ได้ Order สักตัว"
    assert all(isinstance(o.order_id, str) and o.order_id for o in orders)
    assert all(o.order_status is not None for o in orders)

    # ต้อง map สถานะได้เกินครึ่ง ไม่งั้นแปลว่า status_map ตกยุคแล้ว
    known = sum(1 for o in orders if o.order_status is not OrderStatus.UNKNOWN)
    assert known / len(orders) > 0.5, f"map สถานะได้แค่ {known}/{len(orders)} — ต้องเติม status_map"


def test_lazada_collapses_units_into_quantity(shop, settings):
    """Lazada ออก 1 แถวต่อ 1 ชิ้น — ถ้าไม่ยุบ จำนวนชิ้นจะเป็น 1 ตลอด"""
    files = REAL_FILES["lazada"]
    if not files:
        pytest.skip("ไม่มีไฟล์ Export ของ lazada ใน Downloads")

    s = shop.model_copy(update={"adapter": "playwright", "platform": "lazada"})
    adapter = build_adapter(s, settings)
    rows = adapter.map.read_export(files[-1])
    orders = adapter.normalize(rows)

    assert len(orders) <= len(rows), "จำนวนแถวหลังยุบต้องไม่มากกว่าไฟล์ต้นทาง"
    assert sum(o.quantity or 0 for o in orders) == len(rows), \
        "ผลรวม quantity ต้องเท่ากับจำนวนแถวในไฟล์ (1 แถว = 1 ชิ้น)"


def test_tiktok_skips_description_row(shop, settings):
    """แถวที่ 2 ของไฟล์ TikTok เป็นคำอธิบายคอลัมน์ ต้องไม่กลายเป็นออเดอร์ผี"""
    files = REAL_FILES["tiktok"]
    if not files:
        pytest.skip("ไม่มีไฟล์ Export ของ tiktok ใน Downloads")

    s = shop.model_copy(update={"adapter": "playwright", "platform": "tiktok"})
    adapter = build_adapter(s, settings)
    orders = adapter.normalize(adapter.map.read_export(files[-1]))
    assert all(o.order_id.isdigit() for o in orders), "มีแถวคำอธิบายหลุดเข้ามา"


# ── PDPA ─────────────────────────────────────────────────────

def test_username_is_masked_by_default():
    orders = apply_privacy([make_order("1", buyer_username="somchai")], include_pii=False)
    assert orders[0].buyer_username == "s*****i"


def test_province_survives_masking():
    """จังหวัดต้องเก็บไว้ — เป็นข้อมูลที่ใช้วิเคราะห์ได้โดยไม่ระบุตัวตน"""
    orders = apply_privacy([make_order("1", province="เชียงใหม่")], include_pii=False)
    assert orders[0].province == "เชียงใหม่"


def test_include_pii_true_keeps_original():
    orders = apply_privacy([make_order("1", buyer_username="somchai")], include_pii=True)
    assert orders[0].buyer_username == "somchai"


def test_masking_does_not_mutate_input():
    original = make_order("1", buyer_username="somchai")
    apply_privacy([original], include_pii=False)
    assert original.buyer_username == "somchai", "ต้องไม่แก้ของเดิม"


@pytest.mark.parametrize("value,expected", [("ab", "a*"), ("a", "a*"), (None, None), ("", "")])
def test_mask_username_edge_cases(value, expected):
    assert mask_username(value) == expected


def test_secret_shows_only_last_four():
    assert mask("super-secret-token-abcd1234") == "****1234"
    assert mask("xyz") == "****"
