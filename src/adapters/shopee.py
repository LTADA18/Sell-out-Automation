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
    "confirm": ['.eds-modal__box button.eds-button--primary:has-text("ดาวน์โหลด")',
                'button.eds-button--primary:has-text("ดาวน์โหลด")'],
    # ⚠️ ช่องช่วงเวลาเป็น <div> ไม่ใช่ <input> — หา input จะไม่เจอ
    "range_input": [".eds-date-picker__input"],
    "picker_panel": [".eds-daterange-picker-panel"],
    "month_label": [".eds-picker-header__label"],
    "prev_month": [".eds-picker-header__prev"],
    "history_btn": ['button:has-text("ประวัติการดาวน์โหลด")'],
    # แถวในประวัติ ชื่อไฟล์ขึ้นต้นด้วย Order. เสมอ
    "report_rows": ['text=/Order\\.[\\w.]+\\.\\d{8}_\\d{8}\\.(xlsx|zip|csv)/'],
    "row_download": ['button.eds-button--primary:has-text("ดาวน์โหลด")',
                     'button:has-text("ดาวน์โหลด")'],
    "onboarding": ["div.onboarding-masked"],
}

ONBOARD_CLOSE = ("ตกลง", "ต่อไป", "ข้าม", "เข้าใจแล้ว", "Got it", "Next")


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

        self._enter_shop(page)
        self._ensure_logged_in(page, self.orders_url)
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

    def _enter_shop(self, page) -> None:
        """ถ้าโดนเด้งไปหน้าเลือกร้าน ให้กด "รายละเอียด" ของร้านที่ต้องการ

        กดที่ชื่อร้านตรง ๆ ไม่ทำงาน — ไม่ใช่ลิงก์ ปุ่มเดียวในแถวคือ "รายละเอียด"
        """
        if "/portal/shop" not in page.url:
            return

        want = self.shop.web_name
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

        row.locator('button:has-text("รายละเอียด")').first.click()
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

    def _do_export(self, page, date_from: date, date_to: date) -> Path:
        before = self._report_names(page)

        if not _click_first(page, SEL["open_modal"], 15000):
            raise AdapterError(ErrorType.PARSE_ERROR, 'หาปุ่ม "ดาวน์โหลด" (เปิดกล่อง) ไม่เจอ')
        page.wait_for_timeout(3000)

        self._set_range(page, date_from, date_to)

        if not _click_first(page, SEL["confirm"], 10000):
            raise AdapterError(ErrorType.PARSE_ERROR, 'กดปุ่มยืนยัน "ดาวน์โหลด" ในกล่องไม่ได้')
        page.wait_for_timeout(4000)

        label = self._wait_for_report(page, before, date_from, date_to)
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

    def _panel_for(self, page, target: date):
        """คืนแผงเดือน (ซ้าย/ขวา) ที่กำลังแสดงเดือนของ target — ไม่เจอคืน None

        ปฏิทินโชว์ 2 เดือนคู่กัน หัวแต่ละแผงเป็น 2 span: ชื่อเดือนไทย + ปี ค.ศ.
        """
        want = f"{self.TH_MONTHS[target.month - 1]}{target.year}"
        for side in ("left", "right"):
            panel = page.locator(f".eds-daterange-picker-panel__body-{side}").first
            if panel.count() == 0:
                continue
            try:
                labels = panel.locator(SEL["month_label"][0]).all_inner_texts()
            except Exception:                            # noqa: BLE001
                continue
            if "".join(x.strip() for x in labels[:2]) == want:
                return panel
        return None

    def _click_day(self, page, target: date) -> None:
        """คลิกวันในปฏิทิน — เลื่อนเดือนจนกว่าจะเห็นเดือนที่ต้องการ แล้วกดเลขวัน

        ช่องวันเป็น span.eds-date-table__cell-inner ไม่มี attribute วันที่ให้เล็ง
        จึงต้องมั่นใจก่อนว่ากำลังดูเดือนถูก แล้วค่อยกดเลขวันในแผงนั้น
        """
        want_iso = target.isoformat()

        panel = None
        for _ in range(24):                              # ย้อนหลังได้ ~2 ปี
            panel = self._panel_for(page, target)
            if panel is not None:
                break
            if not _click_first(page, SEL["prev_month"], 4000):
                break
            page.wait_for_timeout(700)

        if panel is None:
            raise AdapterError(
                ErrorType.PARSE_ERROR,
                f"เลื่อนปฏิทินไปหาเดือนของ {want_iso} ไม่ได้",
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
        try:
            return set(page.locator(SEL["report_rows"][0]).all_inner_texts())
        except Exception:                                # noqa: BLE001
            return set()

    def _wait_for_report(self, page, before: set[str], date_from: date, date_to: date,
                         timeout_sec: int = 300) -> str:
        """รอจนแถวใหม่ในประวัติสร้างเสร็จ (สปินเนอร์ -> ปุ่มดาวน์โหลด)

        ชื่อไฟล์มีช่วงวันที่ในตัว จึงยืนยันได้ว่าได้ไฟล์ของรอบนี้จริง
        ไม่ใช่ไฟล์เก่าที่ค้างอยู่ในประวัติ
        """
        stamp = f"{date_from:%Y%m%d}_{date_to:%Y%m%d}"
        deadline = datetime.now() + timedelta(seconds=timeout_sec)

        while datetime.now() < deadline:
            page.wait_for_timeout(5000)
            new = self._report_names(page) - before
            hit = [n for n in new if stamp in n] or sorted(new)
            if hit and self._try_row_download_button(page, hit[-1]) is not None:
                return hit[-1]

        raise AdapterError(
            ErrorType.TIMEOUT,
            f"รอไฟล์ช่วง {stamp} ในประวัติการดาวน์โหลดเกิน {timeout_sec} วินาทีแล้วยังไม่เสร็จ",
        )

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
                "ยังดึงข้อมูลไม่ได้ — config/column_maps/shopee.yaml ยังไม่มี fields\n"
                "ต้องได้ไฟล์ Export จริงมาอ่านหัวตารางก่อน แล้วค่อยเติม map\n"
                "ห้ามเดาชื่อคอลัมน์ เดาผิดจะได้ Excel ที่หน้าตาถูกแต่ตัวเลขผิด",
            )
        raise AdapterError(ErrorType.UNKNOWN, "normalize() ของ Shopee ยังไม่ได้เขียน")
