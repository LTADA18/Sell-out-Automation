# ต่ออายุ session ก่อนหมด — กันไม่ให้ต้องล็อกอินใหม่ (และไม่ต้องขอ OTP)
#
# session ของ TikTok อยู่ได้ประมาณ 24 ชั่วโมง ส่วนรอบรายวันห่างกัน 24 ชม. เป๊ะ
# จึงนั่งอยู่บนเส้นแบ่งพอดี เป็นการโยนหัวก้อยทุกวัน
# ตัวนี้แตะกลางวันหนึ่งครั้ง อายุ session จึงไม่มีวันแตะ 24 ชม.
#
# ⚠️ ไฟล์นี้ต้องเซฟเป็น UTF-8 with BOM (กฎเหล็กข้อ 6)

param(
    [string]$Platform = "tiktok",
    [double]$MaxAge = 8.0
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "ไม่พบ .venv — รัน .\setup.ps1 ก่อน" -ForegroundColor Red
    exit 4
}

Write-Host "ต่ออายุ session $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
& $py -u scripts\keepalive.py --platform $Platform --max-age $MaxAge
exit 0
