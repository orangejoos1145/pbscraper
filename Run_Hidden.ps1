$ScriptDir = Split-Path -Parent$MyInvocation.MyCommand.Definition
Set-Location $ScriptDir

# Load Windows Notification modules
[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

# 1. Show "Starting" Notification
$startXml = New-Object Windows.Data.Xml.Dom.XmlDocument
$startTemplate = "<toast duration=`"short`"><visual><binding template=`"ToastText02`"><text id=`"1`">PB Scraper Started</text><text id=`"2`">Running in the background. Please wait...</text></binding></visual></toast>"
$startXml.LoadXml($startTemplate)
$startToast = [Windows.UI.Notifications.ToastNotification]::new($startXml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("PowerShell").Show($startToast)

# 2. Run the actual scraper
$log = & "cmd.exe" /c "Update_Site.bat" 2>&1 | Out-String

# 3. Determine the final result
$title = "PB Scraper Complete"
if ($log -match "fatal:" -or $log -match "error:") {
    $message = "Failed: Git connection or network error occurred."
} elseif ($log -match "nothing added to commit" -or $log -match "up to date") {
    $message = "Already ran. No new data to push."
} else {
    $message = "Success! Live website updated."
}

# 4. Show "Finished" Notification
$endXml = New-Object Windows.Data.Xml.Dom.XmlDocument
$endTemplate = "<toast duration=`"short`"><visual><binding template=`"ToastText02`"><text id=`"1`">$title</text><text id=`"2`">$message</text></binding></visual></toast>"
$endXml.LoadXml($endTemplate)
$endToast = [Windows.UI.Notifications.ToastNotification]::new($endXml)
[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("PowerShell").Show($endToast)