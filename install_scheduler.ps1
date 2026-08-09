# ติดตั้ง/ถอด Task Scheduler ให้รันรอบประจำวันอัตโนมัติ (Phase 4)
#
#   .\install_scheduler.ps1                          ติดตั้ง (ดึง 09:00 / อีเมล 10:00)
#   .\install_scheduler.ps1 -Time 05:30 -MailTime 07:00   เปลี่ยนเวลา
#   .\install_scheduler.ps1 -Status          ดูสถานะ/รอบล่าสุด
#   .\install_scheduler.ps1 -RunNow          สั่งรันเดี๋ยวนี้เพื่อทดสอบ
#   .\install_scheduler.ps1 -Remove          ถอดออก
#
# ต้องเปิด PowerShell แบบ Run as Administrator ตอนติดตั้ง/ถอด

param(
    # 08:30 ดึง / 09:00 ส่งอีเมล — เจ้าของงานเปิดโน้ตบุ๊กราว 8 โมง
    # ตั้งหลังเวลานั้นเพื่อให้เครื่องตื่นอยู่แล้วจริง ๆ ไม่ต้องพึ่งการปลุก
    # เว้นห่าง 30 นาทีให้รอบดึง (~15-20 นาที) จบก่อนถึงรอบอีเมล
    [string]$Time = "08:30",
    [string]$MailTime = "09:00",
    # ⚠️ ต้องมีมากกว่า 1 เวลา — 20:00 อย่างเดียวพลาด 2 คืนติด (8 และ 9 ส.ค.)
    #    เพราะโน้ตบุ๊กเข้า Modern Standby ตอนเย็น งานจึงยิงไม่ได้
    #    StartWhenAvailable ตามเก็บให้ก็จริง แต่ไปรันตอนดึกหรือเช้าซึ่งสายเกินไป
    #
    # 13:00 = ช่วงเครื่องเปิดใช้งานแน่นอน (เวลาทำงาน) เป็นตัวหลัก
    # 20:00 = เผื่อไว้ ถ้าเครื่องยังเปิดอยู่
    # แตะครั้งใดครั้งหนึ่งสำเร็จ อายุตอน 08:30 ก็ไม่เกิน ~19.5 ชม. ซึ่งต่ำกว่าเส้นตาย
    # (วัดจริง: 23.8 ชม. ตาย / 21.0 ชม. รอด)
    [string[]]$KeepAliveTimes = @("13:00", "20:00"),
    [switch]$Status,
    [switch]$RunNow,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$TaskName = "DealerMKP-DailyOrders"
$MailTask = "DealerMKP-DailyMail"
$KeepTask = "DealerMKP-KeepAlive"
$script   = Join-Path $PSScriptRoot "run_daily.ps1"
$mailScr  = Join-Path $PSScriptRoot "send_report.ps1"
$keepScr  = Join-Path $PSScriptRoot "keepalive.ps1"

function Show-One {
    param([string]$Name)
    $t = Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue
    if (-not $t) {
        Write-Host "$Name : ยังไม่ได้ติดตั้ง" -ForegroundColor Yellow
        return
    }
    $i = Get-ScheduledTaskInfo -TaskName $Name
    Write-Host "$Name : $($t.State) | รอบถัดไป $($i.NextRunTime) | รอบล่าสุด $($i.LastRunTime) (ผล $($i.LastTaskResult))"
}

function Show-Status {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $t) {
        Write-Host "ยังไม่ได้ติดตั้ง — รัน .\install_scheduler.ps1" -ForegroundColor Yellow
        return
    }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "ชื่องาน      : $TaskName"
    Write-Host "สถานะ        : $($t.State)"
    Write-Host "รอบถัดไป     : $($info.NextRunTime)"
    Write-Host "รอบล่าสุด    : $($info.LastRunTime)"
    $code = $info.LastTaskResult
    $meaning = switch ($code) {
        0       { "ครบทุกร้าน" }
        1       { "มีร้านที่ล้มเหลว — เปิด output\dashboard.html ดู" }
        2       { "มีรอบอื่นรันอยู่" }
        4       { "ไม่พบ .venv — รัน .\setup.ps1" }
        267011  { "ยังไม่เคยรัน" }
        default { "ดู exit code ใน README" }
    }
    Write-Host "ผลรอบล่าสุด  : $code ($meaning)"
    foreach ($tr in $t.Triggers) { Write-Host "trigger      : $($tr.CimClass.CimClassName)" }
    Write-Host ""
    Write-Host "── งานส่งอีเมล ──"
    Show-One -Name $MailTask
    Write-Host ""
    Write-Host "── งานต่ออายุ session ──"
    Show-One -Name $KeepTask
}

