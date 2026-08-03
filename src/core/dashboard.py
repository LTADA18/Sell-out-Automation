"""สร้าง Dashboard เป็นไฟล์ HTML ไฟล์เดียว — เปิดด้วยเบราว์เซอร์ได้เลย

ทำไมเป็น HTML ไม่ใช่ Streamlit:
  รอบจริงรันตี 6 แล้วเช้ามาเปิดดูว่า "เมื่อคืนร้านไหนพัง" ไม่ได้ต้องโต้ตอบอะไร
  HTML ไม่ต้องลง dependency เพิ่ม ไม่ต้องรัน server ส่งต่อทางแชทได้ทันที

⚠️ Dashboard อ่านจาก data/status.db เท่านั้น ห้ามยิงเว็บหลังบ้านเอง
   (ถ้ายิงเอง ตัวเลขบน Dashboard จะไม่ใช่ตัวเลขที่รอบจริงได้มา)
"""

from __future__ import annotations

import html
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from src.core.models import RETRYABLE, ErrorType, RunStatus

# สี/ไอคอนต้องตรงกับตารางใน CLAUDE.md เป๊ะ ไม่งั้นคนอ่านสองที่แล้วสับสน
STATUS_META: dict[str, tuple[str, str, str]] = {
    RunStatus.SUCCESS.value: ("🟢", "ok", "ครบ"),
    RunStatus.PARTIAL.value: ("🟡", "warn", "ได้ไฟล์แต่ไม่สมบูรณ์"),
    RunStatus.FAILED.value: ("🔴", "bad", "ต้องลงมือแก้"),
    RunStatus.SKIPPED.value: ("⚪", "skip", "ปิดไว้เองใน shops.yaml"),
    RunStatus.RUNNING.value: ("🔵", "run", "กำลังทำงาน"),
}
ORDER = [RunStatus.FAILED.value, RunStatus.RUNNING.value, RunStatus.PARTIAL.value,
         RunStatus.SUCCESS.value, RunStatus.SKIPPED.value]

NO_RETRY_HINT = {
    ErrorType.AUTH_EXPIRED.value: "cookie หมดอายุ — ต้อง login ร้านนี้ใหม่",
    ErrorType.AUTH_REQUIRED.value: "ยังไม่เคย login ร้านนี้",
    ErrorType.NO_PERMISSION.value: "บัญชีไม่มีสิทธิ์ดูคำสั่งซื้อ — ให้เจ้าของร้านเพิ่มสิทธิ์",
}

CSS = """
:root{--bg:#f6f7f9;--card:#fff;--line:#e3e6ea;--fg:#1b1f24;--muted:#697280;
--ok:#1a7f37;--warn:#9a6700;--bad:#cf222e;--skip:#8c959f;--run:#0969da}
@media(prefers-color-scheme:dark){:root{--bg:#0d1117;--card:#161b22;--line:#30363d;
--fg:#e6edf3;--muted:#9198a1;--ok:#3fb950;--warn:#d29922;--bad:#f85149;--skip:#6e7681;--run:#58a6ff}}
*{box-sizing:border-box}
body{margin:0;padding:24px;background:var(--bg);color:var(--fg);
font:15px/1.55 "Segoe UI",system-ui,-apple-system,sans-serif}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}
.sub{color:var(--muted);font-size:13px;margin-bottom:20px}
.kpis{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:22px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:12px 16px;min-width:118px}
.kpi .n{font-size:26px;font-weight:700;line-height:1.1}
.kpi .l{font-size:12px;color:var(--muted);margin-top:2px}
.ok{color:var(--ok)}.warn{color:var(--warn)}.bad{color:var(--bad)}
.skip{color:var(--skip)}.run{color:var(--run)}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;
padding:0;margin-bottom:22px;overflow:hidden}
.card h2{font-size:15px;margin:0;padding:12px 16px;border-bottom:1px solid var(--line)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:13.5px}
th,td{text-align:left;padding:9px 12px;border-bottom:1px solid var(--line);white-space:nowrap}
th{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.03em}
tr:last-child td{border-bottom:none}
td.wrap-cell{white-space:normal;min-width:280px}
.alert{background:color-mix(in srgb,var(--bad) 8%,transparent);
border-left:3px solid var(--bad);padding:12px 16px;border-radius:0 8px 8px 0;margin-bottom:22px}
.alert b{color:var(--bad)}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:11.5px;
border:1px solid var(--line);color:var(--muted)}
.hm td{padding:5px 7px;text-align:center;border:none}
.hm .shop{text-align:left;white-space:nowrap;padding-right:14px}
.dot{display:inline-block;width:15px;height:15px;border-radius:4px}
.legend{padding:10px 16px;color:var(--muted);font-size:12px;
display:flex;gap:16px;flex-wrap:wrap;border-top:1px solid var(--line)}
.empty{padding:26px 16px;color:var(--muted);text-align:center}
footer{color:var(--muted);font-size:12px;text-align:center;margin-top:26px}
"""


