"""Shopee Seller Centre — กดปุ่ม "ดาวน์โหลด" ในหน้าคำสั่งซื้อแล้วรอไฟล์ในประวัติ

ต่างจาก Lazada/TikTok 2 อย่างที่กระทบโครงสร้าง:

1. **1 บัญชี ดูแลได้หลายร้าน** — มีหน้า /portal/shop "เลือกร้านที่จะจัดการ" คั่นหลังล็อกอิน
   session จึงเป็นของ "บัญชี" ไม่ใช่ "ร้าน" → ใช้ shop.profile_id ร่วมกันได้
   แล้วเลือกร้านด้วย shop.web_name ตอนเข้าหน้าคำสั่งซื้อ

2. **มีทัวร์แนะนำฟีเจอร์บัง** — div.onboarding-masked ดักคลิกไว้ทั้งหน้า
   ถ้าไม่ปิดก่อน กดปุ่มอะไรไม่ได้เลย (ค้างจน timeout 60 วิ)

flow อ้างอิงจากวิดีโอที่ผู้ใช้บันทึกไว้ (2026-08-04) + หน้าจริง
เป็น async เหมือน TikTok: กดแล้วเข้าคิว ต้อง poll รอในแผง "รายงานล่าสุด"
ชื่อไฟล์บอกช่วงวันที่ในตัว เช่น
    Order.all.order_creation_date.20260803_20260803.xlsx   (1 วัน)
    Order.all.order_creation_date.20260701_20260731.zip    (ช่วงยาว)
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from src.adapters.playwright_base import PlaywrightAdapter
from src.core.logging_setup import get_logger
from src.core.models import AdapterError, ErrorType, Order

log = get_logger()

SEL = {
    # ปุ่มเปิด modal — ใช้ class เฉพาะ เพราะคำว่า "ดาวน์โหลด" โผล่ 13 จุดบนหน้าเดียว
    "open_modal": ["button.export-with-modal"],
    # ปุ่มยืนยันในกล่อง (สีแดง = primary) คนละตัวกับปุ่มเปิด
    # ⚠️ ห้ามพึ่งข้อความอย่างเดียว — ปุ่มนี้เปลี่ยนคำตามภาษาและตามเวอร์ชันหน้าเว็บ
    #    (2026-08-07 shopee_03/08 พังเพราะไม่ตรงทั้ง "ดาวน์โหลด" และ "Download")
    #    ตัวสุดท้ายเป็นทางถอยแบบไม่สนข้อความ: ปุ่ม primary ในกล่อง ซึ่งคือปุ่มยืนยันเสมอ
    "confirm": ['.eds-modal__box button.eds-button--primary:has-text("ดาวน์โหลด")',
                '.eds-modal__box button.eds-button--primary:has-text("Download")',
                '.eds-modal__box button.eds-button--primary:has-text("ยืนยัน")',
                '.eds-modal__box button.eds-button--primary:has-text("Confirm")',
                'button.eds-button--primary:has-text("ดาวน์โหลด")',
                'button.eds-button--primary:has-text("Download")',
                '.eds-modal__box button.eds-button--primary',
                '.eds-modal__footer button.eds-button--primary'],
    # ⚠️ ช่องช่วงเวลาเป็น <div> ไม่ใช่ <input> — หา input จะไม่เจอ
    "range_input": [".eds-date-picker__input"],
    "picker_panel": [".eds-daterange-picker-panel"],
    "month_label": [".eds-picker-header__label"],
    "prev_month": [".eds-picker-header__prev"],
    # ⚠️ หลังบ้าน Shopee ตั้งภาษาได้รายร้าน — shopee_08 เป็นอังกฤษ ร้านอื่นเป็นไทย
    #    ถ้าใส่แต่ข้อความไทย ร้านที่ตั้งอังกฤษจะหาปุ่มไม่เจอแล้วค้างจนหมดเวลา 60 วิ
    #    (เจอจริง 2026-08-06: shopee_08 สั่งไฟล์ได้ครบ 7 เดือนเพราะปุ่มนั้นเล็งด้วย
    #     class แต่เก็บไฟล์ไม่ได้เลยเพราะปุ่มประวัติเล็งด้วยข้อความไทย)
    "history_btn": ['button:has-text("ประวัติการดาวน์โหลด")',
                    'button:has-text("Export History")'],
    # แถวในประวัติ ชื่อไฟล์ขึ้นต้นด้วย Order. เสมอ
    "report_rows": ['text=/Order\\.[\\w.]+\\.\\d{8}_\\d{8}\\.(xlsx|zip|csv)/'],
    # ใช้คัดว่า "ข้อความที่แมตช์มา" เป็นชื่อไฟล์จริง ไม่ใช่กล่องใหญ่ที่มีชื่อไฟล์อยู่ข้างใน
    # ดูเหตุผลเต็มในคอมเมนต์ของ _report_names
    "row_download": ['button.eds-button--primary:has-text("ดาวน์โหลด")',
                     'button.eds-button--primary:has-text("Download")',
                     'button:has-text("ดาวน์โหลด")',
                     'button:has-text("Download")'],
    "onboarding": ["div.onboarding-masked"],
    # ร่องรอย CAPTCHA / OTP — เจอเมื่อไหร่ต้องหยุด ห้ามพยายามผ่าน (กฎเหล็กข้อ 5)
    "challenge": ["iframe[src*='captcha']", "iframe[src*='verify']",
                  ".shopee-captcha", "[class*='captcha']",
                  'text=/รหัส OTP/', 'text=/verification code/i',
                  'text=/เลื่อนเพื่อยืนยัน/', 'text=/Slide to verify/i'],
}

# ชื่อไฟล์รายงานของ Shopee เต็มรูปแบบ เช่น
#   Order.all.order_creation_date.20260101_20260131.zip
REPORT_NAME_RE = re.compile(r"Order\.[\w.]+\.\d{8}_\d{8}\.(?:xlsx|zip|csv)")

# "ยืนยัน" มาจากกล่องทัวร์ "ดูคำสั่งซื้อที่ตรงกัน (2/2)" ที่เจอจริงกับ shopee_01
# เมื่อ 2026-08-05 — ไม่มีในลิสต์เดิมจึงปิดกล่องนั้นไม่ได้
ONBOARD_CLOSE = ("ตกลง", "ต่อไป", "ข้าม", "เข้าใจแล้ว", "ยืนยัน",
                 "Got it", "Next", "Skip", "OK", "Confirm", "I understand")


def _click_first(page, keys: list[str], timeout: int = 8000) -> bool:
    for sel in keys:
        loc = page.locator(sel).first
        try:
            loc.wait_for(state="visible", timeout=timeout)
            loc.click(timeout=timeout)
            return True
        except Exception:                                # noqa: BLE001
            continue
    return False


class ShopeeAdapter(PlaywrightAdapter):
    name = "playwright"
    base_url_env = "SHOPEE_SELLER_URL"
    login_path = "/account/signin"

    # รอไฟล์ในประวัติการดาวน์โหลดนานสุดกี่วินาที
    # 300 พอสำหรับรอบรายวัน (ช่วง 1 วัน) แต่ช่วงยาวต้องยืด — ผู้เรียกตั้งทับได้
    report_timeout_sec: int = 300

    # ⚠️ หน้า login ของ Shopee อยู่คนละโดเมนกับ Seller Centre
    #    (accounts.shopee.co.th ไม่ใช่ seller.shopee.co.th)
    #    LOGIN_URL_HINTS ใน playwright_base จับ "/login" ได้อยู่แล้วจึงครอบคลุม

    @property
    def orders_url(self) -> str:
        return f"{self.base_url}/portal/sale/order"

    # ── ขั้นตอนดึง ──────────────────────────────────────────

    def _export(self, page, date_from: date, date_to: date) -> Path:
        page.goto(self.orders_url, wait_until="domcontentloaded")
        self.api_calls += 1
        page.wait_for_timeout(9000)

        # ⚠️ ลำดับสำคัญ: ต้องตรวจ/ต่ออายุ login ให้เสร็จ "ก่อน" เลือกร้าน
        #    ของเดิมเลือกร้านก่อน ซึ่งถ้ายังไม่ล็อกอินมันจะ return ทันที
        #    พอ auto_relogin ทำงานเสร็จจะกลับมาอยู่หน้าเลือกร้าน แต่ขั้นเลือกร้าน
        #    ผ่านไปแล้ว → ค้างที่ /portal/shop แล้วหาปุ่มดาวน์โหลดไม่เจอ
        #    (เจอจริง 2026-08-07 ตอน auto_relogin ใช้ได้ครั้งแรก)
        self._ensure_logged_in(page, self.orders_url)
        self._enter_shop(page)
        self._dismiss_onboarding(page)

        try:
            return self._do_export(page, date_from, date_to)
        except AdapterError:
            self._screenshot_on_error(page, "export_failed")
            raise
        except Exception as exc:                         # noqa: BLE001
            self._screenshot_on_error(page, "export_failed")
            raise AdapterError(
                ErrorType.PARSE_ERROR,
                f"ทำตามขั้นตอน Export ไม่สำเร็จ ({type(exc).__name__}: {exc}) "
                f"— ดูภาพหน้าจอใน logs/screenshots/",
            ) from exc

    def _current_shop_name(self, page) -> str | None:
        """ชื่อร้านที่กำลังเปิดอยู่ (มุมขวาบนของ Seller Centre)"""
        for sel in (".shop-name", "[class*='shop-name']", "[class*='account-name']"):
            try:
                loc = page.locator(sel).first
                if loc.count():
                    txt = (loc.inner_text(timeout=2500) or "").strip()
                    if txt:
                        return txt.split("\n")[0].strip()
            except Exception:                            # noqa: BLE001
                continue

        # ⚠️ ทางถอย: อ่านจากแถบหัวเว็บตรง ๆ
        #    หน้าภาษาอังกฤษใช้ class คนละชุด ตัวเลือกด้านบนจึงหาไม่เจอ
        #    แล้วโค้ดจะเข้าใจผิดว่า "อยู่ผิดร้าน" → บังคับไปหน้าเลือกร้าน
        #    ซึ่ง Shopee เด้งกลับเพราะเลือกร้านไว้แล้ว → ตารางว่าง → รายงานผิดว่าไม่มีร้าน
        #    (เจอจริง 2026-08-07 กับ toolspartner ที่หน้าเป็นอังกฤษ)
        try:
            head = page.locator(".shopee-header-bar, header, [class*='header-bar']").first
            if head.count():
                txt = (head.inner_text(timeout=2500) or "")
                want = (self.shop.web_name or "").strip().lower()
                for line in (x.strip() for x in txt.split("\n") if x.strip()):
                    if want and line.lower() == want:
                        return line
        except Exception:                                # noqa: BLE001
            pass
        return None

    def _enter_shop(self, page) -> None:
        """เลือกร้านให้ตรงกับ web_shop_name — กด "รายละเอียด" ในแถวของร้านนั้น

        กดที่ชื่อร้านตรง ๆ ไม่ทำงาน — ไม่ใช่ลิงก์ ปุ่มเดียวในแถวคือ "รายละเอียด"

        ⚠️ อันตรายที่ต้องกันให้ได้: โปรไฟล์ "จำร้านที่เลือกไว้ล่าสุด"
           ร้านถัดไปที่ใช้บัญชีเดียวกันจะเข้าหน้าคำสั่งซื้อได้เลยโดยไม่เจอหน้าเลือกร้าน
           = ดึงข้อมูลของร้านก่อนหน้ามาใส่ป้ายชื่อร้านนี้ โดยไม่มีอะไรเตือน
           จึงต้องเช็คชื่อร้านที่เปิดอยู่ทุกครั้ง ถ้าไม่ตรงให้บังคับกลับไปหน้าเลือกร้าน
        """
        want = self.shop.web_name

        # เด้งไปหน้า login = ยังไม่ได้ล็อกอิน ปล่อยให้ _ensure_logged_in รายงาน AUTH_EXPIRED
        # ถ้าไม่กันตรงนี้ ตัวกัน "อยู่ผิดร้าน" จะรายงานเป็น PARSE_ERROR ซึ่งชวนไขว้เขว
        if any(k in page.url.lower() for k in ("login", "signin")):
            return

        if "/portal/shop" not in page.url:
            # ⚠️ เช็คเฉพาะร้านที่ประกาศ profile_key = ใช้บัญชีร่วมกับร้านอื่น
            #    บัญชีที่มีร้านเดียวจะเข้าหน้าคำสั่งซื้อตรง ๆ ไม่มีหน้าเลือกร้านให้กลับไป
            #    เคยเช็คทุกร้านแล้วทำให้ shopee_05/06 ที่เคยดึงได้พังไปด้วย
            if not self.shop.profile_key:
                return

            current = self._current_shop_name(page)
            if current and current.lower() == want.lower():
                return                                   # อยู่ถูกร้านแล้ว
            log.info("shopee_wrong_shop_open", shop_id=self.shop.shop_id,
                     current=current, want=want)

            # ⚠️ ต้องไป /portal/shop "เปล่า ๆ" ห้ามใส่ ?next=
            #    ถ้าใส่ next= Shopee เห็นว่ามีร้านเปิดอยู่แล้วจะข้ามหน้าเลือกร้าน
            #    พาไปที่ next ทันที = สลับร้านไม่ได้เลย ติดที่ร้านเดิมตลอด
            #    (เจอจริง 2026-08-05 กับ shopee_08 — diag ยืนยันว่าตัดออกแล้วเข้าได้)
            #    ตัวเลือกสำรองยังคง ?next= ไว้เผื่อ Shopee เปลี่ยนพฤติกรรมอีก
            # ⚠️ ต้องเช็คว่า "มีตารางร้านจริง" ไม่ใช่แค่ URL ถูก
            #    /portal/shop แบบไม่มีพารามิเตอร์บางครั้งเรนเดอร์ว่างเปล่า (tr=0)
            #    ของเดิมหยุดที่ URL แรกเพราะ URL ตรง แล้วไปเจอตารางว่าง
            #    รายงานผิดว่า "บัญชีนี้ไม่มีร้านชื่อ ..." (เจอจริง 2026-08-07)
            for url in (f"{self.base_url}/portal/shop?next=%2Fportal%2Fsale%2Forder",
                        f"{self.base_url}/portal/shop"):
                page.goto(url, wait_until="domcontentloaded")
                for _ in range(6):
                    page.wait_for_timeout(2500)
                    if page.locator("tr").count() > 1:
                        break
                if "/portal/shop" in page.url and page.locator("tr").count() > 1:
                    break
            if "/portal/shop" not in page.url:
                # ⚠️ Shopee เด้งออกจากหน้าเลือกร้าน = มีร้านเปิดอยู่แล้ว
                #    ถ้าชื่อบนหน้าตรงกับที่ต้องการ ถือว่าอยู่ถูกร้าน ไม่ต้องบังคับต่อ
                #    (ไม่งั้นจะพังทั้งที่อยู่ถูกร้าน — เจอจริง 2026-08-07)
                again = self._current_shop_name(page)
                if again and again.lower() == want.lower():
                    log.info("shopee_already_on_wanted_shop",
                             shop_id=self.shop.shop_id, shop=again)
                    return
                raise AdapterError(
                    ErrorType.PARSE_ERROR,
                    f"บังคับกลับไปหน้าเลือกร้านไม่ได้ (อยู่ที่ {page.url[:80]}) "
                    f"— เสี่ยงดึงข้อมูลผิดร้าน จึงหยุดไว้ก่อน",
                )
        # ⚠️ ตารางร้านเรนเดอร์ช้ากว่า domcontentloaded — ถ้าไม่รอจะได้ [] แล้วรายงาน
        #    ผิดว่า "บัญชีนี้ไม่มีร้านชื่อ ..." ทั้งที่มีอยู่ (เจอจริง 2026-08-07)
        for _ in range(6):
            if page.locator("tr").count() > 1:
                break
            page.wait_for_timeout(2500)

        row = page.locator(f'tr:has-text("{want}")').first
        if row.count() == 0:
            names = []
            for tr in page.locator("tr").all()[1:]:
                try:
                    names.append(tr.locator("td").nth(0).inner_text().strip().replace("\n", " "))
                except Exception:                        # noqa: BLE001
                    continue
            raise AdapterError(
                ErrorType.NO_PERMISSION,
                f"บัญชีนี้ไม่มีร้านชื่อ {want!r} — ที่มีคือ {names} "
                f"(แก้ web_shop_name ใน shops.yaml ให้ตรงกับชื่อบนเว็บ)",
            )

        # ⚠️ ปุ่มในแถวเป็น "รายละเอียด" (ไทย) หรือ "Details" (อังกฤษ) แล้วแต่ภาษาของร้าน
        #    ถ้าใส่แต่ไทย ร้านที่ตั้งอังกฤษจะค้างรอ 60 วินาทีแล้วโยน Timeout
        #    (เจอจริง 2026-08-07 กับบัญชี tnltools ที่หน้าเป็น "Choose a Shop to Manage")
        for sel in ('button:has-text("รายละเอียด")', 'button:has-text("Details")'):
            btn = row.locator(sel).first
            if btn.count():
                btn.click()
                break
        else:
            raise AdapterError(
                ErrorType.PARSE_ERROR,
                f'เจอแถวของร้าน {want!r} แล้วแต่ไม่มีปุ่ม "รายละเอียด"/"Details"',
            )
        page.wait_for_timeout(8000)
        log.info("shopee_shop_selected", shop_id=self.shop.shop_id, web_name=want)

        page.goto(self.orders_url, wait_until="domcontentloaded")
        page.wait_for_timeout(9000)

    def _dismiss_onboarding(self, page) -> None:
        """ปิดทัวร์แนะนำฟีเจอร์ — div.onboarding-masked ดักคลิกไว้ทั้งหน้า"""
        for _ in range(6):
            if page.locator(SEL["onboarding"][0]).count() == 0:
                return
            closed = False
            for label in ONBOARD_CLOSE:
                try:
                    page.locator(f'button:has-text("{label}")').first.click(timeout=2000)
                    page.wait_for_timeout(1200)
                    closed = True
                    break
                except Exception:                        # noqa: BLE001
                    continue
            if not closed:
                # ปิดด้วยปุ่มไม่ได้ก็เอา overlay ออกไปเลย — เป็นแค่ชั้นบังคลิก ไม่ใช่ข้อมูล
                page.evaluate(
                    "() => document.querySelectorAll('.onboarding-masked').forEach(e => e.remove())"
                )
                page.wait_for_timeout(800)
                log.info("onboarding_removed", shop_id=self.shop.shop_id)
                return

    def auto_relogin(self, page) -> bool:
        """ต่ออายุ session เองโดยกดปุ่มบนฟอร์มที่ Chrome เติมรหัสไว้แล้ว

        ⚠️ ระบบไม่เก็บ ไม่อ่าน ไม่พิมพ์รหัสผ่าน — Chrome ในโปรไฟล์ร้านนี้เป็นคนเติม
           (จากตอนที่คนล็อกอินด้วยมือครั้งแรกแล้วให้ Chrome จำไว้)
           โค้ดทำแค่ 2 อย่าง: เช็คว่าช่องรหัสมีค่าไหม (ดูความยาว ไม่ดูค่า) แล้วกดปุ่ม

        เจอ CAPTCHA / OTP เมื่อไหร่ = หยุดทันที ไม่พยายามผ่าน (กฎเหล็กข้อ 5)

        ทำไมต้องมี: บัญชี tnltools ถูกเตะ session ทุกวัน (มีคนอื่นล็อกอินพร้อมกัน)
        ถ้าไม่ต่ออายุเอง shopee_03/shopee_08 จะพังทุกเช้าและต้องให้คนมาล็อกอินมือ
        แบบเดียวกับที่ Lazada ทำมาแล้วและได้ผลจริง
        """
        page.goto(f"{self.base_url}{self.login_path}", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)

        # ⚠️ ถ้าถูกเด้งออกจากหน้า login = ยังล็อกอินอยู่ ไม่ต้องทำอะไรต่อ
        #    ของเดิมไล่หาช่องรหัสผ่านซึ่งไม่มีในหน้าหลัก แล้วคืน False
        #    ทำให้รายงานว่า "ต่ออายุไม่ได้" ทั้งที่เข้าหลังบ้านได้อยู่ (เจอ 2026-08-07)
        if not any(h in page.url.lower() for h in ("login", "signin")):
            log.info("relogin_already_logged_in", shop_id=self.shop.shop_id,
                     url=page.url[:70])
            return True

        # ── ทางหลัก: เข้าผ่าน "บัญชีหลัก/บัญชีย่อย" ที่ Shopee จำไว้ ────────
        # ⚠️ วิธีนี้ไม่ต้องใช้รหัสผ่านเลย — Shopee เก็บบัญชีไว้ใน account chooser
        #    (เจ้าของงานบันทึกวิดีโอวิธีทำไว้ให้ 2026-08-07 085618)
        #    ขั้นตอน: กด "เข้าสู่ระบบด้วยบัญชีหลัก/บัญชีย่อย" → หน้า "เลือกบัญชีผู้ใช้"
        #             → กดชื่อบัญชี → เข้าหลังบ้านได้เลย
        #    ทางนี้ต้องลองก่อนการเติมรหัสผ่านเสมอ เพราะได้ผลแม้ Chrome ไม่ได้จำรหัส
        if self._relogin_via_account_chooser(page):
            return True

        # ── ทางสำรอง: ฟอร์มที่ Chrome เติมรหัสไว้ ────────────────────────
        # Chrome เติมรหัสช้ากว่า domcontentloaded — ต้อง poll ไม่ใช่รอเวลาตายตัว
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

        # ปุ่มมี <span> ซ้อนข้างใน — ใช้ get_by_role ที่ดู accessible name ถึงจะกดติด
        clicked = False
        for name in ("เข้าสู่ระบบ", "Log In", "Login", "Sign in"):
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
                        return False                     # OTP/CAPTCHA ต้องให้คนทำเอง
                except Exception:                        # noqa: BLE001
                    continue
            if not any(h in page.url.lower() for h in ("login", "signin")):
                log.info("relogin_ok", shop_id=self.shop.shop_id, url=page.url[:70])
                return True
        return False

    def _relogin_via_account_chooser(self, page) -> bool:
        """เข้าระบบผ่านบัญชีที่ Shopee จำไว้ — ไม่ต้องใช้รหัสผ่าน

        ที่มา: เจ้าของงานบันทึกวิดีโอวิธีทำไว้ให้ (2026-08-07)
        หน้า login มีปุ่มล่างสุด "เข้าสู่ระบบด้วยบัญชีหลัก/บัญชีย่อย"
        กดแล้วไปหน้า account chooser ที่มีชื่อบัญชีรออยู่ กดชื่อก็เข้าได้เลย

        ⚠️ ต้องไม่ไปกด "เข้าสู่ระบบด้วยบัญชีอื่น" ซึ่งอยู่ในกล่องเดียวกัน
           อันนั้นพาไปกรอกรหัสใหม่ ซึ่งเราทำไม่ได้
        """
        # ⚠️ ต้องเข้า accounts.shopee.co.th โดยตรง — ถ้าไปที่ base_url/account/signin
        #    Shopee จะเด้งไป shopee.co.th/seller/login ซึ่งเป็นคนละหน้าและ
        #    **ไม่มี** ปุ่มบัญชีหลัก/บัญชีย่อย (ยืนยันจาก DOM จริง 2026-08-07)
        #    URL นี้ตรงกับที่เจ้าของงานใช้ในวิดีโอ
        from urllib.parse import quote
        page.goto(f"https://accounts.shopee.co.th/seller/login?next={quote(self.orders_url, safe='')}",
                  wait_until="domcontentloaded")
        page.wait_for_timeout(6000)
        if not any(h in page.url.lower() for h in ("login", "signin")):
            log.info("relogin_already_logged_in", shop_id=self.shop.shop_id)
            return True

        for sel in ('text=/เข้าสู่ระบบด้วยบัญชีหลัก/',
                    'text=/บัญชีหลัก/',
                    'text=/บัญชีย่อย/',
                    'text=/Main Account.*Sub.?Account/i'):
            try:
                loc = page.locator(sel).first
                if loc.count() == 0:
                    continue
                loc.click(timeout=6000)
                break
            except Exception:                            # noqa: BLE001
                continue
        else:
            log.info("relogin_no_account_chooser_link", shop_id=self.shop.shop_id)
            return False

        page.wait_for_timeout(5000)
        if "accountchooser" not in page.url.lower() and "signin/oauth" not in page.url.lower():
            log.info("relogin_chooser_not_reached", shop_id=self.shop.shop_id,
                     url=page.url[:70])
            return False

        # กดชื่อบัญชีในกล่อง — ถ้ารู้ชื่อบัญชีจาก .env ให้เล็งตัวนั้นก่อน
        want = (self.shop.account or "").strip()
        picked = False
        if want:
            try:
                row = page.locator(f'text="{want}"').first
                if row.count():
                    row.click(timeout=5000)
                    picked = True
            except Exception:                            # noqa: BLE001
                pass
        if not picked:
            # ชื่อบัญชีของ Shopee อยู่ในรูป "user:sub" — เล็งด้วยรูปแบบนั้น
            # เลี่ยงปุ่ม "เข้าสู่ระบบด้วยบัญชีอื่น" ที่อยู่กล่องเดียวกัน
            try:
                row = page.locator('a:has-text(":"), [class*="account"] a, li a').first
                if row.count() == 0:
                    row = page.get_by_text(re.compile(r"^[\w.\-]+:[\w.\-]+$")).first
                row.click(timeout=6000)
                picked = True
            except Exception as exc:                     # noqa: BLE001
                log.info("relogin_pick_account_failed", shop_id=self.shop.shop_id,
                         err=str(exc)[:60])
                return False

        for _ in range(12):
            page.wait_for_timeout(1500)
            for sel in SEL["challenge"]:
                try:
                    if page.locator(sel).first.is_visible(timeout=600):
                        self._screenshot_on_error(page, "relogin_challenge")
                        log.warning("relogin_challenge", shop_id=self.shop.shop_id)
                        return False
                except Exception:                        # noqa: BLE001
                    continue
            if not any(h in page.url.lower() for h in ("login", "signin", "accountchooser")):
                log.info("relogin_via_chooser_ok", shop_id=self.shop.shop_id,
                         url=page.url[:70])
                return True
        return False

    def _clear_overlay_over(self, page, sel: str) -> str:
        """ซ่อนสิ่งที่ลอยทับปุ่มอยู่ คืนผลลัพธ์ไว้ log

        ⚠️ Shopee เด้งป๊อปอัปโฆษณามุมขวาบนเป็นครั้งคราว ("เพิ่ม Discovery ROI...")
           ทับปุ่ม "ดาวน์โหลด" พอดีเป๊ะ Playwright จึงคลิกไม่ได้เพราะปุ่มไม่รับ
           pointer event แล้วรายงานว่า "หาปุ่มไม่เจอ" ทั้งที่ปุ่มอยู่ตรงนั้น
           (เจอจริง 2026-08-05 กับ shopee_01 และ shopee_05 — diag ยืนยันว่า
            ปุ่ม visible=True enabled=True ตำแหน่ง x=912 y=94 แต่คลิกไม่ผ่าน)

           ปิดด้วยปุ่มกากบาทไม่ได้เพราะ class ของป๊อปอัปไม่แน่นอนและขึ้นแบบสุ่ม
           จึงใช้ elementFromPoint ถามตรง ๆ ว่าตอนนี้ "อะไรอยู่บนสุด" ตรงกลางปุ่ม
           ถ้าไม่ใช่ปุ่มเอง = มีของทับ ให้ซ่อนตัวนั้นทิ้ง
        """
        js = """
        (sel) => {
          const btn = document.querySelector(sel);
          if (!btn) return 'no-button';
          const r = btn.getBoundingClientRect();
          const top = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
          if (!top || btn.contains(top) || top.contains(btn)) return 'clear';
          let el = top;
          for (let i = 0; i < 6 && el && el !== document.body; i++) {
            const cs = getComputedStyle(el);
            if (cs.position === 'fixed' || cs.position === 'absolute') {
              el.style.display = 'none';
              return 'hidden:' + (el.className || '').toString().slice(0, 60);
            }
            el = el.parentElement;
          }
          top.style.display = 'none';
          return 'hidden-fallback';
        }
        """
        try:
            res = str(page.evaluate(js, sel))
        except Exception:                                # noqa: BLE001
            return "eval-failed"
        if res.startswith("hidden"):
            log.info("shopee_overlay_cleared", shop_id=self.shop.shop_id, detail=res[:80])
            page.wait_for_timeout(600)
        return res

    def _do_export(self, page, date_from: date, date_to: date) -> Path:
        before = self._report_names(page)

        self._clear_overlay_over(page, SEL["open_modal"][0])
        if not _click_first(page, SEL["open_modal"], 15000):
            # คลิกไม่ผ่านมัก = มีของลอยทับ ไม่ใช่ปุ่มหาย — เคลียร์แล้วลองอีกครั้ง
            self._dismiss_onboarding(page)
            state = self._clear_overlay_over(page, SEL["open_modal"][0])
            if not _click_first(page, SEL["open_modal"], 10000):
                self._screenshot_on_error(page, "open_modal_blocked")
                raise AdapterError(
                    ErrorType.PARSE_ERROR,
                    f'กดปุ่ม "ดาวน์โหลด" (เปิดกล่อง) ไม่ได้ — สถานะสิ่งที่ทับ: {state} '
                    f"— ดูภาพหน้าจอใน logs/screenshots/",
                )
        page.wait_for_timeout(3000)

        self._set_range(page, date_from, date_to)

        if not _click_first(page, SEL["confirm"], 10000):
            raise AdapterError(ErrorType.PARSE_ERROR, 'กดปุ่มยืนยัน "ดาวน์โหลด" ในกล่องไม่ได้')
        page.wait_for_timeout(4000)

        # ช่วงยาวใช้เวลาปั่นไฟล์นานกว่ามาก — ให้ผู้เรียกยืดเวลารอได้
        # (2026-08-10: ขอช่วง 9 วัน ไฟล์โผล่ในประวัติแล้วแต่ยังปั่นไม่เสร็จใน 300 วินาที)
        label = self._wait_for_report(page, before, date_from, date_to,
                                      timeout_sec=self.report_timeout_sec)
        log.info("shopee_report_ready", shop_id=self.shop.shop_id, file=label)

        btn = self._row_download_button(page, label)
        return self._capture_download(page, btn.click, timeout_ms=120_000)

    def _set_range(self, page, date_from: date, date_to: date) -> None:
        """ตั้งช่วงวันที่ในกล่อง — ช่องแสดงเป็น 'YYYY/MM/DD – YYYY/MM/DD'"""
        field = None
        for sel in SEL["range_input"]:
            loc = page.locator(sel).first
            try:
                loc.wait_for(state="visible", timeout=5000)
                field = loc
                break
            except Exception:                            # noqa: BLE001
                continue
        if field is None:
            raise AdapterError(ErrorType.PARSE_ERROR, "หาช่องช่วงเวลาในกล่องดาวน์โหลดไม่เจอ")

        field.click()
        page.wait_for_timeout(2000)

        for target in (date_from, date_to):
            self._click_day(page, target)
        page.wait_for_timeout(2000)
        log.info("shopee_range_set", shop_id=self.shop.shop_id,
                 date_from=date_from.isoformat(), date_to=date_to.isoformat())

    TH_MONTHS = ("มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
                 "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม")
    # ⚠️ ร้านที่ตั้งหลังบ้านเป็นอังกฤษ หัวปฏิทินจะขึ้น "August 2026" ไม่ใช่ "สิงหาคม2026"
    #    ถ้าเทียบแต่ไทยจะหาเดือนไม่เจอแล้วเลื่อนปฏิทินไม่ได้เลย
    #    (เจอจริง 2026-08-07 กับ shopee_03/shopee_08 บัญชี tnltools)
    EN_MONTHS = ("January", "February", "March", "April", "May", "June",
                 "July", "August", "September", "October", "November", "December")

    def _panel_for(self, page, target: date):
        """คืนแผงเดือน (ซ้าย/ขวา) ที่กำลังแสดงเดือนของ target — ไม่เจอคืน None

        ปฏิทินโชว์ 2 เดือนคู่กัน หัวแต่ละแผงเป็น 2 span: ชื่อเดือน + ปี ค.ศ.
        รองรับทั้งไทยและอังกฤษ และรองรับทั้งชื่อเต็ม/ชื่อย่อ (Aug / August)
        """
        y = str(target.year)
        th, en = self.TH_MONTHS[target.month - 1], self.EN_MONTHS[target.month - 1]
        for side in ("left", "right"):
            panel = page.locator(f".eds-daterange-picker-panel__body-{side}").first
            if panel.count() == 0:
                continue
            try:
                labels = panel.locator(SEL["month_label"][0]).all_inner_texts()
            except Exception:                            # noqa: BLE001
                continue
            # ตัดช่องว่างทิ้งทั้งหมดก่อนเทียบ — อังกฤษมีเว้นวรรคระหว่างเดือนกับปี
            got = "".join(x.strip() for x in labels[:2]).replace(" ", "")
            if not got or y not in got:
                continue
            head = got.replace(y, "")
            if head == th or head.lower() in (en.lower(), en[:3].lower()):
                return panel
        return None

    def _header_text(self, page) -> str:
        """ข้อความหัวปฏิทินแผงซ้าย เช่น 'July2026' — ใช้ดูว่าเลื่อนไปถึงไหนแล้ว"""
        try:
            panel = page.locator(".eds-daterange-picker-panel__body-left").first
            if panel.count() == 0:
                return ""
            labels = panel.locator(SEL["month_label"][0]).all_inner_texts()
            return "".join(x.strip() for x in labels[:2]).replace(" ", "")
        except Exception:                                # noqa: BLE001
            return ""

    def _panel_month(self, page) -> tuple[int, int] | None:
        """เดือน/ปีที่แผงซ้ายกำลังแสดง เช่น (2026, 7) — อ่านไม่ได้คืน None"""
        text = self._header_text(page)
        if not text:
            return None
        year = "".join(c for c in text if c.isdigit())
        word = "".join(c for c in text if not c.isdigit()).strip()
        if not year or not word:
            return None
        for i, name in enumerate(self.TH_MONTHS, 1):
            if word.startswith(name):
                return int(year), i
        low = word.lower()
        for i, name in enumerate(self.EN_MONTHS, 1):
            if low.startswith(name.lower()) or low.startswith(name[:3].lower()):
                return int(year), i
        return None

    def _step_one_month(self, page, forward: bool) -> bool:
        """เลื่อนปฏิทิน 1 เดือน ไปข้างหน้าหรือถอยหลัง — คืน False ถ้าไปต่อไม่ได้

        ⚠️ ต้องเลื่อนไปข้างหน้าได้ด้วย ไม่ใช่ถอยอย่างเดียว
           ช่วงข้ามเดือน (เช่น 1 ม.ค. – 31 ก.ค.) พอเลือกวันเริ่มเสร็จ ปฏิทินจะอยู่ที่ ม.ค.
           แล้ววันจบอยู่ ก.ค. ซึ่งต้องเดินหน้า 6 เดือน
           ของเดิมถอยได้ทางเดียว จึงเดินถอยจนสุดแล้วรายงานว่าหาเดือนไม่เจอ
           (เจอจริง 2026-08-13: ขอ 1 ม.ค.–31 ก.ค. แล้วปฏิทินไปจบที่ July2023)
           ดึงทีละเดือนไม่เคยเจอ เพราะวันเริ่มกับวันจบอยู่เดือนเดียวกัน
        """
        sel = ".eds-picker-header__next" if forward else SEL["prev_month"][0]
        undo = SEL["prev_month"][0] if forward else ".eds-picker-header__next"
        return self._step_with_arrows(page, sel, undo)

    def _step_back_one_month(self, page) -> bool:
        """ถอยปฏิทิน 1 เดือน — คืน False ถ้าถอยต่อไม่ได้แล้ว

        ⚠️ ทำไมต้องมีตัวนี้ แทนที่จะกด .eds-picker-header__prev เฉย ๆ
           ในหัวปฏิทินมีลูกศรถอยหลัง 2 ปุ่มที่ใช้ class เดียวกันเป๊ะ:
               ปุ่มที่ 1  ลูกศรคู่   = ถอย "ปี"
               ปุ่มที่ 2  ลูกศรเดี่ยว = ถอย "เดือน"
           ของเดิมใช้ _click_first ซึ่งกดตัวแรกเสมอ = ถอยทีละปี
           จาก July 2026 จะไป July 2025 → July 2024 กด 24 ครั้งก็ไม่มีวันถึง Jan 2026
           แล้วรายงานว่า "เลื่อนปฏิทินไปหาเดือนไม่ได้" ทั้งที่ปฏิทินใช้งานได้ปกติ
           (เจอจริง 2026-08-13 กับ shopee_10 ซึ่งหลังบ้านตั้งเป็นภาษาอังกฤษ)

           ไม่ hardcode ว่า "กดปุ่มที่ 2" เพราะร้านอื่นอีก 9 ร้านใช้ทางนี้แล้วผ่าน
           หน้าตาอาจไม่เหมือนกันทุกร้าน จึงกดแล้ววัดผลจริงจากหัวปฏิทิน
           ถ้าเลื่อนผิดทาง (ปีเปลี่ยนแทนเดือน) ให้ถอยคืนแล้วเปลี่ยนไปกดอีกปุ่ม
        """
        return self._step_with_arrows(page, SEL["prev_month"][0],
                                      ".eds-picker-header__next")

    def _step_with_arrows(self, page, sel: str, undo_sel: str) -> bool:
        """กดลูกศรแล้ววัดผลจริง — ถ้าโดนปุ่ม 'ปี' ให้ถอยคืนแล้วลองปุ่มถัดไป"""
        arrows = page.locator(sel)
        n = arrows.count()
        if n == 0:
            return False

        # ปุ่มเดือนอยู่ถัดจากปุ่มปีเสมอ จึงลอง nth(1) ก่อน แล้วค่อยถอยไป nth(0)
        for idx in ([1, 0] if n >= 2 else [0]):
            before = self._header_text(page)
            try:
                arrows.nth(idx).click(timeout=4000)
            except Exception:                            # noqa: BLE001
                continue
            page.wait_for_timeout(700)
            after = self._header_text(page)
            if not after or after == before:
                continue

            # ปีเปลี่ยนแต่ชื่อเดือนเท่าเดิม = กดโดนปุ่มปี ไม่ใช่ปุ่มเดือน
            b_digits = "".join(c for c in before if c.isdigit())
            a_digits = "".join(c for c in after if c.isdigit())
            b_word = "".join(c for c in before if not c.isdigit())
            a_word = "".join(c for c in after if not c.isdigit())
            if b_word == a_word and b_digits != a_digits:
                log.info("shopee_arrow_was_year", shop_id=self.shop.shop_id,
                         before=before, after=after, arrow_index=idx, sel=sel)
                undo = page.locator(undo_sel)
                if undo.count() > idx:
                    try:
                        undo.nth(idx).click(timeout=4000)
                        page.wait_for_timeout(700)
                    except Exception:                    # noqa: BLE001
                        pass
                continue
            return True
        return False

    def _click_day(self, page, target: date) -> None:
        """คลิกวันในปฏิทิน — เลื่อนเดือนจนกว่าจะเห็นเดือนที่ต้องการ แล้วกดเลขวัน

        ช่องวันเป็น span.eds-date-table__cell-inner ไม่มี attribute วันที่ให้เล็ง
        จึงต้องมั่นใจก่อนว่ากำลังดูเดือนถูก แล้วค่อยกดเลขวันในแผงนั้น
        """
        want_iso = target.isoformat()

        panel = None
        for _ in range(36):                              # เลื่อนได้ ~3 ปี ทั้งสองทาง
            panel = self._panel_for(page, target)
            if panel is not None:
                break
            # เดินไปทางที่ใกล้เป้าหมาย ไม่ใช่ถอยหลังอย่างเดียว
            cur = self._panel_month(page)
            forward = bool(cur and (target.year, target.month) > cur)
            if not self._step_one_month(page, forward):
                break

        if panel is None:
            raise AdapterError(
                ErrorType.PARSE_ERROR,
                f"เลื่อนปฏิทินไปหาเดือนของ {want_iso} ไม่ได้ "
                f"(หัวปฏิทินตอนนี้: {self._header_text(page)!r})",
            )

        # ⚠️ ปฏิทินไม่ใช่ <table> — ไม่มี td เลย ช่องวันเป็น span.eds-date-table__cell-inner
        #    และเลขวันซ้ำได้ (วันของเดือนก่อน/ถัดไปที่ล้นมาในตาราง)
        #    จึงต้องดู class ของ element แม่ว่าเป็นวันของเดือนนี้จริงไหม
        day = str(target.day)
        skip = ("prev", "next", "other", "disabled")
        seen: list[str] = []

        for e in panel.locator("span.eds-date-table__cell-inner").all():
            try:
                if (e.inner_text() or "").strip() != day:
                    continue
                parent_cls = e.evaluate("el => el.parentElement.className || ''")
                seen.append(parent_cls)
                if any(k in parent_cls.lower() for k in skip):
                    continue
                e.click()
                page.wait_for_timeout(900)
                log.info("shopee_day_picked", shop_id=self.shop.shop_id,
                         date=want_iso, cell_class=parent_cls[:60])
                return
            except Exception:                            # noqa: BLE001
                continue

        raise AdapterError(
            ErrorType.PARSE_ERROR,
            f"เจอเดือนของ {want_iso} แล้วแต่กดวันที่ {day} ไม่ได้ "
            f"(class ของช่องที่เจอ: {seen}) — ดูภาพใน logs/screenshots/",
        )

    # ── ประวัติการดาวน์โหลด ─────────────────────────────────

    def _report_names(self, page) -> set[str]:
        """ชื่อไฟล์ในประวัติการดาวน์โหลด — เอาเฉพาะที่เป็นชื่อไฟล์จริง ๆ

        ⚠️ `text=/regex/` ของ Playwright แมตช์ทุก element ที่ "มีข้อความนั้นอยู่ข้างใน"
           จึงติดกล่องใหญ่ที่ครอบทั้งหน้ามาด้วย — ข้อความยาวเป็นหมื่นตัวอักษร
           และมีครบทุกเดือนอยู่ในก้อนเดียว
           ผลคือ `next(n for n in names if want in n)` ซึ่งวนบน set (ไม่มีลำดับ)
           มีโอกาสหยิบก้อนใหญ่นั้นมาเป็น "ชื่อไฟล์" แล้วหาปุ่มดาวน์โหลดของแถวไม่เจอ
           ระบบจะรายงานว่า "Shopee ยังปั่นไฟล์ไม่เสร็จ" ทั้งที่ปุ่มพร้อมกดอยู่แล้ว
           (เจอจริง 2026-08-07 กับ shopee_08 — ค้างครบทั้ง 7 เดือน)
        """
        try:
            raw = page.locator(SEL["report_rows"][0]).all_inner_texts()
        except Exception:                                # noqa: BLE001
            return set()
        return {t.strip() for t in raw if REPORT_NAME_RE.fullmatch(t.strip())}

    def _wait_for_report(self, page, before: set[str], date_from: date, date_to: date,
                         timeout_sec: int = 300) -> str:
        """รอจนไฟล์ของรอบนี้พร้อมดาวน์โหลด (สปินเนอร์ -> ปุ่มดาวน์โหลด)

        ⚠️ ชื่อไฟล์ Shopee มีแค่ช่วงวันที่ ไม่มีเวลา — ต่างจาก TikTok
           ดึงช่วงเดิมซ้ำจะได้ชื่อเดิมเป๊ะ เทียบแบบ "มีชื่อใหม่โผล่ไหม" จึงรอเก้อตลอด
           (เจอจริงตอนรันซ้ำช่วง 20260803_20260803 ที่เคยดึงไปแล้ว)

        จึงดู "แถวบนสุด" แทน — Shopee เรียงใหม่สุดไว้บน
        ถ้าแถวบนสุดตรงกับช่วงที่ขอ และกดดาวน์โหลดได้ = ไฟล์ของรอบนี้พร้อมแล้ว
        """
        stamp = f"{date_from:%Y%m%d}_{date_to:%Y%m%d}"
        deadline = datetime.now() + timedelta(seconds=timeout_sec)
        last_seen = ""

        while datetime.now() < deadline:
            page.wait_for_timeout(5000)
            names = list(self._report_names(page))
            top = self._top_report_name(page) or (names[0] if names else "")
            if top != last_seen:
                log.info("shopee_report_top", shop_id=self.shop.shop_id, name=top[:70])
                last_seen = top

            if stamp in top and self._try_row_download_button(page, top) is not None:
                return top

        raise AdapterError(
            ErrorType.TIMEOUT,
            f"รอไฟล์ช่วง {stamp} ในประวัติการดาวน์โหลดเกิน {timeout_sec} วินาทีแล้วยังไม่เสร็จ "
            f"(แถวบนสุดตอนนี้: {last_seen[:70]!r})",
        )

    def _top_report_name(self, page) -> str | None:
        """ชื่อไฟล์แถวบนสุดของประวัติ = รายการล่าสุด

        กรองด้วย REPORT_NAME_RE ด้วยเหตุผลเดียวกับ _report_names —
        .first อาจเป็นกล่องใหญ่ที่ครอบทั้งหน้า ไม่ใช่ชื่อไฟล์
        """
        try:
            texts = page.locator(SEL["report_rows"][0]).all_inner_texts()
        except Exception:                                # noqa: BLE001
            return None
        for t in texts:
            t = t.strip()
            if REPORT_NAME_RE.fullmatch(t):
                return t
        return None

    def _try_row_download_button(self, page, label: str):
        """ปุ่มดาวน์โหลด "ของแถวนั้น" — ไต่ขึ้นจากชื่อไฟล์ทีละชั้น

        count == 1 คือตัวบอกว่าไต่มาถึงระดับแถวพอดี
        ไต่สูงเกินไปจะเจอปุ่มของทุกแถวรวมกัน (บทเรียนจาก TikTok)
        """
        node = page.locator(f'text="{label}"').first
        if node.count() == 0:
            return None
        for _ in range(6):
            node = node.locator("xpath=..")
            for sel in SEL["row_download"]:
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

    # ── แปลงเป็น schema กลาง ────────────────────────────────

    def normalize(self, raw: Any) -> list[Order]:
        if not self.map.fields:
            raise AdapterError(
                ErrorType.UNKNOWN,
                "config/column_maps/shopee.yaml ยังไม่มี fields — ต้องมีไฟล์ Export จริงก่อน",
            )

        rows = raw["rows"] if isinstance(raw, dict) else raw
        m = self.map
        orders: list[Order] = []

        for row in rows:
            order_id = m.to_text(m.get(row, "order_id"))
            if not order_id:
                continue

            status_raw = m.get(row, "status_raw")
            # ⚠️ ค่า "ผู้ซื้อได้รับสินค้าแล้ว โปรดทราบว่า..." ยาวกว่าคีย์ใน status_map
            #    map_status จับไม่ได้ ต้องตัดให้เหลือส่วนขึ้นต้นที่ตรงกับคีย์ก่อน
            status_key = status_raw
            if status_raw:
                for k in m._status_map:
                    if str(status_raw).startswith(k):
                        status_key = k
                        break

            notes = []
            province = m.get(row, "province")
            if province and str(province).startswith("จังหวัด"):
                notes.append('province ยังมีคำว่า "จังหวัด" นำหน้าตามไฟล์ต้นทาง')

            orders.append(Order(
                order_id=order_id,
                platform=self.shop.platform,
                shop_id=self.shop.shop_id,
                shop_name=self.shop.report_name,
                order_created_at=m.parse_dt(m.get(row, "order_created_at")),
                order_updated_at=m.parse_dt(m.get(row, "delivered_at"))
                                 or m.parse_dt(m.get(row, "shipped_at")),
                paid_at=m.parse_dt(m.get(row, "paid_at")),
                # ── เวลาแต่ละขั้น เดิมถูกยุบทิ้งใน order_updated_at ──
                promised_ship_at=m.parse_dt(m.get(row, "promised_ship_at")),
                shipped_at=m.parse_dt(m.get(row, "shipped_at")),
                delivered_at=m.parse_dt(m.get(row, "delivered_at")),
                completed_at=m.parse_dt(m.get(row, "completed_at")),
                cancelled_at=m.parse_dt(m.get(row, "cancelled_at")),
                settlement_date=m.parse_dt(m.get(row, "settlement_date")),
                status_raw=str(status_raw) if status_raw is not None else None,
                order_status=m.map_status(status_key),
                payment_method=m.get(row, "payment_method"),
                sku=m.to_text(m.get(row, "sku")),
                parent_sku=m.to_text(m.get(row, "parent_sku")),
                product_name=m.get(row, "product_name"),
                variation=m.get(row, "variation"),
                quantity=int(m.to_float(m.get(row, "quantity")) or 0) or None,
                returned_qty=m.to_float(m.get(row, "returned_qty")),
                item_price=m.to_float(m.get(row, "item_price")),
                deal_price=m.to_float(m.get(row, "deal_price")),
                # ยอดทั้งบรรทัดก่อนหักส่วนลด — ใช้เป็นน้ำหนักเฉลี่ยยอดออเดอร์ลงรายบรรทัด
                net_price=m.to_float(m.get(row, "net_price")),
                seller_discount=m.to_float(m.get(row, "seller_discount")),
                platform_discount=m.to_float(m.get(row, "platform_discount")),
                shipping_fee=m.to_float(m.get(row, "shipping_fee")),
                # ── ส่วนลดที่เหลือ เปิดใช้ 2026-08-13 ────────────
                # เก็บแยกช่องใครช่องมัน ห้ามบวกรวมเอง (ดูเหตุผลใน shopee.yaml)
                seller_voucher=m.to_float(m.get(row, "seller_voucher")),
                seller_coin_cashback=m.to_float(m.get(row, "seller_coin_cashback")),
                seller_bundle_discount=m.to_float(m.get(row, "seller_bundle_discount")),
                seller_tradein_bonus=m.to_float(m.get(row, "seller_tradein_bonus")),
                platform_voucher=m.to_float(m.get(row, "platform_voucher")),
                platform_bundle_discount=m.to_float(m.get(row, "platform_bundle_discount")),
                coin_discount=m.to_float(m.get(row, "coin_discount")),
                payment_discount=m.to_float(m.get(row, "payment_discount")),
                tradein_discount=m.to_float(m.get(row, "tradein_discount")),
                tradein_bonus=m.to_float(m.get(row, "tradein_bonus")),
                voucher_total=m.to_float(m.get(row, "voucher_total")),
                # ── ค่าธรรมเนียม เปิดใช้ 2026-08-11 ──────────────
                # เป็นค่าที่ Shopee หักจากผู้ขาย เก็บเป็นเลขบวกตามที่ไฟล์ให้มา
                commission_fee=m.to_float(m.get(row, "commission_fee")),
                transaction_fee=m.to_float(m.get(row, "transaction_fee")),
                service_fee=m.to_float(m.get(row, "service_fee")),
                installation_fee_buyer=m.to_float(m.get(row, "installation_fee_buyer")),
                installation_fee_actual=m.to_float(m.get(row, "installation_fee_actual")),
                estimated_shipping_fee=m.to_float(m.get(row, "estimated_shipping_fee")),
                return_shipping_fee=m.to_float(m.get(row, "return_shipping_fee")),
                shipping_carrier=m.get(row, "shipping_carrier"),
                shipping_method=m.get(row, "shipping_method"),
                tracking_no=m.to_text(m.get(row, "tracking_no")),
                # ทั้งคู่เป็นค่าระดับออเดอร์ ซ้ำทุกบรรทัด — ห้ามบวกข้ามบรรทัด
                item_paid_by_buyer=m.to_float(m.get(row, "item_paid_by_buyer")),
                total_amount=m.to_float(m.get(row, "total_amount")),
                buyer_username=m.get(row, "buyer_username"),
                province=province,               # Shopee ไม่ mask จังหวัด ใช้ได้เลย
                district=m.get(row, "district"),
                postcode=m.to_text(m.get(row, "postcode")),
                country=m.get(row, "country"),
                order_type=m.get(row, "order_type"),
                fulfilled_by_platform=m.to_text(m.get(row, "fulfilled_by_platform")),
                owned_by_platform=m.to_text(m.get(row, "owned_by_platform")),
                in_bundle_deal=m.to_text(m.get(row, "in_bundle_deal")),
                hot_listing=m.to_text(m.get(row, "hot_listing")),
                tax_invoice_requested=m.to_text(m.get(row, "tax_invoice_requested")),
                tax_invoice_type=m.get(row, "tax_invoice_type"),
                cancel_reason=m.get(row, "cancel_reason"),
                return_status=m.to_text(m.get(row, "return_status")),
                seller_note=m.get(row, "seller_note"),
                notes=" / ".join(notes),
                fetched_at=datetime.now(),
            ))
        return orders
