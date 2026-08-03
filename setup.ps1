# ติดตั้งครั้งเดียว — รันจากโฟลเดอร์โปรเจกต์:  .\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "[1/3] สร้าง .venv" -ForegroundColor Cyan
if (-not (Test-Path ".venv")) { python -m venv .venv }

Write-Host "[2/3] ติดตั้งไลบรารี" -ForegroundColor Cyan
.\.venv\Scripts\python.exe -m pip install --quiet --upgrade pip
.\.venv\Scripts\python.exe -m pip install --quiet -r requirements.txt

Write-Host "[3/3] เตรียมไฟล์ .env" -ForegroundColor Cyan
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "    สร้าง .env จาก .env.example แล้ว (Phase 1 ยังไม่ต้องเติมอะไร)"
} else {
    Write-Host "    มี .env อยู่แล้ว ข้าม"
}

Write-Host ""
Write-Host "เสร็จแล้ว ลองรัน:" -ForegroundColor Green
Write-Host "    .\run_daily.ps1"
Write-Host "    .\.venv\Scripts\python.exe -m src.cli health"