if ($Status) { Show-Status; exit 0 }

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "สั่งรันแล้ว — ดูความคืบหน้าด้วย .\install_scheduler.ps1 -Status" -ForegroundColor Cyan
    exit 0
}

if ($Remove) {
    foreach ($n in @($TaskName, $MailTask, $KeepTask)) {
        if (Get-ScheduledTask -TaskName $n -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $n -Confirm:$false
            Write-Host "ถอด $n ออกแล้ว" -ForegroundColor Green
        }
    }
    exit 0
}

# ── ติดตั้ง ────────────────────────────────────────────────────
if (-not (Test-Path $script)) {
    Write-Host "ไม่พบ run_daily.ps1 ที่ $script" -ForegroundColor Red
    exit 1
}

# -Mail = ส่งอีเมลท้ายรอบทันทีที่ดึงเสร็จ
# สำคัญสำหรับเครื่องโน้ตบุ๊กที่เปิดสาย: รอบดึงจะเริ่มตอนล็อกอิน ไม่ใช่ตามนาฬิกา
# ถ้าปล่อยให้อีเมลยิงตามเวลาอย่างเดียว จะส่งตอนข้อมูลยังดึงไม่เสร็จ
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`" -SkipIfDone -Mail" `
    -WorkingDirectory $PSScriptRoot

# ⛔ เคยมี trigger ตอนล็อกอินด้วย — ถอดออกแล้ว 2026-08-06
#    เจตนาเดิมคือเผื่อคืนนั้นเครื่องปิด จะได้ตามเก็บตอนเปิดเครื่อง
#    แต่ของจริงคือมัน "ตายทุกครั้ง" เพราะยิงตอน session Windows ยังตั้งตัวไม่เสร็จ
#      5 ส.ค. 08:17 ยิง -> ตาย (รหัส 3221225786 = ถูกสั่งหยุด)
#      6 ส.ค. 08:18 ยิง -> ตาย + ทิ้ง run.lock ค้างไว้
#    ครั้งหลังร้ายกว่าเพราะ run.lock ที่ค้างจะบล็อกรอบจริงตอน 08:30 (exit 2)
#    แล้วเงียบสนิทโดยไม่มีอะไรเตือน ถ้าไม่บังเอิญไปเจอก่อนก็ไม่ได้ข้อมูลทั้งวัน
#
#    StartWhenAvailable ด้านล่างครอบเคสเปิดเครื่องสายอยู่แล้ว จึงไม่ต้องใช้ trigger นี้
$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At $Time)
)

# StartWhenAvailable = ถ้าถึงเวลาแล้วเครื่องปิดอยู่ ให้รันทันทีที่เปิดเครื่อง
# IgnoreNew          = ถ้ารอบก่อนยังไม่จบ อย่าเปิดรอบใหม่ซ้อน
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 10)

# Interactive = ต้องล็อกอินเข้า Windows อยู่ เพราะ Chrome ต้องการ desktop session
# ถ้าตั้งเป็น S4U/รันแบบไม่ล็อกอิน Playwright จะเปิดเบราว์เซอร์ไม่ขึ้น
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description "ดึงคำสั่งซื้อจากหลังบ้านทุกร้าน แล้วออก Excel + dashboard.html" `
    -Force | Out-Null

Write-Host "ติดตั้ง $TaskName แล้ว — รันทุกวัน $Time" -ForegroundColor Green

# ── งานส่งอีเมล แยกอีกตัว ─────────────────────────────────────
# แยกจากรอบดึงเพราะดึงเสร็จตี 6 แต่คนเข้างาน 8 โมง
# และเผื่อรอบตี 6 มี retry ยืดเวลา กว่าจะ 8 โมงก็เสร็จแน่นอน
# งานนี้เป็น "ตาข่ายรองรับ" ไม่ใช่ตัวส่งหลัก — ตัวหลักคือท้าย run_daily.ps1
# -SkipIfSent กันส่งซ้ำ: ถ้ารอบดึงส่งไปแล้ววันนี้ ตัวนี้จะออกทันทีไม่ส่งอีกฉบับ
# มีไว้เผื่อรอบดึงพังกลางทางจนไม่ได้ส่ง หรือวันที่เครื่องเปิดหลัง 8 โมง
$mailAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$mailScr`" -SkipIfSent" `
    -WorkingDirectory $PSScriptRoot

$mailSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -RestartCount 2 `
    -RestartInterval (New-TimeSpan -Minutes 10)

