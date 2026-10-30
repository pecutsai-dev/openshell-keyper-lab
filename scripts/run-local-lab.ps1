param(
    [switch]$ProbeUpstream,
    [switch]$OpenShell,
    [switch]$PortableVM
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$labRoot = Join-Path $repoRoot '.approval-lab/isolated-run'
$runId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 8)
$runRoot = Join-Path $labRoot $runId
$projectRoot = Join-Path $runRoot 'project'
$reportRoot = Join-Path $runRoot 'reports'
$tempRoot = Join-Path $runRoot 'temp'
$dataRoot = Join-Path $runRoot 'data'
$venvRoot = Join-Path $runRoot 'venv'
$uv = (Get-Command uv -ErrorAction Stop).Source

# Reuse an existing interpreter without installing Python into the host.
$existingPython = Join-Path $repoRoot '.venv/Scripts/python.exe'
if (Test-Path -LiteralPath $existingPython) {
    $pythonCommand = $existingPython
} else {
    $pythonCommand = (Get-Command python -ErrorAction Stop).Source
}
$pythonPath = & $pythonCommand -I -c 'import sys; assert sys.version_info >= (3, 11); print(sys._base_executable)'
if ($LASTEXITCODE -ne 0 -or -not $pythonPath -or -not (Test-Path -LiteralPath $pythonPath)) {
    throw 'An existing Python 3.11+ installation is required; no system installation was attempted.'
}

foreach ($directory in @($projectRoot, $reportRoot, $tempRoot, $dataRoot)) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}
# Copy only project source and documentation, never credentials, .git or a venv.
foreach ($name in @('pyproject.toml', 'uv.lock', 'README.md', 'README.zh-TW.md', '.gitignore')) {
    Copy-Item -LiteralPath (Join-Path $repoRoot $name) -Destination $projectRoot
}
foreach ($name in @('src', 'tests', 'docs', 'examples')) {
    $sourceRoot = Join-Path $repoRoot $name
    foreach ($file in Get-ChildItem -LiteralPath $sourceRoot -Recurse -File) {
        if (($file.Extension -notin @('.py', '.md', '.xml', '.proto', '.json') -and $file.Name -ne 'LICENSE') -or $file.FullName -match '[\\/]__pycache__[\\/]') { continue }
        $relative = $file.FullName.Substring($repoRoot.Length).TrimStart([char[]]'\/')
        $destination = Join-Path $projectRoot $relative
        New-Item -ItemType Directory -Path (Split-Path -Parent $destination) -Force | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $destination
    }
}

$changes = @{
    TEMP = $tempRoot
    TMP = $tempRoot
    TMPDIR = $tempRoot
    UV_CACHE_DIR = (Join-Path $labRoot 'uv-cache')
    UV_PROJECT_ENVIRONMENT = $venvRoot
    UV_PYTHON_INSTALL_DIR = (Join-Path $runRoot 'python-downloads')
    UV_PYTHON_DOWNLOADS = 'never'
    UV_NO_CONFIG = '1'
    UV_TOOL_DIR = (Join-Path $runRoot 'uv-tools')
    UV_TOOL_BIN_DIR = (Join-Path $runRoot 'uv-bin')
    PYTHONNOUSERSITE = '1'
    PYTHONPATH = $null
    PYTHONHOME = $null
    VIRTUAL_ENV = $null
    APPROVAL_LAB_DB = (Join-Path $dataRoot 'approvals.sqlite3')
}
$previous = @{}
$success = $false
function Invoke-LabCommand {
    param([string]$Executable, [string[]]$Arguments, [string]$Log)
    # Windows PowerShell wraps normal native stderr as ErrorRecord objects.
    # The exit code determines success, rather than informational stderr.
    $ErrorActionPreference = 'Continue'
    & $Executable @Arguments 2>&1 | ForEach-Object { $_.ToString() } | Tee-Object -FilePath $Log
    if ($LASTEXITCODE -ne 0) { throw "Command failed (exit $LASTEXITCODE). See $Log" }
}
try {
    foreach ($name in $changes.Keys) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
        [Environment]::SetEnvironmentVariable($name, $changes[$name], 'Process')
    }
    Push-Location -LiteralPath $projectRoot
    try {
        Write-Host "Lab directory: $runRoot"
        $syncArguments = @('sync', '--locked', '--python', $pythonPath, '--no-python-downloads', '--no-config', '--system-certs')
        if ($OpenShell) { $syncArguments += @('--extra', 'openshell') }
        if ($PortableVM) { $syncArguments += @('--extra', 'portable-vm') }
        Invoke-LabCommand -Executable $uv -Arguments $syncArguments -Log (Join-Path $reportRoot 'setup.log')
        $labPython = Join-Path $venvRoot 'Scripts/python.exe'
        Invoke-LabCommand -Executable $labPython -Arguments @('-m', 'approval_lab.demo') -Log (Join-Path $reportRoot 'demo.log')
        Invoke-LabCommand -Executable $labPython -Arguments @('-m', 'pytest', '-q', '--tb=short', '--basetemp', (Join-Path $tempRoot 'pytest'), '--junitxml', (Join-Path $reportRoot 'tests.xml')) -Log (Join-Path $reportRoot 'tests.log')
        if ($ProbeUpstream) {
            Invoke-LabCommand -Executable $labPython -Arguments @('-m', 'approval_lab.openshell_probe', '--output', (Join-Path $reportRoot 'openshell-probe.json')) -Log (Join-Path $reportRoot 'probe.log')
        }
        $success = $true
    } finally {
        Pop-Location
    }
} finally {
    foreach ($name in $previous.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process')
    }
    @{
        success = $success
        mode = 'local-mock-folder'
        os_isolation = $false
        live_openshell_verified = $false
        project = $projectRoot
        python = (Join-Path $venvRoot 'Scripts/python.exe')
        database = (Join-Path $dataRoot 'approvals.sqlite3')
        reports = $reportRoot
        upstream_probe_requested = [bool]$ProbeUpstream
        openshell_protocol_tests = [bool]$OpenShell
        portable_vm_tools = [bool]$PortableVM
    } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reportRoot 'summary.json') -Encoding UTF8
}
Write-Host "PASS. Reports: $reportRoot"
