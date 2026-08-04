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
    "all_tab": ['text="ทั้งหมด"'],
    "custom_range": ['text="กำหนดเอง"', 'text="Custom"'],
    "yesterday": ['text="เมื่อวานนี้"', 'text="Yesterday"'],
    "date_from": ['input[placeholder="วันที่เริ่มต้น"]', 'input[placeholder="Start date"]'],
    "date_to": ['input[placeholder="วันที่สิ้นสุด"]', 'input[placeholder="End date"]'],
    "time_input": ['input[placeholder="HH:mm:ss"]'],
    "export_btn": ['button:has-text("ส่งออก")', 'button:has-text("Export")'],
    # "Export All" เป็น li.next-menu-item — ไม่ใช่ role=menuitem (อันนั้นคือเมนูซ้ายของ Seller Center)
    "export_all": ['li[class*="menu-item"]:has-text("Export All")',
                   'li[class*="menu-item"]:has-text("ส่งออกทั้งหมด")',
                   'text="Export All"',
                   'text="ส่งออกทั้งหมด"'],
    "confirm_btn": ['button:has-text("ยืนยัน")', 'button:has-text("Confirm")', 'button:has-text("OK")'],
    "download_link": ['text="ดาวน์โหลดไฟล์"', 'text="Download file"'],
    # ปุ่มบนหน้า login — exact=True กันไปโดน "เข้าสู่ระบบด้วย OTP" ที่อยู่ใต้กันพอดี
    "login_btn": ['button:text-is("เข้าสู่ระบบ")', 'button:text-is("Login")',
                  'button:text-is("Sign in")'],
    # ร่องรอย CAPTCHA / OTP ตระกูล Alibaba — เจอแล้วต้องหยุด ห้ามพยายามผ่าน
    "challenge": ['#nc_1_wrapper', '.nc-container', "iframe[src*='punish']",
                  "iframe[src*='captcha']", 'text=/เลื่อนเพื่อยืนยัน/',
                  'text=/รหัส OTP/', 'text=/verification code/i'],
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
        self._ensure_logged_in(page, url)                # หมดอายุแล้วต่อเองได้ (ดู auto_relogin)

        # หน้าเปิดมาที่แท็บ "ที่ต้องจัดส่ง" ซึ่ง **ไม่มีตัวกรองวันที่**
        # ต้องสลับไปแท็บ "ทั้งหมด" ก่อน ช่องวันที่เริ่มต้น/สิ้นสุดถึงจะโผล่
        # (และได้ออเดอร์ทุกสถานะ ไม่ใช่เฉพาะที่รอจัดส่ง)
        if _click_first(page, SEL["all_tab"], 8000):
            page.wait_for_timeout(4000)
        else:
            log.warning("all_tab_not_found", shop_id=self.shop.shop_id)

        try:
            self._set_date_range(page, date_from, date_to)
            return self._do_export(page)
        except AdapterError:
            # เดิมไม่ถ่ายภาพในเคสนี้ ทำให้ selector พังแล้วไล่สาเหตุไม่ได้เลย
            self._screenshot_on_error(page, "export_failed")
            raise
        except Exception as exc:                         # noqa: BLE001
            self._screenshot_on_error(page, "export_failed")
            raise AdapterError(
                ErrorType.PARSE_ERROR,
                f"ทำตามขั้นตอน Export ไม่สำเร็จ ({type(exc).__name__}: {exc}) "
                f"— ดูภาพหน้าจอใน logs/screenshots/ แล้วแก้ selector ใน adapters/lazada.py",
            ) from exc

    # ── ต่ออายุ session เอง ─────────────────────────────────

    def auto_relogin(self, page) -> bool:
        """กดปุ่ม "เข้าสู่ระบบ" บนฟอร์มที่ Chrome เติมรหัสไว้ให้แล้ว

        ⚠️ ระบบไม่เก็บ ไม่อ่าน ไม่พิมพ์รหัสผ่าน — Chrome ในโปรไฟล์ของร้านนี้
        เป็นคนเติมช่องให้เอง (จากตอนที่คนล็อกอินด้วยมือครั้งแรก)
        โค้ดทำแค่ 2 อย่าง: เช็คว่าช่องมีค่าอยู่ไหม (ดูความยาว ไม่ดูค่า) แล้วกดปุ่ม

        เจอ CAPTCHA / OTP เมื่อไหร่ = หยุดทันที ไม่พยายามผ่าน (กฎเหล็กข้อ 5)
        """
        page.goto(f"{self.base_url}{self.login_path}", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # ถ้าโดนเด้งไปหน้าสมัครสมาชิก แปลว่า Lazada ไม่รู้จักเครื่องนี้แล้ว
        # หน้านั้นมีช่องรหัสผ่านของฟอร์มสมัคร (ว่าง) ถ้าไม่กันไว้จะเข้าใจผิดว่าเป็นฟอร์มล็อกอิน
        if any(k in page.url.lower() for k in ("/register", "/signup")):
            log.warning("relogin_landed_on_signup", shop_id=self.shop.shop_id, url=page.url[:120])
            return False

        # Chrome เติมรหัสให้ช้ากว่า domcontentloaded พอสมควร ต้อง poll ไม่ใช่รอเวลาตายตัว
        filled = 0
        for _ in range(10):
            page.wait_for_timeout(1500)
            filled = page.evaluate(
                "() => { const p = document.querySelector('input[type=password]');"
                " return p ? p.value.length : 0; }"
            )
            if filled:
                break
        if not filled:
            log.warning("relogin_no_saved_password", shop_id=self.shop.shop_id)
            return False
        log.info("relogin_form_prefilled", shop_id=self.shop.shop_id, pw_len=filled)

        # ⚠️ ห้ามใช้ button:text-is("เข้าสู่ระบบ") — ปุ่มมี <span> ซ้อนข้างใน
        #    :text-is เทียบข้อความของ element ตัวเอง จึงไม่แมตช์ (เจอจริง 2026-08-04)
        #    get_by_role ดูจาก accessible name จึงกดติด — วิธีเดียวกับที่กดด้วยมือแล้วผ่าน
        #    exact=True สำคัญ ไม่งั้นไปโดน "เข้าสู่ระบบด้วย OTP" ที่อยู่ใต้กันพอดี
        clicked = False
        for name in ("เข้าสู่ระบบ", "Login", "Sign in"):
            try:
                btn = page.get_by_role("button", name=name, exact=True).first
                btn.wait_for(state="visible", timeout=6000)
                btn.click(timeout=8000)
                clicked = True
                break
            except Exception:                            # noqa: BLE001
                continue
        if not clicked and not _click_first(page, SEL["login_btn"], 6000):
            log.warning("relogin_button_missing", shop_id=self.shop.shop_id)
            return False

        for _ in range(12):
            page.wait_for_timeout(1500)
            for sel in SEL["challenge"]:
                try:
                    if page.locator(sel).first.is_visible(timeout=600):
                        self._screenshot_on_error(page, "relogin_challenge")
                        log.warning("relogin_challenge", shop_id=self.shop.shop_id, sel=sel)
                        return False                     # ต้องให้คนมาทำเอง
                except Exception:                        # noqa: BLE001
                    continue
            if "login" not in page.url.lower():
                return True
        return False

    # ── ตั้งช่วงวันที่ ───────────────────────────────────────

    def _set_date_range(self, page, date_from: date, date_to: date) -> None:
        """ใช้ปุ่มสำเร็จรูป "เมื่อวานนี้" ถ้าตรงกันพอดี — ทนกว่าการกรอกปฏิทินมาก"""
        yesterday = date.today() - timedelta(days=1)
        if date_from == date_to == yesterday and _click_first(page, SEL["yesterday"], 5000):
            log.info("date_range_preset", shop_id=self.shop.shop_id, preset="เมื่อวานนี้")
            page.wait_for_timeout(2500)
            return

        # ⚠️ ช่องวันที่ **พิมพ์ไม่ได้** — เป็น <input disabled readonly role="combobox">
        # ต้องกด "กำหนดเอง" เพื่อปลดล็อก แล้วเลือกวันจากปฏิทินที่กางออกมาเท่านั้น
        # (โค้ดเดิมใช้ .fill() จึงค้างจน timeout — backfill พังมาตลอดโดยไม่มีใครรู้)
        if not _click_first(page, SEL["custom_range"], 8000):
            raise AdapterError(ErrorType.PARSE_ERROR, 'หาปุ่มช่วงวันที่ "กำหนดเอง" ไม่เจอ')
        page.wait_for_timeout(1500)

        # เป็น range picker: เปิดปฏิทิน **ครั้งเดียว** จากช่องเริ่มต้น
        # แล้วคลิก 2 วันติดกันในปฏิทินเดิม
        # (เดิมไปคลิกช่อง "วันที่สิ้นสุด" เพื่อเปิดใหม่ ปฏิทินเลยปิดไปเฉย ๆ
        #  แล้วค้างรอ actionability อยู่ 60 วินาทีก่อนพัง)
        self._open_calendar(page, SEL["date_from"])
        self._click_day(page, date_from)
        self._click_day(page, date_to)
        page.wait_for_timeout(3000)

        # ปฏิทินบางรุ่นต้องกด "ตกลง" ปิดก่อนตารางถึงจะ refresh
        _click_first(page, ['button:has-text("ตกลง")', 'button:has-text("OK")'], 3000)
        page.wait_for_timeout(3000)
        log.info("date_range_custom", shop_id=self.shop.shop_id,
                 date_from=date_from.isoformat(), date_to=date_to.isoformat())

    def _open_calendar(self, page, input_sels: list[str]) -> None:
        """คลิกช่องวันที่เพื่อกางปฏิทิน แล้วรอจนเห็นช่องวันจริง ๆ"""
        for sel in input_sels:
            loc = page.locator(sel).first
            try:
                loc.wait_for(state="visible", timeout=5000)
                loc.click(timeout=8000)
                page.wait_for_selector("td[title]:visible", timeout=8000)
                return
            except Exception:                            # noqa: BLE001
                continue
        raise AdapterError(
            ErrorType.PARSE_ERROR,
            f"กางปฏิทินไม่ได้ — ลองแล้ว {input_sels} ดูภาพใน logs/screenshots/",
        )

    def _click_day(self, page, target: date) -> None:
        """คลิก 1 วันในปฏิทินที่กางอยู่ — ช่องวันมี title="YYYY-MM-DD" ให้เล็งได้ตรง ๆ

        ปฏิทินโชว์ทีละ 2 เดือน ถ้าวันที่ต้องการไม่อยู่ในหน้าจอต้องกดลูกศรเลื่อนก่อน
        """
        want = target.isoformat()
        # ⚠️ ต้องมี :visible — ปฏิทินของช่อง "วันที่เริ่มต้น" ที่ปิดไปแล้วยังอยู่ใน DOM
        # ถ้าใช้ .first เฉย ๆ จะไปโดนช่องในปฏิทินที่ซ่อนอยู่ แล้วกดไม่ติด
        cell = page.locator(f'td[title="{want}"]:visible')
        for _ in range(24):                              # เผื่อย้อนหลังได้ ~2 ปี
            if cell.count():
                cell.first.click()
                page.wait_for_timeout(1200)
                log.info("date_picked", shop_id=self.shop.shop_id, date=want)
                return

            shown = self._first_shown_date(page)
            arrow = "prev-month" if shown is None or want < shown else "next-month"
            nav = page.locator(f'[class*="{arrow}"]:visible').first
            try:
                log.info("calendar_nav", shop_id=self.shop.shop_id,
                         want=want, shown=shown, arrow=arrow)
                nav.click(timeout=4000)
            except Exception as exc:                     # noqa: BLE001
                raise AdapterError(
                    ErrorType.PARSE_ERROR,
                    f"เลื่อนปฏิทินไปหา {want} ไม่ได้ (ปุ่ม {arrow}: {type(exc).__name__})",
                ) from exc
            page.wait_for_timeout(900)

        raise AdapterError(
            ErrorType.PARSE_ERROR,
            f"หาวันที่ {want} ในปฏิทินไม่เจอ หลังเลื่อน 24 ครั้ง",
        )

    @staticmethod
    def _first_shown_date(page) -> str | None:
        """วันแรกสุดที่ปฏิทินกำลังแสดง — ใช้ตัดสินว่าจะเลื่อนไปหน้าหรือหลัง"""
        try:
            return page.locator("td[title]:visible").first.get_attribute("title")
        except Exception:                                # noqa: BLE001
            return None

    # ── กด Export แล้วดักไฟล์ ────────────────────────────────

    def _do_export(self, page) -> Path:
        def trigger() -> None:
            if not _click_first(page, SEL["export_btn"]):
                raise AdapterError(ErrorType.PARSE_ERROR, 'หาปุ่ม "ส่งออก" ไม่เจอ')
            page.wait_for_timeout(1500)
            # ⚠️ ห้ามหยิบ [role="menuitem"] ตัวแรก — เมนูซ้ายของ Seller Center
            # ก็เป็น role=menuitem เหมือนกัน ตัวแรกคือ "เครื่องมือที่ใช้บ่อย"
            # ตัวที่ต้องการชื่อ "Export All" (อีกตัวคือ "Export History" = ประวัติ)
            if not _click_first(page, SEL["export_all"], 6000):
                raise AdapterError(
                    ErrorType.PARSE_ERROR,
                    'กด "ส่งออก" แล้วไม่เจอเมนู "Export All" — หน้าเว็บอาจเปลี่ยน',
                )
            page.wait_for_timeout(1200)
            if not _click_first(page, SEL["confirm_btn"], 15000):
                raise AdapterError(
                    ErrorType.PARSE_ERROR,
                    'กด "ส่งออก" แล้วไม่เจอกล่องยืนยัน — หน้าเว็บอาจเปลี่ยน',
                )

        try:
            return self._capture_download(page, trigger, timeout_ms=180_000)
        except AdapterError as exc:
            # TIMEOUT = กดสำเร็จแต่ไฟล์ไม่เด้งเอง ยังมีทางรอด: กดลิงก์ในกล่องผลลัพธ์
            # error อื่น (หาปุ่มไม่เจอ ฯลฯ) ลองต่อไปก็ไม่มีประโยชน์
            if exc.error_type is not ErrorType.TIMEOUT:
                raise
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
