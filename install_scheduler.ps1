# ติดตั้ง/ถอด Task Scheduler ให้รันรอบประจำวันอัตโนมัติ (Phase 4)
#
#   .\install_scheduler.ps1                  ติดตั้ง (ค่าเริ่มต้น 06:00)
#   .\install_scheduler.ps1 -Time 05:30      เปลี่ยนเวลา
#   .\install_scheduler.ps1 -Status          ดูสถานะ/รอบล่าสุด
#   .\install_scheduler.ps1 -RunNow          สั่งรันเดี๋ยวนี้เพื่อทดสอบ
#   .\install_scheduler.ps1 -Remove          ถอดออก
#
# ต้องเปิด PowerShell แบบ Run as Administrator ตอนติดตั้ง/ถอด

param(
    [string]$Time = "06:00",
    [string]$MailTime = "08:00",
    [switch]$Status,
    [switch]$RunNow,
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$TaskName = "DealerMKP-DailyOrders"
$MailTask = "DealerMKP-DailyMail"
$script   = Join-Path $PSScriptRoot "run_daily.ps1"
$mailScr  = Join-Path $PSScriptRoot "send_report.ps1"

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
}

if ($Status) { Show-Status; exit 0 }

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "สั่งรันแล้ว — ดูความคืบหน้าด้วย .\install_scheduler.ps1 -Status" -ForegroundColor Cyan
    exit 0
}

if ($Remove) {
    foreach ($n in @($TaskName, $MailTask)) {
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

# trigger 1: ทุกวันตามเวลาที่ตั้ง
# trigger 2: ตอนล็อกอิน — เผื่อคืนนั้นเครื่องปิดอยู่ จะได้ตามเก็บให้ตอนเปิดเครื่อง
#            (-SkipIfDone กันไม่ให้ดึงซ้ำถ้ารอบเช้าวิ่งไปแล้ว)
$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At $Time),
    (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME")
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

$mailTriggers = @(
    (New-ScheduledTaskTrigger -Daily -At $MailTime),
    # trigger ตอนล็อกอิน + หน่วง 25 นาที — เผื่อเปิดเครื่องสาย
    # หน่วงเพื่อให้รอบดึง (ที่เริ่มตอนล็อกอินเหมือนกัน) ทำงานจบก่อน
    # ถ้ารอบดึงส่งอีเมลไปแล้ว -SkipIfSent จะกันไม่ให้ส่งซ้ำอยู่ดี
    (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME")
)
$mailTriggers[1].Delay = "PT25M"

Register-ScheduledTask `
    -TaskName $MailTask `
    -Action $mailAction `
    -Trigger $mailTriggers `
    -Settings $mailSettings `
    -Principal $principal `
    -Description "ส่งอีเมลสรุปผลการดึงคำสั่งซื้อประจำวัน (Outlook)" `
    -Force | Out-Null

Write-Host "ติดตั้ง $MailTask แล้ว — ส่งอีเมลทุกวัน $MailTime" -ForegroundColor Green
Write-Host ""
Show-Status
Write-Host ""
Write-Host "ทดสอบเลยด้วย : .\install_scheduler.ps1 -RunNow" -ForegroundColor Cyan
Write-Host "ดูผล          : output\dashboard.html" -ForegroundColor Cyan
