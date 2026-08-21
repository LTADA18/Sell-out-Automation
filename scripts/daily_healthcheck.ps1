# ตรวจว่างานรายวันทั้ง 3 ตัวรันครบและได้ผลจริงไหม
#
# ไม่ดูแค่ว่า Task Scheduler บอกว่าสำเร็จ เพราะ exit code 0 ไม่ได้แปลว่าได้ข้อมูล
# ต้องตรวจของจริงด้วย — ไฟล์ออกมากี่ร้าน อีเมลส่งไปจริงไหม ฐานมีข้อมูลวันนั้นกี่แถว
#
# ⚠️ ไฟล์นี้ต้องเป็น UTF-8 with BOM (กฎข้อ 6 ใน CLAUDE.md)
[CmdletBinding()]
param([string]$Date)      # วันของข้อมูล ไม่ใส่ = เมื่อวาน

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$ROOT = Split-Path -Parent $PSScriptRoot
$PSQL = 'C:\Program Files\PostgreSQL\18\bin\psql.exe'
$env:PGPASSFILE       = 'C:\Users\tada.p\Postgres\pgpass.conf'
$env:PGCLIENTENCODING = 'UTF8'

$INV = [Globalization.CultureInfo]::InvariantCulture
if (-not $Date) { $Date = [datetime]::Now.AddDays(-1).ToString('yyyy-MM-dd', $INV) }
$runDate = [datetime]::ParseExact($Date,'yyyy-MM-dd',$INV).AddDays(1).ToString('yyyy-MM-dd', $INV)

$fail = 0
function Ok  ([string]$m) { Write-Output "  [ผ่าน]   $m" }
function Bad ([string]$m) { Write-Output "  [ตกรอบ] $m"; $script:fail++ }
function Note([string]$m) { Write-Output "          $m" }

Write-Output "===== ตรวจงานรายวัน ข้อมูลวันที่ $Date (โฟลเดอร์รัน $runDate) ====="
Write-Output ""

# ---------- 1. ดึง + สกรีน ----------
Write-Output "1) DealerMKP-DailyOrders  08:30  ดึง 16 ร้าน + สกรีน"
$t = Get-ScheduledTask -TaskName 'DealerMKP-DailyOrders' -ErrorAction SilentlyContinue
if (-not $t) { Bad 'ไม่พบงานใน Task Scheduler' }
else {
    $i = Get-ScheduledTaskInfo $t
    Note "รันล่าสุด $($i.LastRunTime)  ผลลัพธ์ $($i.LastTaskResult)"
    if ($i.LastRunTime.Date -ne (Get-Date).Date) { Bad "ยังไม่ได้รันวันนี้" }
    elseif ($i.LastTaskResult -ne 0)             { Bad "จบด้วย exit $($i.LastTaskResult)" }
    else                                         { Ok  'Task Scheduler รายงานว่าสำเร็จ' }
}
$raw = @(Get-ChildItem (Join-Path $ROOT "output\$runDate") -Filter '*.xlsx' -ErrorAction SilentlyContinue)
$scr = @(Get-ChildItem (Join-Path $ROOT "output\$runDate\screened") -Filter '*_matched.xlsx' -ErrorAction SilentlyContinue)
if ($raw.Count -ge 16) { Ok "ไฟล์ดิบ $($raw.Count) ไฟล์" } else { Bad "ไฟล์ดิบมีแค่ $($raw.Count) ควรได้ 16" }
if ($scr.Count -ge 16) { Ok "ไฟล์สกรีน $($scr.Count) ร้าน" } else { Bad "ไฟล์สกรีนมีแค่ $($scr.Count) ร้าน ควรได้ 16" }

# ---------- 2. อีเมล ----------
Write-Output ""
Write-Output "2) DealerMKP-DailyMail  09:00  ส่งอีเมลรายงาน"
$t = Get-ScheduledTask -TaskName 'DealerMKP-DailyMail' -ErrorAction SilentlyContinue
if (-not $t) { Bad 'ไม่พบงานใน Task Scheduler' }
else {
    $i = Get-ScheduledTaskInfo $t
    Note "รันล่าสุด $($i.LastRunTime)  ผลลัพธ์ $($i.LastTaskResult)"
    if ($i.LastRunTime.Date -ne (Get-Date).Date) { Bad 'ยังไม่ได้รันวันนี้' }
    elseif ($i.LastTaskResult -ne 0)             { Bad "จบด้วย exit $($i.LastTaskResult)" }
    else                                         { Ok  'ส่งอีเมลสำเร็จ' }
}

# ---------- 3. ขึ้น Postgres ----------
Write-Output ""
Write-Output "3) DealerMKP-DailyPostgres  09:15  โหลดขึ้นฐาน"
$t = Get-ScheduledTask -TaskName 'DealerMKP-DailyPostgres' -ErrorAction SilentlyContinue
if (-not $t) { Bad 'ไม่พบงานใน Task Scheduler' }
else {
    $i = Get-ScheduledTaskInfo $t
    Note "รันล่าสุด $($i.LastRunTime)  ผลลัพธ์ $($i.LastTaskResult)"
    if ($i.LastRunTime.Date -ne (Get-Date).Date) { Bad 'ยังไม่ได้รันวันนี้' }
    elseif ($i.LastTaskResult -ne 0)             { Bad "จบด้วย exit $($i.LastTaskResult) — ดู log" }
    else                                         { Ok  'สคริปต์จบปกติ' }
}
$log = Join-Path $ROOT "output\_pg_logs\pg_load_$Date.log"
if (Test-Path $log) {
    $last = (Get-Content $log -Encoding UTF8 | Where-Object { $_ -match '\[ผ่าน\]|✅|❌' } | Select-Object -Last 1)
    Note "log: $last"
} else { Bad "ไม่มี log $log" }

# ---------- 4. ข้อมูลในฐานจริง ----------
Write-Output ""
Write-Output "4) ข้อมูลในฐานจริง"
$sqlFile = Join-Path $env:TEMP 'healthcheck.sql'
@"
SELECT count(*), count(DISTINCT shop_id), count(DISTINCT order_id),
       coalesce(round(sum(revenue_thb) FILTER (WHERE counts_as_sale)),0)
FROM intel.mp_order_line WHERE ordered_at::date = DATE '$Date';
"@ | Set-Content $sqlFile -Encoding UTF8
$r = & $PSQL 'service=osuka' -w -A -t -F'|' -f $sqlFile 2>&1
if ($LASTEXITCODE -ne 0) { Bad "ต่อฐานไม่ได้: $r" }
else {
    $p = ("$r".Trim() -split '\|')
    if ($p.Count -ge 4 -and [int]$p[0] -gt 0) {
        Ok "$([int]$p[0]) บรรทัด · $($p[1]) ร้าน · $($p[2]) ออเดอร์ · ยอดขาย $([decimal]$p[3]) บาท"
        if ([int]$p[1] -lt 16) { Bad "ร้านในฐานมีแค่ $($p[1]) ควรได้ 16" }
    } else { Bad "ฐานไม่มีข้อมูลวันที่ $Date เลย" }
}

Write-Output ""
if ($fail -eq 0) { Write-Output "===== ครบทั้ง 3 งาน ไม่มีอะไรต้องแก้ ====="; exit 0 }
Write-Output "===== มี $fail จุดที่ไม่ผ่าน ต้องดู ====="
exit 1
