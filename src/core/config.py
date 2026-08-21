"""โหลด config จาก YAML + .env แล้ว validate — ผิดตรงไหนให้พังตั้งแต่ตอนเริ่ม ไม่ใช่กลางรอบ"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"

AdapterName = Literal["mock", "playwright", "api"]


def rel_to_project(path: Path) -> str:
    """path สั้น ๆ ไว้โชว์/เก็บลง DB

    ถ้าอยู่นอกรากโปรเจกต์ (เช่นตั้ง output ไว้บน OneDrive หรือไดรฟ์อื่น)
    ให้คืน absolute แทนที่จะโยน ValueError — เดิมทีเคสนี้ทำให้ร้านที่ดึงสำเร็จแล้ว
    กลายเป็น PARSE_ERROR ทั้งที่ไฟล์ออกครบ
    """
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


class ShopConfig(BaseModel):
    shop_id: str
    platform: str
    adapter: AdapterName = "mock"
    display_name: str
    enabled: bool = True
    skip_reason: str | None = None      # เหตุผลที่ปิด — โผล่บน Dashboard ช่อง SKIPPED

    # ชี้ไปที่ตัวแปรใน .env ว่าร้านนี้ล็อกอินด้วยบัญชีไหน เช่น LAZADA_01 -> LAZADA_01_ACCOUNT
    # เก็บแค่ "ชื่อบัญชี" ไว้เตือนตอนสั่ง login — ไม่มีรหัสผ่านอยู่ในระบบนี้ที่ไหนเลย
    account_key: str | None = None

    # ── รองรับ "1 บัญชี ดูแลหลายร้าน" (เจอกับ Shopee) ────────
    #
    # Shopee มีหน้า /portal/shop "เลือกร้านที่จะจัดการ" คั่นหลังล็อกอิน
    # บัญชีเดียวจึงเปิดได้หลายร้าน — session เป็นของ "บัญชี" ไม่ใช่ของ "ร้าน"
    #
    # profile_key   : ใช้โปรไฟล์เบราว์เซอร์ร่วมกับร้านอื่น (ค่าว่าง = ใช้ shop_id ตัวเอง)
    #                 ร้านที่อยู่ใต้บัญชีเดียวกันให้ใส่ค่าเดียวกัน จะได้ล็อกอินครั้งเดียว
    # web_shop_name : ชื่อร้านที่โชว์บนหน้าเลือกร้าน (ค่าว่าง = ใช้ display_name)
    #                 แยกไว้เพราะ display_name เป็นชื่อที่เราเรียกกันเอง
    #                 ส่วนชื่อบนเว็บต้องตรงเป๊ะถึงจะกดถูกแถว
    # web_account_name : ชื่อ "บัญชี" ที่ Seller Centre โชว์มุมขวาบน
    #
    # ⚠️ ทำไมต้องมีแยกจาก web_shop_name
    #    ร้านที่มีร้านเดียวต่อบัญชี Shopee จะไม่มีหน้าเลือกร้านคั่น
    #    ตัวอ่านชื่อจึงตกไปหยิบ class 'account-name' ซึ่งเป็น "ชื่อบัญชี" ไม่ใช่ชื่อร้าน
    #    เช่น shopee_10 โชว์ 'diy.tools' ทั้งที่ชื่อร้านคือ 'DIY tools ขายเครื่องมือช่าง'
    #    ด่านกันติดป้ายผิดร้านจึงตีว่า "อยู่ผิดร้าน" แล้วบล็อกงานย้อนหลังทั้งก้อน
    #
    #    ต้องประกาศไว้ ไม่ใช่ปล่อยให้ผ่านทุกชื่อ — ถ้ายอมรับชื่ออะไรก็ได้
    #    วันที่โปรไฟล์ล็อกอินผิดบัญชีจริง ไฟล์จะถูกติดป้ายผิดร้านโดยไม่มีอะไรเตือน
    #    (เคยเกิดแล้วกับ tiktok_01 ที่ล็อกอินด้วยบัญชีของ tiktok_02)
    profile_key: str | None = None
    web_shop_name: str | None = None
    web_account_name: str | None = None

    @property
    def profile_id(self) -> str:
        return self.profile_key or self.shop_id

    @property
    def web_name(self) -> str:
        return self.web_shop_name or self.display_name

    def name_matches(self, seen: str | None) -> bool:
        """ชื่อที่อ่านได้จากหน้าเว็บ เป็นของร้านนี้จริงไหม

        ยอมรับได้ 2 ค่าเท่านั้น: ชื่อร้าน (web_name) หรือชื่อบัญชี (web_account_name)
        อ่านไม่ได้ (None) ให้ถือว่าไม่ผ่าน — คนเรียกเป็นคนตัดสินว่าจะปล่อยผ่านไหม
        """
        if not seen:
            return False
        s = seen.strip().lower()
        ok = {self.web_name.strip().lower()}
        if self.web_account_name:
            ok.add(self.web_account_name.strip().lower())
        return s in ok

    @property
    def report_name(self) -> str:
        """ชื่อมาตรฐานที่ใช้ในรายงาน — ร้านเดียวกันคนละแพลตฟอร์มได้ชื่อเดียวกัน

        มาจาก `name` ของแบรนด์ใน brands.yaml ถ้าไม่ได้ประกาศไว้ก็ใช้ display_name
        ⚠️ อย่าเอาไปใช้จับคู่ร้านบนเว็บ — ตรงนั้นต้องใช้ web_name ที่เป็นชื่อจริง
        """
        from src.core.naming import canonical_name

        return canonical_name(self.shop_id, self.display_name)

    @property
    def email_name(self) -> str:
        """ชื่อสำหรับอีเมล — วงเล็บชื่อจริงไว้ถ้าไม่ตรงกับชื่อมาตรฐาน"""
        from src.core.naming import email_label

        return email_label(self.shop_id, self.display_name)

    @property
    def account(self) -> str | None:
        if not self.account_key:
            return None
        return os.getenv(f"{self.account_key}_ACCOUNT")

    @field_validator("shop_id")
    @classmethod
    def _safe_filename(cls, v: str) -> str:
        # shop_id ถูกเอาไปตั้งชื่อไฟล์และโฟลเดอร์ กันอักขระที่ Windows ไม่รับ
        bad = set(v) & set('<>:"/\\|?* ')
        if bad:
            raise ValueError(f"shop_id '{v}' มีอักขระที่ใช้ตั้งชื่อไฟล์ไม่ได้: {sorted(bad)}")
        return v


class FetchConfig(BaseModel):
    lookback_days: int = Field(default=1, ge=1, le=365)
    refresh_status_days: int = Field(default=0, ge=0, le=365)


class PrivacyConfig(BaseModel):
    include_pii: bool = False


class RetryConfig(BaseModel):
    backoff_seconds: list[float] = Field(default_factory=lambda: [2, 8, 30])

    @property
    def max_attempts(self) -> int:
        return len(self.backoff_seconds) + 1   # ลองครั้งแรก + จำนวนครั้งที่หน่วง


class RateLimitConfig(BaseModel):
    delay_between_shops: tuple[float, float] = (3.0, 7.0)
    shop_timeout_sec: float = 600.0

    @field_validator("delay_between_shops")
    @classmethod
    def _min_three_seconds(cls, v: tuple[float, float]) -> tuple[float, float]:
        # กฎเหล็กที่ยกมาจาก pdp-scraper: ยิงถี่กว่า 3 วิ เสี่ยงโดนบล็อก IP/บัญชี
        if v[0] < 3:
            raise ValueError("delay_between_shops ต่ำสุดต้อง 3 วินาที")
        if v[1] < v[0]:
            raise ValueError("delay_between_shops: ค่าสูงต้องไม่น้อยกว่าค่าต่ำ")
        return v


class ScheduleConfig(BaseModel):
    hour: int = Field(default=6, ge=0, le=23)
    minute: int = Field(default=0, ge=0, le=59)


class PathsConfig(BaseModel):
    raw_dir: str = "data/raw"
    profiles_dir: str = "data/profiles"     # โปรไฟล์ Chrome แยกต่อร้าน (ของจริงที่ใช้ล็อกอิน)
    sessions_dir: str = "data/sessions"     # สำเนา cookie ไว้ debug
    output_dir: str = "output"
    archive_dir: str = "output/_archive"
    logs_dir: str = "logs"
    db_path: str = "data/status.db"
    lock_file: str = "data/run.lock"

    def resolve(self, name: str) -> Path:
        """แปลง path ใน config เป็น absolute เทียบกับรากโปรเจกต์เสมอ
        (ไม่งั้นรันจากโฟลเดอร์อื่นแล้วไฟล์ไปโผล่ผิดที่)"""
        return PROJECT_ROOT / getattr(self, name)


class Settings(BaseModel):
    timezone: str = "Asia/Bangkok"
    fetch: FetchConfig = Field(default_factory=FetchConfig)
    privacy: PrivacyConfig = Field(default_factory=PrivacyConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    rate_limit: RateLimitConfig = Field(default_factory=RateLimitConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)


class AppConfig(BaseModel):
    settings: Settings
    shops: list[ShopConfig]

    def shop(self, shop_id: str) -> ShopConfig:
        for s in self.shops:
            if s.shop_id == shop_id:
                return s
        known = ", ".join(s.shop_id for s in self.shops)
        raise KeyError(f"ไม่รู้จักร้าน '{shop_id}' — ร้านที่มีใน shops.yaml: {known}")

    def select(
        self,
        shop_id: str | None = None,
        platform: str | None = None,
    ) -> list[ShopConfig]:
        """เลือกร้านตามเงื่อนไข CLI — ร้านที่ enabled=false ยังถูกเลือกมาด้วย
        เพราะ runner ต้องบันทึกสถานะ SKIPPED ให้เห็นบน Dashboard ไม่ใช่หายไปเฉย ๆ"""
        if shop_id:
            return [self.shop(shop_id)]
        if platform:
            picked = [s for s in self.shops if s.platform == platform]
            if not picked:
                raise KeyError(f"ไม่มีร้านของแพลตฟอร์ม '{platform}' ใน shops.yaml")
            return picked
        return list(self.shops)


def load_config(config_dir: Path | None = None) -> AppConfig:
    load_dotenv(PROJECT_ROOT / ".env")

    cfg_dir = config_dir or CONFIG_DIR
    settings_path = cfg_dir / "settings.yaml"
    shops_path = cfg_dir / "shops.yaml"

    for p in (settings_path, shops_path):
        if not p.exists():
            raise FileNotFoundError(f"ไม่พบไฟล์ config: {p}")

    settings_raw = yaml.safe_load(settings_path.read_text(encoding="utf-8")) or {}
    shops_raw = yaml.safe_load(shops_path.read_text(encoding="utf-8")) or {}

    shops = [ShopConfig(**s) for s in shops_raw.get("shops", [])]
    if not shops:
        raise ValueError(f"{shops_path} ไม่มีร้านเลยสักร้าน")

    dupes = {s.shop_id for s in shops if [x.shop_id for x in shops].count(s.shop_id) > 1}
    if dupes:
        raise ValueError(f"shop_id ซ้ำใน shops.yaml: {sorted(dupes)}")

    return AppConfig(settings=Settings(**settings_raw), shops=shops)
