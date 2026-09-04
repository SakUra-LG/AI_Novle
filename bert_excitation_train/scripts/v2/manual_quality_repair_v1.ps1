$chapterRoot = Join-Path (Get-Location) 'bert_excitation_train\outputs_pop_king_v6_compiled_story_first_500\chapters'
$replacements = @{
  'chapter_008.txt' = @{
    '这个变化虽然微小，却标志着整个行业规则的一次重要修正。' = '这个变化虽然微小，却让制作方第一次把童星的现场安全和表演自主权写进了实际流程。'
  }
  'chapter_010.txt' = @{
    '巴里·布鲁姆的名字被写进了停职名单，那份名单将被送到联邦文化事务署备案。' = '巴里·布鲁姆的名字被写进了停职名单，那份名单将由制作方和河湾镇文化委员会共同备案。'
  }
  'chapter_018.txt' = @{
    '上周三，也就是七月十二日，你们强行切掉了这首歌；而今天，七月十三日，它已经登上了本地排行榜的第三位，并且还在上升。' = '昨晚，也就是七月十二日，你们强行切掉了这首歌；一夜之后，它已经登上了本地排行榜的第三位，并且还在上升。'
  }
  'chapter_021.txt' = @{
    '此刻却 united 起来' = '此刻却站到了一起'
  }
  'chapter_022.txt' = @{
    '此刻却 united 起来' = '此刻却站到了一起'
    '像是在看一场早已 rehearsed 的闹剧' = '像是在看一场早已排练过的闹剧'
  }
  'chapter_032.txt' = @{
    '有人拿出手机拍摄他失态的样子。' = '有人拿出随身相机拍摄他失态的样子。'
  }
  'chapter_040.txt' = @{
    '三千张试听卡全部售罄' = '五千张试听卡全部售罄'
    '销售流水单被打印出来' = '销售流水单被油墨打印出来'
    '这一战，他彻底赢了。不仅赢得了市场，更赢得了尊严和自由。他深吸一口气，将那份邀请函收进衣兜，转身走进了奥瑞恩集团的大楼。' = '这一战，他赢得了市场，也赢得了暂时拒绝资本的自由。他深吸一口气，将那份邀请函收进衣兜，转身离开奥瑞恩集团的台阶，没有走进那栋大楼。'
  }
  'chapter_026.txt' = @{
    '联邦税务局（IRS）' = '河湾镇税务稽核处'
    ' IRS' = ''
  }
}
foreach ($name in $replacements.Keys) {
  $path = Join-Path $chapterRoot $name
  $text = Get-Content -LiteralPath $path -Raw -Encoding UTF8
  foreach ($old in $replacements[$name].Keys) {
    $text = $text.Replace($old, $replacements[$name][$old])
  }
  Set-Content -LiteralPath $path -Value $text -Encoding UTF8
}

$changed = @(1, 2, 5, 6, 8, 10, 18, 21, 22, 26, 32, 40)
$memoryRoot = Join-Path (Get-Location) 'bert_excitation_train\outputs_pop_king_v6_compiled_story_first_500\knowledge_graph\stories\planning-be26ba6bb2c83203\chapter_memory'
$records = @()
foreach ($chapterId in $changed) {
  $chapterPath = Join-Path $chapterRoot ('chapter_{0:D3}.txt' -f $chapterId)
  $bytes = [System.IO.File]::ReadAllBytes($chapterPath)
  $hash = [System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash($bytes)).Replace('-', '').ToLowerInvariant()
  $memoryPath = Join-Path $memoryRoot ('chapter_{0:D3}_memory.json' -f $chapterId)
  if (Test-Path -LiteralPath $memoryPath) {
    $memory = Get-Content -LiteralPath $memoryPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $memory.content_hash = $hash
    $memory | Add-Member -NotePropertyName manual_quality_review -NotePropertyValue '2026-08-21: chapter manually corrected after human quality review; semantic memory retained for continuity.' -Force
    $memory | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $memoryPath -Encoding UTF8
  }
  $records += [ordered]@{ chapter_id = $chapterId; content_sha256 = $hash }
}
$reviewPath = Join-Path (Get-Location) 'bert_excitation_train\outputs_pop_king_v6_compiled_story_first_500\manual_quality_review_20260821.json'
[ordered]@{
  review_date = '2026-08-21'
  scope = 'accepted正文第1—40章'
  action = '人工修订；未发现需要重新调用模型的核心情节级失败'
  backup_directory = 'chapters_pre_quality_review_20260821'
  corrected_chapters = $changed
  corrections = @(
    '第1章删除提前重生，补足死亡与临终记忆碎片；第2章补入短暂创伤反应与母亲先核查再倾听。',
    '修复英文混入、年代技术词、现实机构称谓和第18章日期叙述。',
    '修复第39—40章销售数量不一致，以及第40章拒绝邀请后仍走入奥瑞恩大楼的情节矛盾。'
  )
  chapter_hashes = $records
} | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $reviewPath -Encoding UTF8
