# tae-verify B-22 (2026-10-19, MoKa "DSAS가 실제로 사용하는 히트박스 계산 경로를 확인"): the hitbox capsule DSAnimStudio 4.9.9 draws
# for one attack, recomputed outside its GUI with its own libraries (SoulsFormats.dll, SoulsAssetPipeline.dll) and the matrix
# order of its source at tag ver4.9.9 (github.com/Meowmaritus/DSAnimStudio) — file:line of each step is in the comments.
# DS ANIM STUDIO.dll itself is not called: its Model / DummyPolyManager need the MonoGame graphics device.
#   pwsh -File experiments/dsas_hitbox.ps1 -Chr c2540 -Anim 3000 -Dmy 1,11 -Radius 0.2 -T0 0.8333 -T1 1.0667 -Out data/samples/x.csv
# The AtkParam row (DummyPoly ids, radius) comes from GameParam via combat_extract / soulstruct; this script takes them as input.
param([string]$Chr = 'c2540', [int]$Anim = 3000, [string]$Dmy = '1,11', [double]$Radius = 0.2,
      [double]$T0 = 0.8333, [double]$T1 = 1.0667, [double]$WinStart = 0.8667, [double]$WinEnd = 1.0333, [double]$Step = (1.0 / 60), [string]$Out = '',
      [string]$Game = 'D:\SteamLibrary\steamapps\common\DARK SOULS REMASTERED')
$ErrorActionPreference = 'Stop'
Add-Type -Path 'D:\tools\dsas\SoulsFormats.dll'
$sap = [Reflection.Assembly]::LoadFrom('D:\tools\dsas\SoulsAssetPipeline.dll')
$HKX = $sap.GetType('SoulsAssetPipeline.Animation.HKX')
$Var = $sap.GetType('SoulsAssetPipeline.Animation.HKX+HKXVariation')
$BT = $sap.GetType('SoulsAssetPipeline.Animation.NewBlendableTransform')
$readHkx = $HKX.GetMethod('Read', [type[]]@([byte[]], $Var, [bool], [bool]))
$M = [System.Numerics.Matrix4x4]
$V3 = [System.Numerics.Vector3]

$chrbnd = [SoulsFormats.BND3]::Read("$Game\chr\$Chr.chrbnd.dcx")
$anibnd = [SoulsFormats.BND3]::Read("$Game\chr\$Chr.anibnd.dcx")
$flv = ($chrbnd.Files | Where-Object { $_.Name -like '*.flver' })[0].Bytes
$flver = try { [SoulsFormats.FLVER2]::Read($flv) } catch { [SoulsFormats.FLVER0]::Read($flv) }

# DSR's .hkx are Havok 2015 tagfiles ("TAG0", SDKV20150100): GameRoot.GameTypeIsHavokTagfile is true for DS1R, so DSAS
# reads them with HKX.GenFakeFromTagFile(bytes, compendium = null) (NewAnimationContainer.cs:979-981, 1036-1038)
$fromTag = $HKX.GetMethod('GenFakeFromTagFile', [type[]]@([byte[]], [byte[]]))
function Read-Hkx([byte[]]$b) { $fromTag.Invoke($null, @($b, $null)) }
$skHkx = Read-Hkx ($anibnd.Files | Where-Object { $_.Name -match '\\Skeleton\.hkx$' })[0].Bytes
$anHkx = Read-Hkx ($anibnd.Files | Where-Object { $_.Name -match ("\\a00_{0:D4}\.hkx$" -f $Anim) })[0].Bytes
$skel = $skHkx.DataSection.Objects | Where-Object { $_.GetType().Name -eq 'HKASkeleton' } | Select-Object -First 1
$spline = $anHkx.DataSection.Objects | Where-Object { $_.GetType().Name -eq 'HKASplineCompressedAnimation' } | Select-Object -First 1
$binding = $anHkx.DataSection.Objects | Where-Object { $_.GetType().Name -eq 'HKAAnimationBinding' } | Select-Object -First 1
$refFrame = $anHkx.DataSection.Objects | Where-Object { $_.GetType().Name -eq 'HKADefaultAnimatedReferenceFrame' } | Select-Object -First 1
# NewHavokAnimation_SplineCompressed.cs:31 → SoulsAssetPipeline HavokAnimationData_SplineCompressed(name, skeleton, refFrame, binding, anim)
$ctor = $sap.GetType('SoulsAssetPipeline.Animation.HavokAnimationData_SplineCompressed').GetConstructors() | Where-Object { $_.GetParameters().Count -eq 5 }
$data = $ctor.Invoke([object[]]@("a00_$Anim", $skel.psobject.BaseObject, $refFrame.psobject.BaseObject, $binding.psobject.BaseObject, $spline.psobject.BaseObject))

