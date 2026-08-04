"""ส่งสรุปผลการดึงทางอีเมลผ่าน Outlook ที่ล็อกอินอยู่ในเครื่อง

ทำไมใช้ Outlook COM ไม่ใช่ SMTP:
  SMTP ต้องมีรหัสผ่าน/app password เก็บไว้ที่ไหนสักที่ ซึ่งขัดกับหลักของระบบนี้
  ที่ว่า "ไม่เก็บรหัสผ่านไว้ที่ไหนเลย" — COM ยืมสิทธิ์จาก Outlook ที่ล็อกอินอยู่แล้ว

⚠️ ใช้ได้กับ **classic Outlook** เท่านั้น — "new Outlook" ไม่มี COM API
   ถ้าวันหนึ่งถอน classic ออก ต้องเปลี่ยนไปใช้ Microsoft Graph API แทน

⚠️ อีเมลเป็นภาพนิ่ง ณ เวลาที่ส่ง ไม่ใช่ realtime
   ไฟล์ dashboard.html ที่แนบไปจะไม่อัปเดตตัวเองหลังส่ง
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from src.core.models import RunStatus

STATUS_META: dict[str, tuple[str, str]] = {
    RunStatus.SUCCESS.value: ("🟢", "#1a7f37"),
    RunStatus.PARTIAL.value: ("🟡", "#9a6700"),
    RunStatus.FAILED.value: ("🔴", "#cf222e"),
    RunStatus.SKIPPED.value: ("⚪", "#8c959f"),
    RunStatus.RUNNING.value: ("🔵", "#0969da"),
}
ORDER = [RunStatus.FAILED.value, RunStatus.RUNNING.value, RunStatus.PARTIAL.value,
         RunStatus.SUCCESS.value, RunStatus.SKIPPED.value]


def read_rows(db_path: Path, run_date: str | None = None) -> tuple[str, list[dict]]:
    """อ่านสถานะล่าสุดของแต่ละร้านในวันนั้น — เปิดแบบ read-only กันชนกับรอบที่กำลังรัน"""
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
    finally:
        conn.close()
    return run_date, rows


def build_subject(run_date: str, rows: list[dict]) -> str:
    n_ok = sum(1 for r in rows if r["status"] == RunStatus.SUCCESS.value)
    n_bad = sum(1 for r in rows if r["status"] == RunStatus.FAILED.value)
    orders = sum(r["orders_fetched"] or 0 for r in rows)
    head = "⚠️ " if n_bad else ""
    tail = f" · ต้องแก้ {n_bad} ร้าน" if n_bad else ""
    return f"{head}ยอดคำสั่งซื้อ {run_date} — {n_ok}/{len(rows)} ร้าน · {orders:,} ออเดอร์{tail}"


def build_html(run_date: str, rows: list[dict]) -> str:
    """ตารางสรุปฝังในเนื้ออีเมล — เปิดแล้วเห็นเลยไม่ต้องกดไฟล์แนบ

    ใช้ inline style ทั้งหมด เพราะ Outlook ตัด <style> ใน <head> ทิ้ง
    """
    n_ok = sum(1 for r in rows if r["status"] == RunStatus.SUCCESS.value)
    n_bad = sum(1 for r in rows if r["status"] == RunStatus.FAILED.value)
    n_skip = sum(1 for r in rows if r["status"] == RunStatus.SKIPPED.value)
    total_orders = sum(r["orders_fetched"] or 0 for r in rows)

    rank = {s: i for i, s in enumerate(ORDER)}
    body = []
    for r in sorted(rows, key=lambda x: (rank.get(x["status"], 9), x["shop_id"])):
        icon, color = STATUS_META.get(r["status"], ("❔", "#697280"))
        note = r.get("error_message") or ""
        if r["status"] == RunStatus.FAILED.value and r.get("error_type"):
            note = f'<b>{r["error_type"]}</b> — {note[:90]}'
        body.append(
            "<tr>"
            f'<td style="padding:6px 10px;border-bottom:1px solid #e3e6ea;color:{color};'
            f'white-space:nowrap">{icon} {r["status"]}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e3e6ea">'
            f'<b>{r["shop_name"]}</b><br><span style="color:#697280;font-size:12px">'
            f'{r["shop_id"]} · {r["platform"]}</span></td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e3e6ea;text-align:right">'
            f'{r["orders_fetched"]:,}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e3e6ea;text-align:right">'
            f'{r["rows_written"]:,}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e3e6ea;'
            f'color:#697280;font-size:12px">{note or "—"}</td>'
            "</tr>"
        )

    alert = ""
    if n_bad:
        names = ", ".join(f'{r["shop_id"]} ({r.get("error_type") or "?"})'
                          for r in rows if r["status"] == RunStatus.FAILED.value)
        alert = (
            '<p style="background:#ffebe9;border-left:3px solid #cf222e;padding:10px 14px;'
            f'margin:0 0 18px">ต้องลงมือแก้ <b>{n_bad} ร้าน</b>: {names}</p>'
        )

    return f"""<div style="font-family:'Segoe UI',sans-serif;font-size:14px;color:#1b1f24">
