# ต่ออายุ session ก่อนหมด — กันไม่ให้ต้องล็อกอินใหม่ (และไม่ต้องขอ OTP)
#
# session ของ TikTok อยู่ได้ประมาณ 24 ชั่วโมง ส่วนรอบรายวันห่างกัน 24 ชม. เป๊ะ
# จึงนั่งอยู่บนเส้นแบ่งพอดี เป็นการโยนหัวก้อยทุกวัน
# ตัวนี้แตะกลางวันหนึ่งครั้ง อายุ session จึงไม่มีวันแตะ 24 ชม.
#
# ⚠️ ไฟล์นี้ต้องเซฟเป็น UTF-8 with BOM (กฎเหล็กข้อ 6)

param(
    # ครอบ Shopee ด้วย ไม่ใช่แค่ TikTok — ร้าน Shopee ก็ session หมดอายุได้
    # (เพิ่ม shopee เมื่อ 2026-08-09 ตอนเพิ่มร้านใหม่ 3 ร้าน)
    #
    # ⚠️ ไม่รวม Lazada โดยตั้งใจ — session ของ Lazada อยู่ได้แค่ ~85 นาที
    #    ต่ออายุตอน 13:00 ก็ตายก่อนถึง 08:30 อยู่ดี ไม่มีประโยชน์
    #    Lazada พึ่ง auto_relogin ตอนดึงจริงแทน ซึ่งทำงานได้มาตลอด
    [string]$Platform = "shopee,tiktok",
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