# HKX skeleton (NewAnimSkeleton_HKX.cs:86-123): name, parent, relative reference transform
$nb = $skel.Bones.Size
$hk = @()
for ($i = 0; $i -lt $nb; $i++) {
  $tr = $skel.Transforms[$i]
  $rel = [Activator]::CreateInstance($BT)
  $rel.Translation = [System.Numerics.Vector3]::new($tr.Position.Vector.X, $tr.Position.Vector.Y, $tr.Position.Vector.Z)
  $rel.Rotation = [System.Numerics.Quaternion]::new($tr.Rotation.Vector.X, $tr.Rotation.Vector.Y, $tr.Rotation.Vector.Z, $tr.Rotation.Vector.W)
  $rel.Scale = [System.Numerics.Vector3]::new($tr.Scale.Vector.X, $tr.Scale.Vector.Y, $tr.Scale.Vector.Z)
  $hk += [pscustomobject]@{ Name = $skel.Bones[$i].Name.GetString(); Parent = [int]$skel.ParentIndices[$i].data; Rel = $rel; Cur = $M::Identity }
}

# FLVER bone reference matrix (NewAnimSkeleton_FLVER.cs:392-423): scale · rotX · rotZ · rotY · translate, walked up to the root
function Flver-Ref([int]$i) {
  $r = $M::Identity
  $b = $flver.Bones[$i]
  while ($null -ne $b) {
    $r = $r * $M::CreateScale($b.Scale.X, $b.Scale.Y, $b.Scale.Z) * $M::CreateRotationX($b.Rotation.X) *
         $M::CreateRotationZ($b.Rotation.Z) * $M::CreateRotationY($b.Rotation.Y) *
         $M::CreateTranslation($b.Translation.X, $b.Translation.Y, $b.Translation.Z)
    $b = if ($b.ParentIndex -ge 0) { $flver.Bones[$b.ParentIndex] } else { $null }
  }
  $r
}
$fref = @(); for ($i = 0; $i -lt $flver.Bones.Count; $i++) { $fref += (Flver-Ref $i) }
# MapToSkeleton (NewAnimSkeleton_FLVER.cs:286): FLVER bone → HKX bone by name
$fmap = @(); for ($i = 0; $i -lt $flver.Bones.Count; $i++) { $n = $flver.Bones[$i].Name; $fmap += [array]::FindIndex([object[]]$hk, [Predicate[object]]{ param($x) $x.Name -eq $n }) }

$want = $Dmy -split ',' | ForEach-Object { [int]$_ }
$dummies = @{}
foreach ($d in $flver.Dummies) { if ($want -contains $d.ReferenceID -and -not $dummies.ContainsKey([int]$d.ReferenceID)) { $dummies[[int]$d.ReferenceID] = $d } }
# DummyPolyInfo local matrix (NewDummyPolyManager.cs:416-447): CreateWorld(0, forward, up) · translate(position)
function Dmy-Local($d) {
  $fw = [System.Numerics.Vector3]::Normalize([System.Numerics.Vector3]::new($d.Forward.X, $d.Forward.Y, $d.Forward.Z))
  $up = if ($d.UseUpwardVector) { [System.Numerics.Vector3]::Normalize([System.Numerics.Vector3]::new($d.Upward.X, $d.Upward.Y, $d.Upward.Z)) } else { [System.Numerics.Vector3]::UnitY }
  $M::CreateWorld([System.Numerics.Vector3]::Zero, $fw, $up) * $M::CreateTranslation($d.Position.X, $d.Position.Y, $d.Position.Z)
}

