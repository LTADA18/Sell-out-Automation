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
    # ⚠️ ไม่รวม Lazada ในรอบนี้ — session ของ Lazada อยู่ได้แค่ ~85 นาที
    #    ต่ออายุวันละ 3 ครั้ง (10:00/16:00/22:00) ก็ตายก่อนถึงรอบถัดไปอยู่ดี
    #
    #    Lazada แยกไปอยู่ task ของตัวเองที่รัน "ทุกชั่วโมง" แทน
    #    (DealerMKP-KeepAlive-Lazada สร้าง 2026-08-13 ตามที่เจ้าของงานสั่ง)
    #    ชั่วโมงละครั้งทำให้อายุ session ไม่มีวันแตะ 85 นาที
    [string]$Platform = "shopee,tiktok",
    # 0 = แตะทุกร้านทุกครั้ง ไม่สนว่า session เพิ่งต่อไปหรือยัง
    #
    # ทำไมไม่ใช้ 8 ชั่วโมงแบบเดิม: การ "แตะ" คือการเปิดหน้าหลังบ้านจริงแล้วเช็คว่ายังล็อกอินอยู่ไหม
    # จึงเป็น "การทดสอบล็อกอิน" ไปในตัว ถ้าข้ามร้านที่ session ยังใหม่
    # เราจะไม่มีวันรู้ว่าร้านนั้นถูกเตะออกจากระบบไปแล้ว
    #
    # เคสจริง 2026-08-10: tiktok_02 ต่ออายุตอน 08:31 แล้วถูกเตะออกภายใน 3 ชั่วโมง
    # (น่าจะมีคนอื่นล็อกอินบัญชีเดียวกัน) ถ้าเช็คแค่ตามอายุจะไม่เห็นเลยจนถึงเช้าวันรุ่งขึ้น
    # แตะทุกร้านใช้เวลาราว 3 นาที ต่อรอบ — คุ้มกับการรู้ล่วงหน้าตั้งแต่กลางวัน
    [double]$MaxAge = 0
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "ไม่พบ .venv — รัน .\setup.ps1 ก่อน" -ForegroundColor Red
    exit 4
}

# ⚠️ ต้องใช้ InvariantCulture — เครื่องตั้งภาษาไทย ปีจะออกมาเป็น พ.ศ.
Write-Host "ต่ออายุ session $([datetime]::Now.ToString('yyyy-MM-dd HH:mm:ss', [Globalization.CultureInfo]::InvariantCulture))" -ForegroundColor Cyan
& $py -u scripts\keepalive.py --platform $Platform --max-age $MaxAge
exit 0