def _e(v: object) -> str:
    return html.escape("" if v is None else str(v))


def _dur(sec: float | None) -> str:
    if sec is None:
        return "—"
    return f"{sec:.0f} วิ" if sec < 90 else f"{sec / 60:.1f} นาที"


def _kpis(rows: list[dict]) -> str:
    counts = Counter(r["status"] for r in rows)
    out = []
    for st in ORDER:
        icon, cls, _ = STATUS_META[st]
        out.append(
            f'<div class="kpi"><div class="n {cls}">{counts.get(st, 0)}</div>'
            f'<div class="l">{icon} {st}</div></div>'
        )
    return f'<div class="kpis">{"".join(out)}</div>'


def _action_box(rows: list[dict]) -> str:
    """สิ่งที่ต้องลงมือทำ — แยก 'ยิงซ้ำได้' กับ 'ยิงซ้ำก็ไม่ผ่าน' ออกจากกัน"""
    failed = [r for r in rows if r["status"] == RunStatus.FAILED.value]
    if not failed:
        return ""
    items = []
    for r in failed:
        et = r.get("error_type") or ErrorType.UNKNOWN.value
        try:
            retry_ok = ErrorType(et) in RETRYABLE
        except ValueError:
            retry_ok = False
        hint = NO_RETRY_HINT.get(et)
        if hint:
            what = f"{hint} — <code>python -m src.cli login --shop {_e(r['shop_id'])}</code>"
        elif retry_ok:
            what = "ยิงซ้ำได้ (ปัญหาชั่วคราว)"
        else:
            what = "ต้องแก้โค้ด/selector — ดูภาพใน <code>logs/screenshots/</code>"
        items.append(
            f"<li><b>{_e(r['shop_id'])}</b> ({_e(r['shop_name'])}) "
            f'<span class="pill">{_e(et)}</span><br>{what}</li>'
        )
    return (
        f'<div class="alert"><b>ต้องลงมือแก้ {len(failed)} ร้าน</b>'
        f'<ul style="margin:8px 0 0;padding-left:20px">{"".join(items)}</ul></div>'
    )


def _shop_table(rows: list[dict]) -> str:
    if not rows:
        return '<div class="card"><div class="empty">ยังไม่มีข้อมูลของวันนี้</div></div>'

    rank = {s: i for i, s in enumerate(ORDER)}
    body = []
    for r in sorted(rows, key=lambda x: (rank.get(x["status"], 9), x["shop_id"])):
        icon, cls, _ = STATUS_META.get(r["status"], ("❔", "", ""))
        err = r.get("error_message") or ""
        if r.get("error_type"):
            err = f'<span class="pill">{_e(r["error_type"])}</span> {_e(err)[:170]}'
        body.append(
            "<tr>"
            f'<td class="{cls}">{icon} {_e(r["status"])}</td>'
            f'<td><b>{_e(r["shop_id"])}</b></td>'
            f'<td>{_e(r["shop_name"])}</td>'
            f'<td>{_e(r["platform"])}</td>'
            f'<td style="text-align:right">{r.get("orders_fetched") or 0:,}</td>'
            f'<td style="text-align:right">{r.get("rows_written") or 0:,}</td>'
            f'<td>{_dur(r.get("duration_sec"))}</td>'
            f'<td>{_e((r.get("finished_at") or "")[11:19])}</td>'
            f'<td class="wrap-cell">{err or "—"}</td>'
            "</tr>"
        )
    return (
        '<div class="card"><h2>สถานะรายร้าน</h2><div class="scroll"><table>'
        "<tr><th>สถานะ</th><th>ร้าน</th><th>ชื่อ</th><th>แพลตฟอร์ม</th>"
        "<th>ออเดอร์</th><th>แถว</th><th>ใช้เวลา</th><th>เสร็จ</th><th>ข้อผิดพลาด</th></tr>"
        f'{"".join(body)}</table></div></div>'
    )


