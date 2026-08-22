r"""ดึงรายงานโฆษณา Shopee → ไฟล์ CSV

⛔ ข้อห้ามที่สำคัญกว่าผลลัพธ์ — อ่านก่อนแก้
   หน้าโฆษณามีปุ่ม "เติมเครดิต" / "ปรับงบประมาณ" / "สร้างโฆษณา" อยู่ติดกับ
   ข้อมูลที่เราต้องการ กดพลาดทีเดียวคือเงินจริงของร้าน
   โมดูลนี้จึงกดได้แค่ 4 อย่าง: แท็บโฆษณาคำค้นหา · ปุ่มดาวน์โหลดข้อมูล ·
   รายการในเมนูดาวน์โหลด · ปุ่มดาวน์โหลดในแถวประวัติ
   ห้ามเพิ่ม selector อื่นเข้ามาโดยไม่ตรวจว่าปุ่มนั้นทำอะไร

ลำดับงาน (ยืนยันกับของจริงแล้ว 2026-08-22 กับ shopee_02):
   1. เปิดหน้าโฆษณาพร้อมช่วงวันที่ใน URL (from/to เป็น epoch วินาทีเวลาไทย)
   2. กดแท็บ "โฆษณาคำค้นหา"
   3. กด "ดาวน์โหลดข้อมูล" แล้วเลือก "ข้อมูลโฆษณาคำค้นหา"
   4. Shopee เข้าคิวปั่นไฟล์ — ไม่ได้ไฟล์ทันที (รอตรงปุ่ม 3 นาทีก็ไม่มา)
   5. เปิดแผงประวัติ (ไอคอน download-list) แล้วรอไฟล์ของช่วงที่ขอ
   6. กดปุ่มดาวน์โหลดในแถวนั้น

⚠️ แผงประวัติเก็บแค่ 10 ไฟล์ล่าสุด "ที่ยังไม่ได้ดาวน์โหลด" ย้อนหลัง 6 เดือน
   ขอถี่เกินไปไฟล์เก่าจะหลุดออกก่อนได้โหลด — อย่าขอรายวันย้อนหลังหลายเดือนรวดเดียว
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import yaml

from src.adapters.registry import build_adapter
from src.core.config import PROJECT_ROOT, load_config
from src.core.logging_setup import get_logger
from src.core.models import AdapterError, ErrorType

log = get_logger()

TH = timezone(timedelta(hours=7))
MAP_FILE = PROJECT_ROOT / "config" / "column_maps" / "shopee_ads.yaml"


def _epoch(d: date, end: bool) -> int:
    """ต้นวัน/ท้ายวันตามเวลาไทย เป็น epoch วินาที

    ⚠️ ต้องผูกกับ Asia/Bangkok ให้ชัด ห้ามใช้เวลาเครื่อง
       เครื่องเป็นโน้ตบุ๊กที่พกออกนอกออฟฟิศ ถ้า timezone เพี้ยน
       จะได้ข้อมูลคนละวันโดยไม่มีอะไรเตือน
    """
    t = datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=TH) if end \
        else datetime(d.year, d.month, d.day, 0, 0, 0, tzinfo=TH)
    return int(t.timestamp())


def _stamp(d_from: date, d_to: date) -> str:
    """ชิ้นส่วนวันที่ที่ปรากฏในชื่อไฟล์ประวัติ เช่น 01/07/2026-31/07/2026"""
    return f"{d_from:%d/%m/%Y}-{d_to:%d/%m/%Y}"


class ShopeeAdsFetcher:
    """ยืม session/การเข้าร้านจาก ShopeeAdapter แล้วทำเฉพาะส่วนโฆษณา

    ไม่สืบทอดจาก ShopeeAdapter เพราะสัญญาของ adapter คือคืน list[Order]
    ซึ่งคนละเรื่องกับรายงานโฆษณา สืบทอดแล้วจะต้องบิดสัญญากลาง
    """

    def __init__(self, shop_id: str) -> None:
        cfg = load_config()
        self.shop = cfg.shop(shop_id)
        if self.shop.platform != "shopee":
            raise ValueError(f"{shop_id} ไม่ใช่ร้าน Shopee")
        self.adapter = build_adapter(self.shop, cfg.settings)
        self.map = yaml.safe_load(MAP_FILE.read_text(encoding="utf-8"))
        self.flow = self.map["export_flow"]

    # ── ขั้นตอนย่อย ──────────────────────────────────────────
    def _ads_url(self, d_from: date, d_to: date) -> str:
        """URL พร้อมช่วงวันที่

        ⚠️ ต้องมี type= ด้วย ไม่งั้นช่วงวันที่ที่ส่งไปถูกทิ้ง (เจอจริง 2026-08-22)
           ถ้าใส่แค่ from/to Shopee จะเด้งกลับเป็น type=new_cpc_homepage&group=today
           แล้วรีเซ็ตช่วงเป็น "วันนี้" เงียบ ๆ ผลคือขอเดือน ส.ค. แต่ได้ไฟล์ของวันเดียว
           โดยไม่มีอะไรเตือน — ต่างจาก TikTok ที่ใส่แค่ช่วงวันที่ก็พอ

           ตรวจแล้วว่าเมื่อมี type= ครบ ค่า group= จะเป็นอะไรก็ได้ ช่วงยังคงอยู่
           ใส่ custom ไว้ให้อ่านแล้วรู้เจตนา
        """
        return (f"{self.adapter.base_url}/portal/marketing/pas/index"
                f"?type=shop_homepage&group=custom"
                f"&from={_epoch(d_from, False)}&to={_epoch(d_to, True)}")

    def _history_names(self, page) -> list[str]:
        """ชื่อไฟล์ในแผงประวัติ เรียงตามที่แสดง (ใหม่สุดอยู่บน)

        ⚠️ ชื่อไฟล์ไม่ได้มีรูปแบบเดียว — แต่ละรายการในเมนูดาวน์โหลดตั้งชื่อคนละแบบ
           เจอมาแล้ว 3 แบบ: "ข้อมูล-Shopee-Ads-..." / "Shop+-Ads-Overall-Data-..."
           / "Shop GMV MAX-Detail-Data-..."
           จึงรับทุกไฟล์ .csv แล้วไปกรองด้วยช่วงวันที่เอาทีหลัง
           ถ้าล็อกชื่อไว้แบบเดียวจะรอเก้อทั้งที่ไฟล์พร้อมอยู่แล้ว
        """
        return page.evaluate(
            """() => [...document.querySelectorAll('*')]
                 .filter(e => e.children.length === 0)
                 .map(e => (e.innerText || '').trim())
                 .filter(t => t.length < 120 && /\\.csv$/i.test(t))"""
        )

    def _row_download_button(self, page, name: str):
        """ปุ่มดาวน์โหลด "ของแถวนั้น" — ไต่ขึ้นจากชื่อไฟล์ทีละชั้น

        เงื่อนไข count == 1 คือตัวบอกว่าไต่มาถึงระดับแถวพอดี
        ไต่สูงเกินไปจะเจอปุ่มของทุกแถวรวมกัน แล้วกดผิดแถว
        (บทเรียนเดียวกับ TikTok._try_row_download_button)
        """
        node = page.locator(f'text="{name}"').first
        if node.count() == 0:
            return None
        for _ in range(6):
            node = node.locator("xpath=..")
            btn = node.locator('a:has-text("ดาวน์โหลด"), button:has-text("ดาวน์โหลด")')
            if btn.count() == 1:
                return btn.first
        return None

    def _wait_for_file(self, page, d_from: date, d_to: date,
                       timeout_sec: int = 600) -> str:
        """รอจนไฟล์ของช่วงที่ขอโผล่ในประวัติและกดโหลดได้

        ⚠️ ชื่อไฟล์ Shopee มีแค่ช่วงวันที่ ไม่มีเวลา — ขอช่วงเดิมซ้ำได้ชื่อเดิมเป๊ะ
           จึงเทียบด้วย "ชื่อที่ตรงช่วง + ปุ่มกดได้" ไม่ใช่ "มีชื่อใหม่โผล่ไหม"
           (บทเรียนเดียวกับรายงานออเดอร์ ดู ShopeeAdapter._wait_for_report)
        """
        want = _stamp(d_from, d_to)
        deadline = datetime.now() + timedelta(seconds=timeout_sec)
        last = ""
        while datetime.now() < deadline:
            page.wait_for_timeout(6000)
            names = self._history_names(page)
            top = names[0] if names else ""
            if top != last:
                log.info("shopee_ads_history_top", shop_id=self.shop.shop_id,
                         name=top[:70], total=len(names))
                last = top
            for n in names:
                if want in n and self._row_download_button(page, n) is not None:
                    return n
        raise AdapterError(
            ErrorType.TIMEOUT,
            f"รอไฟล์ช่วง {want} ในแผงประวัติเกิน {timeout_sec} วินาทีแล้วยังไม่เสร็จ "
            f"(แถวบนสุดตอนนี้: {last[:70]!r})",
        )

    # ── ตัวหลัก ─────────────────────────────────────────────
    def fetch(self, d_from: date, d_to: date, timeout_sec: int = 600) -> Path:
        page = self.adapter._open_page(headed=False)
        url = self._ads_url(d_from, d_to)
        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(9000)

        # 1 บัญชีดูแลได้หลายร้าน — ต้องเข้าร้านให้ถูกก่อน ไม่งั้นได้ยอดของร้านอื่น
        self.adapter._enter_shop(page)
        if self.flow.get("has_onboarding_overlay"):
            self.adapter._dismiss_onboarding(page)

        page.goto(url, wait_until="domcontentloaded", timeout=90_000)
        page.wait_for_timeout(9000)
        self.adapter._ensure_logged_in(page, url)

        # ⚠️ ด่านสำคัญ — Shopee เคยเขียนทับช่วงวันที่เป็น "วันนี้" เงียบ ๆ
        #    ถ้าไม่ตรวจตรงนี้ จะได้ไฟล์ของวันเดียวมาแทนทั้งเดือนโดยไม่มีอะไรเตือน
        #    แล้วยอดโฆษณาที่ขึ้นฐานจะผิดทั้งก้อน (เจอจริง 2026-08-22)
        want_from, want_to = _epoch(d_from, False), _epoch(d_to, True)
        if str(want_from) not in page.url or str(want_to) not in page.url:
            raise AdapterError(
                ErrorType.PARSE_ERROR,
                f"Shopee เขียนทับช่วงวันที่ที่ขอ — ขอ {_stamp(d_from, d_to)} "
                f"แต่ URL กลายเป็น {page.url[-90:]!r} · หยุดก่อนเพราะจะได้ข้อมูลผิดช่วง",
            )

        log.info("shopee_ads_request", shop_id=self.shop.shop_id,
                 period=_stamp(d_from, d_to))
        page.locator(self.flow["download_button"]).first.click(timeout=15_000)
        page.wait_for_timeout(3500)
        page.locator(f'text="{self.flow["menu_ads_data"]}"').first.click(timeout=15_000)
        page.wait_for_timeout(6000)

        # เข้าคิวแล้ว ไปรอที่แผงประวัติ
        page.locator(self.flow["history_icon"]).first.click(timeout=15_000)
        page.wait_for_timeout(6000)

        name = self._wait_for_file(page, d_from, d_to, timeout_sec)
        log.info("shopee_ads_ready", shop_id=self.shop.shop_id, file=name[:70])

        btn = self._row_download_button(page, name)
        if btn is None:
            raise AdapterError(ErrorType.PARSE_ERROR,
                               f'หาปุ่มดาวน์โหลดของแถว "{name}" ไม่เจอ')

        # ⚠️ ต้องสั่ง .click() ที่ตัว element ตรง ๆ ไม่ใช่คลิกด้วยเมาส์
        #    แผงประวัติเป็นชั้นลอย มีกล่องอื่นทับตำแหน่งปุ่มอยู่ Playwright
        #    จึงกดไม่ลงแล้ววนลองใหม่จนหมดเวลา (เจอจริง 2026-08-22)
        #    วิธีนี้ยังเจาะจงปุ่มเดียวเหมือนเดิม ไม่ได้ยิงคลิกมั่วลงหน้า
        def go() -> None:
            btn.evaluate("e => e.click()")

        return self.adapter._capture_download(page, go, timeout_ms=180_000)

    def close(self) -> None:
        self.adapter.close()          # ปิดสะอาด cookie ไม่หาย (กฎเหล็กข้อ 5)

    def __enter__(self) -> "ShopeeAdsFetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
