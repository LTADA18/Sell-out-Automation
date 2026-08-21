# โหลดข้อมูลของเมื่อวานขึ้น Postgres — รันหลังส่งอีเมลรายงานประจำวันเสร็จ
#
# ลำดับงานรายวัน
#   08:30  DealerMKP-DailyOrders    ดึงทุกร้านที่เปิดใช้ + สกรีน
#   09:00  DealerMKP-DailyMail      ส่งอีเมลไฟล์ 63 คอลัมน์
#   09:15  DealerMKP-DailyPostgres  ตัวนี้ — โหลดขึ้นฐาน
#
# กันพังเงียบ: ทุกด่านที่ไม่ผ่านคืน exit code ไม่ใช่ 0 และเขียนเหตุผลลง log
#   1 = ไม่มีไฟล์สกรีน / ไม่ครบตามจำนวนร้านที่เปิดใช้ใน shops.yaml
#   2 = export ไม่ผ่าน
#   3 = ซ้อม ROLLBACK ไม่ผ่าน (ฟังก์ชัน RAISE เจอสถานะใหม่ที่ยังไม่รู้จัก)
#   4 = COMMIT ไม่ผ่าน
#   5 = ตรวจหลังโหลดไม่ผ่าน (คีย์ซ้ำ / สถานะไม่ตรง)
#   6 = จำนวนแถวผิดปกติ (0 แถว หรือเกินเพดาน)
#   7 = ต่อฐานข้อมูลไม่ได้ (มักเป็นเพราะยังไม่ได้เปิด VPN)
#
# ⚠️ ไฟล์นี้ต้องเป็น UTF-8 with BOM — PowerShell 5.1 อ่านไฟล์ไม่มี BOM ด้วยโค้ดเพจ 874
#    ภาษาไทยเพี้ยนแล้ว parser พังทั้งไฟล์ (กฎข้อ 6 ใน CLAUDE.md)
[CmdletBinding()]
param(
    [string]$Date,                 # วันของข้อมูล ไม่ใส่ = เมื่อวาน
    [switch]$DryRun,               # ซ้อมอย่างเดียว ไม่ COMMIT
    [int]$MinRows = 100,           # ต่ำกว่านี้ถือว่าผิดปกติ
    [int]$MaxRows = 60000          # สูงกว่านี้ถือว่าผิดปกติ (8/8 ทำได้ 11,118)
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$ROOT    = Split-Path -Parent $PSScriptRoot
$PSQL    = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
$PYTHON  = Join-Path $ROOT '.venv\Scripts\python.exe'
$TEMPLATE= 'C:\Users\tada.p\Postgres\LOAD_day.sql'
$LOGDIR  = Join-Path $ROOT 'output\_pg_logs'

$env:PGPASSFILE      = 'C:\Users\tada.p\Postgres\pgpass.conf'
$env:PGCLIENTENCODING= 'UTF8'
$env:PYTHONIOENCODING= 'utf-8'

$INV = [Globalization.CultureInfo]::InvariantCulture
if (-not $Date) { $Date = [datetime]::Now.AddDays(-1).ToString('yyyy-MM-dd', $INV) }
$runDate = [datetime]::ParseExact($Date,'yyyy-MM-dd',$INV).AddDays(1).ToString('yyyy-MM-dd', $INV)

New-Item -ItemType Directory -Path $LOGDIR -Force | Out-Null
$log = Join-Path $LOGDIR "pg_load_$Date.log"

# เขียนบันทึกลงไฟล์ — ล้มแล้วต้องไม่ฆ่างานหลัก
#
# ⚠️ ของเดิมเรียก Add-Content ตรง ๆ ใต้ ErrorActionPreference = 'Stop'
#    ไฟล์ log ถูกอะไรจับไว้แค่ชั่วขณะ (โปรแกรมเปิดดู log / ตัวเฝ้า / โปรแกรมสำรองข้อมูล)
#    ทั้งรอบจะตายทันที ทั้งที่ข้อมูลไม่มีปัญหาเลย
#    และตายแบบไม่ทิ้งข้อความ เพราะตัวที่ตายคือคำสั่งเขียนบันทึกเอง
#    (เกิดจริง 2026-08-19: รอบ 09:15 ตายกลางคัน ข้อมูลค้างไม่ขึ้นฐาน 50 นาที)
#
#    งานหลักคือโหลดข้อมูล ไม่ใช่เขียนบันทึก — เขียนไม่ได้ก็ข้ามไป
#    แต่ต้องเตือนบนหน้าจอครั้งเดียว ไม่ให้เงียบจนไม่มีใครรู้ว่าบันทึกขาด
$script:LogBroken = $false
function WriteLog([string]$line) {
    try {
        Add-Content -Path $log -Value $line -Encoding utf8 -ErrorAction Stop
    } catch {
        if (-not $script:LogBroken) {
            $script:LogBroken = $true
            Write-Warning "เขียนไฟล์ log ไม่ได้ ($($_.Exception.Message.Split([char]10)[0])) — งานหลักเดินต่อ"
        }
    }
}

function Say([string]$m) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
    Write-Output $line
    WriteLog $line
}

