<#
TIRAI installer for Windows (PowerShell 5.1+).
  irm https://raw.githubusercontent.com/2tsoftwareapp/TIRAI/main/install.ps1 | iex
  & ([scriptblock]::Create((irm .../install.ps1))) --yes --agent claude     # other args go to `tirai setup`
  ./install.ps1 --binary | --source                                         # force one install method
Methods: --binary downloads the prebuilt tirai-windows-<arch>.exe from GitHub Releases (no Python needed);
         --source builds from source into a virtualenv; uses Python >= 3.10 if present, otherwise
         downloads uv + a private Python 3.12 into TIRAI_HOME (system Python is never touched).
         Default (auto): binary when a release asset exists, otherwise source.
Env: TIRAI_INSTALL_MODE (auto|binary|source), TIRAI_VERSION (release tag, default latest),
     TIRAI_BINARY (local path or URL of a prebuilt .exe), TIRAI_REPO, TIRAI_REF, TIRAI_SOURCE (local checkout or archive URL), TIRAI_HOME (default ~\.tirai),
     TIRAI_BIN_DIR (default ~\.local\bin), TIRAI_EXTRAS (default postgres), TIRAI_NO_SETUP=1,
     TIRAI_SETUP_ARGS (extra `tirai setup` args when piping into iex, e.g. "--yes --agent claude").
#>
$ErrorActionPreference = 'Stop'
# PowerShell turns unquoted `a,b` into an array; pass it on as one comma-separated argument.
$SetupArgs = @($args | ForEach-Object { if ($_ -is [array]) { $_ -join ',' } else { "$_" } })
if ($env:TIRAI_SETUP_ARGS) { $SetupArgs += ($env:TIRAI_SETUP_ARGS -split '\s+' | Where-Object { $_ }) }
$Mode = if ($env:TIRAI_INSTALL_MODE) { $env:TIRAI_INSTALL_MODE } else { 'auto' }
if ($SetupArgs -contains '--binary') { $Mode = 'binary' }
if ($SetupArgs -contains '--source') { $Mode = 'source' }
$SetupArgs = @($SetupArgs | Where-Object { $_ -ne '--binary' -and $_ -ne '--source' })

$Repo = if ($env:TIRAI_REPO) { $env:TIRAI_REPO } else { '2tsoftwareapp/TIRAI' }
$Ref = if ($env:TIRAI_REF) { $env:TIRAI_REF } else { 'main' }
$Source = if ($env:TIRAI_SOURCE) { $env:TIRAI_SOURCE } else { "https://github.com/$Repo/archive/$Ref.zip" }
$TiraiHome = if ($env:TIRAI_HOME) { $env:TIRAI_HOME } else { Join-Path $HOME '.tirai' }
$BinDir = if ($env:TIRAI_BIN_DIR) { $env:TIRAI_BIN_DIR } else { Join-Path $HOME '.local\bin' }
$Extras = if ($env:TIRAI_EXTRAS) { $env:TIRAI_EXTRAS } else { 'postgres,excel' }

function Log($m) { Write-Host "[tirai] $m" }
function Die($m) { Write-Host "[tirai] ERROR: $m" -ForegroundColor Red; exit 1 }

function Install-Binary {
  $BinHome = Join-Path $TiraiHome 'bin'
  New-Item -ItemType Directory -Force -Path $BinHome | Out-Null
  $Dest = Join-Path $BinHome 'tirai.exe'
  $Tmp = Join-Path $BinHome 'tirai.tmp.exe'
  if ($env:TIRAI_BINARY -and (Test-Path -LiteralPath $env:TIRAI_BINARY -PathType Leaf)) {
    Log "Using prebuilt binary $env:TIRAI_BINARY"
    Copy-Item -LiteralPath $env:TIRAI_BINARY -Destination $Tmp -Force
  } else {
    if ($env:TIRAI_BINARY) { $Url = $env:TIRAI_BINARY } else {
      $Arch = if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64') { 'arm64' } else { 'x64' }
      $Base = if ($env:TIRAI_VERSION) { "https://github.com/$Repo/releases/download/$env:TIRAI_VERSION" } else { "https://github.com/$Repo/releases/latest/download" }
      $Url = "$Base/tirai-windows-$Arch.exe"
    }
    Log "Downloading $Url"
    try { Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Tmp } catch { Log "Download failed: $Url"; return $false }
    try {
      $Expected = ((Invoke-WebRequest -UseBasicParsing -Uri "$Url.sha256").Content -split '\s+')[0]
      if ((Get-FileHash -Algorithm SHA256 -LiteralPath $Tmp).Hash -ne $Expected.ToUpper()) { Remove-Item $Tmp; Die "Checksum mismatch for $Url" }
      Log 'Checksum OK'
    } catch { }
  }
  & $Tmp --version *> $null
  if ($LASTEXITCODE -ne 0) { Remove-Item $Tmp -ErrorAction SilentlyContinue; Log 'Prebuilt binary does not run on this machine'; return $false }
  Move-Item -Force -LiteralPath $Tmp -Destination $Dest
  $script:Exe = $Dest
  return $true
}

