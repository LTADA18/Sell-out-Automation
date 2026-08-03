"""log เป็น JSON lines ต่อ 1 รอบ + mask ความลับอัตโนมัติก่อนเขียนลงไฟล์"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Any

import structlog

# คีย์ที่ถือว่าเป็นความลับ ไม่ว่าจะโผล่ที่ชั้นไหนของ log event
SECRET_KEYS = (
    "token", "access_token", "refresh_token", "password", "passwd", "secret",
    "app_secret", "partner_key", "api_key", "cookie", "session", "authorization",
    "shop_cipher", "sign",
)

# จับ token ที่หลุดมาในข้อความยาว ๆ เช่น "Bearer eyJhbGc..." หรือ "cookie=abc123..."
_INLINE_SECRET = re.compile(
    r"(?i)\b(bearer|token|cookie|secret|key|sign)\b\s*[=:]?\s*([A-Za-z0-9._\-]{8,})"
)


def mask(value: object) -> str:
    """เหลือแค่ 4 ตัวท้าย — พอให้ยืนยันว่าใช้ค่าถูกตัว แต่เอาไปใช้ต่อไม่ได้"""
    s = str(value)
    if len(s) <= 4:
        return "****"
    return f"****{s[-4:]}"


def _mask_processor(_logger: Any, _name: str, event_dict: dict) -> dict:
    for key, val in list(event_dict.items()):
        if any(sk in key.lower() for sk in SECRET_KEYS):
            event_dict[key] = mask(val)
        elif isinstance(val, str) and len(val) > 12:
            event_dict[key] = _INLINE_SECRET.sub(
                lambda m: f"{m.group(1)}={mask(m.group(2))}", val
            )
    return event_dict


def setup_logging(logs_dir: Path, run_id: str, console: bool = True) -> Path:
    """ตั้ง log 1 ไฟล์ต่อ 1 รอบ คืน path ของไฟล์นั้น"""
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / f"run_{run_id}.jsonl"

    handlers: list[logging.Handler] = [logging.FileHandler(log_file, encoding="utf-8")]
    if console:
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(format="%(message)s", handlers=handlers, level=logging.INFO, force=True)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=False),
            _mask_processor,                      # mask ก่อน render เสมอ
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
    return log_file


def get_logger(name: str = "order-pipeline") -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