function Pose([double]$t) {
  $frame = [single]($t / $data.FrameDuration)
  # NewAnimationContainer.cs:853 + WalkTree 908-949: local = sampled transform, current = local · parent (row vectors), scale apart
  $cur = New-Object 'System.Numerics.Matrix4x4[]' $nb; $sc = New-Object 'System.Numerics.Matrix4x4[]' $nb
  for ($i = 0; $i -lt $nb; $i++) {
    $loc = $data.GetTransformOnFrameByBone($i, $frame, $false)
    $m = $loc.GetMatrix(); $s = $loc.GetMatrixScale()
    $p = $hk[$i].Parent
    if ($p -ge 0) { $m = $m * $cur[$p]; $s = $s * $sc[$p] }
    $cur[$i] = $m; $sc[$i] = $s
  }
  $out = New-Object 'System.Numerics.Matrix4x4[]' $nb
  for ($i = 0; $i -lt $nb; $i++) { $out[$i] = $sc[$i] * $cur[$i] }
  $out
}
function Skin($hkCur, [int]$fi) {
  # CopyFromHavokSkeleton (NewAnimSkeleton_FLVER.cs:300-312): inverse(FLVER reference) · HKX current; unmapped → reference
  $j = $fmap[$fi]
  if ($j -ge 0) { $inv = [System.Numerics.Matrix4x4]::Identity; [void]$M::Invert($fref[$fi], [ref]$inv); return $inv * $hkCur[$j] }
  $fref[$fi]
}
function Dmy-Matrix($d, $hkCur) {
  # UpdateFlverBone (NewDummyPolyManager.cs:1051-1077), after the first skeleton update:
  #   reference bone (ParentBoneIndex): follow flag → local · skin[parent], else local only (NullRefBoneMatrix)
  #   attach bone (AttachBoneIndex):    follow flag → skin[attach], else identity
  #   CurrentMatrix = Reference · Attach (NewDummyPolyManager.cs:400)
  $loc = Dmy-Local $d
  $ref = if ($d.ParentBoneIndex -ge 0 -and $d.Flag1) { $loc * (Skin $hkCur $d.ParentBoneIndex) } elseif ($d.ParentBoneIndex -ge 0) { $loc } else { $loc * $M::Identity }
  $att = if ($d.AttachBoneIndex -ge 0 -and $d.Flag1) { Skin $hkCur $d.AttachBoneIndex } else { $M::Identity }
  $ref * $att
}

