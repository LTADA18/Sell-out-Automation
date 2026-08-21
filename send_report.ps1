# ส่งอีเมลสรุปผลการดึงประจำวัน — ใช้กับ Task Scheduler รอบ 08:00
#
#   .\send_report.ps1                          ส่งของรอบล่าสุด
#   .\send_report.ps1 -DataDate 2026-08-13     ส่งยอดของ "วันที่ 13"  ← แนะนำให้ใช้ตัวนี้
#   .\send_report.ps1 -Date 2026-08-14         เท่ากันเป๊ะ (วันที่ "รัน" ซึ่งคือวันถัดไป)
#   .\send_report.ps1 -Draft                   เปิดร่างให้ตรวจก่อน ไม่ส่งจริง
#   .\send_report.ps1 -To a@b.com              ส่งหาคนอื่นแทน
#
# ⚠️ ทำไมต้องมี -DataDate เพิ่ม (เพิ่ม 2026-08-14 หลังส่งอีเมลผิดวันออกไปจริง)
#    สคริปต์ในโปรเจกต์นี้ใช้คำว่า -Date คนละความหมายกัน:
#        pg_daily_load.ps1 -Date 2026-08-13  = ข้อมูล "วันที่ 13"
#        send_report.ps1   -Date 2026-08-13  = ข้อมูล "วันที่ 12"  (เพราะเป็นวันที่รัน)
#    ใช้สลับกันเมื่อไหร่ อีเมลออกไปผิดวันทันที และเรียกคืนไม่ได้
#    (เกิดจริง 2026-08-14 09:10 ส่งยอดวันที่ 12 ซ้ำไปหาผู้รับ 21 คน)
#    -DataDate จึงรับ "วันของข้อมูล" ตรง ๆ แล้วบวก 1 ให้เอง
#    ความหมายจะตรงกับ pg_daily_load.ps1 และ export_pg_day.py ทุกตัว
#
# แยกจาก run_daily.ps1 เพราะรอบดึงจบตี 6 แต่คนเข้างาน 8 โมง
# และเผื่อรอบตี 6 มี retry ยืดเวลาออกไป กว่าจะถึง 8 โมงก็เสร็จแน่นอนแล้ว
#
# exit code: 0 = ส่งแล้ว, 1 = ส่งไม่สำเร็จ, 4 = ไม่พบ .venv, 5 = ใส่วันที่ขัดกัน,
#            6 = อ่าน config\recipients.yaml ไม่ได้ (ไม่ส่งให้ใครทั้งนั้น)

