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
    # ⚠️ หน้าจริง (2026-08) ปุ่มชื่อ "ดาวน์โหลด" ไม่ใช่ "ส่งออก"
    # เหลือ "ส่งออก"/"Export" ไว้ท้ายเผื่อ TikTok เปลี่ยนคำกลับ
    "export_btn": ['button:has-text("ดาวน์โหลด")', 'button:has-text("Download")',
                   'button:has-text("ส่งออก")', 'button:has-text("Export")'],
    # ขอบเขตที่ต้องเลือกในแผง — "คำสั่งซื้อที่กรอง" คือชุดที่ตรงกับช่วงวันที่ใน URL
    # อีก 2 ตัวเลือกคือ "ทั้งหมดที่รอการจัดส่ง" กับ "ทั้งหมดภายใต้แท็บปัจจุบัน" ซึ่งไม่สนช่วงวันที่
    "scope_filtered": ['label:has-text("คำสั่งซื้อที่กรอง")', 'text=/คำสั่งซื้อที่กรอง/',
                       'label:has-text("Filtered orders")'],
    "excel_radio": ['label:has-text("Excel")', 'text="Excel"'],
    # ปุ่มยืนยันในแผง ชื่อ "ส่งออก" (ต่างจากปุ่มนอกแผงที่ชื่อ "ดาวน์โหลด")
    "confirm_btn": ['button:has-text("ส่งออก")', 'button:has-text("Export")'],
    "history_rows": ['text=/คำสั่งซื้อ-\\d{4}-\\d{2}-\\d{2}/'],
    # ⚠️ ปุ่มในแถวประวัติใช้คำว่า "ดาวน์โหลด" เหมือนปุ่มเปิดแผงเป๊ะ
    # แยกกันที่ขนาด: ในแถว = p-btn-size-small, ปุ่มเปิดแผง = p-btn-size-default
    # ถ้าไม่ระบุจะไปกดปุ่มนอกที่ถูก drawer บังอยู่ แล้วค้างจน timeout
    "download_btn": ['button.p-btn-size-small:has-text("ดาวน์โหลด")',
                     'button.p-btn-size-small:has-text("Download")'],
    # ร่องรอย CAPTCHA / OTP — เจอเมื่อไหร่ต้องหยุด ห้ามพยายามผ่าน (กฎเหล็กข้อ 5)
    "challenge": ["iframe[src*='captcha']", "iframe[src*='verify']",
                  "[class*='captcha']", "[class*='secsdk']",
                  'text=/รหัสยืนยัน/', 'text=/verification code/i',
                  'text=/เลื่อนเพื่อ/', 'text=/Slide to/i'],
}


