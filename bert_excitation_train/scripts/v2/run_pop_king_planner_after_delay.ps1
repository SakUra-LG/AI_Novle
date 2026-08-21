param(
    [ValidateRange(1, 86400)]
    [int]$DelaySeconds = 1020,
    [ValidateSet("groq", "qwen")]
    [string]$Provider = "groq"
)

$ErrorActionPreference = "Stop"
$launcher = Join-Path $PSScriptRoot "run_pop_king_planner_saved.ps1"
if (-not (Test-Path -LiteralPath $launcher)) {
    throw "Saved-key planner launcher not found: $launcher"
}

Write-Output "[$(Get-Date -Format o)] delayed planner waiting ${DelaySeconds}s"
Start-Sleep -Seconds $DelaySeconds
Write-Output "[$(Get-Date -Format o)] delayed planner starting"
& $launcher -Provider $Provider -RetryCycles 3
exit $LASTEXITCODE
