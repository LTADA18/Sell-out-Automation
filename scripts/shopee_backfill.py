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
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"requested": [], "collected": {}}


def save_state(st: dict) -> None:
    BASE.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")


def open_shop(adapter):
    """เปิดหน้าคำสั่งซื้อของร้าน ผ่านหน้าเลือกร้าน + ปิดทัวร์แนะนำ"""
    page = adapter._open_page(headed=False)
    page.goto(adapter.orders_url, wait_until="domcontentloaded")
    page.wait_for_timeout(9000)
    adapter._enter_shop(page)
    adapter._ensure_logged_in(page, adapter.orders_url)
    adapter._dismiss_onboarding(page)
    return page


# ── เฟส 1: สั่งให้ Shopee ปั่นไฟล์ (ไม่รอ) ────────────────────

TH_MONTHS = ("มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
             "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม")

# ผู้สมัครปุ่ม "ย้อน 1 เดือน" — ต้องลองหลายตัวแล้ววัดผลจริง
# ⚠️ .eds-picker-header__prev ตัวเดียวที่ adapter ใช้อยู่ น่าจะไปโดนปุ่ม "ย้อนปี"
#    กดทีเดียวกระโดด 12 เดือน วนเท่าไหร่ก็ไม่มีทางเจอเดือนที่ต้องการ
PREV_CANDIDATES = [
    ".eds-picker-header__prev-month",
    "button[class*='prev-month']",
    ".eds-picker-header__prev",
]


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


def goto_month(page, target: date, log_fn) -> str:
    """เลื่อนปฏิทินให้แผงซ้ายเป็นเดือนของ target — คืน selector ที่ใช้ได้

    วัดผลจริงหลังกดทุกครั้ง ถ้าขยับ 12 เดือน = กดโดนปุ่มปี ให้เปลี่ยนตัวเลือก
    """
    want = (target.year, target.month)
    chosen = ""

    for sel in PREV_CANDIDATES:
        if page.locator(sel).count() == 0:
            continue
        before = parse_label(panel_label(page, "left"))
        if before is None:
            continue
        if before == want:
            return sel
        try:
            page.locator(sel).first.click(timeout=4000)
        except Exception:                                # noqa: BLE001
            continue
        page.wait_for_timeout(800)
        after = parse_label(panel_label(page, "left"))
        if after is None or after == before:
            continue
        moved = months_between(after, before)            # กดย้อน = before อยู่หลัง after
        log_fn(f"      selector {sel} ขยับ {moved} เดือน")
        if moved == 1:
            chosen = sel
            break
        # ขยับผิดจังหวะ (มักคือ 12 = ปุ่มปี) ดันกลับแล้วลองตัวถัดไป
        fwd = sel.replace("prev", "next")
        if page.locator(fwd).count():
            try:
                page.locator(fwd).first.click(timeout=4000)
                page.wait_for_timeout(800)
            except Exception:                            # noqa: BLE001
                pass

    if not chosen:
        raise RuntimeError("หาปุ่มย้อนเดือนที่ขยับทีละ 1 เดือนไม่เจอ")

    for _ in range(30):
        cur = parse_label(panel_label(page, "left"))
        if cur is None:
            raise RuntimeError("อ่านหัวแผงปฏิทินไม่ได้")
        diff = months_between(cur, want)
        if diff == 0:
            return chosen
        step = chosen if diff < 0 else chosen.replace("prev", "next")
        if page.locator(step).count() == 0:
            raise RuntimeError(f"ไม่มีปุ่ม {step}")
        page.locator(step).first.click(timeout=4000)
        page.wait_for_timeout(700)

    raise RuntimeError(f"เลื่อนไปเดือน {target:%Y-%m} ไม่สำเร็จภายใน 30 ครั้ง")


def close_modal(page) -> None:
    """ปิดกล่องให้สนิทก่อนขึ้นรอบใหม่

    ⚠️ บทเรียนจากรอบแรก: เดือนแรกพังแล้วกล่องค้างเปิด
       เดือนที่เหลือเลยหาปุ่ม "เปิดกล่อง" ไม่เจอ ล้มต่อกันหมดทั้ง 7 เดือน
    """
    for _ in range(3):
        if page.locator(".eds-modal__box").count() == 0:
            return
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)


def request_one(adapter, page, a: date, b: date, log_fn) -> None:
    close_modal(page)
    if not _click_first(page, SEL["open_modal"], 15000):
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
        todo = [(a, b) for a, b in PERIODS
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
    _click_first(page, SEL["history_btn"], 8000)
    page.wait_for_timeout(3000)

    for a, b in PERIODS:
        key = f"{shop_id}|{stamp(a, b)}"
        if key in st["collected"]:
            continue
        want = stamp(a, b)
        label = next((n for n in adapter._report_names(page) if want in n), None)
        if not label:
            continue
        btn = adapter._try_row_download_button(page, label)
        if btn is None:                                   # ยังเป็นสปินเนอร์ = ยังไม่เสร็จ
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
    return got


def phase_collect(cfg, st: dict, rounds: int, wait_min: int) -> None:
    print("\n===== เฟส 2: เก็บไฟล์ =====", flush=True)
    total_want = len(SHOP_IDS) * len(PERIODS)
    for rnd in range(1, rounds + 1):
        have = len(st["collected"])
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
                page = open_shop(adapter)
                collect_shop(adapter, page, shop_id, st)
            except Exception as exc:                      # noqa: BLE001
                print(f"   ❌ {exc}")
            finally:
                adapter.close()
            time.sleep(3)

        have = len(st["collected"])
        if have >= total_want:
            break
        if rnd < rounds:
            print(f"\n   ได้ {have}/{total_want} — รอ {wait_min} นาทีแล้วลองใหม่", flush=True)
            time.sleep(wait_min * 60)


# ── เฟส 3: รวมเป็น Excel ร้านละไฟล์ ──────────────────────────

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
                rows = adapter.map.read_export(path)
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
    args = ap.parse_args()

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

    print(f"\nสรุป: สั่งไป {len(st['requested'])} · เก็บได้ {len(st['collected'])}/"
          f"{len(SHOP_IDS) * len(PERIODS)}")
    print(f"ไฟล์อยู่ที่ {BASE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
