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
    # ส่งอีเมลท้ายรอบ = การันตีว่าอีเมลออกหลังดึงเสร็จเสมอ
    # (เครื่องเป็นโน้ตบุ๊ก เปิด 8 โมง รอบดึงจะเริ่มตอนล็อกอิน ไม่ใช่ตี 6
    #  ถ้าตั้งอีเมลตามนาฬิกาจะส่งตอนข้อมูลยังไม่ครบ)
    [switch]$Mail,
    [string]$MailTo = "Pitchaya.L@imaxpowertool.com",
    # สำเนาถึง — คั่นด้วย , (เพิ่ม 3 คนตามที่เจ้าของงานสั่ง 2026-08-06)
    [string]$MailCc = "Natcha.S@imaxpowertool.com,Tanapoom.S@imaxpowertool.com,panupun.s@imaxpowertool.com,Narissa.W@imaxpowertool.com"
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

$started = Get-Date
Write-Host "เริ่มรอบ $($started.ToString('yyyy-MM-dd HH:mm:ss'))" -ForegroundColor Cyan

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

# ครอบ try/catch เหมือน Dashboard: อีเมลไม่ออกไม่ควรทำให้ exit code ของรอบเพี้ยน
if ($Mail) {
    try {
        # --only-if-complete: เจ้าของงานสั่ง 2026-08-07 ว่าไม่ครบทุกร้านห้ามส่ง
        # --skip-if-sent    : กันส่งซ้ำ ถ้าวันนั้นมีการส่งไปแล้ว (เช่นสั่งรันมือก่อน
        #                     แล้วตัวตั้งเวลายิงตามอีกรอบ) ผู้รับ 5 คนจะได้ไม่ได้เมลซ้ำ
        & $py -m src.cli notify --to $MailTo --cc $MailCc --only-if-complete --skip-if-sent
    } catch {
        Write-Host "ส่งอีเมลไม่สำเร็จ (ไม่กระทบผลการดึง): $_" -ForegroundColor Yellow
    }
}

exit $code
