"""แปลงไฟล์รายงานโฆษณา → แถวสำหรับ intel.mp_ads_raw

⚠️ กฎเหล็กข้อ 1 ใช้ที่นี่ด้วย — คอลัมน์ไหนไม่มีในไฟล์ ต้องเป็น None
   แล้วเขียนเหตุผลไว้ใน dq_flags ห้ามใส่ 0 แทน เพราะ 0 แปลว่า
   "วัดได้ว่าเป็นศูนย์" ซึ่งคนละความหมายกับ "ไม่มีข้อมูล"
   ถ้าใส่ 0 ค่าเฉลี่ยและ ROAS ที่คำนวณต่อจะเพี้ยนโดยไม่มีอะไรเตือน
"""
from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MAP_FILE = PROJECT_ROOT / "config" / "column_maps" / "shopee_ads.yaml"

# ตัวเลขในไฟล์มาหลายหน้าตา: "4.30%" / "7,936,274.00" / "-" / ""
_NUM_JUNK = re.compile(r"[,\s฿]")


def load_map() -> dict:
    return yaml.safe_load(MAP_FILE.read_text(encoding="utf-8"))


def to_number(raw: Any) -> float | None:
    """แปลงเป็นตัวเลข — คืน None ถ้าไม่มีข้อมูล ห้ามคืน 0

    "-" คือสิ่งที่ Shopee ใส่เมื่อไม่มีค่า ไม่ใช่ค่าศูนย์
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if s in ("", "-", "--", "N/A", "Null"):
        return None
    pct = s.endswith("%")
    s = _NUM_JUNK.sub("", s.rstrip("%"))
    try:
        v = float(s)
    except ValueError:
        return None
    return v / 100 if pct else v


def to_text(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return None if s in ("", "-", "--") else s


def find_header_row(rows: list[list[str]], min_width: int = 5) -> int:
    """หาแถวหัวตาราง = แถวแรกที่กว้างพอ

    ⚠️ ห้ามฝังเลข 8 ไว้ในโค้ด ถึงจะรู้ว่าไฟล์ปัจจุบันหัวอยู่แถว 8
       หัวไฟล์ของ Shopee มี ชื่อร้าน / Shop ID / ช่วงเวลา ซึ่งเพิ่มบรรทัดได้
       ถ้ายึดเลขตายตัวแล้ววันหนึ่งเขาเพิ่มบรรทัด จะอ่านหัวตารางเป็นข้อมูล
       แล้วได้แถวขยะเข้าฐานโดยไม่มีอะไรเตือน
    """
    for i, r in enumerate(rows):
        if len([c for c in r if str(c).strip()]) > min_width:
            return i
    raise ValueError("หาแถวหัวตารางไม่เจอ — ไฟล์อาจไม่ใช่รายงานโฆษณา")


def read_meta(rows: list[list[str]], header_i: int) -> dict[str, str]:
    """อ่านหัวไฟล์ (ชื่อร้าน / Shop ID / ช่วงเวลา) ที่อยู่เหนือหัวตาราง"""
    meta: dict[str, str] = {}
    for r in rows[:header_i]:
        cells = [str(c).strip() for c in r if str(c).strip()]
        if len(cells) >= 2:
            meta[cells[0]] = cells[1]
        elif len(cells) == 1 and ":" in cells[0]:
            k, _, v = cells[0].partition(":")
            meta[k.strip()] = v.strip()
    return meta


def parse_period(meta: dict[str, str]) -> tuple[date | None, date | None]:
    """ช่วงวันที่จากหัวไฟล์ เช่น "01/07/2026 - 31/07/2026" """
    raw = meta.get("ระยะเวลา") or meta.get("Period") or ""
    m = re.findall(r"(\d{2})/(\d{2})/(\d{4})", raw)
    if len(m) != 2:
        return None, None
    out = []
    for d, mo, y in m:
        try:
            out.append(date(int(y), int(mo), int(d)))
        except ValueError:
            return None, None
    return out[0], out[1]


def parse_shopee_ads(path: Path, shop_id: str, platform: str = "shopee") -> list[dict]:
    """อ่านไฟล์ CSV รายงานโฆษณา Shopee → list ของแถวพร้อมโหลดขึ้นฐาน"""
    cfg = load_map()
    fields: dict[str, list[str]] = cfg["fields"]

    text = path.read_text(encoding=cfg["file"].get("encoding", "utf-8-sig"),
                          errors="replace")
    rows = [r for r in csv.reader(io.StringIO(text))]
    if not rows:
        raise ValueError(f"ไฟล์ว่าง: {path.name}")

    header_i = find_header_row(rows)
    header = [str(c).strip() for c in rows[header_i]]
    meta = read_meta(rows, header_i)
    p_from, p_to = parse_period(meta)

    # ชื่อคอลัมน์ -> ตำแหน่ง (เทียบแบบตัดช่องว่าง กันไฟล์มีช่องว่างท้ายชื่อ)
    pos = {h.strip(): i for i, h in enumerate(header)}
    missing = [f for f, names in fields.items()
               if not any(n in pos for n in names)]

    # แยกว่าเป็นรายงานแบบไหน จากคอลัมน์ที่มี ไม่ใช่จากชื่อไฟล์
    # (ชื่อไฟล์ Shopee เปลี่ยนรูปแบบมาแล้ว ยึดไม่ได้)
    variant = "keyword" if "Keywords" in pos else "all_ads"

    out: list[dict] = []
    for raw in rows[header_i + 1:]:
        if not any(str(c).strip() for c in raw):
            continue
        rec: dict[str, Any] = {
            "platform": platform,
            "shop_scope": shop_id,
            "source_file": path.name,
            "period_from": p_from,
            "period_to": p_to,
            "captured_dd_mm_yyyy": date.today(),
            "date_collection_method": f"period_total:{variant}",
        }
        for field, names in fields.items():
            col = next((pos[n] for n in names if n in pos), None)
            val = raw[col] if col is not None and col < len(raw) else None
            rec[field] = (to_number(val) if field in NUMERIC else to_text(val))

        # บอกให้ชัดว่าอะไรไม่มีในไฟล์ ไม่ใช่เงียบ ๆ ปล่อยเป็น None ลอย ๆ
        flags = [f"ไม่มีคอลัมน์ {f} ในไฟล์" for f in missing]
        for f in cfg.get("unmapped", []):
            rec.setdefault(f, None)
            flags.append(f"{f} ไม่มีในรายงานนี้")
        rec["dq_flags"] = flags
        out.append(rec)

    return out


NUMERIC = {
    "impressions", "clicks", "ctr", "conversions", "direct_conversions",
    "conv_rate", "cost_per_conv_thb", "items_sold", "gmv_thb",
    "direct_gmv_thb", "expense_thb", "roas", "acos",
}
