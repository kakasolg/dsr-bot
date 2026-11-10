# Havok skeleton + animations of one DSR character → JSON (MoKa M1109-57: real Hollow motion in the replay room).
#
#   pwsh sim/hkx_dump.ps1 -Dir <folder with Skeleton.hkx and aXX_YYYY.hkx> -OutFile <file.json> [-Anims a00_3000,a00_3003]
#
# Decoding is DSAnimStudio's own (D:\tools\dsas\SoulsAssetPipeline.dll, ver 4.9.9): DSR .hkx are Havok 2015 tagfiles,
# read with HKX.GenFakeFromTagFile, spline-compressed tracks sampled with HavokAnimationData_SplineCompressed.
# Output per animation: frame count, frame duration, per frame and per skeleton bone the LOCAL transform
# [tx, ty, tz, qx, qy, qz, qw, sx, sy, sz] in Havok/FromSoft space (y up, left-handed), and the root motion samples
# (Havok reference frame: x, y, z, yaw) — the replay keeps the recorded position, so root motion is only reported.
param([Parameter(Mandatory)][string]$Dir, [Parameter(Mandatory)][string]$OutFile, [string[]]$Anims = @(),
      [string]$Dsas = "D:\tools\dsas")
$ErrorActionPreference = "Stop"
$asm = [Reflection.Assembly]::LoadFrom("$Dsas\SoulsAssetPipeline.dll")
[void][Reflection.Assembly]::LoadFrom("$Dsas\SoulsFormats.dll")
$HKX = $asm.GetType('SoulsAssetPipeline.Animation.HKX')
$SPL = $asm.GetType('SoulsAssetPipeline.Animation.HavokAnimationData_SplineCompressed')

function Objs($path) { $HKX::GenFakeFromTagFile([IO.File]::ReadAllBytes($path), $null).DataSection.Objects }
function R4($v) { [math]::Round([double]$v, 5) }

$skel = Objs "$Dir\Skeleton.hkx" | Where-Object { $_.GetType().Name -eq 'HKASkeleton' } | Select-Object -First 1
$n = [int]$skel.Bones.Size
$bones = for ($i = 0; $i -lt $n; $i++) {
    $t = $skel.Transforms.get_Item($i)
    [ordered]@{ name = $skel.Bones.get_Item($i).Name.GetString(); parent = [int]$skel.ParentIndices.get_Item($i).data
        ref = @((R4 $t.Position.Vector.X), (R4 $t.Position.Vector.Y), (R4 $t.Position.Vector.Z),
                (R4 $t.Rotation.Vector.X), (R4 $t.Rotation.Vector.Y), (R4 $t.Rotation.Vector.Z), (R4 $t.Rotation.Vector.W),
                (R4 $t.Scale.Vector.X), (R4 $t.Scale.Vector.Y), (R4 $t.Scale.Vector.Z)) }
}
if ($Anims.Count -eq 0) { $Anims = Get-ChildItem "$Dir\a*.hkx" | ForEach-Object { $_.BaseName } }
$res = [ordered]@{ tool = "DSAnimStudio 4.9.9 SoulsAssetPipeline (GenFakeFromTagFile + HavokAnimationData_SplineCompressed)"
                   bones = @($bones); anims = [ordered]@{} }
foreach ($a in $Anims) {
    try {
        $o = Objs "$Dir\$a.hkx"
        $ref = $o | Where-Object { $_.GetType().Name -eq 'HKADefaultAnimatedReferenceFrame' } | Select-Object -First 1
        $sca = $o | Where-Object { $_.GetType().Name -eq 'HKASplineCompressedAnimation' } | Select-Object -First 1
        $bnd = $o | Where-Object { $_.GetType().Name -eq 'HKAAnimationBinding' } | Select-Object -First 1
        if (-not $sca) { $res.anims[$a] = [ordered]@{ error = "not spline-compressed: " + (($o | ForEach-Object { $_.GetType().Name }) -join ',') }; continue }
        $ctor = $SPL.GetConstructors() | Where-Object { $_.GetParameters().Count -eq 5 }
        $data = $ctor.Invoke([object[]]@([string]$a, $skel.psobject.BaseObject, $(if ($ref) { $ref.psobject.BaseObject } else { $null }), $(if ($bnd) { $bnd.psobject.BaseObject } else { $null }), $sca.psobject.BaseObject))
        $frames = for ($f = 0; $f -lt $data.FrameCount; $f++) {
            ,@(for ($b = 0; $b -lt $n; $b++) {
                $x = $data.GetTransformOnFrameByBone($b, [single]$f, $false)
                ,@((R4 $x.Translation.X), (R4 $x.Translation.Y), (R4 $x.Translation.Z),
                   (R4 $x.Rotation.X), (R4 $x.Rotation.Y), (R4 $x.Rotation.Z), (R4 $x.Rotation.W),
                   (R4 $x.Scale.X), (R4 $x.Scale.Y), (R4 $x.Scale.Z))
            })
        }
        $rm = if ($data.RootMotion) { @($data.RootMotion.Frames | ForEach-Object { ,@((R4 $_.X), (R4 $_.Y), (R4 $_.Z), (R4 $_.W)) }) } else { @() }
        $res.anims[$a] = [ordered]@{ frames = [int]$data.FrameCount; frame_s = (R4 $data.FrameDuration)
                                     duration = (R4 $data.Duration); pose = @($frames); root_motion = $rm }
    } catch { Write-Host "$a ERR $($_.Exception.Message) @ $($_.InvocationInfo.ScriptLineNumber)"; $res.anims[$a] = [ordered]@{ error = $_.Exception.Message } }
}
$res | ConvertTo-Json -Depth 8 -Compress | Set-Content -Encoding utf8 $OutFile
"hkx_dump: $n bones, $($Anims.Count) anims → $OutFile"
