r"""ดึงรายงานโฆษณา TikTok → ไฟล์ Excel

⛔ ข้อห้ามเดียวกับฝั่ง Shopee — หน้าโฆษณามีปุ่ม "สร้างโฆษณา GMV Max" และ
   "แก้ไขแผนการโฆษณา" อยู่ในหน้าเดียวกัน กดพลาดคือเงินจริงของร้าน
   โมดูลนี้แตะแค่ 3 อย่าง: ช่องวันที่เริ่ม · ช่องวันที่สิ้นสุด · ปุ่มดาวน์โหลด

ต่างจาก Shopee 2 อย่างที่ต้องรู้ (ยืนยันกับของจริง 2026-08-22):
   1. ไม่มีคิว — กดปุ่มดาวน์โหลดแล้วได้ไฟล์เลย ไม่ต้องไปรอในแผงประวัติ
   2. ตั้งช่วงวันที่ผ่าน URL ไม่ได้ ต้องพิมพ์ลงช่องวันที่ในหน้า
      (Shopee ใช้ URL ได้ TikTok ต้องพิมพ์ อย่าเอาวิธีของอีกเจ้ามาใช้ข้ามกัน)

⚠️ ไฟล์ที่ได้เป็น "Campaign overview" = ยอดรวมระดับร้านรายวัน 7 คอลัมน์
   ไม่มี impression / คลิก / คีย์เวิร์ด / ชื่อแคมเปญ
   ถ้าต้องการระดับแคมเปญหรือคีย์เวิร์ด ต้องไปที่ TikTok Ads Manager
   (ads.tiktok.com) ซึ่งเป็นคนละระบบ ยังไม่ได้ทำ
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path

import yaml

from src.adapters.registry import build_adapter
from src.core.config import PROJECT_ROOT, load_config
from src.core.logging_setup import get_logger
from src.core.models import AdapterError, ErrorType

log = get_logger()

MAP_FILE = PROJECT_ROOT / "config" / "column_maps" / "tiktok_ads.yaml"

START_INPUT = 'input[placeholder="วันที่เริ่มต้น"]'
END_INPUT = 'input[placeholder="วันที่สิ้นสุด"]'
DOWNLOAD_BTN = "button:has(svg.arco-icon-download)"


class TikTokAdsFetcher:
    def __init__(self, shop_id: str) -> None:
        cfg = load_config()
        self.shop = cfg.shop(shop_id)
        if self.shop.platform != "tiktok":
            raise ValueError(f"{shop_id} ไม่ใช่ร้าน TikTok")
        self.adapter = build_adapter(self.shop, cfg.settings)
        self.map = yaml.safe_load(MAP_FILE.read_text(encoding="utf-8"))

    # ── ตั้งช่วงวันที่ ───────────────────────────────────────
    def _type_date(self, page, selector: str, d: date) -> None:
        """พิมพ์วันที่ลงช่อง แล้วกด Enter ให้ตัวเลือกยอมรับ

        ต้องล้างค่าเดิมด้วย Ctrl+A ก่อน ไม่งั้นจะต่อท้ายค่าเดิมกลายเป็นวันที่มั่ว
        """
        box = page.locator(selector).first
        box.click(timeout=15_000)
        page.wait_for_timeout(600)
        box.press("Control+a")
        box.type(d.isoformat(), delay=45)
        page.wait_for_timeout(600)
        box.press("Enter")
        page.wait_for_timeout(2500)

    def _set_range(self, page, d_from: date, d_to: date) -> None:
        self._type_date(page, START_INPUT, d_from)
        self._type_date(page, END_INPUT, d_to)
        page.wait_for_timeout(8000)          # รอหน้าโหลดตัวเลขของช่วงใหม่

        # ⚠️ ด่านกันพลาด — ถ้าตัวเลือกไม่รับค่าที่พิมพ์ หน้าจะยังโชว์ช่วงเดิม
        #    แล้วเราจะดาวน์โหลดข้อมูลผิดช่วงมาโดยไม่มีอะไรเตือน
        #    (ฝั่ง Shopee เคยโดนแบบนี้มาแล้ว ต่างกันแค่สาเหตุ)
        # ปิดปฏิทินที่ยังกางอยู่ ไม่งั้นแผงปฏิทินจะบังปุ่มดาวน์โหลดจนกดไม่ลง
        # (เจอจริง 2026-08-22 — ตั้งวันที่ติดแล้วแต่ดาวน์โหลดค้างจนหมดเวลา)
        page.keyboard.press("Escape")
        page.wait_for_timeout(1500)

        got_from = page.locator(START_INPUT).first.input_value()
        got_to = page.locator(END_INPUT).first.input_value()
        if got_from != d_from.isoformat() or got_to != d_to.isoformat():
            raise AdapterError(
                ErrorType.PARSE_ERROR,
                f"ตั้งช่วงวันที่ไม่ติด — ขอ {d_from} ถึง {d_to} "
                f"แต่ช่องยังเป็น {got_from} ถึง {got_to} · หยุดก่อนเพราะจะได้ข้อมูลผิดช่วง",
            )

    # ── ตัวหลัก ─────────────────────────────────────────────
    def fetch(self, d_from: date, d_to: date) -> Path:
        page = self.adapter._open_page(headed=False)
        url = f"{self.adapter.base_url}/ads"
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(12_000)
        self.adapter._ensure_logged_in(page, url)

        self._set_range(page, d_from, d_to)
        log.info("tiktok_ads_request", shop_id=self.shop.shop_id,
                 date_from=d_from.isoformat(), date_to=d_to.isoformat())

        btn = page.locator(DOWNLOAD_BTN).first
        if btn.count() == 0:
            raise AdapterError(ErrorType.PARSE_ERROR,
                               "หาปุ่มดาวน์โหลดบนแดชบอร์ดโฆษณาไม่เจอ")
        # สั่ง .click() ที่ตัว element ตรง ๆ เหมือนฝั่ง Shopee
        # หน้านี้มีป๊อปอัปแนะนำฟีเจอร์เด้งมาทับปุ่มเป็นระยะ คลิกด้วยเมาส์จึงพลาดได้
        # ยังเจาะจงปุ่มดาวน์โหลดปุ่มเดียวเหมือนเดิม ไม่ได้ยิงคลิกมั่วลงหน้า
        def go() -> None:
            btn.evaluate("e => e.click()")

        try:
            path = self.adapter._capture_download(page, go, timeout_ms=180_000)
        except AdapterError:
            # ⚠️ การส่งออกวิ่งผ่าน ads.tiktok.com (คนละโดเมนกับ Seller Center)
            #    บัญชีที่ไม่มีสิทธิ์ใน Ads Manager จะได้ 403 แล้วไฟล์ไม่มา
            #    ถ้าไม่ดักตรงนี้จะรายงานเป็น TIMEOUT ซึ่งชวนให้ไปแก้ผิดจุด
            #    แล้วยิงซ้ำเรื่อย ๆ ทั้งที่ยิงกี่ครั้งก็ไม่ผ่าน (กฎ error ที่ห้าม retry)
            #    เจอจริง 2026-08-22: tiktok_03 ได้ 403 ส่วน tiktok_01 ผ่านปกติ
            body = ""
            try:
                body = page.inner_text("body", timeout=10_000)
            except Exception:                            # noqa: BLE001
                pass
            if "403" in body or "ไม่มีสิทธิ์" in body or "ถูกปฏิเสธ" in body:
                raise AdapterError(
                    ErrorType.NO_PERMISSION,
                    "บัญชีนี้ไม่มีสิทธิ์เข้า TikTok Ads Manager (ads.tiktok.com ตอบ 403) "
                    "— ต้องให้เจ้าของร้านเพิ่มสิทธิ์โฆษณาให้ก่อน ยิงซ้ำไม่ช่วย",
                ) from None
            raise

        # ชื่อไฟล์ฝังช่วงวันที่ไว้ ("Campaign overview data 20260815 - 20260822")
        # ใช้ยืนยันซ้ำอีกชั้นว่าได้ไฟล์ของช่วงที่ขอจริง ไม่ใช่ช่วงเดิมที่ค้างอยู่
        want = f"{d_from:%Y%m%d}"
        if want not in path.name.replace("_", "").replace("-", ""):
            log.warning("tiktok_ads_range_mismatch", shop_id=self.shop.shop_id,
                        want=want, file=path.name[:70])
        return path

    def close(self) -> None:
        self.adapter.close()          # ปิดสะอาด cookie ไม่หาย (กฎเหล็กข้อ 5)

    def __enter__(self) -> "TikTokAdsFetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
