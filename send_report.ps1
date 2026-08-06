# ส่งอีเมลสรุปผลการดึงประจำวัน — ใช้กับ Task Scheduler รอบ 08:00
#
#   .\send_report.ps1                       ส่งของรอบล่าสุด
#   .\send_report.ps1 -Date 2026-08-03      ส่งของวันที่ระบุ
#   .\send_report.ps1 -Draft                เปิดร่างให้ตรวจก่อน ไม่ส่งจริง
#   .\send_report.ps1 -To a@b.com           ส่งหาคนอื่นแทน
#
# แยกจาก run_daily.ps1 เพราะรอบดึงจบตี 6 แต่คนเข้างาน 8 โมง
# และเผื่อรอบตี 6 มี retry ยืดเวลาออกไป กว่าจะถึง 8 โมงก็เสร็จแน่นอนแล้ว
#
# exit code: 0 = ส่งแล้ว, 1 = ส่งไม่สำเร็จ, 4 = ไม่พบ .venv

param(
    [string]$Date,
    [string]$To = "Pitchaya.L@imaxpowertool.com",
    # สำเนาถึง — คั่นด้วย , (เพิ่ม 3 คนตามที่เจ้าของงานสั่ง 2026-08-06)
    [string]$Cc = "Natcha.S@imaxpowertool.com,Tanapoom.S@imaxpowertool.com,panupun.s@imaxpowertool.com,Narissa.W@imaxpowertool.com",
    [switch]$NoExcel,
    [switch]$Draft,
    # กันส่งซ้ำ — ถ้ารอบดึงส่งอีเมลของวันนี้ไปแล้ว ให้ออกทันที
    [switch]$SkipIfSent
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "ไม่พบ .venv — รัน .\setup.ps1 ก่อน" -ForegroundColor Red
    exit 4
}

# สร้าง Dashboard ใหม่ก่อนส่งเสมอ — จะได้แนบไฟล์ที่ตรงกับสถานะล่าสุดจริง
try { & $py -m src.cli dashboard | Out-Null } catch { }

$cliArgs = @("-m", "src.cli", "notify", "--to", $To)
if ($Cc)      { $cliArgs += @("--cc", $Cc) }
if ($Date)    { $cliArgs += @("--date", $Date) }
if ($NoExcel)    { $cliArgs += "--no-excel" }
if ($Draft)      { $cliArgs += "--draft" }
if ($SkipIfSent) { $cliArgs += "--skip-if-sent" }

Write-Host "ส่งสรุปผลการดึง $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
& $py @cliArgs
$code = $LASTEXITCODE

if ($code -ne 0) {
    Write-Host "ส่งอีเมลไม่สำเร็จ (exit $code)" -ForegroundColor Red
}
exit $code
