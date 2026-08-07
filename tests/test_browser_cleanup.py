"""ตัวเคลียร์ Chrome ค้าง — จุดที่พลาดแล้วเสียหายคือ "ไปปิด Chrome ที่ไม่ใช่ของเรา" """
from __future__ import annotations

from src.core import browser_cleanup as bc


def test_only_targets_this_project_profiles(monkeypatch) -> None:
    """คำค้นต้องเป็น path เต็มของ data/profiles ไม่ใช่คำว่า profiles ลอย ๆ

    ถ้าเล็งกว้าง จะไปปิด Chrome ของโปรเจกต์อื่นหรือของเจ้าของเครื่องเอง
    """
    captured: list[str] = []
    monkeypatch.setattr(bc, "_ps", lambda script, timeout=90: captured.append(script) or "")
    bc._find_pids()

    script = captured[0]
    assert str(bc.PROFILES_DIR) in script
    assert "Dealer MKP Platform" in script                # ผูกกับโปรเจกต์นี้จริง
    assert "chrome.exe" in script


def test_no_chrome_running_does_nothing(monkeypatch) -> None:
    """ไม่มีอะไรค้าง = ต้องไม่ไปสั่ง Stop-Process เลย"""
    calls: list[str] = []

    def fake_ps(script: str, timeout: int = 90) -> str:
        calls.append(script)
        return ""                                        # ไม่เจอ pid

    monkeypatch.setattr(bc, "_ps", fake_ps)
    assert bc.close_stale_browsers() == 0
    assert not any("Stop-Process" in c for c in calls)


def test_closes_gracefully_before_forcing(monkeypatch) -> None:
    """ต้องกด CloseMainWindow ก่อน Stop-Process เสมอ

    ถ้าบังคับปิดเลย cookie ที่ยังอยู่ในหน่วยความจำจะไม่ถูกเขียนลงดิสก์
    การล็อกอินที่เพิ่งทำจะหายทั้งดุ้น (กฎเหล็กข้อ "ห้ามฆ่า Chrome ด้วย Stop-Process")
    """
    scripts: list[str] = []
    seq = iter(["111 222", "", ""])                       # เจอ 2 ตัว → ปิด → เกลี้ยง

    def fake_ps(script: str, timeout: int = 90) -> str:
        scripts.append(script)
        return next(seq, "")

    monkeypatch.setattr(bc, "_ps", fake_ps)
    assert bc.close_stale_browsers() == 2

    kill = next(s for s in scripts if "Stop-Process" in s)
    assert kill.index("CloseMainWindow") < kill.index("Stop-Process")
    assert "Start-Sleep" in kill


def test_survives_powershell_failure(monkeypatch) -> None:
    """เคลียร์ไม่ได้ต้องไม่ล้มทั้งรอบ — งานหลักคือดึงข้อมูล ไม่ใช่เคลียร์เบราว์เซอร์"""
    def boom(script: str, timeout: int = 90) -> str:
        raise OSError("powershell หาย")

    monkeypatch.setattr(bc, "_ps", boom)
    assert bc.close_stale_browsers() == 0                 # ต้องไม่โยน exception


def test_reports_partial_cleanup(monkeypatch) -> None:
    """ปิดได้ไม่หมดต้องรายงานตามจริง ไม่ใช่บอกว่าเคลียร์ครบ"""
    seq = iter(["111 222 333", "", "333"])                # เหลือค้าง 1 ตัว

    monkeypatch.setattr(bc, "_ps", lambda script, timeout=90: next(seq, ""))
    assert bc.close_stale_browsers() == 2                 # 3 - 1