# ── เรียกโปรแกรมภายนอกโดยไม่ให้ stderr ฆ่าสคริปต์ ──────────────────
#
# ⚠️ บน PowerShell 5.1 ถ้า $ErrorActionPreference = 'Stop' แล้วโปรแกรมภายนอก
#    เขียนอะไรลง stderr (แม้แต่ข้อความเตือนธรรมดา) การเรียกแบบ `& exe ... 2>&1`
#    จะกลายเป็น NativeCommandError ซึ่งเป็น terminating error → สคริปต์ตายทันที
#    ตายตรงบรรทัดนั้นเลย จึงไม่ได้เขียน log ว่าเกิดอะไรขึ้น = เงียบสนิท
#
#    เกิดจริง 2 วันติด (2026-08-18 และ 2026-08-19) รอบ 09:15 ตายด้วย exit 1
#    ไม่มีข้อความใด ๆ เพราะตอนนั้นต่อฐานไม่ได้ (VPN ยังไม่ขึ้น) psql จึงเขียน
#    "connection to server failed" ลง stderr แล้วสคริปต์ก็ตายตรงนั้น
#    พอรันเองทีหลังตอน VPN ขึ้นแล้วกลับผ่านทุกครั้ง ทำให้หาสาเหตุยาก
#
#    ตัวนี้ปิด Stop เฉพาะช่วงที่เรียกโปรแกรมภายนอก แล้วคืนค่าเดิมทันที
#    สคริปต์ยังตรวจ exit code เองทุกจุดอยู่แล้ว จึงไม่ได้เสียการดักพลาด
function RunExe([string]$exe, [string[]]$exeArgs) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $exe @exeArgs 2>&1
        $script:LastExe = $LASTEXITCODE
        return $out
    } finally {
        $ErrorActionPreference = $prev
    }
}

# ── ด่าน 0: ฐานต้องต่อได้ก่อนถึงจะเริ่ม ──────────────────────────────
#
# ⚠️ เครื่องเป็นโน้ตบุ๊ก บางวันอยู่นอกออฟฟิศ ต้องรอ VPN ขึ้นก่อน
#    ของเดิมไม่มีด่านนี้ พอต่อไม่ได้ก็ไปตายกลางทางแบบไม่มีใครรู้
#    ตรงนี้รอให้ต่อได้นานสุด 25 นาที เช็คทุก 30 วินาที
#    ถ้าครบเวลาแล้วยังไม่ได้ ค่อยยอมแพ้พร้อมบอกเหตุผลชัด ๆ
# ⚠️ ห้ามใช้ค่าที่ฟังก์ชันคืนกลับมาตัดสิน — Say ข้างในใช้ Write-Output
#    ซึ่งใน PowerShell ทุกอย่างที่เขียนออก output stream จะกลายเป็นค่าที่ฟังก์ชันคืน
#    ค่าที่ได้จึงเป็นข้อความ ไม่ใช่ true/false แล้ว `if (-not (WaitForDb))` จะไม่มีวันจริง
#    ใช้ตัวแปร $script:DbOk แทน ปลอดภัยกว่าและอ่านง่ายกว่า
$script:DbOk = $false
function WaitForDb([int]$maxMinutes = 25) {
    $script:DbWaitMin = $maxMinutes
    $deadline = (Get-Date).AddMinutes($maxMinutes)
    $begin = Get-Date
    $tries = 0
    while ((Get-Date) -lt $deadline) {
        $tries++
        $t = Test-NetConnection -ComputerName '192.168.30.45' -Port 5432 -WarningAction SilentlyContinue
        if ($t.TcpTestSucceeded) {
            if ($tries -gt 1) {
                Say ("ต่อฐานได้แล้ว รอไป {0} วินาที" -f [int]((Get-Date) - $begin).TotalSeconds)
            }
            $script:DbOk = $true
            return
        }
        if ($tries -eq 1) {
            Say "ต่อฐานไม่ได้ - น่าจะยังไม่ได้เปิด VPN รอสูงสุด $maxMinutes นาที"
        } elseif ($tries % 4 -eq 0) {
            Say ("   ยังต่อไม่ได้ รอมาแล้ว {0} วินาที" -f [int]((Get-Date) - $begin).TotalSeconds)
        }
        Start-Sleep -Seconds 30
    }
    $script:DbOk = $false
}

