param(
    [ValidateSet("groq", "qwen")]
    [string]$Provider = "groq"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
. (Join-Path $PSScriptRoot "planner_api_key_vault.ps1")

$form = New-Object System.Windows.Forms.Form
$form.Text = "500-Chapter Planner - Secure API Key"
$form.StartPosition = "CenterScreen"
$form.TopMost = $true
$form.Width = 620
$form.Height = 275
$form.FormBorderStyle = "FixedDialog"
$form.MaximizeBox = $false
$form.MinimizeBox = $false

$label = New-Object System.Windows.Forms.Label
$label.Left = 24
$label.Top = 20
$label.Width = 550
$label.Height = 44
$savedAvailable = Test-PlannerApiKeySaved -Provider $Provider
$label.Text = if ($savedAvailable) {
    "A Windows-user encrypted $Provider key is available. Click Start securely to reuse it, or paste a replacement key."
}
else {
    "Paste a valid $Provider API key. It can be encrypted for this Windows user and will never enter the project, arguments, or logs."
}
$form.Controls.Add($label)

$textBox = New-Object System.Windows.Forms.TextBox
$textBox.Left = 24
$textBox.Top = 72
$textBox.Width = 550
$textBox.Height = 28
$textBox.UseSystemPasswordChar = $true
$form.Controls.Add($textBox)

$status = New-Object System.Windows.Forms.Label
$status.Left = 24
$rememberBox = New-Object System.Windows.Forms.CheckBox
$rememberBox.Left = 24
$rememberBox.Top = 108
$rememberBox.Width = 550
$rememberBox.Height = 24
$rememberBox.Checked = $true
$rememberBox.Text = "Remember with Windows DPAPI for future planner runs"
$form.Controls.Add($rememberBox)

$status.Top = 136
$status.Width = 550
$status.Height = 24
$status.ForeColor = [System.Drawing.Color]::DarkRed
$form.Controls.Add($status)

$startButton = New-Object System.Windows.Forms.Button
$startButton.Left = 354
$startButton.Top = 174
$startButton.Width = 105
$startButton.Height = 32
$startButton.Text = "Start securely"
$form.Controls.Add($startButton)

$cancelButton = New-Object System.Windows.Forms.Button
$cancelButton.Left = 469
$cancelButton.Top = 174
$cancelButton.Width = 105
$cancelButton.Height = 32
$cancelButton.Text = "Cancel"
$form.Controls.Add($cancelButton)

$cancelButton.Add_Click({ $form.Close() })
$startButton.Add_Click({
    $plainSecret = $null
    $secretPtr = [IntPtr]::Zero
    $typedSecret = $textBox.Text.Trim()
    $secureSecret = $null
    if (-not [string]::IsNullOrWhiteSpace($typedSecret)) {
        $plainSecret = $typedSecret
        $secureSecret = ConvertTo-SecureString -String $typedSecret -AsPlainText -Force
    }
    elseif ($savedAvailable) {
        $secureSecret = Get-PlannerApiKey -Provider $Provider
        if ($null -ne $secureSecret) {
            $secretPtr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureSecret)
            $plainSecret = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPtr)
        }
    }
    $valid = if ($Provider -eq "groq") {
        -not [string]::IsNullOrWhiteSpace($plainSecret) -and $plainSecret -match '^gsk_[A-Za-z0-9_-]{40,}$'
    }
    else {
        -not [string]::IsNullOrWhiteSpace($plainSecret) -and $plainSecret -match '^sk-[A-Za-z0-9._-]{30,}$'
    }
    if (-not $valid) {
        $status.Text = "No usable saved key. Paste the complete key and try again."
        $plainSecret = $null
        $typedSecret = $null
        $secureSecret = $null
        if ($secretPtr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPtr)
        }
        return
    }
    $projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..")).Path
    $outputRelative = "bert_excitation_train\outputs_pop_king_v6_compiled_story_first_500"
    $plannerRelative = "bert_excitation_train\scripts\v2\generate_pop_king_500_qwen.py"
    $runtimeDir = Join-Path $projectRoot "$outputRelative\runtime_logs"
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null
    $stdout = Join-Path $runtimeDir "planner_secure_stdout.log"
    $stderr = Join-Path $runtimeDir "planner_secure_stderr.log"
    try {
        if ($rememberBox.Checked -and $null -ne $secureSecret) {
            Save-PlannerApiKey -Provider $Provider -Secret $secureSecret
        }
        if ($Provider -eq "groq") {
            $env:GROQ_API_KEY = $plainSecret
            $env:PLANNER_PROVIDER = "groq"
            Remove-Item Env:DASHSCOPE_API_KEY -ErrorAction SilentlyContinue
            # The direct route to api.groq.com can be rejected before API-key
            # authentication. Reuse the user's already-running local proxy only
            # for this child process; do not modify Windows/system proxy state.
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
        $arguments = @(
            $plannerRelative, "--output-dir", $outputRelative,
            "--stop-after-macro", "50", "--stop-after-block", "25",
            "--retry-cycles", "1"
        )
        $process = Start-Process -FilePath "python.exe" -ArgumentList $arguments `
            -WorkingDirectory $projectRoot -WindowStyle Hidden `
            -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
        $textBox.Clear()
        [System.Windows.Forms.MessageBox]::Show(
            "Planner started (PID $($process.Id)). Codex will monitor generation and validation.",
            "Started", "OK", "Information"
        ) | Out-Null
        $form.Close()
    }
    catch {
        $status.Text = "Launch failed: $($_.Exception.Message)"
    }
    finally {
        $plainSecret = $null
        $typedSecret = $null
        $secureSecret = $null
        if ($secretPtr -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPtr)
        }
        Remove-Item Env:GROQ_API_KEY -ErrorAction SilentlyContinue
        Remove-Item Env:DASHSCOPE_API_KEY -ErrorAction SilentlyContinue
        Remove-Item Env:PLANNER_PROVIDER -ErrorAction SilentlyContinue
        Remove-Item Env:OPENAI_COMPATIBLE_CURL_PROXY -ErrorAction SilentlyContinue
    }
})

$form.AcceptButton = $startButton
$form.CancelButton = $cancelButton
$form.Add_Shown({ $textBox.Focus() })
[void]$form.ShowDialog()
