# โหลดข้อมูล "หลายวันรวดเดียว" ขึ้น Postgres — ใช้กับงานย้อนหลัง
#
# ต่างจาก pg_daily_load.ps1 ที่ทำวันเดียวต่อรอบ
#   งานย้อนหลัง 212 วัน ถ้าใช้ตัวรายวันต้องเปิด/ปิด transaction 424 รอบ
#   (ซ้อม + เขียนจริง วันละ 2) ทั้งที่ข้อมูลจริงราว 60,000 แถว
#   เวลาเกือบทั้งหมดหมดไปกับ overhead ไม่ใช่การเขียนข้อมูล
#   รวบเป็นรอบเดียวเหลือราว 5 นาที จาก 55 นาที
#
# ด่านตรวจครบเหมือนตัวรายวันทุกตัว แค่เปลี่ยนขอบเขตจาก "วันนั้น" เป็น "ช่วงนั้น"
#   1 = ไม่มีไฟล์สกรีน
#   2 = export ไม่ผ่าน
#   3 = ซ้อม ROLLBACK ไม่ผ่าน
#   4 = COMMIT ไม่ผ่าน
#   6 = จำนวนแถวผิดปกติ
#
# ⚠️ ไฟล์นี้ต้องเป็น UTF-8 with BOM (กฎข้อ 6 ใน CLAUDE.md)
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$From,
    [Parameter(Mandatory)][string]$To,
    [switch]$DryRun,
    [int]$MinRows = 1000,
    # เพิ่มร้านทีหลัง — โหลดเฉพาะร้านนั้น ไม่ต้องอ่าน Excel ของอีก 15 ร้านที่ไม่เปลี่ยน
    # ปลอดภัยเพราะร้านที่เพิ่งเปิดยังไม่มีแถวในช่วงนั้นเลย เป็น INSERT ล้วน
    [string]$Shop = "",
    # ⚠️ ไฟล์จากงานย้อนหลังอยู่รวมเป็นไฟล์เดียวใน output\_backfill_* ไม่ใช่โฟลเดอร์รายวัน
    #    ตัวหาไฟล์ปกติจึงไม่เจอ ระบุเองด้วยตัวนี้ (ด่านกรองวันที่ยังทำงานเหมือนเดิม)
    [string[]]$Files = @()
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$ROOT    = Split-Path -Parent $PSScriptRoot
$PSQL    = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
$PYTHON  = Join-Path $ROOT '.venv\Scripts\python.exe'
$TEMPLATE= 'C:\Users\tada.p\Postgres\LOAD_range.sql'
$LOGDIR  = Join-Path $ROOT 'output\_pg_logs'

$env:PGPASSFILE      = 'C:\Users\tada.p\Postgres\pgpass.conf'
$env:PGCLIENTENCODING= 'UTF8'
$env:PYTHONIOENCODING= 'utf-8'

New-Item -ItemType Directory -Path $LOGDIR -Force | Out-Null
$log = Join-Path $LOGDIR "pg_load_${From}_to_${To}$(if($Shop){"_$Shop"}).log"

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
# ⚠️ เหตุผลเต็มอยู่ใน pg_daily_load.ps1 — สรุป: PowerShell 5.1 + ErrorActionPreference Stop
#    + `& exe ... 2>&1` = โปรแกรมเขียน stderr เมื่อไหร่ สคริปต์ตายทันทีแบบไม่ทิ้งข้อความ
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

Say "===== โหลดช่วง $From ถึง $To ====="

# ---- ด่าน 1+2: สร้าง CSV ทั้งช่วง ----
# ⚠️ ต้องเป็น ASCII ล้วน — psql เปิดไฟล์ที่ path มีอักษรไทยไม่ได้
# ⚠️ ต้องตั้งชื่อให้ตรงกับที่ export_pg_day.py ตั้ง ไม่งั้นหาไฟล์ไม่เจอแล้ว exit 2
#    ตัวนั้นใช้ "<วัน>" เฉย ๆ เมื่อช่วงเป็นวันเดียว ไม่ใส่ _to_ ซ้ำ
$base   = if ($From -eq $To) { $From } else { "${From}_to_${To}" }
$tag    = if ($Shop) { "${base}_${Shop}" } else { $base }
$csvDir = Join-Path $ROOT "output\_pg_day_$tag"
$csv    = Join-Path $csvDir "all_shops_$tag.csv"
Say "กำลังสร้าง CSV ทั้งช่วง..."
$pyArgs = @('-u', (Join-Path $ROOT 'scripts\export_pg_day.py'), '--from', $From, '--to', $To)
if ($Shop) { $pyArgs += @('--shop', $Shop) }
if ($Files.Count -gt 0) { $pyArgs += '--files'; $pyArgs += $Files }
$exportOut = RunExe $PYTHON $pyArgs
$exportOut | ForEach-Object { WriteLog "    $_" }
if ($script:LastExe -ne 0 -or -not (Test-Path $csv)) {
    Say "❌ export ไม่ผ่าน (exit $LASTEXITCODE) — ดู $log"
    $exportOut | Select-Object -Last 12 | ForEach-Object { Say "    $_" }
    exit 2
}

