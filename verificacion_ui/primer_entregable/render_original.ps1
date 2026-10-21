$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
$pageWordTask=[System.Runtime.InteropServices.Marshal]::GetActiveObject('Word.Application')
$pageDocTask=$pageWordTask.Documents.Item('Primer Entregable IA 1.0.docx')
$pageDocTask.Repaginate()
$pageWindowTask=$pageDocTask.Windows.Item(1)
$pageWindowTask.View.Type=3
$pageCountTask=$pageDocTask.ComputeStatistics(2)
Write-Output "PAGINAS=$pageCountTask"
$pagesOutTask=Join-Path $PSScriptRoot 'referencia_paginas'
$null=New-Item -ItemType Directory -Path $pagesOutTask -Force
$pageTextsTask=@()
for($pageIndexTask=1;$pageIndexTask -le $pageCountTask;$pageIndexTask++) {
    $pageObjectTask=$pageWindowTask.Panes.Item(1).Pages.Item($pageIndexTask)
    [byte[]]$pageBytesTask=$pageObjectTask.EnhMetaFileBits
    $pageStreamTask=New-Object System.IO.MemoryStream(,$pageBytesTask)
    $pageMetaTask=New-Object System.Drawing.Imaging.Metafile($pageStreamTask)
    $pageBitmapTask=New-Object System.Drawing.Bitmap(1240,1754)
    $pageGraphicsTask=[System.Drawing.Graphics]::FromImage($pageBitmapTask)
    $pageGraphicsTask.Clear([System.Drawing.Color]::White)
    $pageGraphicsTask.SmoothingMode=[System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $pageGraphicsTask.InterpolationMode=[System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $pageGraphicsTask.DrawImage($pageMetaTask,0,0,1240,1754)
    $pageNameTask='pagina-{0:D2}.png' -f $pageIndexTask
    $pageBitmapTask.Save((Join-Path $pagesOutTask $pageNameTask),[System.Drawing.Imaging.ImageFormat]::Png)
    $pageGraphicsTask.Dispose(); $pageBitmapTask.Dispose(); $pageMetaTask.Dispose(); $pageStreamTask.Dispose()
    $rangeStartTask=$pageDocTask.GoTo(1,1,$pageIndexTask).Start
    $rangeEndTask=if($pageIndexTask -lt $pageCountTask){$pageDocTask.GoTo(1,1,($pageIndexTask+1)).Start}else{$pageDocTask.Content.End}
    $pageTextsTask+=@{pagina=$pageIndexTask;texto=$pageDocTask.Range($rangeStartTask,$rangeEndTask).Text}
    Write-Output "RENDER=$pageIndexTask"
}
$pageTextsTask | ConvertTo-Json -Depth 3 | Set-Content -Encoding UTF8 (Join-Path $PSScriptRoot 'texto_paginas.json')
Write-Output 'RENDER_COMPLETO'