param(
    # วันที่ "รัน" — ข้อมูลที่ได้คือของเมื่อวานของวันนี้
    [string]$Date,
    # วันของ "ข้อมูล" ตรง ๆ — ปลอดภัยกว่า ใช้ตัวนี้เวลาสั่งเอง
    [string]$DataDate,
    # ⚠️ ห้ามใส่ที่อยู่จริงเป็นค่าเริ่มต้นที่นี่
    #    รายชื่อทั้งหมดอยู่ใน config\recipients.yaml ซึ่งอยู่ใน .gitignore
    #    เพราะเป็นอีเมลของคนอื่น ไม่ควรขึ้น git ให้ใครที่เข้าถึง repo อ่านได้
    #    ปล่อยว่างไว้ = ไปอ่านจากไฟล์นั้น (ดูด่านโหลดรายชื่อข้างล่าง)
    #    ใส่ค่าที่นี่ได้เฉพาะเวลาจงใจส่งหาคนอื่นเป็นครั้งคราว
    [string]$To = "",
    [string]$Cc = "",
    [switch]$NoExcel,
    [switch]$Draft,
    # กันส่งซ้ำ — ถ้ารอบดึงส่งอีเมลของวันนี้ไปแล้ว ให้ออกทันที
    [switch]$SkipIfSent,
    # ส่งทั้งที่ยังไม่ครบทุกร้าน — ต้องจงใจใส่เองเท่านั้น
    [switch]$Force,
    # เจอที่อยู่ที่ Exchange ยืนยันไม่ได้ = หยุดเลย ไม่ส่งให้ใครทั้งนั้น
    # ค่าเริ่มต้นคือเตือนแล้วส่งต่อ เพราะคนอื่นไม่ควรอดรับเพราะที่อยู่คนเดียวผิด
    [switch]$StrictRecipients
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# จับเวลาแต่ละขั้น — เคยค้างหลายนาทีแล้วไล่หาจุดไม่เจอเพราะไม่มีตัวบอก (2026-08-17)
$__sw = [Diagnostics.Stopwatch]::StartNew()
function Step([string]$name) {
    Write-Host ("  [{0,6:n1}s] {1}" -f $__sw.Elapsed.TotalSeconds, $name) -ForegroundColor DarkGray
}
Step "เริ่ม"

# ---- แปลง -DataDate เป็นวันที่รัน แล้วบอกให้ชัดว่ากำลังส่งของวันไหน ----
# ใส่มาทั้งคู่แล้วขัดกัน = หยุดทันที ดีกว่าเดาว่าเจ้าของงานหมายถึงอันไหน
# ⚠️ ต้องแปลงวันที่ด้วย InvariantCulture เสมอ
#    เครื่องนี้ตั้งภาษาไทย [datetime]"2026-08-16" จึงถูกอ่านเป็นพุทธศักราช
#    แล้ว ToString('yyyy-MM-dd') คืนค่า 2569-08-17 (2026+543)
#    ถ้าเรียกซ้ำอีกรอบจะกลายเป็น 3112 (เจอจริง 2026-08-17)
#    ผลคือส่งอีเมลผิดวัน หรือหาข้อมูลของวันนั้นไม่เจอเลย
$INV = [Globalization.CultureInfo]::InvariantCulture
function ToDate([string]$s) { [datetime]::ParseExact($s, 'yyyy-MM-dd', $INV) }
function FromDate([datetime]$d) { $d.ToString('yyyy-MM-dd', $INV) }

if ($DataDate) {
    $fromData = FromDate (ToDate($DataDate)).AddDays(1)
    if ($Date -and $Date -ne $fromData) {
        Write-Host "❌ -Date $Date กับ -DataDate $DataDate ขัดกัน" -ForegroundColor Red
        Write-Host "   -DataDate $DataDate ตรงกับ -Date $fromData" -ForegroundColor Yellow
        Write-Host "   ใส่มาอย่างเดียวก็พอ" -ForegroundColor Yellow
        exit 5
    }
    $Date = $fromData
}
if ($Date) {
    $shown = FromDate (ToDate($Date)).AddDays(-1)
    Write-Host "กำลังส่งยอดของวันที่ $shown  (รอบรัน $Date)" -ForegroundColor Yellow
}

$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    Write-Host "ไม่พบ .venv — รัน .\setup.ps1 ก่อน" -ForegroundColor Red
    exit 4
}

# ---- ด่าน: โหลดรายชื่อผู้รับจาก config\recipients.yaml ----
#
# PowerShell 5.1 ไม่มีตัวอ่าน YAML ในตัว จึงเรียกผ่าน python ที่มีอยู่แล้ว
# ข้อดีคือรายชื่ออยู่ไฟล์เดียวรูปแบบเดียวกับ config อื่นของโปรเจกต์
#
# ⚠️ อ่านไม่ได้ = หยุดเลย ห้ามส่งต่อด้วยรายชื่อว่าง
#    อีเมลที่ "ส่งสำเร็จ" แต่ไม่ถึงใครเลย ไม่มีสัญญาณอะไรบอกว่าผิด
#    แย่กว่าส่งไม่ออกเสียอีก (กฎเหล็กข้อ 1 — ไม่มีข้อมูลห้ามเดาแทน)
function LoadRecipients([string]$group, [string]$field) {
    $prev = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $out = & $py -m src.core.recipients --group $group --field $field 2>&1
        $rc  = $LASTEXITCODE
    } finally { $ErrorActionPreference = $prev }
    if ($rc -ne 0) {
        Write-Host "อ่านรายชื่อผู้รับไม่ได้ (กลุ่ม $group/$field)" -ForegroundColor Red
        Write-Host ($out -join "`n") -ForegroundColor Red
        exit 6
    }
    return ($out | Where-Object { $_ -is [string] }) -join ""
}

