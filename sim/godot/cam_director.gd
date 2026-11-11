extends RefCounted
## Viewer camera for watching the bot (MoKa M1111-34: Tomb Raider-style hands-off follow + section profiles + ladder side shot,
## written by us — docs/room_camera_pplx_2026-11-11.md Follow-up 2/3). Pure logic, no nodes: step() takes the body and
## returns the wanted camera pose; ramp.gd's presenter checks it against walls and alone writes the viewer Camera3D.
## The bot's play camera (main.gd cam / cam_yaw, which Moves.stick_to steers by) is not touched.
##
## Section = the scene's "cam_path" (planned route, ~1 m points [x, y, z, leg, tag], sim/burg_scene.py). The point nearest the
## body (within PATH_NEAR m and PATH_DY m of height — stacked floors are close in space, far along the route) gives the
## section tag and the route direction LOOK_AHEAD m on.
##
## /**
##  * ── 알려진 한계 ──────────────────────────────
##  *  · cam_path는 장면을 만들 때 NavMesh find_path로 그린 "계획 경로"다. 봇이 실제로 걷는 길(walk_path 중 재계획)과
##  *    다를 수 있다 — 경로에서 멀어지면 이동 방향으로 따라간다.
##  *  · 프로필 숫자(거리·각도·회전 속도)는 전부 [guess]. MoKa가 창으로 보고 고칠 값이다.
##  */

const PATH_NEAR := 4.0        # [guess] m: farther than this from the route → follow the body's travel direction
const PATH_DY := 2.5          # [guess] m of height: a route point on another floor doesn't count
const LOOK_AHEAD := 5.0       # [guess] m along the route the camera faces
const ENTER_S := 0.25         # [guess] a new section must hold this long (Perplexity: 0.15–0.25)
const HOLD_S := 1.5           # [guess] a section stays at least this long once taken
const LADDER_KEEP_S := 0.8    # [guess] ladder shot stays after the climb ends
const BLEND_S := 0.7          # [guess] blend into / out of the ladder shot (Perplexity: 0.5–0.8 / 0.7–1.0)
const PARAM_RATE := 1.8       # [guess] 1/s distance / pitch / height approach a new section's values
const MOVE_MIN := 0.4         # [guess] m/s: slower than this the travel direction is not trusted
const HEAD_RATE := 3.0        # [guess] 1/s smoothing of the travel direction

const PROFILES := {           # [guess] all; dist m, pitch rad (negative = looking down), yaw_rate rad/s max, side rad off the route
	"default": {"dist": 4.0, "pitch": -0.25, "yaw_rate": 1.2, "yaw_k": 2.0, "side": 0.0, "org_y": 1.42},
	"corridor": {"dist": 3.2, "pitch": -0.18, "yaw_rate": 1.6, "yaw_k": 2.5, "side": 0.0, "org_y": 1.42},
	"stairs": {"dist": 4.6, "pitch": -0.40, "yaw_rate": 1.0, "yaw_k": 1.6, "side": 0.0, "org_y": 1.2},
	"bridge": {"dist": 5.5, "pitch": -0.35, "yaw_rate": 0.8, "yaw_k": 1.2, "side": 0.35, "org_y": 1.42},
	"elevator": {"dist": 3.0, "pitch": -0.95, "yaw_rate": 0.4, "yaw_k": 1.0, "side": 0.0, "org_y": 1.0},   # above, looking down the shaft (M1111-35)
}

var path: Array = []          # [[x, y, z, leg, tag], …]
var cum: PackedFloat32Array   # metres along the route at each point
var ladders: Array = []       # [{"at": Vector3, "f": Vector3, "bot", "top"}]
var idx := -1                 # route point nearest the body, -1 = off the route
var yaw := 0.0                # viewer camera yaw (same convention as main.gd cam_yaw)
var travel := 0.0             # smoothed travel direction of the body
var travel_ok := false
var prof := "default"         # section in use
var cand := ""                # section waiting for ENTER_S
var cand_t := 0.0
var prof_t := 0.0             # s since prof was taken
var cur := {}                 # current (smoothed) dist / pitch / org_y / side
var mode := "follow"          # follow | ladder
var ladder_i := -1
var ladder_off_t := 0.0
var blend_t := -1.0           # ≥ 0 while blending between follow and the ladder shot
var blend_from := {}          # {"pos", "look"} shown when the blend began
var shown := {}               # last pose returned {"pos", "look"}
var last_p := Vector3.ZERO
var started := false
var switches := 0             # section changes (logged; the test bounds it)


func setup(cam_path: Array, ladder_rows: Array, start_yaw: float) -> void:
	path = cam_path
	cum = PackedFloat32Array()
	cum.resize(path.size())
	for i in range(1, path.size()):
		cum[i] = cum[i - 1] + _pt(i - 1).distance_to(_pt(i))
	ladders = ladder_rows
	yaw = start_yaw
	travel = start_yaw
	cur = PROFILES["default"].duplicate()


func _pt(i: int) -> Vector3:
	return Vector3(float(path[i][0]), float(path[i][1]), float(path[i][2]))


func _nearest(p: Vector3) -> int:
	# around the last index first (the route goes on); the whole route when lost or after a jump
	var best := -1
	var bd := PATH_NEAR
	var lo := 0
	var hi := path.size()
	if idx >= 0:
		lo = maxi(0, idx - 40)
		hi = mini(path.size(), idx + 80)
	for pass_i in 2:
		for i in range(lo, hi):
			var q := _pt(i)
			if absf(q.y - p.y) > PATH_DY:
				continue
			var d := Vector2(q.x - p.x, q.z - p.z).length()
			if d < bd:
				bd = d
				best = i
		if best >= 0 or idx < 0:
			break
		lo = 0
		hi = path.size()
	return best


