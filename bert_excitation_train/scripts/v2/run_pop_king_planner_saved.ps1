param(
    [ValidateSet("groq", "qwen", "vectorengine")]
    [string]$Provider = "groq",
    [string]$OutputDir = "bert_excitation_train\outputs_pop_king_v6_compiled_story_first_500",
    [ValidateRange(1, 50)]
    [int]$StopAfterMacro = 50,
    [ValidateRange(1, 25)]
    [int]$StopAfterBlock = 25,
    [ValidateRange(1, 20)]
    [int]$RetryCycles = 1
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "planner_api_key_vault.ps1")

$secretPtr = [IntPtr]::Zero
$plainSecret = $null
$secureSecret = $null
$exitCode = 1
try {
    $plainFileName = "api.txt"
    if ($Provider -eq "vectorengine") {
        $plainFileName = "vectorengine_api.txt"
    }
    $plainFile = Join-Path $PSScriptRoot $plainFileName
    if (Test-Path -LiteralPath $plainFile) {
        # Explicit user-selected local plaintext fallback.  Never print the
        # value or pass it as a process argument.
        $plainSecret = (Get-Content -LiteralPath $plainFile -Raw -Encoding UTF8).Trim().Trim(
            [char]0x22, [char]0x201c, [char]0x201d
        )
    }
    else {
        $secureSecret = Get-PlannerApiKey -Provider $Provider
        if ($null -eq $secureSecret) {
            throw "No api.txt or Windows-user encrypted API key is available for '$Provider'."
        }
        $secretPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureSecret)
        $plainSecret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPtr)
    }
    if ([string]::IsNullOrWhiteSpace($plainSecret)) {
        throw "The saved API key decrypted to an empty value."
    }
    if ($Provider -eq "vectorengine") {
        # The planner's compatible transport reads this generic bearer-key
        # slot; provenance still records the real provider as vectorengine.
        $env:GROQ_API_KEY = $plainSecret
        $env:PLANNER_PROVIDER = "vectorengine"
        $env:GROQ_PLANNER_MODEL = "qwen-plus"
        # The user explicitly selected the stable qwen-plus tier and does not
        # want an automatic promotion to the much more expensive 3.8-max.
        $env:GROQ_PLANNER_FALLBACK_MODELS = ""
        $env:GROQ_MODELS_ENDPOINT = "https://api.vectorengine.ai/v1/models"
        $env:GROQ_CHAT_COMPLETIONS_ENDPOINT = "https://api.vectorengine.ai/v1/chat/completions"
        $env:PLANNER_MACRO_DIRECTION_BATCH_SIZE = "5"
        $env:PLANNER_EVENT_BATCH_SIZE = "1"
        $env:PLANNER_EVENT_MAX_OUTPUT_TOKENS = "4800"
        $env:OPENAI_COMPATIBLE_STREAM = "1"
        Remove-Item Env:DASHSCOPE_API_KEY -ErrorAction SilentlyContinue
        # VectorEngine is called through Python/OpenSSL, whose direct route is
        # stable even when Windows curl/Schannel is not.  Large detailed-event
        # requests were being dropped by the desktop proxy, so bypass it.
        Remove-Item Env:OPENAI_COMPATIBLE_CURL_PROXY -ErrorAction SilentlyContinue
    }
    elseif ($Provider -eq "groq") {
        $env:GROQ_API_KEY = $plainSecret
        $env:PLANNER_PROVIDER = "groq"
        # Qwen 3.6 has been the most reliable Groq model for long Chinese JSON
        # event objects.  The 20B OSS fallback repeatedly returned truncated
        # minified JSON, so keep only the stronger 120B emergency fallback.
        $env:GROQ_PLANNER_MODEL = "qwen/qwen3.6-27b"
        $env:GROQ_PLANNER_FALLBACK_MODELS = "openai/gpt-oss-120b,llama-3.3-70b-versatile,llama-3.1-8b-instant"
        # Two events fit the 8B model's 6K TPM fallback while the larger-model
        # daily windows recover.  This is still 40% fewer direction calls than
        # the earlier one-event mode.
        $env:PLANNER_MACRO_DIRECTION_BATCH_SIZE = "2"
        # Detailed-event payloads are large. One two-chapter event per call
        # avoids wasting the free quota on truncated two-event responses and
        # lets checkpoint resume preserve every accepted event immediately.
        $env:PLANNER_EVENT_BATCH_SIZE = "1"
        # A complete single-event object is usually slightly above 3k output
        # tokens.  The former cap repeatedly cut JSON inside the event body.
        $env:PLANNER_EVENT_MAX_OUTPUT_TOKENS = "4000"
        Remove-Item Env:DASHSCOPE_API_KEY -ErrorAction SilentlyContinue
        $proxyListening = Test-NetConnection -ComputerName "127.0.0.1" -Port 7897 `
            -InformationLevel Quiet -WarningAction SilentlyContinue
        if ($proxyListening) {
            $env:OPENAI_COMPATIBLE_CURL_PROXY = "http://127.0.0.1:7897"
        }
        else {
            Remove-Item Env:OPENAI_COMPATIBLE_CURL_PROXY -ErrorAction SilentlyContinue
        }
    }
    else {
        $env:DASHSCOPE_API_KEY = $plainSecret
        $env:PLANNER_PROVIDER = "qwen"
        Remove-Item Env:GROQ_API_KEY -ErrorAction SilentlyContinue
    }
    $env:PYTHONIOENCODING = "utf-8"
    $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
    $planner = Join-Path $projectRoot "bert_excitation_train\scripts\v2\generate_pop_king_500_qwen.py"
    $arguments = @(
        $planner, "--output-dir", $OutputDir,
        "--stop-after-macro", [string]$StopAfterMacro,
        "--stop-after-block", [string]$StopAfterBlock,
        "--retry-cycles", [string]$RetryCycles
    )
    Push-Location $projectRoot
    try {
        & python @arguments
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
}
finally {
    $plainSecret = $null
    $secureSecret = $null
    Remove-Item Env:GROQ_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:DASHSCOPE_API_KEY -ErrorAction SilentlyContinue
    Remove-Item Env:PLANNER_PROVIDER -ErrorAction SilentlyContinue
    Remove-Item Env:GROQ_PLANNER_MODEL -ErrorAction SilentlyContinue
    Remove-Item Env:GROQ_PLANNER_FALLBACK_MODELS -ErrorAction SilentlyContinue
    Remove-Item Env:GROQ_MODELS_ENDPOINT -ErrorAction SilentlyContinue
    Remove-Item Env:GROQ_CHAT_COMPLETIONS_ENDPOINT -ErrorAction SilentlyContinue
    Remove-Item Env:PLANNER_MACRO_DIRECTION_BATCH_SIZE -ErrorAction SilentlyContinue
    Remove-Item Env:PLANNER_EVENT_BATCH_SIZE -ErrorAction SilentlyContinue
    Remove-Item Env:PLANNER_EVENT_MAX_OUTPUT_TOKENS -ErrorAction SilentlyContinue
    Remove-Item Env:OPENAI_COMPATIBLE_CURL_PROXY -ErrorAction SilentlyContinue
    Remove-Item Env:OPENAI_COMPATIBLE_STREAM -ErrorAction SilentlyContinue
    if ($secretPtr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPtr)
    }
}
exit $exitCode