if (-not $To) { $To = LoadRecipients 'report' 'to' }
if (-not $Cc) { $Cc = LoadRecipients 'report' 'cc' }

# ---- ด่าน: ที่อยู่ผู้รับต้องมีตัวตนจริงใน Exchange ทุกตัว ----
#
# ⚠️ ทำไมต้องมี (เจอจริง 2026-08-14)
#    รายชื่อ 17 คนที่ได้มามีพิมพ์ผิด 2 จุดโดยไม่มีใครรู้ — ตัวหนึ่งตก @ ไป
#    อีกตัวมีจุดเกินมาหนึ่งจุดจนกลายเป็นที่อยู่ที่ไม่มีตัวตนในองค์กร
#    ตัวหลังส่งออกไป "สำเร็จ" ทุกวันโดยไม่มีข้อความตีกลับเลยแม้แต่ฉบับเดียว
#    กว่าจะรู้ก็ต่อเมื่อคนปลายทางทักมาเองว่าไม่ได้รับ
#    (รายละเอียดว่าตัวไหนผิดยังไง อยู่ในคอมเมนต์ของ config\recipients.yaml)
#
#    Exchange แปลงที่อยู่ในองค์กรเป็นชื่อคนได้ ถ้าแปลงไม่ได้แปลว่าไม่มีคนนั้นอยู่จริง
#    ตรวจก่อนส่งจึงจับได้ทันทีแทนที่จะเงียบไปเป็นสัปดาห์
#
#    ไม่บล็อกการส่ง — เตือนแล้วส่งต่อ เพราะคนที่เหลืออีก 20 คนไม่ควรอดรับรายงาน
#    เพราะที่อยู่คนเดียวพิมพ์ผิด ใช้ -StrictRecipients ถ้าอยากให้หยุดเลย
Step "เริ่มด่านตรวจผู้รับ"
$allAddr = @()
foreach ($x in @($To, $Cc)) {
    if ($x) { $allAddr += ($x -split '[,;]' | ForEach-Object { $_.Trim() } | Where-Object { $_ }) }
}
$badAddr = @()

# ตรวจรูปแบบก่อน — ทำได้เองไม่ต้องพึ่ง Outlook
$needCom = @()
foreach ($a in $allAddr) {
    if ($a -notmatch '^[^@\s]+@[^@\s]+\.[^@\s]+$') { $badAddr += "$a  (รูปแบบไม่ถูกต้อง)" }
    else { $needCom += $a }
}

