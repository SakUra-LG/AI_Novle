# 设置PowerShell编码为UTF-8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

# 设置环境变量
$env:PYTHONIOENCODING = "utf-8"

# 运行评分脚本
Write-Host "正在启动样本评分系统..." -ForegroundColor Green
python scripts\incremental_sample_scorer.py

# 等待用户按键
Write-Host "`n按任意键退出..." -ForegroundColor Yellow
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

