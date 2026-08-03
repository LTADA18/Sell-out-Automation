"""Lazada Seller Center — กดปุ่ม "ส่งออก" ในหน้าคำสั่งซื้อแล้วอ่านไฟล์ที่ได้

flow อ้างอิงจากวิดีโอที่ผู้ใช้บันทึกไว้ (2026-08-03) + หน้าจริง
ต่างจาก TikTok: ได้ไฟล์ทันทีในไม่กี่วินาที ไม่ต้อง poll ประวัติ
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.adapters.playwright_base import PlaywrightAdapter
from src.core.logging_setup import get_logger
from src.core.models import AdapterError, ErrorType, Order

log = get_logger()

# selector หลายตัวต่อ 1 ปุ่ม — ไล่ลองจนกว่าจะเจอ
# อิงข้อความ/role เป็นหลัก เพราะ class ของ Next design system เปลี่ยนบ่อย
SEL = {
    "custom_range": ['text="กำหนดเอง"', 'text="Custom"'],
    "yesterday": ['text="เมื่อวานนี้"', 'text="Yesterday"'],
    "date_input": ['input[placeholder="YYYY-MM-DD"]'],
    "time_input": ['input[placeholder="HH:mm:ss"]'],
    "export_btn": ['button:has-text("ส่งออก")', 'button:has-text("Export")'],
    "confirm_btn": ['button:has-text("ยืนยัน")', 'button:has-text("Confirm")', 'button:has-text("OK")'],
    "download_link": ['text="ดาวน์โหลดไฟล์"', 'text="Download file"'],
}


def _click_first(page, keys: list[str], timeout: int = 8000) -> bool:
    for sel in keys:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=timeout)
            loc.click()
            return True
        except Exception:                                # noqa: BLE001
            continue
    return False


class LazadaAdapter(PlaywrightAdapter):
    name = "playwright"
    base_url_env = "LAZADA_SELLER_URL"
    login_path = "/apps/seller/login"

    def _export(self, page, date_from: date, date_to: date) -> Path:
        url = f"{self.base_url}/apps/order/list?oldVersion=1"
        page.goto(url, wait_until="domcontentloaded")
        self.api_calls += 1
        page.wait_for_timeout(3000)                      # หน้านี้ render ช้า รอ widget ขึ้นครบ
        self._assert_logged_in(page)

        try:
            self._set_date_range(page, date_from, date_to)
            return self._do_export(page)
        except AdapterError:
            raise
        except Exception as exc:                         # noqa: BLE001
            self._screenshot_on_error(page, "export_failed")
            raise AdapterError(
                ErrorType.PARSE_ERROR,
                f"ทำตามขั้นตอน Export ไม่สำเร็จ ({type(exc).__name__}: {exc}) "
                f"— ดูภาพหน้าจอใน logs/screenshots/ แล้วแก้ selector ใน adapters/lazada.py",
            ) from exc

    # ── ตั้งช่วงวันที่ ───────────────────────────────────────

    def _set_date_range(self, page, date_from: date, date_to: date) -> None:
        """ใช้ปุ่มสำเร็จรูป "เมื่อวานนี้" ถ้าตรงกันพอดี — ทนกว่าการกรอกปฏิทินมาก"""
        yesterday = date.today() - timedelta(days=1)
        if date_from == date_to == yesterday and _click_first(page, SEL["yesterday"], 5000):
            log.info("date_range_preset", shop_id=self.shop.shop_id, preset="เมื่อวานนี้")
            page.wait_for_timeout(2500)
            return

        if not _click_first(page, SEL["custom_range"]):
            raise AdapterError(ErrorType.PARSE_ERROR, 'หาปุ่มช่วงวันที่ "กำหนดเอง" ไม่เจอ')
        page.wait_for_timeout(1200)

        dates = page.locator(SEL["date_input"][0])
        times = page.locator(SEL["time_input"][0])
        if dates.count() < 2:
            raise AdapterError(
                ErrorType.PARSE_ERROR,
                f"คาดว่าจะมีช่องวันที่ 2 ช่อง แต่เจอ {dates.count()} ช่อง — หน้าเว็บเปลี่ยนแล้ว",
            )

        for i, day in enumerate((date_from, date_to)):
            dates.nth(i).fill(day.isoformat())
            dates.nth(i).press("Enter")
            page.wait_for_timeout(400)
            if times.count() > i:
                times.nth(i).fill("00:00:00" if i == 0 else "23:59:59")
                times.nth(i).press("Enter")
                page.wait_for_timeout(400)

        # ปฏิทินบางรุ่นต้องกด "ตกลง" ปิดก่อนตารางถึงจะ refresh
        _click_first(page, ['button:has-text("ตกลง")', 'button:has-text("OK")'], 3000)
        page.wait_for_timeout(3000)
        log.info("date_range_custom", shop_id=self.shop.shop_id,
                 date_from=date_from.isoformat(), date_to=date_to.isoformat())

    # ── กด Export แล้วดักไฟล์ ────────────────────────────────

    def _do_export(self, page) -> Path:
        def trigger() -> None:
            if not _click_first(page, SEL["export_btn"]):
                raise AdapterError(ErrorType.PARSE_ERROR, 'หาปุ่ม "ส่งออก" ไม่เจอ')
            page.wait_for_timeout(1200)
            # ปุ่มเป็น next-menu-btn — บางครั้งกางเมนูก่อน ต้องเลือกรายการแรก
            menu = page.locator('[role="menuitem"], li[class*="menu-item"]').first
            try:
                if menu.is_visible(timeout=2500):
                    menu.click()
                    page.wait_for_timeout(800)
            except Exception:                            # noqa: BLE001
                pass
            if not _click_first(page, SEL["confirm_btn"], 15000):
                raise AdapterError(
                    ErrorType.PARSE_ERROR,
                    'กด "ส่งออก" แล้วไม่เจอกล่องยืนยัน — หน้าเว็บอาจเปลี่ยน',
                )

        try:
            return self._capture_download(page, trigger, timeout_ms=180_000)
        except AdapterError:
            raise
        except Exception:                                # noqa: BLE001
            # ไฟล์ไม่เด้งเอง — ลองกดลิงก์ "ดาวน์โหลดไฟล์" ใน modal ผลลัพธ์
            log.warning("auto_download_missed", shop_id=self.shop.shop_id)
            return self._capture_download(
                page, lambda: _click_first(page, SEL["download_link"], 20000), 120_000
            )

    # ── แปลงเป็น schema กลาง ─────────────────────────────────

    def normalize(self, raw: Any) -> list[Order]:
        rows = raw["rows"] if isinstance(raw, dict) else raw
        m = self.map

        # Lazada ออก 1 แถวต่อ "1 ชิ้น" — ไม่มีคอลัมน์ quantity
        # ต้องยุบ (orderNumber, sellerSku) แล้วนับเองก่อน ไม่งั้นจำนวนชิ้นเป็น 1 ตลอด
        grouped: dict[tuple[str, str], dict] = {}
        for row in rows:
            order_id = m.to_text(m.get(row, "order_id"))
            if not order_id:
                continue
            sku = m.to_text(m.get(row, "sku")) or ""
            key = (order_id, sku)
            if key in grouped:
                grouped[key]["_qty"] += 1
                grouped[key]["_paid"] += m.to_float(m.get(row, "paid_price")) or 0.0
            else:
                grouped[key] = {"_row": row, "_qty": 1,
                                "_paid": m.to_float(m.get(row, "paid_price")) or 0.0}

        # total_amount ระดับออเดอร์ = ผลรวม paidPrice ทุกชิ้น + ค่าส่ง (ค่าส่งซ้ำทุกแถว นับครั้งเดียว)
        order_total: dict[str, float] = {}
        order_ship: dict[str, float] = {}
        for (order_id, _), g in grouped.items():
            order_total[order_id] = order_total.get(order_id, 0.0) + g["_paid"]
            order_ship[order_id] = m.to_float(m.get(g["_row"], "shipping_fee")) or 0.0

        orders: list[Order] = []
        for (order_id, sku), g in grouped.items():
            row, qty = g["_row"], g["_qty"]
            status_raw = m.get(row, "status_raw")
            notes = []
            if m.get(row, "postcode"):
                notes.append("province ยังไม่ได้แปลงจากรหัสไปรษณีย์ (shippingCity ถูก mask)")
            notes.append("ค่าธรรมเนียม/settlement อยู่ในรายงานการเงิน ยังไม่ได้ดึง")

            orders.append(Order(
                order_id=order_id,
                platform=self.shop.platform,
                shop_id=self.shop.shop_id,
                shop_name=self.shop.display_name,
                order_created_at=m.parse_dt(m.get(row, "order_created_at")),
                order_updated_at=m.parse_dt(m.get(row, "order_updated_at")),
                status_raw=str(status_raw) if status_raw is not None else None,
                order_status=m.map_status(status_raw),
                payment_method=m.get(row, "payment_method"),
                sku=sku or None,
                product_name=m.get(row, "product_name"),
                variation=m.get(row, "variation"),
                quantity=qty,
                item_price=m.to_float(m.get(row, "item_price")),
                seller_discount=m.to_float(m.get(row, "seller_discount")),
                platform_discount=m.to_float(m.get(row, "platform_discount")),
                shipping_fee=m.to_float(m.get(row, "shipping_fee")),
                shipping_carrier=m.get(row, "shipping_carrier"),
                tracking_no=m.to_text(m.get(row, "tracking_no")),
                total_amount=round(order_total[order_id] + order_ship[order_id], 2),
                province=None,               # shippingCity ถูก mask — ยังไม่ได้ทำตารางรหัสไปรษณีย์
                return_status=m.to_text(m.get(row, "return_status")),
                notes=" / ".join(notes),
                fetched_at=datetime.now(),
            ))
        return orders
