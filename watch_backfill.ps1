# ดูงานดึงย้อนหลังแบบสด ๆ — เกาะไฟล์ log ล่าสุด และสลับเองเมื่อมีไฟล์ใหม่
#
#   .\watch_backfill.ps1
#
# ปิดหน้าต่างได้ตลอด ไม่กระทบการดึง เป็นแค่การอ่านไฟล์
# กด Ctrl+C เพื่อหยุดดู

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$Host.UI.RawUI.WindowTitle = "ดึงย้อนหลังสด - Dealer MKP"

Write-Host "เฝ้าดูงานดึงย้อนหลัง (logs\backfill*.txt)" -ForegroundColor Cyan
Write-Host "ปิดหน้าต่างนี้ได้ ไม่กระทบการดึง  (Ctrl+C เพื่อหยุด)" -ForegroundColor DarkGray
Write-Host ("-" * 74)

$current = ""
$pos = 0

while ($true) {
    # หาไฟล์ที่ถูกเขียนล่าสุด — งานเดินไปทีละเฟส ไฟล์จึงเปลี่ยนไปเรื่อย ๆ
    $newest = Get-ChildItem "logs" -Filter "backfill*.txt" -ErrorAction SilentlyContinue |
              Sort-Object LastWriteTime -Descending | Select-Object -First 1

    if (-not $newest) {
        Start-Sleep -Seconds 3
        continue
    }

    if ($newest.FullName -ne $current) {
        $current = $newest.FullName
        $pos = 0
        Write-Host ""
        Write-Host "── กำลังดู: $($newest.Name) ──" -ForegroundColor Cyan
    }

    try {
        $lines = Get-Content -LiteralPath $current -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch { Start-Sleep -Seconds 2; continue }

    if ($lines.Count -gt $pos) {
        foreach ($line in $lines[$pos..($lines.Count - 1)]) {
            # ตัดบรรทัด JSON ยาว ๆ ให้เหลือแค่ที่อ่านรู้เรื่อง
            if ($line -match '"event":\s*"([^"]+)"') {
                $ev = $matches[1]
                if ($ev -notmatch 'shop_done|shop_failed|export_ready|still_building|downloaded|date_range_custom') {
                    continue
                }
                $shop = if ($line -match '"shop_id":\s*"([^"]+)"') { $matches[1] } else { "" }
                $ts = if ($line -match 'T(\d{2}:\d{2}:\d{2})') { $matches[1] } else { "" }
                Write-Host ("  {0}  {1,-12} {2}" -f $ts, $shop, $ev) -ForegroundColor DarkGray
                continue
            }

            $color = "Gray"
            if ($line -match '❌|TIMEOUT|ล้มเหลว|ไม่ได้ข้อมูล') { $color = "Red" }
            elseif ($line -match '✅|⬇')                        { $color = "Green" }
            elseif ($line -match '^===|^──|ลองซ้ำ')             { $color = "Cyan" }
            elseif ($line -match 'รอบ 2|รอ ')                    { $color = "Yellow" }
            Write-Host $line -ForegroundColor $color
        }
        $pos = $lines.Count
    }

    Start-Sleep -Seconds 2
}