def _heatmap(hist: list[dict], days: int) -> str:
    if not hist:
        return ""
    dates = sorted({r["run_date"] for r in hist})[-days:]
    shops: dict[str, str] = {}
    for r in hist:
        shops.setdefault(r["shop_id"], r["shop_name"])
    cell = {(r["shop_id"], r["run_date"]): r for r in hist}

    head = "".join(f'<td style="color:var(--muted);font-size:10px">{d[5:]}</td>' for d in dates)
    body = []
    for shop_id in sorted(shops):
        tds = []
        for d in dates:
            r = cell.get((shop_id, d))
            if r is None:
                tds.append('<td><span class="dot" style="background:var(--line)"></span></td>')
                continue
            _, cls, _lbl = STATUS_META.get(r["status"], ("", "skip", ""))
            title = f'{d} {r["status"]} · {r.get("orders_fetched") or 0} ออเดอร์'
            tds.append(
                f'<td><span class="dot" style="background:var(--{cls})" '
                f'title="{_e(title)}"></span></td>'
            )
        body.append(f'<tr><td class="shop">{_e(shop_id)}</td>{"".join(tds)}</tr>')

    legend = " ".join(
        f'<span><span class="dot" style="background:var(--{cls});vertical-align:-2px"></span> '
        f"{icon} {st}</span>"
        for st in ORDER
        for icon, cls, _ in [STATUS_META[st]]
    )
    return (
        f'<div class="card"><h2>ย้อนหลัง {len(dates)} วัน</h2>'
        f'<div class="scroll"><table class="hm">'
        f'<tr><td class="shop"></td>{head}</tr>{"".join(body)}</table></div>'
        f'<div class="legend">{legend}<span>'
        '<span class="dot" style="background:var(--line);vertical-align:-2px"></span> '
        "ไม่มีข้อมูล</span></div></div>"
    )


def render(rows: list[dict], hist: list[dict], run_date: str, days: int = 14) -> str:
    ok = sum(1 for r in rows if r["status"] in
             (RunStatus.SUCCESS.value, RunStatus.PARTIAL.value))
    title = f"สถานะการดึงออเดอร์ {run_date}"
    return (
        f'<!doctype html><html lang="th"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_e(title)}</title><style>{CSS}</style></head><body><div class='wrap'>"
        f"<h1>{_e(title)}</h1>"
        f'<div class="sub">สำเร็จ {ok}/{len(rows)} ร้าน · '
        f'สร้างเมื่อ {datetime.now():%Y-%m-%d %H:%M:%S}</div>'
        f"{_kpis(rows)}{_action_box(rows)}{_shop_table(rows)}{_heatmap(hist, days)}"
        f"<footer>อ่านจาก data/status.db — ไม่ได้ยิงเว็บหลังบ้านซ้ำ</footer>"
        f"</div></body></html>"
    )


def build(db_path: Path, out_path: Path, run_date: str | None = None, days: int = 14) -> Path:
    """อ่าน status.db แล้วเขียนไฟล์ HTML — คืน path ที่เขียน

    ไม่ใช้ StatusStore เพื่อจะได้เปิดแบบ read-only ได้ ไม่ไปชนกับรอบที่กำลังรันอยู่
    """
    db_path, out_path = Path(db_path), Path(out_path)
    if not db_path.exists():
        raise FileNotFoundError(f"ยังไม่มี {db_path} — ต้องรัน `python -m src.cli run` อย่างน้อย 1 รอบก่อน")

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        if run_date is None:
            row = conn.execute("SELECT MAX(run_date) AS d FROM run_log").fetchone()
            run_date = row["d"] if row and row["d"] else datetime.now().strftime("%Y-%m-%d")
        rows = [dict(r) for r in conn.execute(
            "SELECT * FROM run_log WHERE run_date=? "
            "AND id IN (SELECT MAX(id) FROM run_log WHERE run_date=? GROUP BY shop_id) "
            "ORDER BY platform, shop_id", (run_date, run_date)).fetchall()]
        hist = [dict(r) for r in conn.execute(
            "SELECT * FROM run_log WHERE id IN "
            "(SELECT MAX(id) FROM run_log GROUP BY shop_id, run_date) "
            "ORDER BY run_date, shop_id").fetchall()]
    finally:
        conn.close()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render(rows, hist, run_date, days), encoding="utf-8")
    return out_path