Say "===== โหลดข้อมูลวันที่ $Date (โฟลเดอร์รัน $runDate) ====="

WaitForDb | Out-Null
if (-not $script:DbOk) {
    Say "❌ ต่อฐานข้อมูลไม่ได้เลยหลังรอ $($script:DbWaitMin) นาที - ยังไม่ได้โหลดข้อมูล"
    Say "   ถ้าอยู่นอกออฟฟิศ ต้องเปิด VPN ก่อน แล้วสั่งใหม่ด้วย:"
    Say "   .\scripts\pg_daily_load.ps1 -Date $Date"
    exit 7
}

# ---- ด่าน 1: ไฟล์สกรีนต้องครบ ----
$screened = Join-Path $ROOT "output\$runDate\screened"
if (-not (Test-Path $screened)) {
    Say "❌ ไม่พบโฟลเดอร์ $screened — รอบดึงยังไม่เสร็จหรือล้ม"
    exit 1
}
# ⚠️ ห้ามฝังจำนวนร้านเป็นเลขตายตัว — ของเดิมเขียน 16 ไว้ พอเพิ่มร้านเป็น 18
#    ด่านนี้จะยังผ่านทั้งที่ขาดไป 2 ร้าน (18 ไฟล์ก็ผ่าน 16 ไฟล์ก็ผ่าน)
#    กลายเป็นด่านที่ดูเหมือนตรวจแต่ไม่ได้ตรวจ (แก้ 2026-08-18 ตอนเพิ่ม tiktok_06)
#
#    ตรงนี้อ่านจาก shops.yaml ได้ เพราะสิ่งที่ตรวจคือ "ดึงครบทุกร้านที่เปิดใช้ไหม"
#    ไม่ใช่ "ใครไปแก้ shops.yaml หรือเปล่า" (อันนั้นเป็นหน้าที่ของ preflight.py
#    ซึ่งฝังเลขไว้ตั้งใจ)
$wantShops = & $PYTHON -c "from src.core.config import load_config; print(sum(1 for s in load_config().shops if s.enabled))"
if ($LASTEXITCODE -ne 0 -or -not ($wantShops -match '^\d+$')) {
    Say "❌ อ่านจำนวนร้านที่เปิดใช้จาก shops.yaml ไม่ได้"
    exit 1
}
$wantShops = [int]$wantShops
$matched = @(Get-ChildItem $screened -Filter '*_matched.xlsx' -ErrorAction SilentlyContinue)
if ($matched.Count -ne $wantShops) {
    Say "❌ ไฟล์สกรีนมี $($matched.Count) ร้าน แต่เปิดใช้อยู่ $wantShops ร้าน — ไม่โหลดข้อมูลไม่ครบ"
    exit 1
}
Say "✅ ไฟล์สกรีนครบ $($matched.Count) ร้าน (ตรงกับที่เปิดใช้ใน shops.yaml)"

# ---- ด่าน 2: สร้าง CSV ----
$csvDir = Join-Path $ROOT "output\_pg_day_$Date"
$csv    = Join-Path $csvDir "all_shops_$Date.csv"
Say "กำลังสร้าง CSV..."
$exportOut = RunExe $PYTHON @('-u', (Join-Path $ROOT 'scripts\export_pg_day.py'), '--date', $Date)
$exportOut | ForEach-Object { WriteLog "    $_" }
if ($script:LastExe -ne 0 -or -not (Test-Path $csv)) {
    Say "❌ export ไม่ผ่าน (exit $($script:LastExe))"
    exit 2
}

