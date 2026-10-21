$ErrorActionPreference = 'Stop'
$rootTask = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$docPathTask = Join-Path $rootTask 'Sistema_Inteligente_Inventario_Actualizado.docx'
$pdfPathTask = Join-Path $PSScriptRoot 'revision.pdf'
$wordTask = $null
$documentTask = $null
try {
    Write-Output 'CONECTANDO_WORD'
    $wordTask = [System.Runtime.InteropServices.Marshal]::GetActiveObject('Word.Application')
    Write-Output 'ABRIENDO_DOCUMENTO_GENERADO'
    $previousAlertsTask = $wordTask.DisplayAlerts
    $wordTask.DisplayAlerts = 0
    $documentTask = $wordTask.Documents.Open($docPathTask, $false, $false)
    Write-Output 'ACTUALIZANDO_INDICE'
    $null = $documentTask.Fields.Update()
    $documentTask.Repaginate()
    foreach ($tocTask in $documentTask.TablesOfContents) { $tocTask.Update() }
    $documentTask.Repaginate()
    foreach ($tocTask in $documentTask.TablesOfContents) { $tocTask.UpdatePageNumbers() }
    $documentTask.Save()
    $documentTask.ExportAsFixedFormat($pdfPathTask,17)
    $pageCountTask = $documentTask.ComputeStatistics(2)
    Write-Output "PAGINAS=$pageCountTask"
    Write-Output "TOC=$($documentTask.TablesOfContents.Count)"
} finally {
    if ($null -ne $documentTask) { $documentTask.Close(0); [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($documentTask) }
    if ($null -ne $wordTask) { $wordTask.DisplayAlerts = $previousAlertsTask; [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($wordTask) }
}
