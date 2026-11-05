param([switch]$Logs)
$ErrorActionPreference = 'Stop'
$pythonCandidates = @(
    'X:\miniconda3\pythonw.exe',
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\pythonw.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\pythonw.exe')
)
$pythonCmd = Get-Command python.exe -ErrorAction SilentlyContinue
if ($pythonCmd) { $pythonCandidates += (Join-Path (Split-Path $pythonCmd.Source) 'pythonw.exe') }
$pythonExe = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $pythonExe) { throw 'Python 3 not found. Use the Python installed for this development environment.' }
$appFile = Join-Path $PSScriptRoot 'native.py'
$appArguments = @(('"' + $appFile + '"'))
if ($Logs) { $appArguments += '--logs' }
Start-Process -FilePath $pythonExe -ArgumentList $appArguments -WorkingDirectory $PSScriptRoot -WindowStyle Normal
