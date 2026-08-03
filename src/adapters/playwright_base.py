"""ฐานร่วมของ adapter ที่ทำงานผ่านเบราว์เซอร์ — จัดการ session / ดาวน์โหลด / ตรวจ login

**ระบบนี้ไม่เก็บรหัสผ่านที่ไหนเลย**
การล็อกอินทำครั้งเดียวต่อร้านด้วยมือผ่าน `python -m src.cli login --shop <id>`
โค้ดเพียงเปิดเบราว์เซอร์รอ แล้วเก็บ cookie ที่ได้ลง data/sessions/
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.adapters.base import BaseAdapter, HealthStatus
from src.core.column_map import PlatformMap
from src.core.config import PROJECT_ROOT
from src.core.logging_setup import get_logger
from src.core.models import AdapterError, ErrorType, Order

log = get_logger()

# ร่องรอยบนหน้าเว็บที่แปลว่า session ใช้ไม่ได้แล้ว
LOGIN_URL_HINTS = ("/login", "/account/login", "/apps/seller/login", "signin")
NO_PERMISSION_HINTS = ("ไม่มีสิทธิ์", "no permission", "not authorized", "ไม่ได้ขออนุญาต")


class PlaywrightAdapter(BaseAdapter):
    """คลาสลูกต้องเขียน 2 อย่าง: `_export(page, date_from, date_to)` และ `normalize(raw)`"""

    name = "playwright"
    base_url_env = ""          # เช่น "LAZADA_SELLER_URL"
    login_path = "/"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.map = PlatformMap(self.shop.platform)
        self._pw = None
        self._browser = None
        self._context = None

    # ── ที่อยู่ไฟล์ ──────────────────────────────────────────

    @property
    def base_url(self) -> str:
        url = os.getenv(self.base_url_env, "")
        if not url:
            raise AdapterError(
                ErrorType.UNKNOWN,
                f"ไม่ได้ตั้ง {self.base_url_env} ใน .env — คัดลอกจาก .env.example",
            )
        return url.rstrip("/")

    @property
    def profile_dir(self) -> Path:
        """โปรไฟล์ Chrome เต็ม ๆ แยก 1 โฟลเดอร์ต่อ 1 ร้าน

        เก็บทั้ง cookie / localStorage / IndexedDB / device trust
        ถ้าเก็บแค่ cookie แพลตฟอร์มจะมองว่าเป็นเครื่องใหม่แล้วขอ OTP ซ้ำ
        โฟลเดอร์นี้แยกจากโปรไฟล์ Chrome ที่ผู้ใช้ใช้งานประจำโดยสิ้นเชิง
        """
        return PROJECT_ROOT / self.settings.paths.profiles_dir / self.shop.shop_id

    @property
    def session_file(self) -> Path:
        """สำเนา cookie ไว้ debug/ย้ายเครื่อง — ตัวจริงที่ใช้งานคือ profile_dir"""
        return (
            PROJECT_ROOT
            / self.settings.paths.sessions_dir
            / f"{self.shop.shop_id}_state.json"
        )

    @property
    def has_session(self) -> bool:
        """โปรไฟล์ที่ล็อกอินแล้วจะมีไฟล์ Cookies อยู่ข้างใน โฟลเดอร์เปล่าไม่นับ

        ⚠️ Chrome ตั้งแต่ v96 ย้าย Cookies ไปไว้ใน Default/Network/
        ตัวที่เจอจริงบนเครื่อง (Chrome 150) คือ Default/Network/Cookies
        เหลือ path เก่าไว้เผื่อ Chromium รุ่นเก่า/ช่องทางอื่น
        """
        return any(
            (self.profile_dir / p).exists()
            for p in (
                Path("Default") / "Network" / "Cookies",   # Chrome 96+
                Path("Default") / "Cookies",               # เก่ากว่านั้น
                Path("Network") / "Cookies",
                Path("Cookies"),
            )
        )

    def download_dir(self, run_date: str) -> Path:
        d = PROJECT_ROOT / self.settings.paths.raw_dir / self.shop.platform / self.shop.shop_id / "files"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── สัญญาของ BaseAdapter ────────────────────────────────

    def authenticate(self) -> None:
        """ไม่เปิดเบราว์เซอร์ — แค่เช็คว่ามี session ให้ใช้ไหม

        การเปิดเบราว์เซอร์จริงเกิดตอน fetch_orders เพื่อไม่ให้เสียเวลาเปิด-ปิดสองรอบ
        """
        if not self.has_session:
            raise AdapterError(
                ErrorType.AUTH_REQUIRED,
                f"ยังไม่เคยล็อกอินร้านนี้ — รัน: python -m src.cli login --shop {self.shop.shop_id}",
            )

    def health_check(self) -> HealthStatus:
        """เช็คว่ามีโปรไฟล์ที่ล็อกอินแล้วและเก่าแค่ไหน — ไม่เปิดเว็บ ไม่ดึงข้อมูล"""
        if not self.has_session:
            return HealthStatus(
                shop_id=self.shop.shop_id,
                ok=False,
                message=f"ยังไม่เคยล็อกอิน — python -m src.cli login --shop {self.shop.shop_id}",
            )
        age_days = (datetime.now() - datetime.fromtimestamp(self.profile_dir.stat().st_mtime)).days
        acct = self.shop.account or "ไม่ได้ระบุบัญชีใน .env"
        return HealthStatus(
            shop_id=self.shop.shop_id,
            ok=True,
            message=f"มี session (อายุ {age_days} วัน) บัญชี: {acct}",
        )

    def fetch_orders(self, date_from: date, date_to: date) -> list[Order]:
        run_date = date_to.isoformat()
        page = self._open_page()
        try:
            export_path = self._export(page, date_from, date_to)
        finally:
            self._save_session()

        rows = self.map.read_export(export_path)
        if not rows:
            raise AdapterError(
                ErrorType.EMPTY_RESULT,
                f"ไฟล์ Export ไม่มีข้อมูลสักแถว ({export_path.name})",
            )

        # เก็บ raw ไว้ debug — ตัดคอลัมน์ PII ออกก่อนถ้าปิด include_pii
        self.save_raw(
            {
                "shop_id": self.shop.shop_id,
                "source_file": export_path.name,
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "row_count": len(rows),
                "rows": self._strip_pii(rows),
            },
            run_date,
        )
        return self.normalize(rows)

    def close(self) -> None:
        for obj in (self._context, self._browser, self._pw):
            try:
                if obj is not None:
                    (obj.close if hasattr(obj, "close") else obj.stop)()
            except Exception:                            # noqa: BLE001
                pass                                     # ปิดไม่ได้ก็ไม่ควรทำให้รอบพัง
        self._pw = self._browser = self._context = None

    # ── สิ่งที่คลาสลูกต้องเขียน ─────────────────────────────

    def _export(self, page, date_from: date, date_to: date) -> Path:
        raise NotImplementedError

    # ── เบราว์เซอร์ ─────────────────────────────────────────

    def _open_page(self, headed: bool = False):
        """เปิดโปรไฟล์ถาวรของร้านนี้ — โปรไฟล์เก็บ state เองอัตโนมัติตอนปิด

        ใช้ Chrome ตัวจริงบนเครื่อง (channel="chrome") ก่อน เพราะหลังบ้าน
        โดยเฉพาะ TikTok คัดกรอง Chromium เปล่าของ Playwright ค่อนข้างหนัก
        ถ้าเครื่องไม่มี Chrome ค่อยถอยไปใช้ Chromium ที่ Playwright ติดตั้งไว้
        """
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        opts = dict(
            user_data_dir=str(self.profile_dir),
            headless=not headed,
            accept_downloads=True,
            locale="th-TH",
            timezone_id=self.settings.timezone,
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            self._context = self._pw.chromium.launch_persistent_context(channel="chrome", **opts)
        except Exception as exc:                         # noqa: BLE001
            log.warning("chrome_channel_unavailable", shop_id=self.shop.shop_id, err=str(exc)[:120])
            self._context = self._pw.chromium.launch_persistent_context(**opts)

        self._context.set_default_timeout(60_000)
        self._restore_session_cookies()
        pages = self._context.pages
        return pages[0] if pages else self._context.new_page()

    def _restore_session_cookies(self) -> None:
        """ยัด cookie จาก storage_state กลับเข้า context

        ⚠️ จุดที่กัดแรงที่สุดของ Lazada: token ที่ใช้ยืนยันตัวตน
        (lzd_sid / _tb_token_ / JSID / TID / CSRFT) เป็น **session cookie**
        คือ expires = -1 ซึ่ง Chrome ทิ้งทิ้งทุกครั้งที่ปิดเบราว์เซอร์
        โปรไฟล์ถาวรเก็บได้แค่ cookie ที่มีวันหมดอายุ (26 จาก 39 ตัว)
        เปิดรอบใหม่จึงไม่มี token แล้วเด้งหน้า login ทั้งที่เพิ่งล็อกอินไป

        storage_state ที่ _save_session() เขียนไว้เก็บครบทั้ง 39 ตัว
        จึงต้องเอากลับมาใส่เองทุกครั้งที่เปิด context
        """
        if self._context is None or not self.session_file.exists():
            return
        try:
            cookies = json.loads(self.session_file.read_text(encoding="utf-8")).get("cookies", [])
            if not cookies:
                return
            self._context.add_cookies(cookies)
            n_session = sum(1 for c in cookies if (c.get("expires") or -1) <= 0)
            # ห้ามตั้งชื่อ field ว่ามีคำว่า "session"/"cookie" — logging_setup จะ mask เป็น ****
            log.info("session_cookies_restored", shop_id=self.shop.shop_id,
                     total=len(cookies), no_expiry=n_session)
        except Exception as exc:                         # noqa: BLE001
            # กู้ไม่ได้ก็ปล่อยผ่าน — เดี๋ยว _assert_logged_in จับเป็น AUTH_EXPIRED เอง
            log.warning("restore_cookies_failed", shop_id=self.shop.shop_id, err=str(exc)[:150])

    def _save_session(self) -> None:
        """สำเนา cookie ออกมาไว้ debug — ตัวจริงถูกเก็บในโปรไฟล์อยู่แล้ว"""
        if self._context is None:
            return
        try:
            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            self._context.storage_state(path=str(self.session_file))
        except Exception as exc:                         # noqa: BLE001
            log.warning("save_session_failed", shop_id=self.shop.shop_id, err=str(exc))

    def _assert_logged_in(self, page) -> None:
        """เด้งหน้า login หรือหน้าไม่มีสิทธิ์ = หยุดร้านนี้ทันที ห้าม retry"""
        url = page.url.lower()
        if any(h in url for h in LOGIN_URL_HINTS):
            # ถ่ายภาพก่อนโยน error — รอบ 06:00 ไม่มีใครนั่งดู ถ้าไม่เก็บไว้จะไล่สาเหตุไม่ได้
            # ⚠️ ภาพมีอีเมลที่ใช้ล็อกอินติดมาด้วย แต่ logs/ อยู่ใน .gitignore แล้ว
            self._screenshot_on_error(page, "auth_expired")
            raise AdapterError(
                ErrorType.AUTH_EXPIRED,
                f"cookie หมดอายุ (เด้งไปหน้า login) — รัน: "
                f"python -m src.cli login --shop {self.shop.shop_id}",
            )
        body = (page.inner_text("body")[:3000] if page.locator("body").count() else "").lower()
        if any(h.lower() in body for h in NO_PERMISSION_HINTS):
            self._screenshot_on_error(page, "no_permission")
            raise AdapterError(
                ErrorType.NO_PERMISSION,
                "บัญชีที่ล็อกอินไม่มีสิทธิ์ดูคำสั่งซื้อ — ให้เจ้าของร้านเพิ่มสิทธิ์ 'จัดการคำสั่งซื้อ'",
            )

    def _capture_download(self, page, action, timeout_ms: int = 180_000) -> Path:
        """ดักไฟล์ที่กำลังจะถูกดาวน์โหลด — ชื่อไฟล์ของ Lazada เป็น hash สุ่ม เดาไม่ได้"""
        with page.expect_download(timeout=timeout_ms) as info:
            action()
        download = info.value
        dest = self.download_dir("") / f"{self.shop.shop_id}_{datetime.now():%Y%m%d_%H%M%S}_{download.suggested_filename}"
        download.save_as(dest)
        log.info("downloaded", shop_id=self.shop.shop_id, file=dest.name,
                 size_kb=round(dest.stat().st_size / 1024, 1))
        return dest

    def _screenshot_on_error(self, page, tag: str) -> None:
        """เก็บภาพหน้าจอตอนพัง — จำเป็นมาก เพราะรัน headless ตอนตี 6 ไม่มีใครเห็น"""
        try:
            d = PROJECT_ROOT / self.settings.paths.logs_dir / "screenshots"
            d.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(d / f"{self.shop.shop_id}_{tag}_{datetime.now():%Y%m%d_%H%M%S}.png"),
                            full_page=False)
        except Exception:                                # noqa: BLE001
            pass

    def _strip_pii(self, rows: list[dict]) -> list[dict]:
        if self.settings.privacy.include_pii or not self.map.pii_columns:
            return rows
        return [{k: v for k, v in r.items() if k not in self.map.pii_columns} for r in rows]

    # ── โหมดล็อกอินด้วยมือ (เรียกจาก cli login) ─────────────

    def interactive_login(self) -> None:
        """เปิดเบราว์เซอร์แบบเห็นหน้าจอ ให้ผู้ใช้พิมพ์รหัสผ่านเอง แล้วเก็บ cookie

        โค้ดไม่แตะช่องรหัสผ่าน ไม่อ่านค่าที่พิมพ์ และไม่ยุ่งกับ OTP/CAPTCHA
        """
        page = self._open_page(headed=True)
        page.goto(f"{self.base_url}{self.login_path}", wait_until="domcontentloaded")

        print()
        print(f"  ร้าน   : {self.shop.display_name} ({self.shop.shop_id})")
        print(f"  บัญชี  : {self.shop.account or '— ไม่ได้ระบุใน .env —'}")
        print()
        print("  กรุณาล็อกอินในหน้าต่างเบราว์เซอร์ที่เปิดขึ้นมา (พิมพ์รหัสผ่านเอง)")
        print("  ถ้ามี OTP / CAPTCHA ให้ทำเองในหน้าต่างนั้น")
        print('  ถ้ามีตัวเลือก "จดจำอุปกรณ์นี้" ให้ติ๊กด้วย จะได้ไม่ต้องขอ OTP อีก')
        print("  เมื่อเข้าหลังบ้านได้แล้ว กลับมาที่หน้าต่างนี้แล้วกด Enter")
        input("  >>> กด Enter เมื่อล็อกอินเสร็จ ")

        self._save_session()
        print(f"\n  เก็บโปรไฟล์แล้วที่ {self.profile_dir.relative_to(PROJECT_ROOT)}")
        print("  รอบต่อไปจะใช้โปรไฟล์นี้ซ้ำ ไม่ต้องล็อกอิน/ไม่ต้อง OTP อีก")
        print("  (อยู่ใน .gitignore — ห้าม commit เด็ดขาด)")
        self.close()