def _click_first(page, keys: list[str], timeout: int = 8000) -> bool:
    """ไล่ลอง selector ทีละตัวจนกดติด — คัดลอกแนวเดียวกับ adapters/lazada.py"""
    for sel in keys:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=timeout)
            loc.click()
            return True
        except Exception:                                # noqa: BLE001
            continue
    return False


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

    @property
    def orders_url(self) -> str:
        """หน้าคำสั่งซื้อแบบไม่ใส่ช่วงวันที่ — ใช้เช็ค login / ต่ออายุ session

        ⚠️ ห้ามใช้ URL นี้ตอนดึงข้อมูล ต้องใส่ time_order_created[] ด้วยเสมอ
           ไม่งั้น TikTok จะ default เป็น 12 เดือนย้อนหลัง (ดู _export)
        """
        return f"{self.base_url}/order"

    def auto_relogin(self, page) -> bool:
        """ต่ออายุ session เองโดยกดปุ่มบนฟอร์มที่ Chrome เติมรหัสไว้แล้ว

        ⚠️ ระบบไม่เก็บ ไม่อ่าน ไม่พิมพ์รหัสผ่าน — Chrome ในโปรไฟล์ร้านนี้เป็นคนเติม
           โค้ดเช็คแค่ว่าช่องรหัสมีค่าไหม (ดูความยาว ไม่ดูค่า) แล้วกดปุ่ม

        เจอ CAPTCHA / OTP = หยุดทันที ไม่พยายามผ่าน (กฎเหล็กข้อ 5)

        ทำไมต้องมี: tiktok_02 (บัญชี toolsdee1) session หลุดข้ามคืนทุกวัน
        ถ้าไม่ต่ออายุเองต้องให้คนมาล็อกอินมือทุกเช้า
        """
        page.goto(f"{self.base_url}{self.login_path}", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # ⚠️ ถ้าถูกเด้งออกจากหน้า login = ยังล็อกอินอยู่ ไม่ต้องทำอะไรต่อ
        #    (2026-08-07 tiktok_02 ถูกเด้งไป /homepage แต่โค้ดหาช่องรหัสไม่เจอ
        #     เลยรายงานว่าต่ออายุไม่ได้ ทั้งที่เข้าหลังบ้านได้อยู่)
        if not any(h in page.url.lower() for h in ("login", "signin")):
            log.info("relogin_already_logged_in", shop_id=self.shop.shop_id,
                     url=page.url[:70])
            return True

        # หน้า login ของ TikTok ตั้งค่าเริ่มต้นเป็นโหมด "ส่งรหัสยืนยัน" (OTP)
        # ต้องกดสลับไปโหมดรหัสผ่านก่อน ไม่งั้นไม่มีช่องรหัสผ่านให้ Chrome เติมเลย
        # (ยืนยันจากหน้าจริง 2026-08-08: มีปุ่ม "ล็อกอินด้วยรหัสผ่าน" อยู่บนหน้า)
        # ⚠️ ไม่ใช่การหลบ OTP — เป็นการเลือกวิธีล็อกอินที่เว็บมีให้อยู่แล้ว
        #    ถ้า TikTok ยังขอ OTP อยู่ดี จะถูกจับที่ลูปเช็ค challenge ด้านล่างแล้วหยุด
        for label in ("ล็อกอินด้วยรหัสผ่าน", "Log in with password", "Login with password"):
            try:
                btn = page.get_by_text(label, exact=True).first
                if btn.is_visible(timeout=1500):
                    btn.click(timeout=4000)
                    page.wait_for_timeout(2000)
                    log.info("relogin_switched_to_password_mode",
                             shop_id=self.shop.shop_id, label=label)
                    break
            except Exception:                            # noqa: BLE001
                continue

        filled = 0
        for _ in range(10):
            page.wait_for_timeout(1500)
            try:
                filled = page.evaluate(
                    "() => { const p = document.querySelector('input[type=password]');"
                    " return p ? p.value.length : 0; }"
                )
            except Exception:                            # noqa: BLE001
                filled = 0
            if filled:
                break
        if not filled:
            log.warning("relogin_no_saved_password", shop_id=self.shop.shop_id)
            return False
        log.info("relogin_form_prefilled", shop_id=self.shop.shop_id, pw_len=filled)

        clicked = False
        for name in ("เข้าสู่ระบบ", "Log in", "Login", "Sign in"):
            try:
                btn = page.get_by_role("button", name=name, exact=True).first
                btn.wait_for(state="visible", timeout=5000)
                btn.click(timeout=8000)
                clicked = True
                break
            except Exception:                            # noqa: BLE001
                continue
        if not clicked:
            log.warning("relogin_button_missing", shop_id=self.shop.shop_id)
            return False

        for _ in range(12):
            page.wait_for_timeout(1500)
            for sel in SEL["challenge"]:
                try:
                    if page.locator(sel).first.is_visible(timeout=600):
                        self._screenshot_on_error(page, "relogin_challenge")
                        log.warning("relogin_challenge", shop_id=self.shop.shop_id, sel=sel)
                        return False
                except Exception:                        # noqa: BLE001
                    continue
            if not any(h in page.url.lower() for h in ("login", "signin")):
                log.info("relogin_ok", shop_id=self.shop.shop_id, url=page.url[:70])
                return True
        return False

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

        # ⚠️ ต้องเป็น _ensure_logged_in ไม่ใช่ _assert_logged_in
        #    _assert_logged_in โยน AUTH_EXPIRED ทันทีโดยไม่ลองต่ออายุ session เลย
        #    ทำให้ auto_relogin ที่เขียนไว้ไม่เคยถูกเรียกใช้ — ร้าน TikTok จึงพังทุกครั้ง
        #    ที่ cookie หมดอายุ แล้วต้องให้คนมาล็อกอินมือ
        #    (เจอจริง 2026-08-08 กับ tiktok_01 — Lazada/Shopee เรียกถูกมาตลอด มีแต่ TikTok ที่พลาด)
        self._ensure_logged_in(page, url)
        log.info("tiktok_range", shop_id=self.shop.shop_id, start_ms=start_ms, end_ms=end_ms)

        try:
            return self._do_export(page)
        except AdapterError:
            # เดิมไม่ถ่ายภาพในเคสนี้ ทำให้ selector พังแล้วไล่สาเหตุไม่ได้
            self._screenshot_on_error(page, "export_failed")
            raise
        except Exception as exc:                         # noqa: BLE001
            self._screenshot_on_error(page, "export_failed")
            raise AdapterError(
                ErrorType.PARSE_ERROR,
                f"ทำตามขั้นตอน Export ไม่สำเร็จ ({type(exc).__name__}: {exc}) "
                f"— ดูภาพหน้าจอใน logs/screenshots/",
            ) from exc

    def _do_export(self, page) -> Path:
        # เปิดแผง — ปุ่มนอกชื่อ "ดาวน์โหลด"
        if not _click_first(page, SEL["export_btn"], 10_000):
            raise AdapterError(ErrorType.PARSE_ERROR, 'หาปุ่ม "ดาวน์โหลด" ไม่เจอ')
        page.wait_for_timeout(2500)

        # ⚠️ ต้องเลือก "คำสั่งซื้อที่กรอง" ก่อนเสมอ
        # ค่าเริ่มต้นของแผงไม่ใช่ตัวนี้ ถ้าไม่เลือกจะได้ออเดอร์ผิดชุด
        # (หน้าเว็บเตือนเองว่า "ไม่เลือกช่วงเวลา = ดาวน์โหลด 12 เดือนย้อนหลัง")
        if not _click_first(page, SEL["scope_filtered"], 6000):
            raise AdapterError(
                ErrorType.PARSE_ERROR,
                'เลือกขอบเขต "คำสั่งซื้อที่กรอง" ไม่ได้ — หยุดก่อน '
                "เพราะเสี่ยงได้ข้อมูลคนละช่วงวันที่โดยไม่รู้ตัว",
            )
        page.wait_for_timeout(1000)

        # เลือกฟอร์แมต Excel (ค่าเริ่มต้นมักเป็น Excel อยู่แล้ว แต่ยืนยันให้ชัวร์)
        _click_first(page, SEL["excel_radio"], 4000)

        before = self._history_labels(page)

        if not _click_first(page, SEL["confirm_btn"], 8000):
            raise AdapterError(ErrorType.PARSE_ERROR, 'หาปุ่มยืนยัน "ส่งออก" ในแผงไม่เจอ')
        page.wait_for_timeout(2500)

        new_label = self._wait_for_new_file(page, before)
        log.info("tiktok_export_ready", shop_id=self.shop.shop_id, file=new_label)

        btn = self._row_download_button(page, new_label)
        return self._capture_download(page, btn.click, timeout_ms=120_000)

    def _try_row_download_button(self, page, label: str):
        """หาปุ่มดาวน์โหลด "ของแถวนั้น" โดยไต่ขึ้นจากชื่อไฟล์ทีละชั้น — ไม่เจอคืน None

        แถวประวัติเป็น <div> ไม่ใช่ <tr> (โค้ดเดิมหา ancestor::tr แล้วไม่เจอ)
        เงื่อนไข count == 1 คือตัวบอกว่าไต่มาถึงระดับ "แถว" พอดี —
        ถ้าไต่สูงเกินไปจะเจอปุ่มของทุกแถวรวมกัน

        แถวที่ยังสร้างไฟล์ไม่เสร็จจะเป็นปุ่ม "กำลังส่งออก" ยังไม่ใช่ "ดาวน์โหลด"
        จึงคืน None ให้ผู้เรียกรอต่อ
        """
        node = page.locator(f'text="{label}"').first
        if node.count() == 0:
            return None
        for _ in range(6):
            node = node.locator("xpath=..")
            for sel in SEL["download_btn"]:
                btn = node.locator(sel)
                if btn.count() == 1:
                    return btn.first
        return None

    def _row_download_button(self, page, label: str):
        btn = self._try_row_download_button(page, label)
        if btn is None:
            raise AdapterError(
                ErrorType.PARSE_ERROR,
                f'หาปุ่มดาวน์โหลดของแถว "{label}" ไม่เจอ — โครงสร้างประวัติเปลี่ยน',
            )
        return btn

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
                # ⚠️ ต้องเช็คปุ่ม "ของแถวใหม่" ไม่ใช่ปุ่มไหนก็ได้บนหน้า
                # แถวเก่ามีปุ่มดาวน์โหลดอยู่แล้วเสมอ เช็คแบบรวม ๆ จะผ่านทันที
                # ทั้งที่แถวใหม่ยังขึ้น "กำลังส่งออก" อยู่
                if self._try_row_download_button(page, label) is not None:
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
                shop_name=self.shop.report_name,
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
