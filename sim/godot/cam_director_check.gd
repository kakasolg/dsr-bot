extends SceneTree
## Headless check of cam_director.gd on made-up routes (no room, no physics): godot --headless --path sim/godot -s
## res://cam_director_check.gd → "ok …" lines, "FAIL …" and exit 1 on the first broken rule. tests/godot_viewcam_test.py runs it.
## Checks the director's own rules only — not how the picture looks.

var fails := 0


func check(msg: String, ok: bool) -> void:
	print(("ok   " if ok else "FAIL ") + msg)
	if not ok:
		fails += 1


func line_path(segs: Array) -> Array:
	# segs: [[length m, dy over it, tag], …] along +z from the origin, 1 m points
	var out := []
	var p := Vector3.ZERO
	for s in segs:
		var n := int(s[0])
		for k in n:
			out.append([p.x, p.y, p.z, out.size(), s[2]])
			p += Vector3(0, float(s[1]) / n, 1.0)
	out.append([p.x, p.y, p.z, out.size(), segs[-1][2]])
	return out


func y_on(path: Array, z: float) -> float:
	var i := clampi(int(z), 0, path.size() - 2)
	return lerpf(float(path[i][1]), float(path[i + 1][1]), z - i)


func _init() -> void:
	var D = load("res://cam_director.gd")
	var dt := 1.0 / 60.0
	var rate_max := 0.0
	for p in D.PROFILES.values():
		rate_max = maxf(rate_max, float(p["yaw_rate"]))

	# 1 · a clean walk: default 40 m → stairs 20 m (up 6 m) → bridge 30 m — sections in order, one switch each
	var path := line_path([[40, 0.0, "default"], [20, 6.0, "stairs"], [30, 0.0, "bridge"]])
	var d = D.new()
	d.setup(path, [], 0.0)
	var seen := []
	var nan := false
	var worst := 0.0
	var last_yaw := 0.0
	var z := 0.0
	var tt := 0.0
	while z < 89.0:
		var w: Dictionary = d.step(dt, Vector3(0, y_on(path, z), z), -1)
		var pos: Vector3 = w["pos"]
		nan = nan or is_nan(pos.x) or is_nan(pos.y) or is_nan(pos.z)
		if seen.is_empty() or seen[-1] != w["prof"]:
			seen.append(w["prof"])
		if tt > 0.1:
			worst = maxf(worst, absf(wrapf(d.yaw - last_yaw, -PI, PI)) / dt)
		last_yaw = d.yaw
		z += 3.4 * dt          # main.gd V_JOG
		tt += dt
	check("clean walk: sections %s" % [seen], seen == ["default", "stairs", "bridge"])
	check("clean walk: no NaN in the pose", not nan)
	check("clean walk: yaw rate %.2f ≤ max profile rate %.2f rad/s" % [worst, rate_max], worst <= rate_max + 1e-3)

	# 2 · sections flipping every metre: switches stay ≥ HOLD_S apart
	var segs := []
	for k in 30:
		segs.append([1, 0.0, "corridor" if k % 2 == 0 else "default"])
	path = line_path(segs)
	d = D.new()
	d.setup(path, [], 0.0)
	var sw_t := []
	var prev := ""
	z = 0.0
	tt = 0.0
	while z < 29.0:
		var w: Dictionary = d.step(dt, Vector3(0, 0, z), -1)
		if prev != "" and w["prof"] != prev:
			sw_t.append(tt)
		prev = w["prof"]
		z += 3.4 * dt
		tt += dt
	var gap := 99.0
	for k in range(1, sw_t.size()):
		gap = minf(gap, sw_t[k] - sw_t[k - 1])
	check("flicker: %d switches in %.1f s, closest %.2f s apart (HOLD_S %.1f)" % [sw_t.size(), tt, gap, D.HOLD_S],
		sw_t.size() <= int(tt / D.HOLD_S) + 1 and (sw_t.size() < 2 or gap >= D.HOLD_S - dt))

	# 3 · stacked floors: a route 4 m below the body is not "here"
	path = line_path([[20, 0.0, "bridge"]])
	d = D.new()
	d.setup(path, [], 0.0)
	var w3: Dictionary = d.step(dt, Vector3(0, 4.0, 10.0), -1)
	check("stacked: body 4 m above the route → off route (idx %d)" % w3["idx"], int(w3["idx"]) == -1)
	w3 = d.step(dt, Vector3(0, 0.5, 10.0), -1)
	check("stacked: body on the route → idx %d near 10" % w3["idx"], absi(int(w3["idx"]) - 10) <= 1)

	# 4 · ladder: shot while climbing, side view, back to follow LADDER_KEEP_S after, facing the route
	path = line_path([[30, 0.0, "default"]])
	var L := {"at": Vector3(0, 0, 10), "f": Vector3(0, 0, 1), "bot": 0.0, "top": 6.0}
	d = D.new()
	d.setup(path, [L], PI / 2)            # starts facing +x, off the route direction
	var modes := []
	var side_ok := true
	tt = 0.0
	var off_at := -1.0
	var back_at := -1.0
	while tt < 6.0:
		var climbing := tt >= 1.0 and tt < 4.0
		var body := Vector3(0, clampf((tt - 1.0) * 2.0, 0.0, 6.0) if tt < 4.0 else 0.0, 10.0)
		var w: Dictionary = d.step(dt, body, 0 if climbing else -1)
		if modes.is_empty() or modes[-1] != w["mode"]:
			modes.append(w["mode"])
		if climbing and tt > 1.0 + D.BLEND_S + 0.05:
			var pos: Vector3 = w["pos"]
			side_ok = side_ok and absf(pos.x) > 2.5       # off to the side of a +z-facing ladder
		if not climbing and tt >= 4.0 and off_at < 0.0:
			off_at = tt
		if off_at >= 0.0 and back_at < 0.0 and w["mode"] == "follow":
			back_at = tt
		tt += dt
	check("ladder: modes %s" % [modes], modes == ["follow", "ladder", "follow"])
	check("ladder: camera beside the ladder during the climb", side_ok)
	check("ladder: back to follow %.2f s after the climb (LADDER_KEEP_S %.1f)" % [back_at - off_at, D.LADDER_KEEP_S],
		back_at >= 0.0 and absf(back_at - off_at - D.LADDER_KEEP_S) <= 2 * dt)
	check("ladder: handed back facing the route (yaw %.2f, route 0)" % d.yaw, absf(wrapf(d.yaw, -PI, PI)) < 0.3)

	print("cam_director_check: %d failed" % fails)
	quit(1 if fails > 0 else 0)
