param([string]$Port = '', [ValidateRange(5,600)][int]$Seconds = 60)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
if (-not $Port) {
    $ports = @(Get-CimInstance Win32_SerialPort | Where-Object { $_.PNPDeviceID -match 'VID_0483' -or $_.Name -match 'STLink|ST-LINK' })
    if ($ports.Count -ne 1) {
        Write-Output 'Expected one ST-LINK virtual COM port. Detected ports:'
        Get-CimInstance Win32_SerialPort | Select-Object DeviceID,Name | Format-Table
        Write-Output 'For multiple boards, run scripts\capture.ps1 -Port COMx.'
        exit 2
    }
    $Port = $ports[0].DeviceID
}
$logs = Join-Path $projectRoot 'logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$outputPath = Join-Path $logs ('board_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.csv')
$serial = [System.IO.Ports.SerialPort]::new($Port,115200,[System.IO.Ports.Parity]::None,8,[System.IO.Ports.StopBits]::One)
$serial.ReadTimeout = 500
$serial.NewLine = "`n"
$writer = [System.IO.StreamWriter]::new($outputPath,$false,[System.Text.UTF8Encoding]::new($false))
$result = 1
try {
    $serial.Open()
    Write-Output "Serial $Port opened at 115200 8N1. Press the board RESET button now."
    Write-Output "Saving to $outputPath"
    $deadline = [DateTime]::UtcNow.AddSeconds($Seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        try { $line = $serial.ReadLine().TrimEnd("`r") } catch [TimeoutException] { continue }
        $writer.WriteLine($line); $writer.Flush(); Write-Output $line
        if ($line -match '^# RESULT=') { if ($line -match '^# RESULT=PASS\b') { $result=0 }; break }
    }
} finally { $serial.Dispose(); $writer.Dispose() }
if ($result -ne 0) { Write-Output 'The board did not report PASS. Preserve this log for diagnosis.' }
exit $result
