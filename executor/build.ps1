$ErrorActionPreference = 'Stop'
$installRoot = $env:SW_INSTALL_DIR
if (-not $installRoot) { $installRoot = 'C:\Program Files\SOLIDWORKS Corp\SOLIDWORKS' }
$apiRoot = Join-Path $installRoot 'api\redist'
if (-not (Test-Path -LiteralPath $apiRoot)) { throw 'Set SW_INSTALL_DIR to your installed SOLIDWORKS directory.' }
$binPath = Join-Path $PSScriptRoot 'bin'
New-Item -ItemType Directory -Path $binPath -Force | Out-Null
foreach ($name in @('SolidWorks.Interop.sldworks.dll','SolidWorks.Interop.swconst.dll','SolidWorks.Interop.swmotionstudy.dll')) {
    Copy-Item -LiteralPath (Join-Path $apiRoot $name) -Destination $binPath
}
$sources = @(Get-ChildItem -LiteralPath $PSScriptRoot -Filter '*.cs' | ForEach-Object { $_.FullName })
& "$env:WINDIR\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /platform:x64 /reference:System.Web.Extensions.dll /reference:System.Windows.Forms.dll /reference:Microsoft.CSharp.dll /out:"$binPath\SwExecutor.exe" /reference:"$apiRoot\SolidWorks.Interop.sldworks.dll" /reference:"$apiRoot\SolidWorks.Interop.swconst.dll" /reference:"$apiRoot\SolidWorks.Interop.swmotionstudy.dll" @sources
if ($LASTEXITCODE -ne 0) { throw 'Executor compilation failed' }
