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
from datetime import date, datetime, time
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


MARK = "[ดึงยอดขาย]"          # ใช้หาว่านัดหมายไหนเป็นของระบบนี้ ตอนลบ/สร้างใหม่


def set_reminders(run_time: str, minutes: list[int]) -> list[str]:
    """สร้างนัดหมายเตือนรายวันในปฏิทิน Outlook — คืนรายการหัวข้อที่สร้าง

    ⚠️ ทำไมใช้ปฏิทินแทนการยิงแจ้งเตือนจากเครื่องนี้:
       สิ่งที่ต้องเตือนคือ "เปิดเครื่อง" แปลว่าตอนต้องเตือน เครื่องนี้ปิดอยู่
       อะไรที่รันบนเครื่องนี้จึงเตือนไม่ได้เลย
       นัดหมายในปฏิทินถูก sync ขึ้น Microsoft 365 ตั้งแต่ตอนสร้าง
       มือถือจะเตือนเองแม้โน้ตบุ๊กปิดสนิท

    สร้างใหม่ทุกครั้ง (ลบของเดิมที่มี MARK ก่อน) เพื่อให้รันซ้ำได้ไม่เกิดนัดซ้อน
    """
    import win32com.client as win32

    _ensure_outlook_running()
    ns = win32.Dispatch("Outlook.Application").GetNamespace("MAPI")
    cal = ns.GetDefaultFolder(9)                         # 9 = Calendar

    # ลบของเดิมก่อน — วนจากท้ายเพราะการลบทำให้ index ขยับ
    items = cal.Items
    for i in range(items.Count, 0, -1):
        try:
            if MARK in (items.Item(i).Subject or ""):
                items.Item(i).Delete()
        except Exception:                                # noqa: BLE001
            continue

    hh, mm = (int(x) for x in run_time.split(":"))
    created: list[str] = []
    app = win32.Dispatch("Outlook.Application")

    for m in sorted(minutes, reverse=True):
        total = hh * 60 + mm - m
        # ⚠️ ต้องส่งเป็น datetime object ไม่ใช่ string
        #    Outlook ภาษาไทยแปลง string วันที่ไม่ได้ ("วัตถุไม่สนับสนุนวิธีการนี้")
        #
        # ใส่ .astimezone() ให้ชัดเจนว่าเป็นเวลาเครื่อง
        # หมายเหตุตอนตรวจสอบ: pywin32 "อ่าน" ค่า .Start กลับมาเป็น UTC
        # ถ้าดูค่าดิบจะเห็นเป็น 01:30 ทั้งที่ของจริงคือ 08:30 ตามเวลาไทย
        # ต้อง .astimezone() ตอนอ่านด้วย ไม่งั้นจะเข้าใจผิดว่าเวลาเพี้ยน
        start_dt = datetime.combine(date.today(), time(total // 60, total % 60)).astimezone()
        subject = f"{MARK} อีก {m} นาที เปิดโน้ตบุ๊กให้ดึงยอดขาย {run_time}"

        appt = app.CreateItem(1)                         # 1 = AppointmentItem
        appt.Subject = subject
        appt.Start = start_dt
        appt.Duration = 5
        appt.BusyStatus = 0                              # 0 = Free ไม่ให้ไปบังตารางงาน
        appt.ReminderSet = True
        appt.ReminderMinutesBeforeStart = 0
        appt.Body = (
            f"ระบบจะเริ่มดึงยอดขายอัตโนมัติเวลา {run_time} น.\n"
            "ขอให้เครื่องเปิดอยู่ เสียบปลั๊ก และล็อกอิน Windows ค้างไว้ (จอล็อกได้)\n\n"
            "ถ้าเปิดไม่ทัน ไม่เป็นไร — ระบบจะดึงให้เองตอนเปิดเครื่อง"
        )

        pattern = appt.GetRecurrencePattern()
        pattern.RecurrenceType = 0                       # 0 = olRecursDaily
        pattern.PatternStartDate = start_dt
        pattern.StartTime = start_dt
        pattern.NoEndDate = True

        appt.Save()
        created.append(f"{start_dt:%H:%M} — เตือนล่วงหน้า {m} นาที")

    return created


def _ensure_outlook_running(wait_sec: int = 40) -> bool:
    """เปิด Outlook ถ้ายังไม่เปิด แล้วรอจนพร้อม

    ⚠️ จำเป็นมาก: mail.Send() แค่หย่อนอีเมลลง Outbox เท่านั้น
    ตัวที่ส่งออกจริงคือโปรเซส Outlook ถ้าไม่เปิดอยู่ อีเมลจะค้างในคิวเงียบ ๆ
    โดยที่โค้ดรายงานว่า "ส่งแล้ว" (เจอจริง 2026-08-04 — Outbox 1 / Sent 0)
    รอบตี 6 ไม่มีใครเปิด Outlook ให้ จึงต้องเปิดเอง
    """
    import subprocess
    import time

    import win32com.client as win32

    try:
        if subprocess.run(["tasklist", "/FI", "IMAGENAME eq OUTLOOK.EXE"],
                          capture_output=True, text=True).stdout.count("OUTLOOK.EXE"):
            return True
    except Exception:                                    # noqa: BLE001
        pass

    for exe in (
        r"C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE",
        r"C:\Program Files (x86)\Microsoft Office\root\Office16\OUTLOOK.EXE",
    ):
        if Path(exe).exists():
            subprocess.Popen([exe], creationflags=0x00000008)   # DETACHED_PROCESS
            break
    else:
        return False

    deadline = time.time() + wait_sec
    while time.time() < deadline:
        time.sleep(3)
        try:
            win32.Dispatch("Outlook.Application").GetNamespace("MAPI").GetDefaultFolder(6)
            return True
        except Exception:                                # noqa: BLE001
            continue
    return False


def flush_outbox(wait_sec: int = 90) -> tuple[int, int]:
    """สั่ง Send/Receive แล้วรอจน Outbox ว่าง — คืน (ค้างก่อน, ค้างหลัง)"""
    import time

    import win32com.client as win32

    ns = win32.Dispatch("Outlook.Application").GetNamespace("MAPI")
    before = ns.GetDefaultFolder(4).Items.Count          # 4 = Outbox
    try:
        ns.SendAndReceive(False)
    except Exception:                                    # noqa: BLE001
        pass

    deadline = time.time() + wait_sec
    while time.time() < deadline:
        if ns.GetDefaultFolder(4).Items.Count == 0:
            return before, 0
        time.sleep(5)
    return before, ns.GetDefaultFolder(4).Items.Count


def send(subject: str, html: str, to: list[str], cc: list[str] | None = None,
         attachments: list[Path] | None = None, send_now: bool = True) -> str:
    """ส่ง (หรือเปิดร่าง) ผ่าน Outlook — คืนที่อยู่ผู้ส่งที่ใช้จริง

    send_now=False จะเปิดหน้าต่างร่างให้ตรวจก่อนกดส่งเอง
    """
    import win32com.client as win32

    if send_now:
        _ensure_outlook_running()

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
        flush_outbox()                                   # ดันออกจาก Outbox ให้จริง
    else:
        mail.Display(False)
    return sender
