r"""ดึงรายงานโฆษณา Lazada (Sponsored Max) → ไฟล์ Excel

⛔ ข้อห้ามเดียวกับอีก 2 เจ้า — หน้านี้มีปุ่ม "เติมเงิน" อยู่มุมขวาบนติดกับ
   ยอดเงินคงเหลือ กดพลาดคือเงินจริงของร้าน
   โมดูลนี้แตะแค่ 2 อย่าง: ช่องวันที่ · ปุ่มดาวน์โหลด

สรุปความต่างของ 3 เจ้า (ยืนยันกับของจริง 2026-08-22) — อย่าเอาวิธีข้ามกัน
   Shopee : ตั้งช่วงผ่าน URL ได้ · มีคิว ต้องรอในแผงประวัติ  · CSV
   TikTok : ต้องพิมพ์ลงช่องวันที่ · ไม่มีคิว กดแล้วได้เลย    · Excel
   Lazada : ต้องพิมพ์ลงช่องวันที่ · ไม่มีคิว กดแล้วได้เลย    · Excel

⚠️ ไฟล์ที่ได้มีแค่ 4 คอลัมน์ (วันที่ / ค่าใช้จ่าย / ยอดรายได้ / คำสั่งซื้อ)
   ตัวเลข impression / คลิก / CVR มีอยู่บนหน้าจอแต่ไม่ไหลลงไฟล์
   ทดสอบแล้วว่าติ๊กตัวชี้วัดเพิ่มก็ไม่ช่วย และสลับแท็บก็ได้ไฟล์เดิม
   ถ้าอยากได้ครบต้องเขียนตัวอ่านตารางจากหน้าเว็บ ซึ่งยังไม่ได้ทำ
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml

from src.adapters.registry import build_adapter
from src.core.config import PROJECT_ROOT, load_config
from src.core.logging_setup import get_logger
from src.core.models import AdapterError, ErrorType

log = get_logger()

MAP_FILE = PROJECT_ROOT / "config" / "column_maps" / "lazada_ads.yaml"

# ช่องวันที่บนหน้ารายงาน — เป็น input คู่แบบเดียวกับ TikTok แต่คนละ component
DATE_INPUTS = "input[placeholder*='YYYY'], .next-date-picker input, input[type='text']"


class LazadaAdsFetcher:
    def __init__(self, shop_id: str) -> None:
        cfg = load_config()
        self.shop = cfg.shop(shop_id)
        if self.shop.platform != "lazada":
            raise ValueError(f"{shop_id} ไม่ใช่ร้าน Lazada")
        self.adapter = build_adapter(self.shop, cfg.settings)
        self.map = yaml.safe_load(MAP_FILE.read_text(encoding="utf-8"))
        self.flow = self.map["export_flow"]

    def _report_url(self) -> str:
        return self.flow["report_url"].replace("{base}", self.adapter.base_url)

    def _set_range(self, page, d_from: date, d_to: date) -> None:
        """ตั้งช่วงวันที่ในช่อง input คู่บนหน้ารายงาน

        ⚠️ เพดาน 90 วันต่อครั้ง — หน้าเว็บประกาศเอง
           เช็คก่อนเลยดีกว่าปล่อยให้ Lazada ตัดช่วงเงียบ ๆ แล้วได้ข้อมูลไม่ครบ
        """
        span = (d_to - d_from).days + 1
        if span > 90:
            raise AdapterError(
                ErrorType.PARSE_ERROR,
                f"ขอช่วง {span} วัน แต่ Lazada ให้ดาวน์โหลดได้สูงสุด 90 วันต่อครั้ง "
                f"— แบ่งเป็นก้อนละไม่เกิน 90 วันแล้วค่อยรวมกันเอง",
            )

        boxes = page.locator("input").filter(has_not_text="")
        # หาช่องที่มีค่าเป็นรูปแบบวันที่อยู่แล้ว (หน้าตั้งค่าเริ่มต้นเป็น "วันนี้")
        found = []
        for i in range(min(boxes.count(), 25)):
            try:
                v = boxes.nth(i).input_value(timeout=2000)
            except Exception:                            # noqa: BLE001
                continue
            if v and len(v) == 10 and v.count("-") == 2:
                found.append(boxes.nth(i))
        if len(found) < 2:
            raise AdapterError(
                ErrorType.PARSE_ERROR,
                f"หาช่องวันที่บนหน้ารายงานไม่เจอ (เจอ {len(found)} ช่อง ต้องการ 2) "
                f"— หน้าเว็บอาจเปลี่ยนโครง",
            )

        for box, d in ((found[0], d_from), (found[1], d_to)):
            box.click(timeout=15_000)
            page.wait_for_timeout(600)
            box.press("Control+a")
            box.type(d.isoformat(), delay=45)
            page.wait_for_timeout(600)
            box.press("Enter")
            page.wait_for_timeout(2500)

        page.keyboard.press("Escape")     # ปิดปฏิทินที่กางอยู่ ไม่ให้บังปุ่ม
        page.wait_for_timeout(8000)

        got = [found[0].input_value(), found[1].input_value()]
        if got != [d_from.isoformat(), d_to.isoformat()]:
            raise AdapterError(
                ErrorType.PARSE_ERROR,
                f"ตั้งช่วงวันที่ไม่ติด — ขอ {d_from} ถึง {d_to} แต่ช่องเป็น {got} "
                f"· หยุดก่อนเพราะจะได้ข้อมูลผิดช่วง",
            )

    def fetch(self, d_from: date, d_to: date) -> Path:
        page = self.adapter._open_page(headed=False)
        url = self._report_url()
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(15_000)
        self.adapter._ensure_logged_in(page, url)

        self._set_range(page, d_from, d_to)
        log.info("lazada_ads_request", shop_id=self.shop.shop_id,
                 date_from=d_from.isoformat(), date_to=d_to.isoformat())

        # ⚠️ แถบแท็บแบบลอยทับปุ่มอยู่ คลิกด้วยเมาส์ไม่ลง (เจอจริง 2026-08-22)
        #    สั่ง .click() ที่ตัวปุ่มตรง ๆ ยังเจาะจงปุ่มเดียวเหมือนเดิม
        want = self.flow["download_button_text"]

        def go() -> None:
            page.evaluate(
                """(t) => {
                     const b = [...document.querySelectorAll('button')]
                       .find(x => (x.innerText || '').trim().includes(t));
                     if (b) b.click();
                   }""", want)

        return self.adapter._capture_download(page, go, timeout_ms=180_000)

    def close(self) -> None:
        self.adapter.close()          # ปิดสะอาด cookie ไม่หาย (กฎเหล็กข้อ 5)

    def __enter__(self) -> "LazadaAdsFetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
