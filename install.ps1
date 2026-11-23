<#
TIRAI installer for Windows (PowerShell 5.1+).
  irm https://raw.githubusercontent.com/2tsoftwareapp/TIRAI/main/install.ps1 | iex
  & ([scriptblock]::Create((irm .../install.ps1))) --yes --agent claude     # args go to `tirai setup`
Env: TIRAI_REPO, TIRAI_REF, TIRAI_SOURCE (local checkout or archive URL), TIRAI_HOME (default ~\.tirai),
     TIRAI_BIN_DIR (default ~\.local\bin), TIRAI_EXTRAS (default postgres), TIRAI_NO_SETUP=1,
     TIRAI_SETUP_ARGS (extra `tirai setup` args when piping into iex, e.g. "--yes --agent claude").
#>
$ErrorActionPreference = 'Stop'
$SetupArgs = @($args)
if ($env:TIRAI_SETUP_ARGS) { $SetupArgs += ($env:TIRAI_SETUP_ARGS -split '\s+' | Where-Object { $_ }) }

$Repo = if ($env:TIRAI_REPO) { $env:TIRAI_REPO } else { '2tsoftwareapp/TIRAI' }
$Ref = if ($env:TIRAI_REF) { $env:TIRAI_REF } else { 'main' }
$Source = if ($env:TIRAI_SOURCE) { $env:TIRAI_SOURCE } else { "https://github.com/$Repo/archive/$Ref.zip" }
$TiraiHome = if ($env:TIRAI_HOME) { $env:TIRAI_HOME } else { Join-Path $HOME '.tirai' }
$BinDir = if ($env:TIRAI_BIN_DIR) { $env:TIRAI_BIN_DIR } else { Join-Path $HOME '.local\bin' }
$Extras = if ($env:TIRAI_EXTRAS) { $env:TIRAI_EXTRAS } else { 'postgres' }

function Log($m) { Write-Host "[tirai] $m" }
function Die($m) { Write-Host "[tirai] ERROR: $m" -ForegroundColor Red; exit 1 }

$Py = $null
foreach ($c in @(@('py', '-3'), @('python'), @('python3'))) {
  if (Get-Command $c[0] -ErrorAction SilentlyContinue) {
    $exe = $c[0]; $pre = @($c | Select-Object -Skip 1)
    & $exe @pre -c "import sys; sys.exit(sys.version_info < (3, 10))" 2>$null
    if ($LASTEXITCODE -eq 0) { $Py = $c; break }
  }
}
if (-not $Py) { Die 'Python >= 3.10 is required: winget install Python.Python.3.12' }
$PyExe = $Py[0]; $PyPre = @($Py | Select-Object -Skip 1)

if (Test-Path -LiteralPath $Source -PathType Container) {
  $Source = ([Uri](Resolve-Path -LiteralPath $Source).Path).AbsoluteUri
}

Log "Creating virtualenv in $TiraiHome\venv"
New-Item -ItemType Directory -Force -Path $TiraiHome | Out-Null
& $PyExe @PyPre -m venv (Join-Path $TiraiHome 'venv')
if ($LASTEXITCODE -ne 0) { Die 'python -m venv failed' }
$VPy = Join-Path $TiraiHome 'venv\Scripts\python.exe'
& $VPy -m pip install --quiet --upgrade pip
Log "Installing tirai[$Extras] from $Source"
& $VPy -m pip install --quiet --upgrade "tirai[$Extras] @ $Source"
if ($LASTEXITCODE -ne 0) { Die 'pip install failed' }

# A .cmd shim keeps the venv's python.exe/pip.exe off PATH.
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
$Exe = Join-Path $TiraiHome 'venv\Scripts\tirai.exe'
Set-Content -Path (Join-Path $BinDir 'tirai.cmd') -Value "@echo off`r`n`"$Exe`" %*" -Encoding ASCII
Log "Created $BinDir\tirai.cmd"

$UserPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
if (-not (($UserPath -split ';') -contains $BinDir)) {
  [Environment]::SetEnvironmentVariable('PATH', (@($BinDir) + @($UserPath -split ';' | Where-Object { $_ })) -join ';', 'User')
  Log "Added $BinDir to your user PATH (open a new terminal)"
}
if (-not (($env:PATH -split ';') -contains $BinDir)) { $env:PATH = "$BinDir;$env:PATH" }

& $Exe --version
if ($env:TIRAI_NO_SETUP -ne '1') {
  & $Exe setup @SetupArgs
  exit $LASTEXITCODE
}
