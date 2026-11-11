# tae-verify step 2 (2026-10-16 [win]): read chosen animations of one anibnd with DSAnimStudio 4.9.9's own TAE parser + DS1 template, no GUI.
# pwsh -File experiments/dsas_tae.ps1 -Anibnd "<game>/chr/c2540.anibnd.dcx" -Ids 3000,3003,3010   (needs D:/tools/dsas = DSAS_4.9.9_HOTFIX_b.zip)
param([string]$Anibnd, [string]$Ids)
$ErrorActionPreference = 'Stop'
Add-Type -Path 'D:\tools\dsas\SoulsFormats.dll'
$sap = [Reflection.Assembly]::LoadFrom('D:\tools\dsas\SoulsAssetPipeline.dll')
$TAE = $sap.GetType('SoulsAssetPipeline.Animation.TAE')
$read = $TAE.BaseType.GetMethod('Read', [type[]]@([byte[]]))
$tpl = $sap.GetType('SoulsAssetPipeline.Animation.TAE+Template')::ReadXMLFile('D:\tools\dsas\Res\TAE.Template.DS1.xml')
$bnd = [SoulsFormats.BND3]::Read($Anibnd)
$want = $Ids -split ',' | ForEach-Object { [long]$_ }
$out = [ordered]@{ tool = 'DSAnimStudio 4.9.9 SoulsAssetPipeline.Animation.TAE + TAE.Template.DS1.xml'; files = @(); anims = @() }
foreach ($f in $bnd.Files) {
  if (-not $f.Name.ToLower().EndsWith('.tae')) { continue }
  $tae = $read.Invoke($null, @(,[byte[]]$f.Bytes))
  $tae.ApplyTemplate($tpl)
  $out.files += [ordered]@{ name = $f.Name; id = $tae.ID; format = "$($tae.Format)"; animations = $tae.Animations.Count }
  foreach ($a in $tae.Animations) {
    if ($want -notcontains $a.ID) { continue }
    $evs = @()
    foreach ($e in $a.Events) {
      $named = [ordered]@{}
      try { foreach ($k in $e.Parameters.Values.Keys) { $named[$k] = "$($e.Parameters.Values[$k])" } } catch {}
      $evs += [ordered]@{ type = $e.Type; name = $e.TypeName; start = $e.StartTime; end = $e.EndTime;
                          param_hex = [BitConverter]::ToString($e.GetParameterBytes($false)); params = $named }
    }
    $out.anims += [ordered]@{ anim = $a.ID; events = $evs }
  }
}
$out | ConvertTo-Json -Depth 8