# ⚠️ ห้ามนับด้วย Measure-Object -Line — บางแถวมีอักขระขึ้นบรรทัดใหม่ฝังอยู่ใน sku
#    1 เรคคอร์ดจึงกินหลายบรรทัด นับแบบนั้นได้ 4,610 ทั้งที่จริงมี 4,603
#    ใช้ตัวเลขที่ export_pg_day.py นับมาให้แทน ซึ่งนับด้วย csv parser จริง
$rows = 0
foreach ($l in $exportOut) {
    if ("$l" -match 'บรรทัดสินค้า\s+([\d,]+)') { $rows = [int]($Matches[1] -replace ',', ''); break }
}
if ($rows -le 0) { Say "❌ อ่านจำนวนแถวจากผล export ไม่ได้"; exit 2 }
Say "✅ CSV $rows บรรทัด"
if ($rows -lt $MinRows -or $rows -gt $MaxRows) {
    Say "❌ จำนวนแถว $rows อยู่นอกช่วง $MinRows-$MaxRows ที่รับได้ — หยุดไว้ก่อน ให้คนมาดู"
    exit 6
}

# ---- เตรียม SQL: \copy ไม่แทนค่าตัวแปรให้ ต้องแทนที่ตัวข้อความเอง ----
$sqlText = [IO.File]::ReadAllText($TEMPLATE).
    Replace('__CSV__', ($csv -replace '\\', '/')).
    Replace('__CSVNAME__', "all_shops_$Date.csv")
$sqlFile = Join-Path $csvDir "LOAD_$Date.sql"
[IO.File]::WriteAllText($sqlFile, $sqlText, (New-Object Text.UTF8Encoding($false)))

# ---- ด่าน 3: ซ้อมด้วย ROLLBACK ----
Say "ซ้อมด้วย ROLLBACK..."
$dry = RunExe $PSQL @('service=osuka-build', '-w', '-P', 'pager=off', '-v', "day=$Date", '-f', $sqlFile)
$dry | ForEach-Object { WriteLog "    $_" }
if ($script:LastExe -ne 0) {
    Say "❌ ซ้อมไม่ผ่าน (exit $($script:LastExe)) — ดูรายละเอียดใน $log"
    Say "   สาเหตุที่พบบ่อย: แพลตฟอร์มเพิ่มคำสถานะใหม่ที่ mp_order_state_v2 ยังไม่รู้จัก"
    exit 3
}
Say "✅ ซ้อมผ่าน"

if ($DryRun) { Say "จบแบบซ้อมอย่างเดียว ไม่ได้เขียนจริง"; exit 0 }

# ---- ด่าน 4: เขียนจริง ----
Say "เขียนจริง COMMIT..."
$real = RunExe $PSQL @('service=osuka-build', '-w', '-P', 'pager=off', '-v', "day=$Date", '-v', 'commit=1', '-f', $sqlFile)
$real | ForEach-Object { WriteLog "    $_" }
if ($script:LastExe -ne 0) {
    Say "❌ COMMIT ไม่ผ่าน (exit $($script:LastExe))"
    exit 4
}

# ---- ด่าน 5: ตรวจหลังโหลด ----
$check = & $PSQL 'service=osuka' -w -A -t -F'|' -c @"
SELECT (SELECT count(*) FROM (SELECT 1 FROM intel.mp_order_line
          WHERE ordered_at::date = DATE '$Date'
          GROUP BY platform, order_id, sku, COALESCE(variation,''), COALESCE(product_name,'')
          HAVING count(*)>1) d),
       (SELECT count(*) FROM intel.mp_order_line
          WHERE ordered_at::date = DATE '$Date'
            AND order_status IS DISTINCT FROM
                intel.mp_order_state_v2(platform,status_raw,paid_at)),
       (SELECT count(*) FROM intel.mp_order_line WHERE ordered_at::date = DATE '$Date')
"@ 2>&1

$parts = ("$check".Trim() -split '\|')
if ($parts.Count -lt 3) { Say "❌ ตรวจหลังโหลดไม่ได้: $check"; exit 5 }
$dup, $bad, $inDb = [int]$parts[0], [int]$parts[1], [int]$parts[2]