# ⚠️ ห้ามนับด้วย Measure-Object -Line — sku บางตัวมีอักขระขึ้นบรรทัดใหม่ฝังอยู่
#    1 เรคคอร์ดกินหลายบรรทัด ใช้ตัวเลขที่ export นับด้วย csv parser จริงแทน
$rows = 0
foreach ($l in $exportOut) {
    if ("$l" -match 'บรรทัดสินค้า\s+([\d,]+)') { $rows = [int]($Matches[1] -replace ',', ''); break }
}
if ($rows -le 0) { Say "❌ อ่านจำนวนแถวจากผล export ไม่ได้"; exit 2 }
Say "✅ CSV $rows บรรทัด"
if ($rows -lt $MinRows) {
    Say "❌ ได้แค่ $rows บรรทัด ต่ำกว่าเกณฑ์ $MinRows — หยุดไว้ก่อน ให้คนมาดู"
    exit 6
}

# ---- เตรียม SQL: \copy ไม่แทนค่าตัวแปรให้ ----
$sqlText = [IO.File]::ReadAllText($TEMPLATE).
    Replace('__CSV__', ($csv -replace '\\', '/')).
    Replace('__CSVNAME__', "all_shops_$tag.csv")
$sqlFile = Join-Path $csvDir "LOAD_$tag.sql"
[IO.File]::WriteAllText($sqlFile, $sqlText, (New-Object Text.UTF8Encoding($false)))

# ---- ด่าน 3: ซ้อมด้วย ROLLBACK ----
Say "ซ้อมด้วย ROLLBACK..."
$dry = RunExe $PSQL @('service=osuka-build','-w','-P','pager=off','-v',"d_from=$From",'-v',"d_to=$To",'-f',$sqlFile)
$dry | ForEach-Object { WriteLog "    $_" }
if ($LASTEXITCODE -ne 0) {
    Say "❌ ซ้อมไม่ผ่าน (exit $LASTEXITCODE) — ดูรายละเอียดใน $log"
    $dry | Select-Object -Last 12 | ForEach-Object { Say "    $_" }
    exit 3
}
Say "✅ ซ้อมผ่าน"
if ($DryRun) { Say "จบแบบซ้อมอย่างเดียว ไม่ได้เขียนจริง"; exit 0 }

# ---- ด่าน 4: เขียนจริง ----
Say "เขียนจริง COMMIT..."
$real = RunExe $PSQL @('service=osuka-build','-w','-P','pager=off','-v',"d_from=$From",'-v',"d_to=$To",'-v','commit=1','-f',$sqlFile)
$real | ForEach-Object { WriteLog "    $_" }
if ($LASTEXITCODE -ne 0) {
    Say "❌ COMMIT ไม่ผ่าน (exit $LASTEXITCODE)"
    $real | Select-Object -Last 12 | ForEach-Object { Say "    $_" }
    exit 4
}

# ---- ด่าน 5: สรุปผลจากรายงานท้ายไฟล์ SQL ----
$real | Select-Object -Last 30 | ForEach-Object { Say "    $_" }

# ---- ด่าน 6: REFRESH matview ที่ Dashboard อ่าน (เหตุผลเดียวกับ pg_daily_load.ps1) ----
Say "REFRESH matview ที่ Dashboard อ่าน..."
$mv = & $PSQL 'service=osuka-build' -w -P pager=off -f 'C:\Users\tada.p\Postgres\REFRESH_matviews.sql' 2>&1
$mv | ForEach-Object { WriteLog "    $_" }
if ($LASTEXITCODE -ne 0) {
    Say "⚠️ REFRESH matview ไม่ผ่าน — ข้อมูลขึ้นฐานแล้วแต่ Dashboard จะยังไม่เห็น"
    $mv | Select-Object -Last 6 | ForEach-Object { Say "    $_" }
} else {
    Say "✅ REFRESH matview เรียบร้อย"
}

Say "✅ เสร็จสมบูรณ์ — $From ถึง $To ขึ้นฐานแล้ว (CSV $rows บรรทัด)"
exit 0