func _route_yaw(i: int) -> float:
	var want := cum[i] + LOOK_AHEAD
	var j := i
	while j < path.size() - 1 and cum[j] < want:
		j += 1
	var a := _pt(i)
	var b := _pt(j)
	if Vector2(b.x - a.x, b.z - a.z).length() < 0.5:
		return travel
	return atan2(b.x - a.x, b.z - a.z)


func _ladder_shot(p: Vector3, L: Dictionary, side: float) -> Dictionary:
	# side view of the climber: off the ladder's side and back from the wall, a little above, looking at the chest
	var f: Vector3 = L["f"]
	var right := Vector3(f.z, 0, -f.x)
	var look := p + Vector3(0, 0.9, 0)
	return {"pos": look + right * 3.2 * side - f * 2.2 + Vector3(0, 0.6, 0), "look": look}


func step(dt: float, p: Vector3, ladder_i_now: int) -> Dictionary:
	## → {"pos", "look", "alt": ladder shot from the other side or {}, "org", "mode", "prof", "idx"}
	if not started:
		last_p = p
	var v := (p - last_p) / maxf(dt, 1e-4)
	last_p = p
	if Vector2(v.x, v.z).length() > MOVE_MIN and Vector2(v.x, v.z).length() < 20.0:
		var h := atan2(v.x, v.z)
		travel = h if not travel_ok else travel + wrapf(h - travel, -PI, PI) * (1.0 - exp(-HEAD_RATE * dt))
		travel_ok = true
	idx = _nearest(p) if not path.is_empty() else -1
	# section with hysteresis: a new tag must hold ENTER_S, the current one stays HOLD_S
	var tag := "default"
	if idx >= 0:
		tag = String(path[idx][4])
	if not PROFILES.has(tag):
		tag = "default"
	prof_t += dt
	if tag == prof:
		cand = ""
	elif tag != cand:
		cand = tag
		cand_t = 0.0
	else:
		cand_t += dt
		if cand_t >= ENTER_S and prof_t >= HOLD_S:
			prof = tag
			prof_t = 0.0
			cand = ""
			switches += 1
	var P: Dictionary = PROFILES[prof]
	var kp := 1.0 - exp(-PARAM_RATE * dt) if started else 1.0
	for k in ["dist", "pitch", "org_y", "side"]:
		cur[k] = lerpf(float(cur[k]), float(P[k]), kp)
	# hands-off yaw: toward the route direction ahead (off the route: travel direction), rate-limited
	var target := yaw
	if idx >= 0:
		target = _route_yaw(idx)
	elif travel_ok:
		target = travel
	target += float(cur["side"])
	var dy := wrapf(target - yaw, -PI, PI)
	var turn := clampf(dy * float(P["yaw_k"]), -float(P["yaw_rate"]), float(P["yaw_rate"]))
	yaw = wrapf(yaw + turn * dt, -PI, PI) if started else target
	var fwd := Vector3(sin(yaw), 0, cos(yaw))
	var org := p + Vector3(0, float(cur["org_y"]), 0)
	var dist := float(cur["dist"])
	var pitch := float(cur["pitch"])
	var follow := {"pos": org - fwd * dist * cos(pitch) + Vector3(0, -sin(pitch) * dist, 0), "look": org}
	# ladder shot (override): in while climbing, out LADDER_KEEP_S after; follow keeps updating underneath
	var want_mode := mode
	if ladder_i_now >= 0:
		want_mode = "ladder"
		ladder_i = ladder_i_now
		ladder_off_t = 0.0
	elif mode == "ladder":
		ladder_off_t += dt
		if ladder_off_t >= LADDER_KEEP_S:
			want_mode = "follow"
	if want_mode != mode:
		mode = want_mode
		blend_t = 0.0
		blend_from = shown.duplicate() if not shown.is_empty() else follow
		switches += 1
		if mode == "follow":       # hand back to the route direction, not the yaw from before the ladder
			yaw = target
			fwd = Vector3(sin(yaw), 0, cos(yaw))
			follow = {"pos": org - fwd * dist * cos(pitch) + Vector3(0, -sin(pitch) * dist, 0), "look": org}
	var out := follow
	var alt := {}
	if mode == "ladder" and ladder_i >= 0 and ladder_i < ladders.size():
		out = _ladder_shot(p, ladders[ladder_i], 1.0)
		alt = _ladder_shot(p, ladders[ladder_i], -1.0)
	if blend_t >= 0.0:
		blend_t += dt
		var k := smoothstep(0.0, 1.0, minf(1.0, blend_t / BLEND_S))
		out = {"pos": (blend_from["pos"] as Vector3).lerp(out["pos"], k), "look": (blend_from["look"] as Vector3).lerp(out["look"], k)}
		if blend_t >= BLEND_S:
			blend_t = -1.0
	started = true
	shown = out
	return {"pos": out["pos"], "look": out["look"], "alt": alt, "org": org, "mode": mode, "prof": prof, "idx": idx,
		"blending": blend_t >= 0.0}


func reset(p: Vector3) -> void:
	## after a teleport / seek: rebuild from where the body is now, no blend from the old pose
	started = false
	idx = -1
	shown = {}
	blend_t = -1.0
	last_p = p