# ⛔ ถอด trigger ตอนล็อกอินออกแล้ว 2026-08-06 เช่นเดียวกับงานดึง
#    ตัวนี้อันตรายกว่าอีก: หน่วง 25 นาทีหลังล็อกอิน ซึ่งอาจตกกลางรอบดึงพอดี
#    (6 ส.ค. ล็อกอิน 08:18 -> จะยิง 08:43 ขณะที่ยังดึงไม่จบ)
#    -SkipIfSent กันได้แค่ "ส่งซ้ำ" กันไม่ได้เรื่อง "ส่งตอนข้อมูลยังไม่ครบ"
$mailTriggers = @(
    (New-ScheduledTaskTrigger -Daily -At $MailTime)
)

Register-ScheduledTask `
    -TaskName $MailTask `
    -Action $mailAction `
    -Trigger $mailTriggers `
    -Settings $mailSettings `
    -Principal $principal `
    -Description "ส่งอีเมลสรุปผลการดึงคำสั่งซื้อประจำวัน (Outlook)" `
    -Force | Out-Null

Write-Host "ติดตั้ง $MailTask แล้ว — ส่งอีเมลทุกวัน $MailTime" -ForegroundColor Green

# ── งานต่ออายุ session ─────────────────────────────────────────
# ตัวนี้ไม่ดึงข้อมูล แค่เปิดหน้าหลังบ้านแล้วเซฟ cookie ชุดใหม่
#
# ที่มา (วัดจริง 2026-08-08): session ของ TikTok อยู่ได้ ~24 ชม.
# รอบรายวันรันเวลาเดิมทุกวัน = ห่างกัน 24 ชม. เป๊ะ จึงนั่งบนเส้นแบ่งพอดี
# วันนั้น tiktok_01/03/04/05 อายุ 23.8-23.9 ชม. ตายหมด ส่วน tiktok_02 อายุ 21 ชม. รอด
# แตะกลางวันหนึ่งครั้ง อายุจึงไม่มีวันแตะ 24 ชม. -> ไม่ต้องล็อกอินใหม่ -> ไม่ต้องขอ OTP
#
# ใช้ run_lock ตัวเดียวกับรอบดึง ถ้าชนกันจะข้ามรอบไปเงียบ ๆ ไม่ใช่ error
$keepAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$keepScr`"" `
    -WorkingDirectory $PSScriptRoot

$keepSettings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -MultipleInstances IgnoreNew `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -RestartCount 1 `
    -RestartInterval (New-TimeSpan -Minutes 15)

$keepTriggers = @($KeepAliveTimes | ForEach-Object { New-ScheduledTaskTrigger -Daily -At $_ })

Register-ScheduledTask `
    -TaskName $KeepTask `
    -Action $keepAction `
    -Trigger $keepTriggers `
    -Settings $keepSettings `
    -Principal $principal `
    -Description "ต่ออายุ session ก่อนหมด — กันไม่ให้ต้องล็อกอินใหม่และขอ OTP" `
    -Force | Out-Null

Write-Host "ติดตั้ง $KeepTask แล้ว — ต่ออายุ session ทุกวัน $($KeepAliveTimes -join ' และ ')" -ForegroundColor Green
Write-Host ""
Show-Status
Write-Host ""
Write-Host "ทดสอบเลยด้วย : .\install_scheduler.ps1 -RunNow" -ForegroundColor Cyan
Write-Host "ดูผล          : output\dashboard.html" -ForegroundColor Cyan
