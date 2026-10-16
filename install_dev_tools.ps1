# Installs Git for Windows and the GitHub CLI, then signs the GitHub CLI in.
# Uses winget when it exists; otherwise downloads the official installers from their GitHub releases.
$ErrorActionPreference = "Stop"
$log = Join-Path $PSScriptRoot "install_dev_tools_log.txt"
Start-Transcript -Path $log -Force | Out-Null
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

function Have($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }
function LatestAsset($repo, $pattern) {
    $rel = Invoke-RestMethod "https://api.github.com/repos/$repo/releases/latest" -Headers @{ "User-Agent" = "install-script" }
    $a = $rel.assets | Where-Object { $_.name -match $pattern } | Select-Object -First 1
    if (-not $a) { throw "No installer matching $pattern in $repo $($rel.tag_name)" }
    return $a
}
function Fetch($asset) {
    $out = Join-Path $env:TEMP $asset.name
    Write-Host "Downloading $($asset.name) ..."
    Invoke-WebRequest $asset.browser_download_url -OutFile $out -UseBasicParsing
    return $out
}

$gitExe = "$env:ProgramFiles\Git\cmd\git.exe"
$ghExe  = "$env:ProgramFiles\GitHub CLI\gh.exe"
$winget = Have "winget"
Write-Host "winget available: $winget"

try {
    if (Test-Path $gitExe) { Write-Host "Git is already installed." }
    elseif ($winget) { winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements }
    else {
        $f = Fetch (LatestAsset "git-for-windows/git" "^Git-.*-64-bit\.exe$")
        Write-Host "Installing Git (Windows may ask for permission: click Yes) ..."
        Start-Process $f -ArgumentList "/VERYSILENT", "/NORESTART", "/SP-" -Wait
    }

    if (Test-Path $ghExe) { Write-Host "GitHub CLI is already installed." }
    elseif ($winget) { winget install --id GitHub.cli -e --source winget --accept-package-agreements --accept-source-agreements }
    else {
        $f = Fetch (LatestAsset "cli/cli" "windows_amd64\.msi$")
        Write-Host "Installing GitHub CLI (Windows may ask for permission: click Yes) ..."
        Start-Process "msiexec.exe" -ArgumentList "/i", "`"$f`"", "/passive" -Wait
    }
} catch {
    Write-Host "INSTALL ERROR: $($_.Exception.Message)" -ForegroundColor Red
}

Write-Host ""
Write-Host "Git installed:        $(Test-Path $gitExe)"
Write-Host "GitHub CLI installed: $(Test-Path $ghExe)"
Stop-Transcript | Out-Null

if (Test-Path $ghExe) {
    Write-Host ""
    Write-Host "Now signing the GitHub CLI in to your GitHub account." -ForegroundColor Cyan
    Write-Host "It shows a one-time code and opens github.com: paste the code there and click Authorize."
    & $ghExe auth login --hostname github.com --git-protocol https --web
    & $ghExe auth status
}
Write-Host ""
Write-Host "Done. Close this window, then restart the Claude desktop app."