# ⚠️ ต้องเรียก Outlook COM ใน process แยกที่เป็นโหมด STA และต้องมี timeout
#
#    Outlook COM ใช้ได้เฉพาะ thread แบบ STA ถ้า shell ที่เรียกอยู่ในโหมด MTA
#    (เกิดกับ Start-Job และกับตัวเรียกอัตโนมัติบางตัว) มันจะ "ค้างรอตลอดกาล"
#    ไม่มี error ไม่มี timeout — เห็นแค่ CPU เต็มแล้วไม่ไปไหน
#    (เจอจริง 2026-08-17: อีเมลไม่ออกเลยหลายรอบ กว่าจะไล่เจอใช้เวลานาน)
#
#    จึงยิงเป็น powershell -STA ลูกแยก แล้วบังคับ timeout
#    ตรวจไม่ได้ = ข้ามด่าน ไม่ใช่ค้าง — การส่งอีเมลสำคัญกว่าการตรวจที่อยู่
if ($needCom.Count -gt 0) {
    $probe = @'
$ErrorActionPreference = "Stop"
$ns = (New-Object -ComObject Outlook.Application).GetNamespace("MAPI")
foreach ($a in $args) {
    $r = $ns.CreateRecipient($a); $null = $r.Resolve()
    $u = try { $r.AddressEntry.GetExchangeUser() } catch { $null }
    if (-not $u) { Write-Output $a }
}
'@
    $tmp = Join-Path $env:TEMP "chk_rcpt_$PID.ps1"
    [IO.File]::WriteAllText($tmp, $probe, (New-Object Text.UTF8Encoding($false)))
    try {
        $psi = New-Object Diagnostics.ProcessStartInfo
        $psi.FileName  = "powershell.exe"
        $psi.Arguments = "-STA -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$tmp`" $($needCom -join ' ')"
        $psi.RedirectStandardOutput = $true
        $psi.UseShellExecute = $false
        $psi.CreateNoWindow = $true
        $proc = [Diagnostics.Process]::Start($psi)
        if ($proc.WaitForExit(60000)) {
            $proc.StandardOutput.ReadToEnd().Split("`n") |
                ForEach-Object { $_.Trim() } | Where-Object { $_ } |
                ForEach-Object { $badAddr += "$_  (ไม่พบในสมุดที่อยู่องค์กร)" }
        } else {
            try { $proc.Kill() } catch { }
            Write-Host "⚠️ ตรวจที่อยู่เกิน 60 วินาที — ข้ามด่านนี้ ส่งต่อ" -ForegroundColor Yellow
        }
    } catch {
        Write-Host "⚠️ ตรวจที่อยู่ไม่ได้ — ข้ามด่านนี้ ส่งต่อ" -ForegroundColor Yellow
    } finally {
        Remove-Item $tmp -Force -EA SilentlyContinue
    }
}
Step "ตรวจผู้รับเสร็จ"
if ($badAddr.Count -gt 0) {
    Write-Host "⚠️ ที่อยู่ที่ Exchange ยืนยันไม่ได้ $($badAddr.Count) จาก $($allAddr.Count) รายการ:" -ForegroundColor Yellow
    $badAddr | ForEach-Object { Write-Host "     $_" -ForegroundColor Yellow }
    if ($StrictRecipients) {
        Write-Host "   หยุดตามที่สั่งด้วย -StrictRecipients" -ForegroundColor Red
        exit 6
    }
    Write-Host "   ส่งต่อให้คนที่เหลือ — แก้ที่อยู่ข้างบนใน send_report.ps1 ด้วย" -ForegroundColor Yellow
} else {
    Write-Host "✅ ผู้รับ $($allAddr.Count) รายการ ยืนยันกับ Exchange ได้ครบ" -ForegroundColor Green
}

# สร้าง Dashboard ใหม่ก่อนส่งเสมอ — จะได้แนบไฟล์ที่ตรงกับสถานะล่าสุดจริง
Step "เริ่มสร้าง Dashboard"
try { & $py -m src.cli dashboard | Out-Null } catch { }
Step "สร้าง Dashboard เสร็จ"

$cliArgs = @("-m", "src.cli", "notify", "--to", $To)
if ($Cc)      { $cliArgs += @("--cc", $Cc) }
if ($Date)    { $cliArgs += @("--date", $Date) }
if ($NoExcel)    { $cliArgs += "--no-excel" }
if ($Draft)      { $cliArgs += "--draft" }
if ($SkipIfSent) { $cliArgs += "--skip-if-sent" }

# ⚠️ กฎที่เจ้าของงานสั่งไว้ 2026-08-07: ไม่ครบ 13 ร้าน ห้ามส่งเมล
#    ของเดิมใส่ไว้แค่ใน run_daily.ps1 ตัวนี้ซึ่งเป็นตัวตั้งเวลา 09:00 ไม่มี
#    ผลคือ 2026-08-08 มันส่งอีเมลออกไปตอนได้แค่ 9/13 ร้าน — ผิดกฎเต็ม ๆ
#    ใส่เป็นค่าเริ่มต้น ถ้าจงใจอยากส่งทั้งที่ไม่ครบให้ใช้ -Force
if (-not $Force) { $cliArgs += "--only-if-complete" }

Write-Host "ส่งสรุปผลการดึง $([datetime]::Now.ToString('yyyy-MM-dd HH:mm:ss', $INV))" -ForegroundColor Cyan
Step "เริ่มส่งอีเมล (src.cli notify)"
& $py @cliArgs
$code = $LASTEXITCODE
Step "ส่งอีเมลเสร็จ"

if ($code -ne 0) {
    Write-Host "ส่งอีเมลไม่สำเร็จ (exit $code)" -ForegroundColor Red
}
exit $code
