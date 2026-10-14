# 跑全部**离线**判据（不联网、不花钱），只打印每套的最后一行与退出码。
# 用法：  pwsh -File D:\画台\tests\run_offline_all.ps1
# 目的：改完代码后一条命令看清"有没有把别的地方弄坏"。
$ErrorActionPreference = 'Continue'
$py = 'C:\ProgramData\miniconda3\envs\bestpic\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$suites = @(
  'tests\smoke_kernel.py',
  'tests\test_server_api.py',
  'tests\test_stdio.py',
  'tests\test_account.py',
  'tests\test_brain_offline.py',
  'tests\test_intent_offline.py',
  'tests\test_render_offline.py',
  'tests\test_knobs_effect.py',
  'tests\test_version_compare.py',
  'tests\test_region_offline.py'
)

Set-Location 'D:\画台'
$fail = 0
foreach ($s in $suites) {
  $out = & $py $s 2>&1
  $code = $LASTEXITCODE
  $last = ($out | Where-Object { $_ -match '\[PASS\]|\[FAIL\]|失败|Traceback' } | Select-Object -Last 1)
  if (-not $last) { $last = ($out | Select-Object -Last 1) }
  $tag = if ($code -eq 0) { 'OK  ' } else { 'BAD ' }
  if ($code -ne 0) { $fail++ }
  "{0} {1,-32} exit={2}  {3}" -f $tag, $s, $code, $last
}
""
if ($fail -eq 0) { "全部离线套通过（{0} 套）" -f $suites.Count } else { "有 {0} 套没过" -f $fail }
