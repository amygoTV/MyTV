# 广告源批量 OCR 检测（利用 Windows 内置 WinRT OCR 识别热线号码）
#
# 原理：购物广告/热线滚动条画面上会出现「订购电话 400-xxx-xxxx」「抢购热线」
#       等字样。直接 OCR 每帧的顶部/底部条带，搜「400」「订购」「热线」「抢购」
#       「咨询电话」等关键词，命中即判污染。
#
# 用法（PowerShell）：pwsh -File scripts/ad_ocr.ps1 -Dir <抽帧目录> -Out <json>
param(
  [Parameter(Mandatory=$true)][string]$Dir,
  [string]$Out = ""
)

Add-Type -AssemblyName System.Runtime.WindowsRuntime | Out-Null
$null = [Windows.Media.Ocr.OcrEngine,Windows.Media.Ocr,ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language,Windows.Globalization,ContentType=WindowsRuntime]

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
  $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
  $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]

function Await($op, $type) {
  $t = $asTaskGeneric.MakeGenericMethod($type).Invoke($null, @($op))
  $t.Wait(60000) | Out-Null
  $t.Result
}

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage(
  [Windows.Globalization.Language]::new('zh-Hans-CN'))
if (-not $engine) { Write-Error "OCR engine unavailable"; exit 1 }

$kw = @('400','订购','抢购','热线','咨询','购物','优惠','订购热线','订购电话','咨询电话','客服','免费领取','扫码','二维码','广告招商','热线电话')
$files = Get-ChildItem -Path $Dir -Filter *.jpg -Recurse | Sort-Object FullName
$results = @()
foreach ($f in $files) {
  $text = ''
  try {
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($f.FullName)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $res = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
    $text = $res.Text
  } catch { }
  $hits = @()
  foreach ($k in $kw) { if ($text -like "*$k*") { $hits += $k } }
  $phone = $false
  if ($text -match '4\s*0\s*0\s*[-—－]?\s*\d{3}\s*[-—－]?\s*\d{4}') { $phone = $true }
  $results += [pscustomobject]@{
    file = $f.FullName; text = $text; hits = ($hits -join ','); phone = $phone
  }
}
if ($Out -ne "") {
  $results | ConvertTo-Json -Depth 3 | Set-Content -Path $Out -Encoding UTF8
}
$results | ForEach-Object {
  $flag = if ($_.phone) { 'PHONE' } elseif ($_.hits) { 'KW' } else { '' }
  "{0,-6} {1,-40} {2}" -f $flag, $_.hits, ($_.text -replace '\s+',' ').Substring(0, [Math]::Min(120, ($_.text -replace '\s+',' ').Length))
}