if ($env:DSAS_BONES) {
  # root-motion double-count check (B-22b): model-space position of the top bones over the whole anim — if they drift with the
  # root motion, the bone poses already carry it and adding root motion again would count it twice
  $names = $env:DSAS_BONES -split ','
  $idx = $names | ForEach-Object { $n = $_; [array]::FindIndex([object[]]$hk, [Predicate[object]]{ param($x) $x.Name -eq $n }) }
  "bones: " + (($hk | Select-Object -First 6 | ForEach-Object { "$($_.Name)(p$($_.Parent))" }) -join ' ')
  foreach ($t in 0, 0.4, 0.8, 0.9, 1.0, 1.2, 1.6, 2.0, 2.4) {
    $c = Pose $t
    "t=$t " + (($idx | ForEach-Object { $p = [System.Numerics.Vector3]::Transform([System.Numerics.Vector3]::Zero, $c[$_]); "$($hk[$_].Name)=($([Math]::Round($p.X,3)), $([Math]::Round($p.Y,3)), $([Math]::Round($p.Z,3)))" }) -join '  ') +
      "  rm=" + $data.RootMotion.GetSampleClamped([single]$t)
  }
  return
}
$rm = $data.RootMotion
$rm0 = if ($rm) { $rm.GetSampleClamped(0) } else { [System.Numerics.Vector4]::Zero }
$info = [ordered]@{
  frame_duration = $data.FrameDuration; frame_count = $data.FrameCount; duration = $data.Duration
  root_motion = if ($rm) { [ordered]@{ forward = "$($rm.Forward)"; up = "$($rm.Up)"; first = "$($rm.FirstFrame)"; last = "$($rm.LastFrame)" } } else { $null }
  dummies = @($want | ForEach-Object { $d = $dummies[$_]; if ($d) { [ordered]@{ id = $_; parent_bone = $d.ParentBoneIndex
      parent_name = if ($d.ParentBoneIndex -ge 0) { $flver.Bones[$d.ParentBoneIndex].Name } else { '' }; attach_bone = $d.AttachBoneIndex
      attach_name = if ($d.AttachBoneIndex -ge 0) { $flver.Bones[$d.AttachBoneIndex].Name } else { '' }; follow = $d.Flag1
      pos = "$($d.Position)"; fwd = "$($d.Forward)"; use_up = $d.UseUpwardVector; up = "$($d.Upward)" } } else { [ordered]@{ id = $_; missing = $true } } })
}
$rows = @()
$n = [int][Math]::Round(($T1 - $T0) / $Step)
for ($k = 0; $k -le $n; $k++) {
  $t = $T0 + $k * $Step
  $hkCur = Pose $t
  $a = [System.Numerics.Vector3]::Transform([System.Numerics.Vector3]::Zero, (Dmy-Matrix $dummies[$want[0]] $hkCur))
  $b = [System.Numerics.Vector3]::Transform([System.Numerics.Vector3]::Zero, (Dmy-Matrix $dummies[$want[1]] $hkCur))
  $r = if ($rm) { $rm.GetSampleClamped([single]$t) - $rm0 } else { [System.Numerics.Vector4]::Zero }
  # world = model · root motion (GetPrimDrawMatrix → MODEL.CurrentTransform.WorldMatrix; NewBlendableTransform.FromRootMotionSample)
  $w = $BT.GetMethod('FromRootMotionSample').Invoke($null, @($r)).GetMatrix()
  $aw = [System.Numerics.Vector3]::Transform($a, $w); $bw = [System.Numerics.Vector3]::Transform($b, $w)
  # dsas_active: DSAS draws the capsule while the TAE event is on, start ≤ t < end (frame 31 = 1.0333 not drawn, B-21)
  $rows += [pscustomobject]@{ t = [Math]::Round($t, 4); frame30 = [Math]::Round($t / $data.FrameDuration, 3); dsas_active = [int]($t -ge $WinStart - 1e-4 -and $t -lt $WinEnd - 1e-4); hit = 0; dmy1 = $want[0]; dmy2 = $want[1]; radius = $Radius
    ax = [Math]::Round($a.X, 4); ay = [Math]::Round($a.Y, 4); az = [Math]::Round($a.Z, 4); bx = [Math]::Round($b.X, 4); by = [Math]::Round($b.Y, 4); bz = [Math]::Round($b.Z, 4)
    rm_x = [Math]::Round($r.X, 4); rm_y = [Math]::Round($r.Y, 4); rm_z = [Math]::Round($r.Z, 4); rm_w = [Math]::Round($r.W, 4)
    awx = [Math]::Round($aw.X, 4); awy = [Math]::Round($aw.Y, 4); awz = [Math]::Round($aw.Z, 4); bwx = [Math]::Round($bw.X, 4); bwy = [Math]::Round($bw.Y, 4); bwz = [Math]::Round($bw.Z, 4) }
}
$info | ConvertTo-Json -Depth 5
if ($Out) { $rows | Export-Csv -NoTypeInformation -Path $Out; "→ $Out ($($rows.Count) rows)" } else { $rows | Format-Table -AutoSize | Out-String -Width 250 }
