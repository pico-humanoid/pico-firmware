param([ValidateSet('Loopback','External','All')][string]$Mode = 'Loopback')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$bundleRoot = Join-Path $env:LOCALAPPDATA 'stm32cube\bundles'
$env:Path = (Join-Path $bundleRoot 'gnu-tools-for-stm32\14.3.1+st.2\bin') + ';' + (Join-Path $bundleRoot 'ninja\1.13.2+st.1\bin') + ';D:\STM32Tools\bin;' + $env:Path
$cmakeExe = Join-Path $bundleRoot 'cmake\4.4.0+st.1\bin\cmake.exe'
Push-Location -LiteralPath $projectRoot
try {
    $presets = if ($Mode -eq 'All') { @('Loopback','External') } else { @($Mode) }
    foreach ($preset in $presets) {
        & $cmakeExe --preset $preset
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & $cmakeExe --build --preset $preset --parallel 4
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
} finally { Pop-Location }