function Install-FromSource {
  $Py = $null
  foreach ($c in @(@('py', '-3'), @('python'), @('python3'))) {
    if (Get-Command $c[0] -ErrorAction SilentlyContinue) {
      $exe = $c[0]; $pre = @($c | Select-Object -Skip 1)
      & $exe @pre -c "import sys, venv, ensurepip; sys.exit(sys.version_info < (3, 10))" 2>$null
      if ($LASTEXITCODE -eq 0) { $Py = $c; break }
    }
  }
  if (Test-Path -LiteralPath $Source -PathType Container) {
    $script:Source = ([Uri](Resolve-Path -LiteralPath $Source).Path).AbsoluteUri
  }
  New-Item -ItemType Directory -Force -Path $TiraiHome | Out-Null
  $VenvDir = Join-Path $TiraiHome 'venv'
  if (Test-Path $VenvDir) { Remove-Item -Recurse -Force $VenvDir }
  $VPy = Join-Path $VenvDir 'Scripts\python.exe'
  if ($Py) {
    $PyExe = $Py[0]; $PyPre = @($Py | Select-Object -Skip 1)
    Log "Creating virtualenv in $VenvDir"
    & $PyExe @PyPre -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) { Die 'python -m venv failed' }
    & $VPy -m pip install --quiet --upgrade pip
    Log "Building tirai[$Extras] from $Source"
    & $VPy -m pip install --quiet --upgrade "tirai[$Extras] @ $Source"
    if ($LASTEXITCODE -ne 0) { Die 'pip install failed' }
  } else {
    # No usable system Python: fetch uv and let it download a private Python into TIRAI_HOME.
    $Uv = (Get-Command uv -ErrorAction SilentlyContinue).Source
    if (-not $Uv) {
      $UvDir = Join-Path $TiraiHome 'uv'
      $Uv = Join-Path $UvDir 'uv.exe'
      if (-not (Test-Path $Uv)) {
        Log "No Python >= 3.10 found; installing uv into $UvDir to provide one"
        $env:UV_INSTALL_DIR = $UvDir; $env:UV_NO_MODIFY_PATH = '1'
        & powershell -NoProfile -ExecutionPolicy Bypass -Command 'irm https://astral.sh/uv/install.ps1 | iex' | Out-Null
        if (-not (Test-Path $Uv)) { Die 'uv install failed; install Python >= 3.10 (winget install Python.Python.3.12) and retry.' }
      }
    }
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $TiraiHome 'python'; $env:RUST_LOG = 'warn'
    & $Uv venv --quiet --python 3.12 $VenvDir
    if ($LASTEXITCODE -ne 0) { Die 'uv could not create a Python 3.12 virtualenv' }
    Log "Building tirai[$Extras] from $Source (uv-managed Python 3.12)"
    & $Uv pip install --quiet --python $VPy "tirai[$Extras] @ $Source"
    if ($LASTEXITCODE -ne 0) { Die 'uv pip install failed' }
  }
  $script:Exe = Join-Path $TiraiHome 'venv\Scripts\tirai.exe'
}

$Exe = $null
switch ($Mode) {
  'binary' { if (-not (Install-Binary)) { Die 'Binary install failed (try --source).' } }
  'source' { Install-FromSource }
  'auto' { if (-not (Install-Binary)) { Log 'Falling back to building from source'; Install-FromSource } }
  default { Die "Unknown TIRAI_INSTALL_MODE: $Mode (auto|binary|source)" }
}

# A .cmd shim keeps the venv's python.exe/pip.exe off PATH.
New-Item -ItemType Directory -Force -Path $BinDir | Out-Null
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