<h2 style="margin:0 0 4px">ยอดคำสั่งซื้อประจำวัน {run_date}</h2>
<p style="color:#697280;margin:0 0 18px">
  ดึงสำเร็จ <b>{n_ok}</b> ร้าน · รวม <b>{total_orders:,}</b> ออเดอร์
  {f"· ล้มเหลว {n_bad}" if n_bad else ""}{f" · ข้าม {n_skip}" if n_skip else ""}
  <br>สร้างเมื่อ {datetime.now():%Y-%m-%d %H:%M:%S}
</p>
{alert}
<table style="border-collapse:collapse;font-size:13px">
<tr style="background:#f6f7f9">
  <th style="padding:8px 10px;text-align:left">สถานะ</th>
  <th style="padding:8px 10px;text-align:left">ร้าน</th>
  <th style="padding:8px 10px;text-align:right">ออเดอร์</th>
  <th style="padding:8px 10px;text-align:right">แถว</th>
  <th style="padding:8px 10px;text-align:left">หมายเหตุ</th>
</tr>
{"".join(body)}
</table>
<p style="color:#697280;font-size:12px;margin-top:18px">
  ไฟล์ Excel ของแต่ละร้านและ dashboard.html แนบมาด้วยแล้ว<br>
  ⚠️ ไฟล์แนบเป็นข้อมูล ณ เวลาที่ส่ง ไม่อัปเดตตัวเองภายหลัง
</p>
</div>"""


def collect_attachments(output_dir: Path, run_date: str,
                        with_excel: bool = True) -> list[Path]:
    files: list[Path] = []
    dash = output_dir / "dashboard.html"
    if dash.exists():
        files.append(dash)
    if with_excel:
        files += sorted((output_dir / run_date).glob("*.xlsx"))
    return files


def send(subject: str, html: str, to: list[str], cc: list[str] | None = None,
         attachments: list[Path] | None = None, send_now: bool = True) -> str:
    """ส่ง (หรือเปิดร่าง) ผ่าน Outlook — คืนที่อยู่ผู้ส่งที่ใช้จริง

    send_now=False จะเปิดหน้าต่างร่างให้ตรวจก่อนกดส่งเอง
    """
    import win32com.client as win32

    outlook = win32.Dispatch("Outlook.Application")
    mail = outlook.CreateItem(0)                 # 0 = MailItem
    mail.To = "; ".join(to)
    if cc:
        mail.CC = "; ".join(cc)
    mail.Subject = subject
    mail.HTMLBody = html
    for path in attachments or []:
        mail.Attachments.Add(str(Path(path).resolve()))

    sender = ""
    try:
        sender = outlook.GetNamespace("MAPI").Accounts.Item(1).SmtpAddress
    except Exception:                                    # noqa: BLE001
        pass

    if send_now:
        mail.Send()
    else:
        mail.Display(False)
    return sender
