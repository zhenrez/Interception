[CmdletBinding()]
param(
    [string]$Project = '',
    [switch]$VerifyOnly,
    [ValidateSet('', '3.13', '3.11')]
    [string]$RequiredPythonMinor = ''
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$Root = Split-Path -Parent $PSScriptRoot
$Venv = Join-Path $Root '.venv'
$VenvPython = Join-Path $Venv 'Scripts\python.exe'
$Artifacts = Join-Path $Root 'artifacts'
$FailureLog = Join-Path $Artifacts 'launcher-failure.txt'
$SuccessLog = Join-Path $Artifacts 'launcher-success.json'

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-ForbiddenPythonPath([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $true }
    return $Path -match '(?i)(conda|anaconda|miniconda|mambaforge|miniforge|nvidia|cuda|windowsapps|[\\/]\.venv[\\/]|[\\/]venv[\\/]|[\\/]envs?[\\/])'
}

function Test-PythonFields(
    [string]$Version,
    [string]$Implementation,
    [int]$Bits,
    [string]$Executable,
    [string]$BaseExecutable,
    [string]$Prefix,
    [string]$BasePrefix,
    [string]$ExpectedMinor,
    [string]$CandidateLabel
) {
    if ($Implementation -ne 'CPython') {
        Write-Host "Rejected $($CandidateLabel): implementation is $Implementation, not CPython." -ForegroundColor DarkYellow
        return $false
    }
    if ($Bits -ne 64) {
        Write-Host "Rejected $($CandidateLabel): $($Bits)-bit runtime; 64-bit required." -ForegroundColor DarkYellow
        return $false
    }
    if ($Version -notmatch "^$([regex]::Escape($ExpectedMinor))\.") {
        Write-Host "Rejected $($CandidateLabel): version $Version does not match $ExpectedMinor." -ForegroundColor DarkYellow
        return $false
    }
    foreach ($CandidatePath in @($Executable, $BaseExecutable, $Prefix, $BasePrefix)) {
        if (Test-ForbiddenPythonPath $CandidatePath) {
            Write-Host "Rejected $($CandidateLabel): forbidden Python environment path $CandidatePath" -ForegroundColor DarkYellow
            return $false
        }
    }
    try {
        $ActualPrefix = [IO.Path]::GetFullPath($Prefix).TrimEnd('\')
        $ActualBasePrefix = [IO.Path]::GetFullPath($BasePrefix).TrimEnd('\')
        if ($ActualPrefix -ine $ActualBasePrefix) {
            Write-Host "Rejected $($CandidateLabel): it is an unrelated virtual environment ($ActualPrefix)." -ForegroundColor DarkYellow
            return $false
        }
    }
    catch {
        Write-Host "Rejected $($CandidateLabel): Python prefix paths could not be validated." -ForegroundColor DarkYellow
        return $false
    }
    return $true
}

function Probe-PyLauncher([string]$Launcher, [string]$ExpectedMinor) {
    $Selector = "-$ExpectedMinor"
    Write-Host "Testing Python launcher candidate: $Launcher $Selector" -ForegroundColor DarkGray
    try {
        $Version = & $Launcher $Selector -I -c "import platform; print(platform.python_version())"
        if ($LASTEXITCODE -ne 0) { return $null }
        $Implementation = & $Launcher $Selector -I -c "import platform; print(platform.python_implementation())"
        $Bits = & $Launcher $Selector -I -c "import sys; print(64 if sys.maxsize > 2**32 else 32)"
        $Executable = & $Launcher $Selector -I -c "import sys; print(sys.executable)"
        $BaseExecutable = & $Launcher $Selector -I -c "import sys; print(sys._base_executable)"
        $Prefix = & $Launcher $Selector -I -c "import sys; print(sys.prefix)"
        $BasePrefix = & $Launcher $Selector -I -c "import sys; print(sys.base_prefix)"
        if ($LASTEXITCODE -ne 0) { return $null }
        if (-not (Test-PythonFields -Version $Version -Implementation $Implementation -Bits ([int]$Bits) -Executable $Executable -BaseExecutable $BaseExecutable -Prefix $Prefix -BasePrefix $BasePrefix -ExpectedMinor $ExpectedMinor -CandidateLabel "$Launcher $Selector")) {
            return $null
        }
        return @{
            Command = $Launcher
            Prefix = @($Selector)
            Version = $Version.Trim()
            Minor = $ExpectedMinor
            Executable = $Executable.Trim()
        }
    }
    catch {
        Write-Host "Rejected launcher candidate: $($_.Exception.Message)" -ForegroundColor DarkYellow
        return $null
    }
}

function Probe-PythonExe([string]$Path, [string]$ExpectedMinor) {
    Write-Host "Testing Python candidate: $Path" -ForegroundColor DarkGray
    try {
        $Version = & $Path -I -c "import platform; print(platform.python_version())"
        if ($LASTEXITCODE -ne 0) { return $null }
        $Implementation = & $Path -I -c "import platform; print(platform.python_implementation())"
        $Bits = & $Path -I -c "import sys; print(64 if sys.maxsize > 2**32 else 32)"
        $Executable = & $Path -I -c "import sys; print(sys.executable)"
        $BaseExecutable = & $Path -I -c "import sys; print(sys._base_executable)"
        $Prefix = & $Path -I -c "import sys; print(sys.prefix)"
        $BasePrefix = & $Path -I -c "import sys; print(sys.base_prefix)"
        if ($LASTEXITCODE -ne 0) { return $null }
        if (-not (Test-PythonFields -Version $Version -Implementation $Implementation -Bits ([int]$Bits) -Executable $Executable -BaseExecutable $BaseExecutable -Prefix $Prefix -BasePrefix $BasePrefix -ExpectedMinor $ExpectedMinor -CandidateLabel $Path)) {
            return $null
        }
        return @{
            Command = $Path
            Prefix = @()
            Version = $Version.Trim()
            Minor = $ExpectedMinor
            Executable = $Executable.Trim()
        }
    }
    catch {
        Write-Host "Rejected Python candidate: $($_.Exception.Message)" -ForegroundColor DarkYellow
        return $null
    }
}

function Select-BasePython {
    $Minors = if ($RequiredPythonMinor) { @($RequiredPythonMinor) } else { @('3.13', '3.11') }

    if ($env:pythonLocation) {
        $ActionPython = Join-Path $env:pythonLocation 'python.exe'
        if (Test-Path -LiteralPath $ActionPython) {
            foreach ($Minor in $Minors) {
                $Candidate = Probe-PythonExe -Path $ActionPython -ExpectedMinor $Minor
                if ($Candidate) { return $Candidate }
            }
        }
    }

    $Launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($Launcher) {
        foreach ($Minor in $Minors) {
            $Candidate = Probe-PyLauncher -Launcher $Launcher.Source -ExpectedMinor $Minor
            if ($Candidate) { return $Candidate }
        }
    }

    $Known = @()
    foreach ($Minor in $Minors) {
        $Compact = $Minor.Replace('.', '')
        if ($env:LocalAppData) {
            $Known += (Join-Path $env:LocalAppData "Programs\Python\Python$Compact\python.exe")
        }
        if ($env:ProgramFiles) {
            $Known += (Join-Path $env:ProgramFiles "Python$Compact\python.exe")
        }
        $Known += "C:\Python$Compact\python.exe"
    }
    foreach ($Path in $Known | Select-Object -Unique) {
        if (-not (Test-Path -LiteralPath $Path)) { continue }
        foreach ($Minor in $Minors) {
            $Candidate = Probe-PythonExe -Path $Path -ExpectedMinor $Minor
            if ($Candidate) { return $Candidate }
        }
    }

    $PathPythons = @(Get-Command python.exe -All -ErrorAction SilentlyContinue)
    foreach ($Minor in $Minors) {
        foreach ($Command in $PathPythons) {
            if (Test-ForbiddenPythonPath $Command.Source) { continue }
            $Candidate = Probe-PythonExe -Path $Command.Source -ExpectedMinor $Minor
            if ($Candidate) { return $Candidate }
        }
    }

    $Wanted = if ($RequiredPythonMinor) { $RequiredPythonMinor } else { '3.13 or 3.11' }
    throw @"
No clean 64-bit CPython $Wanted installation was found.

Interception deliberately refused NVIDIA/CUDA Python, Conda/Anaconda/Miniconda,
Miniforge/Mambaforge, Windows Store aliases, unrelated virtual environments,
and non-CPython runtimes.

Install the official 64-bit CPython build from python.org with the Python
Launcher enabled, then run Start-Interception.cmd again.
"@
}

function Clear-ContaminatingEnvironment {
    Get-ChildItem Env: | Where-Object {
        $_.Name -match '^(PYTHON|PYLAUNCHER|CONDA|_CONDA|VIRTUAL_ENV|PIPENV|POETRY|UV_|CUDA|NVIDIA|MAMBA|MICROMAMBA|PYENV|PIP_)'
    } | ForEach-Object {
        Remove-Item "Env:$($_.Name)" -ErrorAction SilentlyContinue
    }

    foreach ($Name in @('SSL_CERT_FILE', 'REQUESTS_CA_BUNDLE', 'CURL_CA_BUNDLE')) {
        $Value = [Environment]::GetEnvironmentVariable($Name)
        if ($Value -and (Test-ForbiddenPythonPath $Value)) {
            Remove-Item "Env:$Name" -ErrorAction SilentlyContinue
        }
    }

    $SafePath = New-Object System.Collections.Generic.List[string]
    foreach ($Entry in ($env:PATH -split ';')) {
        if ([string]::IsNullOrWhiteSpace($Entry)) { continue }
        if ($Entry -match '(?i)(python|conda|anaconda|miniconda|miniforge|mambaforge|nvidia|cuda|windowsapps|[\\/]\.venv([\\/]|$)|[\\/]venv([\\/]|$)|[\\/]envs?([\\/]|$))') {
            continue
        }
        if (-not $SafePath.Contains($Entry)) { $SafePath.Add($Entry) }
    }

    $env:PATH = (@((Join-Path $Venv 'Scripts')) + @($SafePath)) -join ';'
    $env:VIRTUAL_ENV = $Venv
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONPATH = ''
    $env:PYTHONUTF8 = '1'
    $env:PIP_CONFIG_FILE = 'NUL'
    $env:PIP_DISABLE_PIP_VERSION_CHECK = '1'
    $env:PIP_NO_INPUT = '1'
}

function Test-Venv([hashtable]$Base) {
    if (-not (Test-Path -LiteralPath $VenvPython)) { return $false }
    $VenvConfig = Join-Path $Venv 'pyvenv.cfg'
    if (-not (Test-Path -LiteralPath $VenvConfig)) { return $false }

    $ConfigText = Get-Content -LiteralPath $VenvConfig -Raw -ErrorAction SilentlyContinue
    if ($ConfigText -notmatch '(?im)^\s*include-system-site-packages\s*=\s*false\s*$') {
        return $false
    }

    $Probe = 'import json,platform,struct,sys; print(json.dumps({"version":platform.python_version(),"implementation":platform.python_implementation(),"bits":struct.calcsize("P")*8,"base_executable":getattr(sys,"_base_executable",sys.executable),"prefix":sys.prefix,"base_prefix":sys.base_prefix}))'
    try {
        $Raw = & $VenvPython -I -c $Probe 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $Raw) { return $false }
        $Info = $Raw | ConvertFrom-Json
        if ($Info.implementation -ne 'CPython' -or $Info.bits -ne 64) { return $false }
        if ($Info.version -notmatch "^$([regex]::Escape($Base.Minor))\.") { return $false }
        if (Test-ForbiddenPythonPath $Info.base_executable) { return $false }
        if (Test-ForbiddenPythonPath $Info.base_prefix) { return $false }
        $ExpectedPrefix = [IO.Path]::GetFullPath($Venv).TrimEnd('\')
        $ActualPrefix = [IO.Path]::GetFullPath([string]$Info.prefix).TrimEnd('\')
        return $ActualPrefix -ieq $ExpectedPrefix
    }
    catch {
        return $false
    }
}

function Remove-IncompatibleVenv {
    if (-not (Test-Path -LiteralPath $Venv)) { return }
    Write-Step 'Replacing an incompatible or externally managed .venv'
    try {
        Remove-Item -LiteralPath $Venv -Recurse -Force
    }
    catch {
        throw @"
Interception could not replace the existing .venv because Windows reports that
one or more files are still in use. Close older Interception/Python terminals
using this repository, then run Start-Interception.cmd again.

Nothing outside this repository was changed.
"@
    }
}

function Write-Failure($Failure) {
    $Lines = @(
        "Interception Windows launcher failure",
        "UTC: $([DateTime]::UtcNow.ToString('o'))",
        "Root: $Root",
        "Message: $($Failure.Exception.Message)",
        "",
        "--- PowerShell stack ---",
        [string]$Failure.ScriptStackTrace,
        "",
        "No global Python, CUDA, NVIDIA, Conda, or Anaconda installation was changed."
    )
    try {
        Set-Content -LiteralPath $FailureLog -Value $Lines -Encoding UTF8
    }
    catch {}
}

try {
    Set-Location $Root
    New-Item -ItemType Directory -Force -Path $Artifacts | Out-Null

    if ($Root.StartsWith('\\')) {
        throw 'Interception must bootstrap from a local Windows drive, not a UNC/network share.'
    }

    Write-Step 'Selecting a clean 64-bit CPython 3.13 or 3.11 installation'
    $Base = Select-BasePython
    Write-Host "Using CPython $($Base.Version): $($Base.Executable)"

    if ((Test-Path -LiteralPath $Venv) -and -not (Test-Venv $Base)) {
        Remove-IncompatibleVenv
    }

    if (-not (Test-Path -LiteralPath $VenvPython)) {
        Write-Step 'Creating the isolated repository-local .venv'
        $CreateArgs = @($Base.Prefix) + @('-I', '-m', 'venv', $Venv)
        & $Base.Command @CreateArgs
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $VenvPython)) {
            throw 'Virtual-environment creation failed.'
        }
    }

    Clear-ContaminatingEnvironment

    Write-Step 'Checking pip inside the isolated environment'
    & $VenvPython -I -m pip --version *> $null
    if ($LASTEXITCODE -ne 0) {
        & $VenvPython -I -m ensurepip --upgrade
        if ($LASTEXITCODE -ne 0) {
            throw 'pip bootstrap failed inside .venv.'
        }
    }

    $RuntimeReady = $false
    try {
        & $VenvPython -I -c "import interception, jsonschema" *> $null
        $RuntimeReady = ($LASTEXITCODE -eq 0)
    }
    catch { $RuntimeReady = $false }

    if (-not $RuntimeReady) {
        $Wheelhouse = Join-Path $Root ('wheelhouse\\py' + $Base.Minor + '-win_amd64')
        if (Test-Path -LiteralPath $Wheelhouse -PathType Container) {
            Write-Step 'Installing Interception from the bundled offline wheelhouse'
            & $VenvPython -I -m pip install --disable-pip-version-check --no-input --no-index --find-links $Wheelhouse interception-bridge==0.1.0
        }
        else {
            Write-Step 'Installing Interception with ARIADNE-style pip isolation'
            & $VenvPython -I -m pip install --disable-pip-version-check --no-input --index-url https://pypi.org/simple -e .
        }
        if ($LASTEXITCODE -ne 0) {
            throw 'Interception dependency installation failed.'
        }
    }
    else {
        Write-Step 'Reusing the verified repository-local Interception environment'
    }

    Write-Step 'Verifying required Interception runtime imports'
    & $VenvPython -I -c "import interception, jsonschema"
    if ($LASTEXITCODE -ne 0) {
        throw 'Interception could not import its required runtime dependencies.'
    }

    Write-Step 'Checking optional desktop Tcl/Tk files'
    Remove-Item Env:TCL_LIBRARY -ErrorAction SilentlyContinue
    Remove-Item Env:TK_LIBRARY -ErrorAction SilentlyContinue
    $PythonHome = Split-Path -Parent $Base.Executable
    $TclRoot = Join-Path $PythonHome 'tcl'
    $TclLibrary = $null
    $TkLibrary = $null
    if (Test-Path -LiteralPath $TclRoot -PathType Container) {
        $TclLibrary = Get-ChildItem -LiteralPath $TclRoot -Directory -Filter 'tcl8.*' -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'init.tcl') } |
            Sort-Object Name -Descending | Select-Object -First 1
        $TkLibrary = Get-ChildItem -LiteralPath $TclRoot -Directory -Filter 'tk8.*' -ErrorAction SilentlyContinue |
            Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'tk.tcl') } |
            Sort-Object Name -Descending | Select-Object -First 1
    }
    $DesktopAvailable = ($null -ne $TclLibrary -and $null -ne $TkLibrary)
    if ($DesktopAvailable) {
        $env:TCL_LIBRARY = $TclLibrary.FullName
        $env:TK_LIBRARY = $TkLibrary.FullName
    }
    else {
        Write-Host 'Desktop Tcl/Tk files are unavailable. Interception core is healthy; using headless mode.' -ForegroundColor Yellow
    }

    Write-Step 'Compiling Interception Python sources'
    & $VenvPython -I -m compileall -q (Join-Path $Root 'interception')
    if ($LASTEXITCODE -ne 0) {
        throw 'Python compilation check failed.'
    }

    Write-Step 'Running an isolated mailbox-install smoke test'
    $Smoke = "import tempfile; from pathlib import Path; from interception.cli import install; t=tempfile.TemporaryDirectory(); install(t.name); assert Path(t.name).joinpath('.inference_bridge','connection.json').is_file(); t.cleanup()"
    & $VenvPython -I -c $Smoke
    if ($LASTEXITCODE -ne 0) {
        throw 'Interception mailbox smoke test failed.'
    }

    $Success = @{
        service = 'Interception'
        verified_utc = [DateTime]::UtcNow.ToString('o')
        python = $Base.Version
        python_executable = $Base.Executable
        venv = $Venv
        desktop_available = $DesktopAvailable
    } | ConvertTo-Json
    Set-Content -LiteralPath $SuccessLog -Value $Success -Encoding UTF8

    if ($VerifyOnly) {
        Write-Host ""
        Write-Host 'Windows one-click bootstrap verification passed.' -ForegroundColor Green
        Write-Host "Environment: $Venv"
        if (-not $DesktopAvailable) {
            Write-Host 'Desktop UI unavailable; CLI/headless Interception remains usable.' -ForegroundColor Yellow
        }
        exit 0
    }

    if ($Project) {
        if (-not (Test-Path -LiteralPath $Project -PathType Container)) {
            throw "Requested project directory does not exist: $Project"
        }
        $ResolvedProject = (Resolve-Path -LiteralPath $Project).Path
    }
    else {
        $ResolvedProject = $null
    }

    if ($DesktopAvailable) {
        Write-Step 'Launching Interception desktop'
        if ($ResolvedProject) {
            & $VenvPython -I -m interception desktop $ResolvedProject
        }
        else {
            & $VenvPython -I -m interception desktop
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Interception desktop exited with code $LASTEXITCODE."
        }
    }
    else {
        Write-Step 'Launching Interception in headless mode'
        if ($ResolvedProject) {
            & $VenvPython -I -m interception install $ResolvedProject
            if ($LASTEXITCODE -ne 0) {
                throw "Interception project initialization exited with code $LASTEXITCODE."
            }
            Write-Host ''
            Write-Host 'Interception is ready without the desktop UI.' -ForegroundColor Green
            Write-Host "Project: $ResolvedProject"
            Write-Host 'Use the CLI commands status/proof/batch/import-return until Tcl/Tk is restored.'
        }
        else {
            Write-Host ''
            Write-Host 'Interception core is installed and verified.' -ForegroundColor Green
            Write-Host 'Desktop UI is unavailable because this Python install cannot load Tcl/Tk.'
            Write-Host 'Run this launcher again with -Project followed by a project folder for headless setup.'
        }
    }
}
catch {
    Write-Failure $_
    Write-Host ""
    Write-Host 'STARTUP FAILED' -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host 'A readable diagnostic was saved to:'
    Write-Host "  $FailureLog"
    Write-Host ""
    Write-Host 'No global Python, CUDA, NVIDIA, Conda, or Anaconda installation was changed.'
    exit 1
}
