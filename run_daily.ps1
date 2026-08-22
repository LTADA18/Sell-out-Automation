# รอบประจำวัน — ใช้กับ Windows Task Scheduler ได้เลย
#
#   .\run_daily.ps1                          ดึงทุกร้าน (ข้อมูลของเมื่อวาน)
#   .\run_daily.ps1 -Shop lazada_01          ดึงร้านเดียว
#   .\run_daily.ps1 -Platform lazada         ดึงทั้งแพลตฟอร์ม
#   .\run_daily.ps1 -Date 2026-08-01         ระบุวันที่ของรอบเอง
#
# exit code: 0 = ครบทุกร้าน, 1 = มีร้านที่ล้มเหลว, 2 = มีรอบอื่นรันอยู่

param(
    [string]$Shop,
    [string]$Platform,
    [string]$Date,
    [switch]$SkipIfDone,
    # ข้ามขั้นตรวจความพร้อม — ใช้ตอนสั่งดึงร้านเดียวซ้ำ ๆ จะได้ไม่เสียเวลา
    [switch]$SkipPreflight,
    # ข้ามขั้นสกรีน SKU — ใช้ตอนอยากได้ไฟล์ดิบอย่างเดียว
    [switch]$SkipScreen,
    # ส่งอีเมลท้ายรอบ = การันตีว่าอีเมลออกหลังดึงเสร็จเสมอ
    # (เครื่องเป็นโน้ตบุ๊ก เปิด 8 โมง รอบดึงจะเริ่มตอนล็อกอิน ไม่ใช่ตี 6
    #  ถ้าตั้งอีเมลตามนาฬิกาจะส่งตอนข้อมูลยังไม่ครบ)
    [switch]$Mail,
    # ⚠️ ห้ามใส่รายชื่อผู้รับไว้ที่นี่ — send_report.ps1 เป็นเจ้าของรายชื่อที่เดียว
    #    ของเดิมไฟล์นี้มีรายชื่อ CC ของตัวเอง 4 คน แยกจาก send_report ที่มี 20 คน
    #    พอเจ้าของงานสั่งเพิ่มคนใหม่ 2026-08-13 แก้แค่ send_report ไฟล์เดียว
    #    อีเมลรายวันจึงส่งถึงแค่ 5 คนมาตลอด โดยไม่มีใครรู้ (เจอ 2026-08-19)
    #    ใส่ค่าที่นี่ได้เฉพาะเวลาจงใจส่งหาคนอื่นเป็นครั้งคราว ไม่ใช่รายชื่อประจำ
    [string]$MailTo = "",
    [string]$MailCc = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "ไม่พบ .venv — รัน .\setup.ps1 ก่อน" -ForegroundColor Red
    exit 4
}

