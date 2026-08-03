"""TikTok Shop Seller Center — ส่งช่วงวันที่ผ่าน URL แล้วรอไฟล์ในประวัติการส่งออก

ต่างจาก Lazada 2 อย่าง:
1. ช่วงวันที่ยัดใส่ URL ได้ (epoch ms) — ไม่ต้องแตะปฏิทินเลย เสถียรกว่ามาก
2. กด Export แล้วไฟล์ไม่มาทันที เข้าคิวใน "ประวัติการส่งออก" ต้อง poll รอ
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from src.adapters.playwright_base import PlaywrightAdapter
from src.core.logging_setup import get_logger
from src.core.models import AdapterError, ErrorType, Order

log = get_logger()

TH = timezone(timedelta(hours=7))

SEL = {
    "export_btn": ['button:has-text("ส่งออก")', 'button:has-text("Export")'],
    "excel_radio": ['label:has-text("Excel")', 'text="Excel"'],
    "history_rows": ['text=/คำสั่งซื้อ-\\d{4}-\\d{2}-\\d{2}/'],
    "download_btn": ['button:has-text("ดาวน์โหลด")', 'button:has-text("Download")'],
}


def _epoch_ms(day: date, end_of_day: bool) -> int:
    """แปลงวันที่ไทยเป็น epoch มิลลิวินาที (ตรวจกับ URL จริงแล้ว)

    1785517200000 = 2026-08-01 00:00:00.000 +07
    1785689999999 = 2026-08-02 23:59:59.999 +07
    """
    t = time(23, 59, 59, 999000) if end_of_day else time(0, 0, 0, 0)
    return int(datetime.combine(day, t, tzinfo=TH).timestamp() * 1000)


class TiktokAdapter(PlaywrightAdapter):
    name = "playwright"
    base_url_env = "TIKTOK_SELLER_URL"
    login_path = "/account/login"

    def _export(self, page, date_from: date, date_to: date) -> Path:
        start_ms, end_ms = _epoch_ms(date_from, False), _epoch_ms(date_to, True)
        url = (
            f"{self.base_url}/order?selected_sort=6&tab=all"
            f"&time_order_created[]={start_ms}&time_order_created[]={end_ms}"
        )

        # ถ้าพารามิเตอร์วันที่หลุด TikTok จะ default เป็น "12 เดือนย้อนหลัง"
        # = ดึงทั้งปีทุกเช้า × 5 ร้าน ต้องกันไว้ก่อนกดปุ่มใด ๆ
        if "time_order_created" not in url:
            raise AdapterError(ErrorType.PARSE_ERROR, "URL ไม่มีพารามิเตอร์ช่วงวันที่ — หยุดก่อนดึงทั้งปี")

        page.goto(url, wait_until="domcontentloaded")
        self.api_calls += 1
        page.wait_for_timeout(4000)
        self._assert_logged_in(page)
        log.info("tiktok_range", shop_id=self.shop.shop_id, start_ms=start_ms, end_ms=end_ms)

        try:
            return self._do_export(page)
        except AdapterError:
            raise
        except Exception as exc:                         # noqa: BLE001
            self._screenshot_on_error(page, "export_failed")
            raise AdapterError(
                ErrorType.PARSE_ERROR,
                f"ทำตามขั้นตอน Export ไม่สำเร็จ ({type(exc).__name__}: {exc}) "
                f"— ดูภาพหน้าจอใน logs/screenshots/",
            ) from exc

    def _do_export(self, page) -> Path:
        # เปิดแผงส่งออก
        opened = False
        for sel in SEL["export_btn"]:
            loc = page.locator(sel).first
            try:
                loc.wait_for(state="visible", timeout=10_000)
                loc.click()
                opened = True
                break
            except Exception:                            # noqa: BLE001
                continue
        if not opened:
            raise AdapterError(ErrorType.PARSE_ERROR, 'หาปุ่ม "ส่งออก" ไม่เจอ')
        page.wait_for_timeout(1500)

        # เลือกฟอร์แมต Excel (ค่าเริ่มต้นมักเป็น Excel อยู่แล้ว แต่ยืนยันให้ชัวร์)
        for sel in SEL["excel_radio"]:
            try:
                page.locator(sel).first.click(timeout=3000)
                break
            except Exception:                            # noqa: BLE001
                continue

        before = self._history_labels(page)

        # ปุ่ม "ส่งออก" ในแผง (ตัวสุดท้ายบนหน้า = ปุ่มในแผงที่เพิ่งเปิด)
        page.locator(SEL["export_btn"][0]).last.click()
        page.wait_for_timeout(2000)

        new_label = self._wait_for_new_file(page, before)
        log.info("tiktok_export_ready", shop_id=self.shop.shop_id, file=new_label)

        row = page.locator(f'text="{new_label}"').first
        btn = row.locator("xpath=ancestor::tr[1]").locator(SEL["download_btn"][0]).first
        if btn.count() == 0:
            btn = page.locator(SEL["download_btn"][0]).first
        return self._capture_download(page, btn.click, timeout_ms=120_000)

    def _history_labels(self, page) -> set[str]:
        """ชื่อไฟล์ที่มีอยู่แล้วในประวัติ — ใช้เทียบว่าอันไหนคือของรอบนี้"""
        try:
            return set(page.locator(SEL["history_rows"][0]).all_inner_texts())
        except Exception:                                # noqa: BLE001
            return set()

    def _wait_for_new_file(self, page, before: set[str], timeout_sec: int = 300) -> str:
        """รอจนแถวใหม่ในประวัติสร้างเสร็จ (สปินเนอร์ -> ปุ่มดาวน์โหลด)

        ชื่อไฟล์มีเวลาในตัว ("ทั้งหมด คำสั่งซื้อ-2026-08-03-16:36.xlsx")
        จึงยืนยันได้ว่าได้ไฟล์ของรอบนี้จริง ไม่ใช่ไฟล์เก่าที่ค้างอยู่ในประวัติ
        """
        deadline = datetime.now() + timedelta(seconds=timeout_sec)
        while datetime.now() < deadline:
            page.wait_for_timeout(5000)
            new = self._history_labels(page) - before
            if new:
                label = sorted(new)[-1]
                if page.locator(SEL["download_btn"][0]).count() > 0:
                    return label
        raise AdapterError(
            ErrorType.TIMEOUT,
            f"รอไฟล์ในประวัติการส่งออกเกิน {timeout_sec} วินาทีแล้วยังไม่เสร็จ",
        )

    # ── แปลงเป็น schema กลาง ─────────────────────────────────

    def normalize(self, raw: Any) -> list[Order]:
        rows = raw["rows"] if isinstance(raw, dict) else raw
        m = self.map
        orders: list[Order] = []

        for row in rows:
            order_id = m.to_text(m.get(row, "order_id"))
            if not order_id:
                continue
            # แถวคำอธิบายคอลัมน์ของ TikTok จะไม่ใช่ตัวเลข — กันไว้อีกชั้นนอกจาก data_start_row
            if not order_id.isdigit():
                continue

            # substatus ละเอียดกว่า status หลัก — ใช้ก่อนเสมอถ้ามีค่า
            # ('จัดส่งแล้ว' ไม่บอกว่าถึงมือลูกค้าหรือยัง แต่ substatus บอก)
            status_main = m.get(row, "status_raw")
            status_sub = m.get(row, "status_sub")
            status_for_map = status_sub or status_main
            status_raw = " | ".join(str(s) for s in (status_main, status_sub) if s)
            refund = m.to_float(m.get(row, "refund_amount"))

            orders.append(Order(
                order_id=order_id,
                platform=self.shop.platform,
                shop_id=self.shop.shop_id,
                shop_name=self.shop.display_name,
                order_created_at=m.parse_dt(m.get(row, "order_created_at")),
                order_updated_at=m.parse_dt(m.get(row, "delivered_at"))
                                 or m.parse_dt(m.get(row, "shipped_at")),
                paid_at=m.parse_dt(m.get(row, "paid_at")),
                status_raw=status_raw or None,
                order_status=m.map_status(status_for_map),
                payment_method=m.get(row, "payment_method"),
                sku=m.to_text(m.get(row, "sku")),
                product_name=m.get(row, "product_name"),
                variation=m.get(row, "variation"),
                quantity=int(m.to_float(m.get(row, "quantity")) or 0) or None,
                item_price=m.to_float(m.get(row, "item_price")),
                seller_discount=m.to_float(m.get(row, "seller_discount")),
                platform_discount=m.to_float(m.get(row, "platform_discount")),
                shipping_fee=m.to_float(m.get(row, "shipping_fee")),
                shipping_carrier=m.get(row, "shipping_carrier"),
                tracking_no=m.to_text(m.get(row, "tracking_no")),
                total_amount=m.to_float(m.get(row, "total_amount")),
                buyer_username=m.get(row, "buyer_username"),
                province=m.get(row, "province"),          # TikTok ไม่ mask จังหวัด ใช้ได้เลย
                cancel_reason=m.get(row, "cancel_reason"),
                return_status=f"refund {refund}" if refund else None,
                notes="ค่าธรรมเนียม/settlement อยู่ในเมนูการเงิน ยังไม่ได้ดึง",
                fetched_at=datetime.now(),
            ))
        return orders
