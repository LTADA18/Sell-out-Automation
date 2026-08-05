# ดูความคืบหน้าการดึงข้อมูลแบบสด ๆ
#
#   .\watch_run.ps1              ดูรอบของวันนี้
#   .\watch_run.ps1 -Date 2026-08-05
#
# ปิดหน้าต่างนี้ได้ตลอด ไม่กระทบการดึง — เป็นแค่การอ่านไฟล์ log
# กด Ctrl+C เพื่อหยุดดู

param(
    [string]$Date = (Get-Date -Format 'yyyyMMdd')
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Host.UI.RawUI.WindowTitle = "ดึงข้อมูลสด - Dealer MKP"

$log = Join-Path $PSScriptRoot "logs\run_$Date.txt"
if (-not (Test-Path $log)) {
    # ถ้าไม่มีไฟล์ของวันนั้น ใช้ไฟล์ log ที่เพิ่งถูกเขียนล่าสุดแทน
    $latest = Get-ChildItem (Join-Path $PSScriptRoot "logs") -Filter "*.txt" -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $latest) {
        Write-Host "ไม่พบไฟล์ log" -ForegroundColor Red
        exit 1
    }
    $log = $latest.FullName
}

Write-Host "กำลังดู: $log" -ForegroundColor Cyan
Write-Host "ปิดหน้าต่างนี้ได้ ไม่กระทบการดึง  (Ctrl+C เพื่อหยุด)" -ForegroundColor DarkGray
Write-Host ("-" * 70)

Get-Content -LiteralPath $log -Wait -Tail 40 | ForEach-Object {
    $line = $_
    $color = "Gray"
    if ($line -match 'FAILED|error|Error|❌')      { $color = "Red" }
    elseif ($line -match 'SUCCESS|✅|shop_done')   { $color = "Green" }
    elseif ($line -match 'SKIPPED|⚪')             { $color = "DarkGray" }
    elseif ($line -match 'PARTIAL|🟡|warn')        { $color = "Yellow" }
    elseif ($line -match 'run_start|เริ่มรอบ')      { $color = "Cyan" }

    # ย่อ JSON ให้อ่านง่าย เอาเฉพาะ event กับ shop_id
    if ($line -match '"event":\s*"([^"]+)"') {
        $ev = $matches[1]
        $shop = if ($line -match '"shop_id":\s*"([^"]+)"') { $matches[1] } else { "" }
        $ts = if ($line -match '"timestamp":\s*"[^T]+T(\d{2}:\d{2}:\d{2})') { $matches[1] } else { "" }
        Write-Host ("  {0}  {1,-12} {2}" -f $ts, $shop, $ev) -ForegroundColor $color
    } else {
        Write-Host $line -ForegroundColor $color
    }
}
