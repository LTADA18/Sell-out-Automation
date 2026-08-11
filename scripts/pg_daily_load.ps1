# โหลดข้อมูลของเมื่อวานขึ้น Postgres — รันหลังส่งอีเมลรายงานประจำวันเสร็จ
#
# ลำดับงานรายวัน
#   08:30  DealerMKP-DailyOrders    ดึง 16 ร้าน + สกรีน
#   09:00  DealerMKP-DailyMail      ส่งอีเมลไฟล์ 63 คอลัมน์
#   09:15  DealerMKP-DailyPostgres  ตัวนี้ — โหลดขึ้นฐาน
#
# กันพังเงียบ: ทุกด่านที่ไม่ผ่านคืน exit code ไม่ใช่ 0 และเขียนเหตุผลลง log
#   1 = ไม่มีไฟล์สกรีน / ไม่ครบ 16 ร้าน
#   2 = export ไม่ผ่าน
#   3 = ซ้อม ROLLBACK ไม่ผ่าน (ฟังก์ชัน RAISE เจอสถานะใหม่ที่ยังไม่รู้จัก)
#   4 = COMMIT ไม่ผ่าน
#   5 = ตรวจหลังโหลดไม่ผ่าน (คีย์ซ้ำ / สถานะไม่ตรง)
#   6 = จำนวนแถวผิดปกติ (0 แถว หรือเกินเพดาน)
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

if (-not $Date) { $Date = (Get-Date).AddDays(-1).ToString('yyyy-MM-dd') }
$runDate = ([datetime]$Date).AddDays(1).ToString('yyyy-MM-dd')

New-Item -ItemType Directory -Path $LOGDIR -Force | Out-Null
$log = Join-Path $LOGDIR "pg_load_$Date.log"

function Say([string]$m) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'HH:mm:ss'), $m
    Write-Output $line
    Add-Content -Path $log -Value $line -Encoding utf8
}

Say "===== โหลดข้อมูลวันที่ $Date (โฟลเดอร์รัน $runDate) ====="

# ---- ด่าน 1: ไฟล์สกรีนต้องครบ ----
$screened = Join-Path $ROOT "output\$runDate\screened"
if (-not (Test-Path $screened)) {
    Say "❌ ไม่พบโฟลเดอร์ $screened — รอบดึงยังไม่เสร็จหรือล้ม"
    exit 1
}
$matched = @(Get-ChildItem $screened -Filter '*_matched.xlsx' -ErrorAction SilentlyContinue)
if ($matched.Count -lt 16) {
    Say "❌ ไฟล์สกรีนมีแค่ $($matched.Count) ร้าน ต้องได้ 16 — ไม่โหลดข้อมูลไม่ครบ"
    exit 1
}
Say "✅ ไฟล์สกรีนครบ $($matched.Count) ร้าน"

# ---- ด่าน 2: สร้าง CSV ----
$csvDir = Join-Path $ROOT "output\_pg_day_$Date"
$csv    = Join-Path $csvDir "all_shops_$Date.csv"
Say "กำลังสร้าง CSV..."
$exportOut = & $PYTHON -u (Join-Path $ROOT 'scripts\export_pg_day.py') --date $Date 2>&1
$exportOut | ForEach-Object { Add-Content -Path $log -Value "    $_" -Encoding utf8 }
if ($LASTEXITCODE -ne 0 -or -not (Test-Path $csv)) {
    Say "❌ export ไม่ผ่าน (exit $LASTEXITCODE)"
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
$dry = & $PSQL 'service=osuka-build' -w -P pager=off -v day=$Date -f $sqlFile 2>&1
$dry | ForEach-Object { Add-Content -Path $log -Value "    $_" -Encoding utf8 }
if ($LASTEXITCODE -ne 0) {
    Say "❌ ซ้อมไม่ผ่าน (exit $LASTEXITCODE) — ดูรายละเอียดใน $log"
    Say "   สาเหตุที่พบบ่อย: แพลตฟอร์มเพิ่มคำสถานะใหม่ที่ mp_order_state_v2 ยังไม่รู้จัก"
    exit 3
}
Say "✅ ซ้อมผ่าน"

if ($DryRun) { Say "จบแบบซ้อมอย่างเดียว ไม่ได้เขียนจริง"; exit 0 }

# ---- ด่าน 4: เขียนจริง ----
Say "เขียนจริง COMMIT..."
$real = & $PSQL 'service=osuka-build' -w -P pager=off -v day=$Date -v commit=1 -f $sqlFile 2>&1
$real | ForEach-Object { Add-Content -Path $log -Value "    $_" -Encoding utf8 }
if ($LASTEXITCODE -ne 0) {
    Say "❌ COMMIT ไม่ผ่าน (exit $LASTEXITCODE)"
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

Say "✅ เสร็จสมบูรณ์ — $Date ขึ้นฐานแล้ว $inDb บรรทัด"
exit 0
