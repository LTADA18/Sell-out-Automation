"""กันบั๊ก "พิมพ์ภาษาไทยแล้วโปรเซสตาย" ตอน stdout ถูก redirect

เจอจริง 2026-08-10: backfill ดึงวันแรกสำเร็จครบ แล้วตายตอน click.echo พิมพ์บรรทัดสรุป
เพราะ Windows ให้ stdout ที่ redirect เป็น cp1252 ซึ่งเขียนภาษาไทยไม่ได้
วันที่ 2-9 จึงไม่เคยถูกดึง และไม่มี error โผล่ในล็อกเลย — พังเงียบสนิท
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _run(code: str, encoding: str) -> subprocess.CompletedProcess:
    """รัน python ลูกโดยบังคับ codepage ที่เขียนภาษาไทยไม่ได้ แล้วดักผลลัพธ์

    ⚠️ ต้องยกสภาพแวดล้อมเดิมมาทั้งชุดแล้วทับเฉพาะ PYTHONIOENCODING
       ถ้าส่ง env ว่าง ๆ ไป Windows จะโหลด socket ไม่ได้ (WinError 10106)
       แล้วเทสต์จะพังด้วยเหตุผลคนละเรื่องกับที่ต้องการวัด
    """
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT, capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": encoding},
        timeout=120,
    )


def test_cli_survives_thai_on_legacy_codepage() -> None:
    """import src.cli แล้วพิมพ์ภาษาไทยได้ แม้ codepage เขียนไทยไม่ได้

    ถ้าไม่มีตัว reconfigure ใน cli.py เคสนี้จะ exit ไม่เป็น 0
    """
    res = _run("import src.cli; print('สรุป: ครบทุกร้าน ✅')", "cp1252")
    assert res.returncode == 0, (
        f"พิมพ์ภาษาไทยแล้วตาย — stderr: {res.stderr.decode('utf-8', 'replace')[:300]}"
    )


def test_without_guard_it_really_would_die() -> None:
    """พิสูจน์ว่าเคสนี้พังจริงถ้าไม่ได้ reconfigure — กันเทสต์ข้างบนผ่านแบบหลอก ๆ"""
    res = _run("print('สรุป: ครบทุกร้าน')", "cp1252")
    assert res.returncode != 0, "คาดว่าจะพังแต่กลับผ่าน — เทสต์ข้างบนอาจไม่ได้พิสูจน์อะไร"
    assert b"UnicodeEncodeError" in res.stderr


def test_summarize_output_is_thai() -> None:
    """ยืนยันว่าบรรทัดสรุปมีภาษาไทยจริง ไม่งั้นเทสต์ข้างบนก็ไม่มีความหมาย"""
    import inspect

    from src.core.runner import summarize

    assert any("฀" <= ch <= "๿" for ch in inspect.getsource(summarize))
