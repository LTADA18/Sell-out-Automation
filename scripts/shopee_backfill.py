r"""ดึงออเดอร์ Shopee ย้อนหลังหลายเดือน — แยกเฟส "สั่ง" กับ "เก็บ"

ทำไมต้องแยกเฟส:
    Shopee ให้ Export ได้ทีละ 1 เดือนเท่านั้น (ยืนยันกับของจริง 2026-08-04)
    4 ร้าน × 7 เดือน = 28 ไฟล์ ถ้ารอทีละไฟล์ (คิวละ 20-40 นาที) = ~14 ชั่วโมง
    แต่ Shopee ปั่นไฟล์ขนานกันได้ — ประวัติการดาวน์โหลดมีหลายไฟล์พร้อมกันได้จริง
    จึงสั่งให้ครบก่อน แล้วค่อยวนกลับมาเก็บ → เหลือ ~1-2 ชั่วโมง

ทำต่อจากที่ค้างได้:
    ไฟล์ที่โหลดมาแล้วเก็บไว้ raw/<ร้าน>_<เดือน>.<นามสกุล>
    รันซ้ำจะข้ามเดือนที่มีไฟล์แล้ว — งานยาวขนาดนี้พังกลางทางแล้วเริ่มใหม่หมดไม่ไหว

⚠️ ห้ามรันคาบเกี่ยว 09:00 — ใช้โปรไฟล์ Chrome ชุดเดียวกับรอบดึงอัตโนมัติ

    .\.venv\Scripts\python.exe scripts\shopee_backfill.py --phase request
    .\.venv\Scripts\python.exe scripts\shopee_backfill.py --phase collect
    .\.venv\Scripts\python.exe scripts\shopee_backfill.py --phase merge
    .\.venv\Scripts\python.exe scripts\shopee_backfill.py --phase all
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import traceback
import zipfile
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.adapters.registry import build_adapter          # noqa: E402
from src.adapters.shopee import SEL, _click_first        # noqa: E402
from src.core.config import load_config                  # noqa: E402
from src.core.exporter import export_shop                # noqa: E402
from src.core.logging_setup import setup_logging         # noqa: E402
from src.core.models import AdapterError, Order          # noqa: E402

SHOP_IDS = ["shopee_02", "shopee_04", "shopee_05", "shopee_06"]
MONTHS = [(date(2026, m, 1),
           date(2026, m + 1, 1).toordinal() - 1 if m < 12 else date(2026, 12, 31).toordinal())
          for m in range(1, 8)]
PERIODS = [(a, date.fromordinal(b)) for a, b in MONTHS]

BASE = PROJECT_ROOT / "output" / "_shopee_backfill_2026h1"
RAW = BASE / "raw"
STATE_FILE = BASE / "state.json"


def stamp(a: date, b: date) -> str:
    return f"{a:%Y%m%d}_{b:%Y%m%d}"


def load_state() -> dict:
    if STATE_FILE.exists():
        # utf-8-sig เผื่อไฟล์ถูกแก้ด้วยเครื่องมืออื่นที่ใส่ BOM มา
        # (PowerShell 5.1 -Encoding utf8 ใส่ BOM เสมอ — เคยทำ state พังมาแล้ว)
        return json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
    return {"requested": [], "collected": {}}


def save_state(st: dict) -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def goto_retry(page, url: str, tries: int = 3) -> None:
    """SPA ของ Shopee ชอบสั่ง navigate ทับระหว่าง goto → net::ERR_ABORTED

    ไม่ใช่เน็ตพังและไม่ใช่ session หมด — ลองใหม่ก็ผ่าน
    เจอจริง 2026-08-07 กับ shopee_03 หลังเพิ่งสลับร้านเสร็จ
    """
    last: Exception | None = None
    for _ in range(tries):
        try:
            page.goto(url, wait_until="domcontentloaded")
            return
        except Exception as exc:                          # noqa: BLE001
            last = exc
            if "ERR_ABORTED" not in str(exc):
                raise
            page.wait_for_timeout(3000)
    raise last                                            # type: ignore[misc]


def open_shop(adapter, want_name: str = ""):
    """เปิดหน้าคำสั่งซื้อของร้าน ผ่านหน้าเลือกร้าน + ปิดทัวร์แนะนำ

    ⚠️ ลำดับสำคัญ: ต้อง _ensure_logged_in ก่อน _enter_shop
       ถ้าเลือกร้านก่อน พอ session หมดแล้ว relogin สำเร็จ หน้าจะค้างอยู่ที่หน้าเลือกร้าน
       แล้ว collect_shop จะหาไฟล์ไม่เจอ คืน 0 ไฟล์แบบ "ไม่มี error" — จบรอบเงียบ ๆ
       (เจอจริง 2026-08-07 กับ shopee_08: relogin_ok แต่เก็บได้ 0 ไฟล์ แล้ว exit 0)
       ตรงกับที่แก้ไปแล้วใน ShopeeAdapter._export
    """
    page = adapter._open_page(headed=False)
    goto_retry(page, adapter.orders_url)
    page.wait_for_timeout(9000)
    adapter._ensure_logged_in(page, adapter.orders_url)
    adapter._enter_shop(page)
    adapter._dismiss_onboarding(page)

    # กันติดป้ายผิดร้าน — บัญชีเดียวดูได้หลายร้าน ถ้าอยู่ผิดร้านไฟล์จะเป็นของอีกร้าน
    if want_name:
        cur = adapter._current_shop_name(page)
        if cur and cur.strip().lower() != want_name.strip().lower():
            raise AdapterError(
                f"อยู่ผิดร้าน — เปิดอยู่ {cur!r} แต่ต้องการ {want_name!r}",
                error_type="WRONG_SHOP",
            )
    return page


# ── เฟส 1: สั่งให้ Shopee ปั่นไฟล์ (ไม่รอ) ────────────────────

TH_MONTHS = ("มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
             "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม")

# ⚠️ หัวปฏิทินมีปุ่ม .eds-picker-header__prev "สองอัน" ในแผงเดียว class เหมือนกันเป๊ะ
#      nth(0) = ลูกศรคู่ («) ย้อน 1 ปี
#      nth(1) = ลูกศรเดี่ยว (‹) ย้อน 1 เดือน
#    adapter เดิมใช้ _click_first ซึ่งหยิบ .first = ปุ่มย้อนปี กดทีเดียวข้าม 12 เดือน
#    วนเท่าไหร่ก็ไม่มีทางเจอเดือนที่ต้องการ (ยืนยันด้วยการวัดจริง: "ขยับ 12 เดือน")
#    รอบรายวันไม่เคยเจอเพราะดึงเมื่อวาน = เดือนปัจจุบัน ไม่ต้องเลื่อนปฏิทินเลย
PANEL_LEFT = ".eds-daterange-picker-panel__body-left"
PREV_ARROWS = f"{PANEL_LEFT} .eds-picker-header__prev"


def panel_label(page, side: str) -> str:
    """หัวแผงปฏิทินฝั่งนั้น เช่น 'สิงหาคม2026' — อ่านไม่ได้คืนค่าว่าง"""
    p = page.locator(f".eds-daterange-picker-panel__body-{side}").first
    if p.count() == 0:
        return ""
    try:
        return "".join(x.strip() for x in p.locator(SEL["month_label"][0]).all_inner_texts()[:2])
    except Exception:                                    # noqa: BLE001
        return ""


def parse_label(text: str) -> tuple[int, int] | None:
    """'สิงหาคม2026' -> (2026, 8)"""
    for i, name in enumerate(TH_MONTHS, 1):
        if text.startswith(name):
            tail = "".join(c for c in text[len(name):] if c.isdigit())
            if tail:
                return int(tail), i
    return None


def months_between(cur: tuple[int, int], want: tuple[int, int]) -> int:
    return (want[0] - cur[0]) * 12 + (want[1] - cur[1])


def goto_month(page, target: date, log_fn) -> None:
    """เลื่อนแผงซ้ายไปเดือนของ target — ย้อนอย่างเดียว (ช่วงที่ดึงอยู่ก่อนเดือนปัจจุบัน)

    วัดผลจริงหลังกดครั้งแรก ถ้า nth(1) ไม่ได้ขยับ 1 เดือนก็สลับไปใช้ nth อีกตัว
    ไม่ยึดกับสมมติฐานว่าลำดับปุ่มเป็นแบบไหนตายตัว
    """
    want = (target.year, target.month)
    arrows = page.locator(PREV_ARROWS)
    n = arrows.count()
    if n < 2:
        raise RuntimeError(f"หัวปฏิทินมีปุ่มย้อนแค่ {n} อัน (คาดว่าต้องมี 2: ปี/เดือน)")

    idx_month = 1                                        # เดาไว้ก่อนตามที่เห็นใน DOM
    measured = False

    for _ in range(40):
        cur = parse_label(panel_label(page, "left"))
        if cur is None:
            raise RuntimeError("อ่านหัวแผงปฏิทินไม่ได้")
        diff = months_between(cur, want)                 # ติดลบ = ต้องย้อน
        if diff == 0:
            return
        if diff > 0:
            raise RuntimeError(f"เดือนที่แสดง {cur} เลยเป้า {want} ไปแล้ว")

        # ย้อนทีละปีถ้ายังห่างเกิน 12 เดือน จะได้ไม่ต้องกดเป็นสิบครั้ง
        use_year = diff <= -12
        arrows.nth(0 if use_year else idx_month).click(timeout=5000)
        page.wait_for_timeout(700)

        after = parse_label(panel_label(page, "left"))
        if after is None:
            raise RuntimeError("อ่านหัวแผงปฏิทินหลังกดไม่ได้")
        moved = months_between(cur, after)               # ติดลบ = ย้อนไปแล้วกี่เดือน

        if not measured and not use_year:
            log_fn(f"      ปุ่ม nth({idx_month}) ขยับ {moved} เดือน")
            if moved != -1:
                idx_month = 0 if idx_month == 1 else 1   # เดาผิด สลับไปอีกตัว
                log_fn(f"      สลับไปใช้ nth({idx_month})")
            measured = True

    raise RuntimeError(f"เลื่อนไปเดือน {target:%Y-%m} ไม่สำเร็จภายใน 40 ครั้ง")


def close_modal(page) -> None:
    """ปิดกล่องให้สนิทก่อนขึ้นรอบใหม่

    ⚠️ บทเรียนจาก 2 รอบที่ผ่านมา: พอเดือนไหนพังแล้วกล่องค้างเปิด
       เดือนที่เหลือหาปุ่ม "เปิดกล่อง" ไม่เจอ ล้มต่อกันหมดทุกเดือนที่เหลือ
       Escape อย่างเดียวไม่พอ ต้องลองกดปุ่มกากบาทด้วย
    """
    for _ in range(5):
        if page.locator(".eds-modal__box").count() == 0:
            return
        page.keyboard.press("Escape")
        page.wait_for_timeout(700)
        if page.locator(".eds-modal__box").count() == 0:
            return
        for sel in (".eds-modal__close", ".eds-modal__box [class*='close']"):
            btn = page.locator(sel).first
            if btn.count():
                try:
                    btn.click(timeout=3000)
                    page.wait_for_timeout(700)
                    break
                except Exception:                        # noqa: BLE001
                    continue


def request_one(adapter, page, a: date, b: date, log_fn) -> None:
    close_modal(page)
    if not _click_first(page, SEL["open_modal"], 15000):
        # กล่องอาจยังค้างจากรอบก่อน — ปิดแล้วลองอีกครั้งก่อนยอมแพ้
        close_modal(page)
        page.wait_for_timeout(1500)
        if not _click_first(page, SEL["open_modal"], 10000):
            raise RuntimeError('หาปุ่ม "ดาวน์โหลด" (เปิดกล่อง) ไม่เจอ')
    page.wait_for_timeout(3000)

    field = page.locator(SEL["range_input"][0]).first
    field.wait_for(state="visible", timeout=8000)
    field.click()
    page.wait_for_timeout(1500)

    goto_month(page, a, log_fn)
    adapter._click_day(page, a)
    adapter._click_day(page, b)
    page.wait_for_timeout(1500)

    if not _click_first(page, SEL["confirm"], 10000):
        raise RuntimeError("กดยืนยันในกล่องไม่ได้")
    page.wait_for_timeout(4000)
    close_modal(page)


def phase_request(cfg, st: dict) -> None:
    print("\n===== เฟส 1: สั่งให้ Shopee ปั่นไฟล์ =====", flush=True)
    for shop_id in SHOP_IDS:
        s = cfg.shop(shop_id)
        # ⚠️ ไล่จากเดือนหลังไปหน้า (ก.ค. → ม.ค.) โดยตั้งใจ
        #    ปฏิทินจำตำแหน่งเดือนล่าสุดที่เลือกไว้ ไม่รีเซ็ตกลับเดือนปัจจุบัน
        #    เรียงถอยหลังแล้วเป้าหมายถัดไปจะอยู่ "ก่อน" ตำแหน่งปัจจุบันเสมอ
        #    จึงใช้แต่ปุ่มย้อน ไม่ต้องแตะปุ่มเดินหน้า (ซึ่งยังไม่รู้ว่า nth ไหนคือเดือน)
        todo = [(a, b) for a, b in sorted(PERIODS, reverse=True)
                if f"{shop_id}|{stamp(a, b)}" not in st["requested"]
                and f"{shop_id}|{stamp(a, b)}" not in st["collected"]]
        if not todo:
            print(f"\n{shop_id}: สั่งครบแล้ว ข้าม")
            continue

        print(f"\n{shop_id} — {s.display_name} ({len(todo)} เดือน)", flush=True)
        adapter = build_adapter(s, cfg.settings)
        try:
            page = open_shop(adapter)
            for a, b in todo:
                try:
                    request_one(adapter, page, a, b, lambda m: print(m, flush=True))
                    st["requested"].append(f"{shop_id}|{stamp(a, b)}")
                    save_state(st)
                    print(f"   ✅ สั่งแล้ว {a:%Y-%m}", flush=True)
                except Exception as exc:                  # noqa: BLE001
                    print(f"   ❌ {a:%Y-%m} สั่งไม่ได้: {type(exc).__name__}: {exc}", flush=True)
                    adapter._screenshot_on_error(page, f"request_{shop_id}_{a:%Y%m}")
                time.sleep(2)
        except Exception as exc:                          # noqa: BLE001
            print(f"   ❌ เปิดร้านไม่ได้: {exc}")
            traceback.print_exc()
        finally:
            adapter.close()                               # ต้องปิดแบบนี้เสมอ ไม่งั้น cookie หาย
        time.sleep(3)


# ── เฟส 2: วนเก็บไฟล์ที่พร้อมแล้ว ────────────────────────────

def collect_shop(adapter, page, shop_id: str, st: dict) -> int:
    """โหลดไฟล์ที่พร้อมของร้านนี้ คืนจำนวนที่โหลดได้รอบนี้"""
    got = 0
    missing_from_history: list[tuple[date, date]] = []
    _click_first(page, SEL["history_btn"], 8000)
    page.wait_for_timeout(3000)

    for a, b in PERIODS:
        key = f"{shop_id}|{stamp(a, b)}"
        if key in st["collected"]:
            continue
        want = stamp(a, b)
        label = next((n for n in adapter._report_names(page) if want in n), None)
        if not label:
            # ไม่มีบรรทัดนี้ในประวัติ = ยังไม่ได้สั่ง หรือไฟล์หมดอายุไปแล้ว
            # ต้องพิมพ์บอก ไม่งั้นรอบจะจบเงียบ ๆ แล้วดูเหมือนไม่มีอะไรผิด
            print(f"   ·  {a:%Y-%m} ไม่มีในประวัติการดาวน์โหลด", flush=True)
            missing_from_history.append((a, b))
            continue
        btn = adapter._try_row_download_button(page, label)
        if btn is None:                                   # ยังเป็นสปินเนอร์ = ยังไม่เสร็จ
            print(f"   ⏳ {a:%Y-%m} Shopee ยังปั่นไฟล์ไม่เสร็จ", flush=True)
            continue
        try:
            src = adapter._capture_download(page, btn.click, timeout_ms=180_000)
            dest = RAW / f"{shop_id}_{a:%Y%m}{Path(src).suffix}"
            RAW.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), dest)
            st["collected"][key] = str(dest.relative_to(PROJECT_ROOT))
            save_state(st)
            got += 1
            print(f"   ⬇  {a:%Y-%m} → {dest.name}", flush=True)
        except Exception as exc:                          # noqa: BLE001
            print(f"   ⚠️ {a:%Y-%m} โหลดไม่สำเร็จ: {exc}", flush=True)
        page.wait_for_timeout(2000)

    # สั่ง export ใหม่ให้เดือนที่หายไปจากประวัติ — ไฟล์ของ Shopee มีวันหมดอายุ
    # ถ้าไม่สั่งใหม่ รอบถัดไปก็จะไม่เจอเหมือนเดิม วนฟรีจนครบ rounds แล้วจบเงียบ ๆ
    if missing_from_history:
        print(f"   ↻ สั่ง export ใหม่ {len(missing_from_history)} เดือนที่หมดอายุ", flush=True)
        goto_retry(page, adapter.orders_url)
        page.wait_for_timeout(6000)
        for a, b in missing_from_history:
            try:
                request_one(adapter, page, a, b, lambda m: print(f"      {m}", flush=True))
                st["requested"].append(f"{shop_id}|{stamp(a, b)}")
                save_state(st)
            except Exception as exc:                      # noqa: BLE001
                print(f"   ⚠️ สั่ง {a:%Y-%m} ไม่สำเร็จ: {exc}", flush=True)
            close_modal(page)
            page.wait_for_timeout(2000)
    return got


def collected_in_scope(st: dict) -> int:
    """นับเฉพาะไฟล์ของร้านที่กำลังทำอยู่รอบนี้

    ⚠️ ห้ามใช้ len(st["collected"]) ตรง ๆ — มันนับรวมทุกร้านที่เคยเก็บมาทั้งหมด
       ตอนรันเฉพาะ 2 ร้าน (เป้า 14) แต่ของเก่ามีอยู่ 28 ไฟล์ จะเข้าเงื่อนไข 28 >= 14
       แล้วออกจากลูปทันทีโดยไม่เก็บอะไรเลย (เจอจริง 2026-08-05 กับ shopee_03/08)
    """
    return sum(1 for k in st["collected"] if k.split("|")[0] in SHOP_IDS)


def phase_collect(cfg, st: dict, rounds: int, wait_min: int) -> None:
    print("\n===== เฟส 2: เก็บไฟล์ =====", flush=True)
    total_want = len(SHOP_IDS) * len(PERIODS)
    for rnd in range(1, rounds + 1):
        have = collected_in_scope(st)
        if have >= total_want:
            break
        print(f"\n--- รอบที่ {rnd} (ได้แล้ว {have}/{total_want}) ---", flush=True)
        for shop_id in SHOP_IDS:
            if all(f"{shop_id}|{stamp(a, b)}" in st["collected"] for a, b in PERIODS):
                continue
            s = cfg.shop(shop_id)
            print(f"\n{shop_id} — {s.display_name}", flush=True)
            adapter = build_adapter(s, cfg.settings)
            try:
                page = open_shop(adapter, s.web_name)
                collect_shop(adapter, page, shop_id, st)
            except Exception as exc:                      # noqa: BLE001
                print(f"   ❌ {exc}")
                traceback.print_exc()
            finally:
                adapter.close()
            time.sleep(3)

        have = collected_in_scope(st)
        if have >= total_want:
            break
        if rnd < rounds:
            print(f"\n   ได้ {have}/{total_want} — รอ {wait_min} นาทีแล้วลองใหม่", flush=True)
            time.sleep(wait_min * 60)


# ── เฟส 3: รวมเป็น Excel ร้านละไฟล์ ──────────────────────────

def read_any(adapter, path: Path) -> list[dict]:
    """อ่านไฟล์ Export — รองรับทั้ง .xlsx เดี่ยว และ .zip ที่ข้างในถูกตัดเป็นหลายส่วน

    ⚠️ เดือนที่ข้อมูลเยอะ Shopee จะตัดเป็น part_1_of_N แล้วบีบเป็น zip มาให้
       ต้องแตกแล้วอ่านทุกส่วน ไม่งั้นข้อมูลหายทั้งเดือนแบบเงียบ ๆ
    """
    if path.suffix.lower() != ".zip":
        return adapter.map.read_export(path)

    rows: list[dict] = []
    out = path.with_suffix("")                           # แตกไว้ข้าง ๆ ไฟล์เดิม
    out.mkdir(exist_ok=True)
    with zipfile.ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith((".xlsx", ".xls", ".csv"))]
        for n in sorted(names):                          # เรียงให้ part_1 มาก่อน part_2
            target = out / Path(n).name
            if not target.exists():
                with zf.open(n) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
            rows.extend(adapter.map.read_export(target))
    return rows


def phase_merge(cfg, st: dict) -> None:
    print("\n===== เฟส 3: รวมไฟล์ =====", flush=True)
    BASE.mkdir(parents=True, exist_ok=True)
    for shop_id in SHOP_IDS:
        s = cfg.shop(shop_id)
        adapter = build_adapter(s, cfg.settings)
        merged: dict[str, Order] = {}
        used = 0
        for a, b in PERIODS:
            key = f"{shop_id}|{stamp(a, b)}"
            rel = st["collected"].get(key)
            if not rel:
                continue
            path = PROJECT_ROOT / rel
            try:
                rows = read_any(adapter, path)
                for o in adapter.normalize(rows):
                    merged[f"{o.order_id}|{o.sku}"] = o    # กันซ้ำข้ามเดือน
                used += 1
            except Exception as exc:                      # noqa: BLE001
                print(f"   ⚠️ {shop_id} {a:%Y-%m} อ่านไม่ได้: {exc}")
        adapter.close()

        if not merged:
            print(f"  {shop_id}: ไม่มีข้อมูล ข้าม")
            continue
        path = export_shop(
            list(merged.values()),
            shop_id=shop_id, platform=s.platform, shop_name=s.display_name,
            run_date="2026-01_ถึง_2026-07",
            date_from="2026-01-01", date_to="2026-07-31",
            output_dir=BASE, archive_dir=BASE / "_archive",
            notes=f"รวมจากไฟล์รายเดือน {used}/{len(PERIODS)} เดือน",
        )
        print(f"  {shop_id}: {len(merged):,} ออเดอร์ จาก {used}/7 เดือน → {path.name}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", choices=["request", "collect", "merge", "all"], default="all")
    ap.add_argument("--rounds", type=int, default=8, help="เฟสเก็บ วนกี่รอบ")
    ap.add_argument("--wait", type=int, default=12, help="เฟสเก็บ รอกี่นาทีระหว่างรอบ")
    ap.add_argument("--only-shop", help="จำกัดเฉพาะร้านที่ระบุ คั่นหลายร้านด้วย ,")
    ap.add_argument("--only-month", type=int, help="ทดสอบเดือนเดียว (1-7)")
    args = ap.parse_args()

    # จำกัดขอบเขตตอนทดสอบ — จะได้รู้เร็วว่าปฏิทินเลื่อนถูกไหม
    # ไม่ต้องรอเป็นชั่วโมงแล้วมาพบว่าพังตั้งแต่เดือนแรก
    global SHOP_IDS, PERIODS
    if args.only_shop:
        SHOP_IDS = [s.strip() for s in args.only_shop.split(",") if s.strip()]
    if args.only_month:
        PERIODS = [PERIODS[args.only_month - 1]]

    cfg = load_config()
    setup_logging(PROJECT_ROOT / cfg.settings.paths.logs_dir, "shopee_backfill")
    BASE.mkdir(parents=True, exist_ok=True)
    st = load_state()

    if args.phase in ("request", "all"):
        phase_request(cfg, st)
    if args.phase in ("collect", "all"):
        phase_collect(cfg, st, args.rounds, args.wait)
    if args.phase in ("merge", "all"):
        phase_merge(cfg, st)

    # ⚠️ ต้องนับด้วย collected_in_scope ไม่ใช่ len(st["collected"])
    #    ของเก่าจากร้านอื่นทำให้ตัวเลขเกินเป้าจนดูเหมือนเสร็จ (เคยพิมพ์ "39/14")
    have, want = collected_in_scope(st), len(SHOP_IDS) * len(PERIODS)
    print(f"\nสรุป: เก็บได้ {have}/{want} ไฟล์ (เฉพาะร้านที่รันรอบนี้)")
    print(f"ไฟล์อยู่ที่ {BASE}")

    if args.phase in ("collect", "all") and have < want:
        # exit code ต้องไม่ใช่ 0 — ไม่งั้นงานที่เก็บไม่ครบจะดู "สำเร็จ" แล้วเงียบหายไป
        missing = [f"{sid}|{stamp(a, b)[:6]}"
                   for sid in SHOP_IDS for a, b in PERIODS
                   if f"{sid}|{stamp(a, b)}" not in st["collected"]]
        print(f"❌ ยังขาด {len(missing)} ไฟล์: {missing}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
