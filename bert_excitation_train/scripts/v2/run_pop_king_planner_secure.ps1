param(
    [ValidateSet("groq", "qwen")]
    [string]$Provider = "groq",
    [string]$OutputDir = "",
    [ValidateRange(1, 50)]
    [int]$StopAfterMacro = 50,
    [ValidateRange(1, 25)]
    [int]$StopAfterBlock = 25,
    [switch]$GlobalOnly,
    [switch]$BlocksOnly
)

$ErrorActionPreference = "Stop"
$planner = Join-Path $PSScriptRoot "generate_pop_king_500_qwen.py"
if (-not (Test-Path -LiteralPath $planner)) {
    throw "Planner not found: $planner"
}

$secret = Read-Host "Enter $Provider API key (hidden; used only by this process)" -AsSecureString
$secretPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secret)
try {
    $plainSecret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPtr)
    if ([string]::IsNullOrWhiteSpace($plainSecret)) {
        throw "API key is empty."
    }
    if ($Provider -eq "groq") {
        $env:GROQ_API_KEY = $plainSecret
        $env:PLANNER_PROVIDER = "groq"
        Remove-Item Env:DASHSCOPE_API_KEY -ErrorAction SilentlyContinue
    }
    else {
        $env:DASHSCOPE_API_KEY = $plainSecret
        $env:PLANNER_PROVIDER = "qwen"
        Remove-Item Env:GROQ_API_KEY -ErrorAction SilentlyContinue
    }
    $arguments = @(
        $planner,
        "--stop-after-macro", [string]$StopAfterMacro,
        "--stop-after-block", [string]$StopAfterBlock
    )
    if (-not [string]::IsNullOrWhiteSpace($OutputDir)) {
        $arguments += @("--output-dir", $OutputDir)
    }
    if ($GlobalOnly) { $arguments += "--global-only" }
    if ($BlocksOnly) { $arguments += "--blocks-only" }
    & python @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Planner exited with code $LASTEXITCODE. Check the last validation message."
    }
}
finally {
    $plainSecret = $null
    Remove-Item Env:GROQ_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:DASHSCOPE_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:PLANNER_PROVIDER -ErrorAction SilentlyContinue
    if ($secretPtr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPtr)
    }
}
