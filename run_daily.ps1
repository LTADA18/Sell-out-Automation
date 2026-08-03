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
    [string]$Date
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "ไม่พบ .venv — รัน .\setup.ps1 ก่อน" -ForegroundColor Red
    exit 4
}

$cliArgs = @("-m", "src.cli", "run")
if     ($Shop)     { $cliArgs += @("--shop", $Shop) }
elseif ($Platform) { $cliArgs += @("--platform", $Platform) }
else               { $cliArgs += "--all" }
if ($Date) { $cliArgs += @("--date", $Date) }

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

exit $code