# ── ขั้นแรก: ตรวจความพร้อม + ซ่อมให้เองถ้าเจอว่าเสี่ยง ──────────
#
# ปิดช่องสุดท้ายที่เหลืออยู่: ถ้าเครื่องปิดทั้ง 13:00 และ 20:00
# keepalive ที่ตั้งเวลาไว้จะไม่ได้ทำงานเลย พอถึง 08:30 session ก็อายุ ~24 ชม.
# ซึ่งคือเส้นตายที่วัดได้จริง (23.8 ตาย / 21.0 รอด)
#
# ⚠️ ห้ามให้ขั้นนี้ทำให้รอบดึงล้ม — ถ้า preflight พังหรือซ่อมไม่ได้ ก็ต้องดึงต่อ
#    ร้านที่ยังดึงได้ต้องได้ข้อมูล ไม่ใช่หยุดทั้งรอบเพราะร้านเดียวมีปัญหา
if (-not $SkipPreflight) {
    Write-Host "── ตรวจความพร้อมก่อนดึง ──" -ForegroundColor Cyan
    try {
        & $py -u scripts\preflight.py
        if ($LASTEXITCODE -ne 0) {
            Write-Host "preflight เจอปัญหาที่ซ่อมเองไม่ได้ — ดึงต่อไปก่อน แล้วดูรายละเอียดด้านบน" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "รัน preflight ไม่สำเร็จ (ไม่กระทบการดึง): $_" -ForegroundColor Yellow
    }
    Write-Host ""
}

$cliArgs = @("-m", "src.cli", "run")
if     ($Shop)     { $cliArgs += @("--shop", $Shop) }
elseif ($Platform) { $cliArgs += @("--platform", $Platform) }
else               { $cliArgs += "--all" }
if ($Date) { $cliArgs += @("--date", $Date) }
if ($SkipIfDone) { $cliArgs += "--skip-if-done" }

# ⚠️ รอล็อกแทนที่จะยอมแพ้ทันที (เจอจริง 2026-08-22 เสียยอดทั้งวัน)
#    เครื่องเป็นโน้ตบุ๊ก วันนั้นตื่นสายตอน 08:58 งานที่ค้างไว้ยิงพร้อมกันทั้ง
#    รอบดึงและ KeepAlive (ตั้ง StartWhenAvailable ทั้งคู่) KeepAlive คว้าล็อก
#    ไปก่อน รอบดึงเจอล็อกไม่ว่างแล้วออกทันทีด้วย exit 2 — ไม่ได้ดึงเลยสักร้าน
#    ทั้งที่ตัวที่ถือล็อกใช้เวลาแค่ไม่กี่นาทีแล้วปล่อยเอง
#
#    20 นาทีพอสำหรับ keepalive ครบทุกร้าน (รอบเต็มใช้ราว 8-10 นาที)
#    ถ้าเกินนั้นแปลว่าตัวที่ถือล็อกค้างจริง ค่อยยอมแพ้แล้วรายงาน exit 2 ตามเดิม
$cliArgs += @("--wait-lock", "20")

$started = Get-Date
Write-Host "เริ่มรอบ $($started.ToString('yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture))" -ForegroundColor Cyan

& $py @cliArgs
$code = $LASTEXITCODE

$mins = [math]::Round(((Get-Date) - $started).TotalMinutes, 1)
Write-Host "ใช้เวลา $mins นาที (exit $code)" -ForegroundColor Cyan

# สร้าง Dashboard ทุกครั้ง — โดยเฉพาะรอบที่พังยิ่งต้องมี ไม่งั้นเช้ามาไม่รู้ว่าติดตรงไหน
# ห้ามให้ขั้นนี้ทำให้ exit code ของรอบเพี้ยน: เก็บ $code ไว้ก่อนแล้วคืนค่าเดิมเสมอ
try {
    & $py -m src.cli dashboard | Out-Null
    Write-Host "Dashboard: output\dashboard.html" -ForegroundColor Cyan
} catch {
    Write-Host "สร้าง Dashboard ไม่สำเร็จ (ไม่กระทบผลการดึง): $_" -ForegroundColor Yellow
}

# ── สกรีน SKU ต่อจากรอบดึง ────────────────────────────────────
#
# ของส่งมอบจริงคือไฟล์ 63 คอลัมน์ที่ผ่านการสกรีนแล้ว ไม่ใช่ไฟล์ดิบ 32 คอลัมน์
# (เจ้าของงานยืนยัน 2026-08-10) ไฟล์ดิบยังต้องมีเพราะเป็น input ของตัวสกรีน
#
# ⚠️ ห้ามให้ขั้นนี้ทำให้ exit code ของรอบดึงเพี้ยน — ดึงสำเร็จก็คือสำเร็จ
#    ถ้าสกรีนพัง อีเมลจะถอยไปแนบไฟล์ดิบให้เอง (ดู collect_attachments)
#    ส่งของที่มีดีกว่าไม่ส่งอะไรเลย
if (-not $SkipScreen) {
    Write-Host "── สกรีน SKU ──" -ForegroundColor Cyan
    try {
        # ไม่ใส่ --date = ใช้วันนี้ ซึ่งตรงกับชื่อโฟลเดอร์ output ที่รอบดึงเพิ่งสร้าง
        $screenArgs = @("-u", "scripts\screen_orders.py")
        if ($Date) { $screenArgs += @("--date", $Date) }
        & $py @screenArgs
        if ($LASTEXITCODE -ne 0) {
            Write-Host "สกรีนไม่ครบ — อีเมลจะแนบไฟล์ดิบแทน" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "รันตัวสกรีนไม่สำเร็จ (ไม่กระทบผลการดึง): $_" -ForegroundColor Yellow
    }
    Write-Host ""
}

# ครอบ try/catch เหมือน Dashboard: อีเมลไม่ออกไม่ควรทำให้ exit code ของรอบเพี้ยน
if ($Mail) {
    try {
        # เรียก send_report.ps1 แทนการยิง notify เอง — มันเป็นเจ้าของรายชื่อผู้รับ
        # และมีด่านตรวจที่อยู่กับ Exchange ที่ notify ตรง ๆ ไม่มี
        # -SkipIfSent กันส่งซ้ำ ถ้าวันนั้นส่งไปแล้ว (เช่นสั่งรันมือก่อน แล้ว task ยิงตาม)
        $srArgs = @('-SkipIfSent')
        if ($MailTo) { $srArgs += @('-To', $MailTo) }
        if ($MailCc) { $srArgs += @('-Cc', $MailCc) }
        & (Join-Path $PSScriptRoot 'send_report.ps1') @srArgs
    } catch {
        Write-Host "ส่งอีเมลไม่สำเร็จ (ไม่กระทบผลการดึง): $_" -ForegroundColor Yellow
    }
}

exit $code
