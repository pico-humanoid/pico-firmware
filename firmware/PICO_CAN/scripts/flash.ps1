param([ValidateSet('Loopback','External')][string]$Mode = 'Loopback')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$programmer = Join-Path $env:LOCALAPPDATA 'stm32cube\bundles\programmer\2.23.0\bin\STM32_Programmer_CLI.exe'
$image = Join-Path $projectRoot "build\$Mode\PICO_CAN.elf"
if (-not (Test-Path -LiteralPath $image)) { Write-Error "Build the $Mode preset first."; exit 1 }
$probeList = & $programmer -l st-link 2>&1
$probeList | Write-Output
if (($probeList -join "`n") -notmatch 'ST-LINK SN\s*:') {
    Write-Output 'No ST-LINK detected. Connect the NUCLEO-G474RE ST-LINK USB connector and run again.'
    exit 2
}
& $programmer -c port=SWD freq=1000 -w $image -v -rst
exit $LASTEXITCODE
