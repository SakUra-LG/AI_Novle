Set-StrictMode -Version Latest

function Get-PlannerApiKeyVaultPath {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("groq", "qwen")]
        [string]$Provider
    )
    $root = Join-Path $env:LOCALAPPDATA "Codex\AI_Novle\planner_secrets"
    return Join-Path $root "$Provider.dpapi"
}

function Test-PlannerApiKeySaved {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("groq", "qwen")]
        [string]$Provider
    )
    return Test-Path -LiteralPath (Get-PlannerApiKeyVaultPath -Provider $Provider)
}

function Save-PlannerApiKey {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("groq", "qwen")]
        [string]$Provider,
        [Parameter(Mandatory = $true)]
        [Security.SecureString]$Secret
    )
    $path = Get-PlannerApiKeyVaultPath -Provider $Provider
    $directory = Split-Path -Parent $path
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
    # ConvertFrom-SecureString without a supplied key uses Windows DPAPI.  The
    # ciphertext can only be decrypted by this Windows user on this machine.
    $encrypted = ConvertFrom-SecureString -SecureString $Secret
    Set-Content -LiteralPath $path -Value $encrypted -Encoding UTF8 -NoNewline
}

function Get-PlannerApiKey {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("groq", "qwen")]
        [string]$Provider
    )
    $path = Get-PlannerApiKeyVaultPath -Provider $Provider
    if (-not (Test-Path -LiteralPath $path)) {
        return $null
    }
    $encrypted = Get-Content -LiteralPath $path -Raw -Encoding UTF8
    if ([string]::IsNullOrWhiteSpace($encrypted)) {
        return $null
    }
    return ConvertTo-SecureString -String $encrypted.Trim()
}

function Remove-PlannerApiKey {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("groq", "qwen")]
        [string]$Provider
    )
    $path = Get-PlannerApiKeyVaultPath -Provider $Provider
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
}