Say "ผลในฐาน: $inDb บรรทัด · คีย์ซ้ำ $dup · สถานะไม่ตรง $bad"
if ($dup -ne 0 -or $bad -ne 0) { Say "❌ ตรวจไม่ผ่าน"; exit 5 }
if ($inDb -ne $rows) { Say "⚠️ ในฐาน $inDb แต่ไฟล์ $rows — ต่างกัน $($inDb - $rows) ให้คนมาดู" }

# ---- ด่าน 6: REFRESH matview ที่ Dashboard อ่าน ----
#
# ⚠️ ขาดขั้นตอนนี้มาตลอด — Dashboard ไม่ได้อ่าน mp_order_line ตรง ๆ
#    มันอ่านผ่าน materialized view ซึ่งเป็น "สำเนาแช่แข็ง" ไม่อัปเดตตามเอง
#    ผลคือข้อมูลเข้าฐานครบทุกวันแต่หน้าเว็บค้างอยู่ที่ 10 ส.ค. นาน 6 วัน
#    โดยไม่มีอะไรเตือน (เจอ 2026-08-17 ตอนเจ้าของงานถามว่าทำไมยอดไม่ขึ้น)
#
# ไม่ทำให้ทั้งรอบล้มถ้ารีเฟรชไม่ผ่าน — ข้อมูลเข้าฐานแล้วซึ่งเป็นส่วนสำคัญ
# แต่ต้องเตือนดัง ๆ เพราะถ้าเงียบไปจะกลับไปเป็นปัญหาเดิม
Say "REFRESH matview ที่ Dashboard อ่าน..."
$mv = RunExe $PSQL @('service=osuka-build', '-w', '-P', 'pager=off', '-f', 'C:\Users\tada.p\Postgres\REFRESH_matviews.sql')
$mv | ForEach-Object { WriteLog "    $_" }
if ($script:LastExe -ne 0) {
    Say "⚠️ REFRESH matview ไม่ผ่าน (exit $($script:LastExe)) — ข้อมูลขึ้นฐานแล้วแต่ Dashboard จะยังไม่เห็น"
    $mv | Select-Object -Last 6 | ForEach-Object { Say "    $_" }
} else {
    Say "✅ REFRESH matview เรียบร้อย — Dashboard เห็นข้อมูลใหม่แล้ว"
}

# ---- ด่าน 7: อัปเดตไฟล์ Excel หลักที่เจ้าของงานเปิดดูเอง ----
#
# ⚠️ ต้องอยู่หลังด่าน 6 เสมอ — ตัวนี้อ่านจาก Postgres ถ้ารันก่อนโหลดเสร็จจะได้ยอดเก่า
#
# ไม่ทำให้ทั้งรอบล้มถ้าสร้างไม่ผ่าน — ข้อมูลขึ้นฐานแล้วซึ่งเป็นส่วนสำคัญ
# ไฟล์ Excel เป็นของแถมสำหรับดูเอง สร้างใหม่เมื่อไหร่ก็ได้ด้วยคำสั่งเดียว
#
# ถ้าเจ้าของงานเปิดไฟล์หลักค้างไว้ ตัวสคริปต์จะออกเป็น _ฉบับใหม่.xlsx ให้แทน
# ของเดิมไม่พัง (มันเขียนลงไฟล์ชั่วคราวก่อนแล้วค่อยสลับ)
Say "อัปเดตไฟล์ Excel หลัก (ถึง $Date)..."
$xl = RunExe $PYTHON @('-u', (Join-Path $ROOT 'scripts\build_group_sales.py'), '--to', $Date)
$xl | ForEach-Object { WriteLog "    $_" }
if ($script:LastExe -ne 0) {
    Say "⚠️ สร้างไฟล์ Excel หลักไม่ผ่าน (exit $($script:LastExe)) — ข้อมูลขึ้นฐานแล้ว"
    $xl | Select-Object -Last 5 | ForEach-Object { Say "    $_" }
} else {
    $xl | Where-Object { "$_" -match '^\s*(✅|⚠️)' } | ForEach-Object { Say "    $_" }
}

Say "✅ เสร็จสมบูรณ์ — $Date ขึ้นฐานแล้ว $inDb บรรทัด"
exit 0
