extends Node3D
## Scene replay (MoKa M1109-55/56): a recorded bot run played back in the real Undead Burg geometry, so MoKa and
## Claude look at the same scene instead of re-running it or reading the same log twice.
##
## Data: data/replays/<run>.json (sim/replay_extract.py ← radar recording + run events). Map: assets/m10_01_00_00.glb
## (sim/flver_glb.py --map, DSR map pieces, local only). DSR is left-handed: Godot position = (−x, y, z) of the memory
## position, Godot rotation.y = −heading, camera yaw likewise — without that the picture is mirrored against the game.
##
## What is recorded vs. drawn:
##   positions, headings, HP, animation ids, the bot's camera yaw — [rec] radar snapshots (~9/s), interpolated between
##   body poses — [stand-in] Quaternius clips picked by animation id range (DSR animations are not converted)
##   fights, hits, decisions, log lines — [rec] run events
##
## Keys: Space play/pause · ←/→ 5 s · ,/. one snapshot · [ ] speed · N/P next/previous fight · 1–9 fight n ·
##       C camera (bot camera / orbit / top) · W/S tilt the bot camera (pitch isn't recorded) · mouse drag or ↑/↓ orbit ·
##       wheel zoom · L labels · H body capsules [candidate] · click the timeline = seek
##       orange = foe attack capsules inside the TAE hit window [game files] · cyan = ragdoll body capsules [candidate]
##
## Godot args after "--":  --replay=<file>  --at=<s>  --dump=<s,s,…>  (headless check: prints interpolated positions)

const MAP_GLBS := ["res://assets/m10_01_00_00.glb", "res://assets/m10_02_00_00.glb"]   # Undead Burg, Firelink Shrine
const DEATH_SHOW := 2.0        # s a killed character stays visible (falling)
const CAM_MIN := 1.0           # [guess] closest the bot camera pulls in (walls / roofs); closer hides everything
const MODEL_PATH := "res://assets/UAL1_Standard.glb"
const LIB2_PATH := "res://assets/UAL2_Standard.glb"
const PLAYER_WEAPON := "res://assets/WP_A_0505.glb"    # Battle Axe — the weapon of the 11-09 02:18 run ("무기: 배틀 액스")
const GRIP_R := Vector3(-0.02, 0.08, 0.0)              # [guess] as in main.gd
const DEFAULT_REPLAY := "../../data/replays/20261109_021816_burg-bonfire.json"
const CHR_MODELS := "../../data/gamefiles/chr_models.json"   # sim/chr_glb.py: model, display masks, animation lengths
# Real-model clip choice (MoKa M1109-57). The recorded id is the TAE animation id; c2540's 2255 borrows 2250, a 2-frame
# still pose — the game's walking runs in the Havok behavior graph on top of it, which the radar does not record. So for
# those ids (and −1 = not read) the clip is picked from the recorded speed: [guess] clips picked by eye from the
# anibnd (a00_0200 walk cycle, a00_0500 run cycle, a00_0000 stand), walking direction vs facing ignored.
const MOVE_IDS := [2250, 2255, -1]
const MOVE_CLIPS := {"stand": "a00_0000", "walk": "a00_0200", "run": "a00_0500"}
const CLAMP_IDS := [2205]       # death fall: hold the last frame instead of looping
const CAM_DIST := 4.0          # [game] LockCamParam camDistTarget
const CAM_ORG_Y := 1.42        # [game] LockCamParam chrOrgOffset_Y
const CAM_PITCH := -0.45       # [guess] the radar records yaw only — W/S tilt it
const TEAM_COLOR := {6: Color(0.85, 0.25, 0.2), 1: Color(0.3, 0.5, 0.95), 0: Color(0.55, 0.55, 0.55), 26: Color(0.7, 0.6, 0.3)}

var rp := {}                   # the replay file
var times := PackedFloat64Array()
var t := 0.0
var playing := false
var rate := 1.0
var cam_mode := 0              # 0 bot camera, 1 orbit, 2 top
var bot_pitch := CAM_PITCH
var orbit_yaw := 0.0
var orbit_pitch := -0.5
var orbit_dist := 7.0
var labels_on := true
var body_on := true            # H: ragdoll body capsules [candidate hurtbox]
var dump_body := false         # --dump-body: also dump them (they are many)
var dragging := false

var cam: Camera3D
var player: Node3D
var chars := {}                # id → {node, ap, label, team, npc, max_hp, segs}
var player_segs := []          # [[t_start, anim], …]
var hud: Label
var info: Label
var bar: Control
var hit_ring: MeshInstance3D
var dump_times := []
var map_nodes: Array = []
var xray: Dictionary = {}      # team → overlay material (silhouette through walls)
var chr_models := {}           # chr_models.json
var npc_model := {}            # npc row (String) → [model, masks]


func _ready() -> void:
	var args := {}
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		args[kv[0]] = kv[1] if kv.size() > 1 else ""
	var path: String = args.get("replay", ProjectSettings.globalize_path("res://").path_join(DEFAULT_REPLAY))
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		push_error("replay not found: " + path)
		get_tree().quit(1)
		return
	rp = JSON.parse_string(f.get_as_text())
	for fr in rp["frames"]:
		times.append(float(fr["t"]))
	var fm := FileAccess.open(ProjectSettings.globalize_path("res://").path_join(CHR_MODELS), FileAccess.READ)
	if fm != null:
		chr_models = JSON.parse_string(fm.get_as_text())
		for model in chr_models:
			if not ResourceLoader.exists("res://assets/%s.glb" % model):
				continue
			for row in chr_models[model].get("npc_masks", {}):
				npc_model[row] = [model, chr_models[model]["npc_masks"][row]]
	_build_world()
	_build_chars()
	_build_ui()
	t = float(args.get("at", "0"))
	cam_mode = int(args.get("cam", "0"))                    # start camera: --cam=1 --yaw= --pitch= --dist= (orbit)
	orbit_yaw = float(args.get("yaw", str(orbit_yaw)))
	orbit_pitch = float(args.get("pitch", str(orbit_pitch)))
	orbit_dist = float(args.get("dist", str(orbit_dist)))
	labels_on = args.get("labels", "1") != "0"
	body_on = args.get("body", "1") != "0"
	dump_body = args.has("dump-body")
	if args.has("dump"):
		for s in String(args["dump"]).split(","):
			dump_times.append(float(s))
	playing = not args.has("at") and dump_times.is_empty()
	_apply(t)


# ── World ───────────────────────────────────────────────────────────────
func _build_world() -> void:
	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.55, 0.6, 0.68)
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(0.75, 0.75, 0.75)
	e.ambient_light_energy = 0.9
	e.tonemap_mode = Environment.TONE_MAPPER_FILMIC
	env.environment = e
	add_child(env)
	var sun := DirectionalLight3D.new()
	sun.rotation = Vector3(deg_to_rad(-55), deg_to_rad(35), 0)
	sun.light_energy = 1.1
	sun.shadow_enabled = true
	add_child(sun)
	for g in MAP_GLBS:
		if not ResourceLoader.exists(g):
			continue
		var map_node: Node3D = load(g).instantiate()
		map_node.name = String(g).get_file().get_basename()
		add_child(map_node)
		map_nodes.append(map_node)
		# collision for the camera only (DSR pulls the camera in at walls, as the OBS frames show)
		for mi in map_node.find_children("*", "MeshInstance3D", true, false):
			(mi as MeshInstance3D).create_trimesh_collision()
		for cs in map_node.find_children("*", "CollisionShape3D", true, false):
			var sh := (cs as CollisionShape3D).shape
			if sh is ConcavePolygonShape3D:
				(sh as ConcavePolygonShape3D).backface_collision = true    # map winding isn't trusted (mirrored)
	cam = Camera3D.new()
	cam.fov = 43.0                # [game] LockCamParam VerticalFieldOfView (as main.gd CAM_FOV)
	cam.far = 600.0
	add_child(cam)
	cam.current = true
	hit_ring = MeshInstance3D.new()
	var tm := TorusMesh.new()
	tm.inner_radius = 0.45
	tm.outer_radius = 0.5
	var hm := StandardMaterial3D.new()
	hm.albedo_color = Color(1, 0.1, 0.1)
	hm.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	hm.no_depth_test = true
	tm.material = hm
	hit_ring.mesh = tm
	hit_ring.visible = false
	add_child(hit_ring)


func _mannequin(color: Color, show_color: bool) -> Dictionary:
	var root := Node3D.new()
	var ap: AnimationPlayer = null
	if ResourceLoader.exists(MODEL_PATH):
		var m: Node3D = load(MODEL_PATH).instantiate()
		m.rotation.y = PI                    # glTF faces +Z; heading convention as main.gd
		root.add_child(m)
		var aps := m.find_children("*", "AnimationPlayer", true, false)
		if aps.size() > 0:
			ap = aps[0]
			if ResourceLoader.exists(LIB2_PATH):
				ap.add_animation_library("ual2", _lib2())
		var ov := StandardMaterial3D.new()          # x-ray: faint silhouette even behind a wall
		ov.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		ov.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		ov.no_depth_test = true
		ov.albedo_color = Color(color.r, color.g, color.b, 0.28) if show_color else Color(1.0, 0.8, 0.2, 0.28)
		for mi in m.find_children("*", "MeshInstance3D", true, false):
			(mi as MeshInstance3D).material_overlay = ov
		if show_color:
			var mat := StandardMaterial3D.new()
			mat.albedo_color = color
			for mi in m.find_children("*", "MeshInstance3D", true, false):
				(mi as MeshInstance3D).material_override = mat
	return {"node": root, "ap": ap}


var _lib2_cache: AnimationLibrary
func _lib2() -> AnimationLibrary:
	if _lib2_cache == null:
		var m2: Node = load(LIB2_PATH).instantiate()
		_lib2_cache = m2.find_children("*", "AnimationPlayer", true, false)[0].get_animation_library("")
		m2.queue_free()
	return _lib2_cache


func _segments(key: String) -> Array:
	# [[t_start, anim], …] — when each animation id began (consecutive snapshots with the same id = one segment).
	# The change happened somewhere between the last snapshot with the old id and the first with the new one (~0.11 s
	# apart); the midpoint is used, so the start is off by at most half a snapshot gap.
	var out := []
	var last := -2
	var t_prev := -1.0
	for fr in rp["frames"]:
		var row = fr["p"] if key == "p" else fr["c"].get(key)
		if row == null:
			continue
		var an := int(row[4])
		var tf := float(fr["t"])
		if an != last:
			out.append([(t_prev + tf) * 0.5 if t_prev >= 0.0 else tf, an])
			last = an
		t_prev = tf
	return out


func _real_model(model: String, masks: Array, color: Color) -> Dictionary:
	# the game's own model (sim/chr_glb.py): weapons / shield shown by the NPC row's display masks, x-ray outline in
	# the team colour; faces −Z like the mannequin setup, so no extra turn
	var root := Node3D.new()
	var m: Node3D = load("res://assets/%s.glb" % model).instantiate()
	root.add_child(m)
	var want := masks.map(func(x): return int(x))
	var ov := StandardMaterial3D.new()
	ov.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	ov.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	ov.no_depth_test = true
	ov.albedo_color = Color(color.r, color.g, color.b, 0.22)
	for mi in m.find_children("*", "MeshInstance3D", true, false):
		var nm := String(mi.name)
		if nm.begins_with("mask"):
			mi.visible = nm.substr(4, 2).to_int() in want
		(mi as MeshInstance3D).material_overlay = ov
	var aps := m.find_children("*", "AnimationPlayer", true, false)
	var sks := m.find_children("*", "Skeleton3D", true, false)
	return {"node": root, "ap": aps[0] if aps.size() > 0 else null, "sk": sks[0] if sks.size() > 0 else null}


func _build_chars() -> void:
	var p := _mannequin(Color(), false)
	player = p["node"]
	add_child(player)
	if ResourceLoader.exists(PLAYER_WEAPON):
		var sks := player.find_children("*", "Skeleton3D", true, false)
		if sks.size() > 0:
			var ba := BoneAttachment3D.new()
			ba.bone_name = "hand_r"
			sks[0].add_child(ba)
			var w: Node3D = load(PLAYER_WEAPON).instantiate()
			w.transform = Transform3D(Basis(Vector3(1, 0, 0), Vector3(0, 0, -1), Vector3(0, 1, 0)), GRIP_R)
			ba.add_child(w)
	chars["p"] = {"node": player, "ap": p["ap"], "label": _label(player), "team": 1, "npc": 0,
		"max_hp": 0, "segs": _segments("p")}
	for k in rp["chars"]:
		var c: Dictionary = rp["chars"][k]
		var team := int(c["team"])
		var real: Variant = npc_model.get(str(int(c["npc"])))
		var col: Color = TEAM_COLOR.get(team, Color(0.8, 0.8, 0.8))
		var m := _real_model(real[0], real[1], col) if real != null else _mannequin(col, true)
		add_child(m["node"])
		chars[k] = {"node": m["node"], "ap": m["ap"], "label": _label(m["node"]), "team": team, "npc": int(c["npc"]),
			"max_hp": int(c["max_hp"]), "segs": _segments(k), "model": real[0] if real != null else "",
			"motion": "", "sk": m.get("sk"), "active": [], "cap_nodes": [], "body_nodes": []}


func _label(n: Node3D) -> Label3D:
	var l := Label3D.new()
	l.billboard = BaseMaterial3D.BILLBOARD_ENABLED
	l.no_depth_test = true
	l.font_size = 28
	l.pixel_size = 0.004
	l.outline_size = 8
	l.position.y = 2.1
	n.add_child(l)
	return l


func _build_ui() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	hud = Label.new()
	hud.position = Vector2(12, 10)
	hud.add_theme_font_size_override("font_size", 16)
	layer.add_child(hud)
	info = Label.new()
	info.position = Vector2(12, 120)
	info.add_theme_font_size_override("font_size", 15)
	layer.add_child(info)
	bar = Control.new()
	bar.anchor_left = 0.0
	bar.anchor_right = 1.0
	bar.anchor_top = 1.0
	bar.anchor_bottom = 1.0
	bar.offset_top = -46
	bar.offset_bottom = -10
	bar.offset_left = 12
	bar.offset_right = -12
	bar.draw.connect(_draw_bar)
	bar.gui_input.connect(_bar_input)
	layer.add_child(bar)


# ── Sampling ────────────────────────────────────────────────────────────
func _frame_at(tt: float) -> int:
	# index of the last snapshot at or before tt
	var lo := 0
	var hi := times.size() - 1
	if tt <= times[0]:
		return 0
	while lo < hi:
		var mid := (lo + hi + 1) / 2
		if times[mid] <= tt:
			lo = mid
		else:
			hi = mid - 1
	return lo


func sample(key: String, tt: float):
	# interpolated [x, y, z, heading, anim, hp] at tt, or null when the character isn't in the snapshots around tt
	var i := _frame_at(tt)
	var a: Variant = _row(i, key)
	if a == null:
		return null
	if i + 1 >= times.size():
		return a
	var b: Variant = _row(i + 1, key)
	if b == null or tt <= times[i]:
		return a
	var u := clampf((tt - times[i]) / maxf(times[i + 1] - times[i], 1e-6), 0.0, 1.0)
	return [lerpf(a[0], b[0], u), lerpf(a[1], b[1], u), lerpf(a[2], b[2], u), lerp_angle(a[3], b[3], u), a[4], a[5]]


func _row(i: int, key: String):
	var fr: Dictionary = rp["frames"][i]
	return fr["p"] if key == "p" else fr["c"].get(key)


# ── Stand-in poses by DSR animation id ─────────────────────────────────
func _clip_for(key: String, anim: int, spd: float, hp_now: int) -> Array:
	# [clip, seconds the clip is stretched over (0 = natural speed), backwards]
	if key == "p":
		if anim >= 300000 and anim < 1000000:
			return ["ual2/Sword_Regular_A" if anim % 10 == 0 else "ual2/Sword_Regular_B", 1.4, false]
		if anim in [700, 710, 720]:
			return ["Roll", 1.0, false]
		if anim == 690:
			return ["Roll", 0.9, true]
		if anim >= 7580 and anim < 7600:
			return ["ual2/Consume", 2.3, false]
	else:
		if hp_now <= 0:
			return ["Death01", 1.2, false]
		if anim >= 3000 and anim < 4000:
			return ["ual2/Sword_Regular_A", 1.3, false]
		if anim >= 7000 and anim < 8000:
			return ["Hit_Chest", 0.6, false]
		if anim >= 6000 and anim < 7000:
			return ["Death01", 0.0, false]
	if spd > 3.7:
		return ["Sprint", 0.0, false]
	if spd > 2.0:
		return ["Jog_Fwd", 0.0, false]
	if spd > 0.3:
		return ["Walk", 0.0, false]
	return ["Idle", 0.0, false]


func _seg_start(segs: Array, tt: float) -> float:
	var s := 0.0
	for sg in segs:
		if float(sg[0]) <= tt:
			s = float(sg[0])
		else:
			break
	return s


static func anim_name(anim: int) -> String:
	return "a%02d_%04d" % [anim / 10000, anim % 10000]


func _pose_real(c: Dictionary, anim: int, spd: float, hp_now: int, tt: float) -> void:
	# the recorded animation id played from the game's own clip; time since the id began (restarts of the same id
	# inside one segment wrap around)
	var ap: AnimationPlayer = c["ap"]
	var clip := anim_name(anim)
	var since := tt - _seg_start(c["segs"], tt)
	c["motion"] = "실제"
	if anim in MOVE_IDS or not ap.has_animation(clip):
		var kind := "run" if spd > 2.5 else ("walk" if spd > 0.3 else "stand")
		c["motion"] = ("이동 추정 %s" % kind) if anim in MOVE_IDS else "없는 번호 → %s" % kind
		clip = MOVE_CLIPS[kind]
		since = tt
	var a := ap.get_animation(clip)
	var at := minf(since, a.length) if (anim in CLAMP_IDS or hp_now <= 0) else fmod(since, a.length)
	if ap.current_animation != clip:
		ap.play(clip)
	ap.seek(at, true)
	ap.pause()
	var skel: Skeleton3D = c.get("sk")
	if skel != null and skel.has_method("force_update_all_bone_transforms"):
		skel.force_update_all_bone_transforms()     # bone poses of this seek, not of the last frame
	_attack_caps(c, anim if c["motion"] == "실제" else -9, at)
	_body_caps(c)


# ── Attack hit capsules (MoKa M1109-59) ────────────────────────────────
# While the clip's local time is inside a TAE type-1 window, each AtkParam_Npc hit slot is a capsule from model point
# "from" to model point "to" with its radius (sim/chr_glb.py npc_rows: TAE → BehaviorParam → AtkParam_Npc; FLVER dummy
# points follow their attach bone). Shape and timing come from the game files; whether the engine tests the
# capsule only at each update or swept between updates is not known — drawn as it stands at this instant.
func _attack_caps(c: Dictionary, anim: int, at: float) -> void:
	var act := []
	var sk: Skeleton3D = c.get("sk")
	var model: String = c.get("model", "")
	if sk != null and anim >= 0:
		var wins: Array = chr_models[model].get("npc_attacks", {}).get(str(c["npc"]), {}).get(str(anim), [])
		var dm: Dictionary = chr_models[model].get("dummies", {})
		for w in wins:
			if at < float(w["start"]) or at > float(w["end"]) or not w.has("hit"):
				continue
			for h in w["hit"]:
				var p0: Variant = _dummy_world(sk, dm, str(int(h["from"])))
				var p1: Variant = _dummy_world(sk, dm, str(int(h["to"])))
				if p0 != null and p1 != null:
					act.append([p0, p1, float(h["radius"]), int(h["type"]), int(w["atk"])])
	c["active"] = act
	_draw_caps(c["cap_nodes"], act, Color(1.0, 0.55, 0.0, 0.45), true)


# ── Body capsules [candidate] (MoKa M1109-59) ────────────────────────────
# The model's ragdoll capsules (sim/hkx_ragdoll.py: hkpCapsuleShape per ragdoll rigid body, following the animation
# bone the ragdoll → animation SkeletonMapper names). DS3 uses its ragdoll capsules as the hurtbox (DS3 Codex); for DS1
# nothing was found, so these are drawn as candidates, not as the hurtbox.
func _body_caps(c: Dictionary) -> void:
	var sk: Skeleton3D = c.get("sk")
	var model: String = c.get("model", "")
	var act := []
	if sk != null and body_on:
		for b in chr_models[model].get("body", {}).get("caps", []):
			var bi := sk.find_bone(String(b["bone"]))
			if bi < 0:
				continue
			var g := sk.global_transform * sk.get_bone_global_pose(bi)
			var a: Array = b["a"]
			var e: Array = b["b"]
			act.append([g * Vector3(a[0], a[1], a[2]), g * Vector3(e[0], e[1], e[2]), float(b["r"])])
	c["body"] = act
	_draw_caps(c["body_nodes"], act, Color(0.2, 0.85, 1.0, 0.35), false)


func _draw_caps(nodes: Array, act: Array, col: Color, on_top: bool) -> void:
	while nodes.size() < act.size():
		var mi := MeshInstance3D.new()
		var cm := CapsuleMesh.new()
		cm.radial_segments = 12
		cm.rings = 4
		mi.mesh = cm
		var mat := StandardMaterial3D.new()
		mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		mat.no_depth_test = on_top
		mat.albedo_color = col
		mi.material_override = mat
		add_child(mi)
		nodes.append(mi)
	for i in nodes.size():
		var mi: MeshInstance3D = nodes[i]
		mi.visible = i < act.size()
		if not mi.visible:
			continue
		var p0: Vector3 = act[i][0]
		var p1: Vector3 = act[i][1]
		var r: float = act[i][2]
		var cm: CapsuleMesh = mi.mesh
		cm.radius = r
		cm.height = p0.distance_to(p1) + 2.0 * r
		var up := (p1 - p0).normalized() if p0.distance_to(p1) > 1e-4 else Vector3.UP
		var x := up.cross(Vector3.FORWARD if absf(up.dot(Vector3.FORWARD)) < 0.9 else Vector3.RIGHT).normalized()
		mi.global_transform = Transform3D(Basis(x, up, x.cross(up)), (p0 + p1) * 0.5)


func _hide_caps(c: Dictionary) -> void:
	c["active"] = []
	c["body"] = []
	for mi in c.get("cap_nodes", []) + c.get("body_nodes", []):
		(mi as MeshInstance3D).visible = false


func _dummy_world(sk: Skeleton3D, dm: Dictionary, id: String):
	if not dm.has(id):
		return null
	var d: Dictionary = dm[id][0]
	var bi := sk.find_bone(String(d["bone"]))
	if bi < 0:
		return null
	var o: Array = d["offset"]
	return sk.global_transform * (sk.get_bone_global_pose(bi) * Vector3(o[0], o[1], o[2]))


func _pose(c: Dictionary, key: String, row: Array, tt: float) -> void:
	var ap: AnimationPlayer = c["ap"]
	if ap == null:
		return
	var prev: Variant = sample(key, tt - 0.12)
	var spd := 0.0
	if prev != null:
		spd = Vector2(row[0] - prev[0], row[2] - prev[2]).length() / 0.12
	if c.get("model", "") != "":
		_pose_real(c, int(row[4]), spd, int(row[5]), tt)
		return
	c["active"] = []
	var pick := _clip_for(key, int(row[4]), spd, int(row[5]))
	var clip: String = pick[0]
	if not ap.has_animation(clip):
		clip = "Idle"
	var a := ap.get_animation(clip)
	var since := tt - _seg_start(c["segs"], tt)
	var at: float
	if float(pick[1]) > 0.0:
		at = clampf(since / float(pick[1]), 0.0, 1.0) * a.length
		if pick[2]:
			at = a.length - at
	else:
		at = fmod(tt, a.length) if a.loop_mode != Animation.LOOP_NONE else minf(since, a.length)
	if ap.current_animation != clip:
		ap.play(clip)
	ap.seek(at, true)
	ap.pause()


# ── Apply a time ────────────────────────────────────────────────────────
func _apply(tt: float) -> void:
	for key in chars:
		var c: Dictionary = chars[key]
		var row: Variant = sample(key, tt)
		var n: Node3D = c["node"]
		if row == null:
			n.visible = false
			_hide_caps(c)
			continue
		n.visible = _shown(key, row, tt)
		n.position = Vector3(-float(row[0]), row[1], row[2])
		n.rotation.y = -float(row[3])
		_pose(c, key, row, tt)
		if not n.visible:
			_hide_caps(c)
		var l: Label3D = c["label"]
		l.visible = labels_on
		if key == "p":
			l.text = "bot  HP %d  anim %d" % [row[5], row[4]]
			l.modulate = Color(0.6, 0.8, 1)
		else:
			l.text = "#%s %d  HP %d/%d  anim %d" % [key, c["npc"], row[5], c["max_hp"], row[4]]
			if c.get("model", "") != "":
				l.text += "  [%s]" % c["motion"]
			l.modulate = Color(1, 0.6, 0.5) if int(c["team"]) == 6 else Color(0.8, 0.8, 0.8)
	var hit: Variant = _near(rp["hits"], tt, 0.5)
	hit_ring.visible = hit != null
	if hit != null:
		hit_ring.position = player.position + Vector3(0, 0.1, 0)
	_update_camera(tt)
	_update_hud(tt)
	bar.queue_redraw()


func _shown(key: String, row: Array, tt: float) -> bool:
	# the bot always; others while alive and for DEATH_SHOW s after their HP reached 0 (the falling pose), then gone —
	# a foe already dead when the recording starts never shows
	if key == "p" or int(row[5]) > 0:
		return true
	var before: Variant = sample(key, tt - DEATH_SHOW)
	return before != null and int(before[5]) > 0


func _near(list: Array, tt: float, within: float):
	for e in list:
		if absf(float(e["t"]) - tt) <= within:
			return e
	return null


func _update_camera(tt: float) -> void:
	var org := player.position + Vector3(0, CAM_ORG_Y, 0)
	if cam_mode == 0:
		var fr: Dictionary = rp["frames"][_frame_at(tt)]
		var yaw: float = -float(fr["cam"]) if fr["cam"] != null else player.rotation.y + PI
		var fwd := Vector3(sin(yaw), 0, cos(yaw))
		var want := org - fwd * CAM_DIST * cos(bot_pitch) + Vector3(0, -sin(bot_pitch) * CAM_DIST, 0)
		var q := PhysicsRayQueryParameters3D.create(org, want)
		var hit: Dictionary = get_world_3d().direct_space_state.intersect_ray(q)
		if hit:
			var hp: Vector3 = hit["position"]
			var back := maxf(org.distance_to(hp) - 0.2, CAM_MIN)
			want = org + (want - org).normalized() * back
		cam.position = want
		cam.look_at(org, Vector3.UP)
	elif cam_mode == 1:
		var d := Vector3(sin(orbit_yaw) * cos(orbit_pitch), -sin(orbit_pitch), cos(orbit_yaw) * cos(orbit_pitch))
		cam.position = org + d * orbit_dist
		cam.look_at(org, Vector3.UP)
	else:
		cam.position = org + Vector3(0, 22, 0.01)
		cam.look_at(org, Vector3.UP)


func _fight_at(tt: float):
	for fi in rp["fights"].size():
		var fg: Dictionary = rp["fights"][fi]
		if tt >= float(fg["t"]) - 1.0 and tt <= float(fg["t_end"]) + 1.0:
			return fi
	return -1


func _update_hud(tt: float) -> void:
	var row: Variant = sample("p", tt)
	var fi: int = _fight_at(tt)
	var ftxt := ""
	if fi >= 0:
		var fg: Dictionary = rp["fights"][fi]
		ftxt = "싸움 %d/%d  %s  → %s  (준 %s · 받은 %s, %.1f–%.1f s)" % [fi + 1, rp["fights"].size(), fg["tag"],
			fg["result"], fg["dealt"], fg["taken"], fg["t"], fg["t_end"]]
	hud.text = "%s   %s\n%.2f / %.1f s   ×%.2f %s   camera %s\nHP %s   %s" % [rp["run"], rp["map"], tt, rp["length"], rate,
		"▶" if playing else "❚❚", ["bot", "orbit", "top"][cam_mode], row[5] if row != null else "?", ftxt]
	var lines := []
	var r: Variant = null
	for e in rp["rules"]:
		if float(e["t"]) <= tt and tt - float(e["t"]) < 2.0:
			r = e
	if r != null:
		lines.append("판단 %.1f s: %s → %s (%s)" % [r["t"], r["rule"], r["out"], r["style"]])
	var h: Variant = _near(rp["hits"], tt, 1.5)
	if h != null:
		lines.append("큰 피격 %.1f s: HP %d → %d, %s #%s anim %s, %.1f m" % [h["t"], h["hp0"], h["lo"], h["npc"], h["id"],
			h["anim"], h["d"]])
	var says := []
	for s in rp["says"]:
		if float(s["t"]) <= tt and tt - float(s["t"]) < 4.0:
			says.append("[%.1f] %s" % [s["t"], s["line"]])
	lines.append_array(says.slice(maxi(0, says.size() - 4)))
	info.text = "\n".join(lines)


func _draw_bar() -> void:
	var w := bar.size.x
	var h := bar.size.y
	var L := float(rp["length"])
	bar.draw_rect(Rect2(0, 0, w, h), Color(0, 0, 0, 0.45))
	for fg in rp["fights"]:
		var x0 := float(fg["t"]) / L * w
		var x1 := float(fg["t_end"]) / L * w
		bar.draw_rect(Rect2(x0, 4, maxf(x1 - x0, 2.0), h - 8), Color(1, 0.6, 0.1, 0.6))
	for e in rp["rules"]:
		var x := float(e["t"]) / L * w
		bar.draw_line(Vector2(x, h - 8), Vector2(x, h), Color(0.6, 0.9, 1), 1.0)
	for e in rp["hits"]:
		var x := float(e["t"]) / L * w
		bar.draw_line(Vector2(x, 0), Vector2(x, h), Color(1, 0.1, 0.1), 3.0)
	var xn := t / L * w
	bar.draw_line(Vector2(xn, -4), Vector2(xn, h + 4), Color(1, 1, 1), 2.0)


func _bar_input(ev: InputEvent) -> void:
	if ev is InputEventMouseButton and ev.pressed and ev.button_index == MOUSE_BUTTON_LEFT:
		t = clampf(ev.position.x / bar.size.x, 0.0, 1.0) * float(rp["length"])
		_apply(t)


# ── Input / loop ────────────────────────────────────────────────────────
func _jump_fight(i: int) -> void:
	if i >= 0 and i < rp["fights"].size():
		t = maxf(0.0, float(rp["fights"][i]["t"]) - 2.0)
		_apply(t)


func _unhandled_input(ev: InputEvent) -> void:
	if ev is InputEventKey and ev.pressed:
		match ev.keycode:
			KEY_SPACE:
				playing = not playing
			KEY_LEFT:
				t = maxf(0.0, t - 5.0)
			KEY_RIGHT:
				t = minf(float(rp["length"]), t + 5.0)
			KEY_COMMA:
				playing = false
				t = times[maxi(0, _frame_at(t - 0.001))] if t > times[0] else 0.0
			KEY_PERIOD:
				playing = false
				t = times[mini(times.size() - 1, _frame_at(t) + 1)]
			KEY_BRACKETLEFT:
				rate = maxf(0.125, rate / 2.0)
			KEY_BRACKETRIGHT:
				rate = minf(8.0, rate * 2.0)
			KEY_C:
				cam_mode = (cam_mode + 1) % 3
			KEY_L:
				labels_on = not labels_on
			KEY_H:
				body_on = not body_on
				_apply(t)
			KEY_N:
				var fi: int = _fight_at(t + 2.5)
				_jump_fight(fi + 1 if fi >= 0 else _next_fight(t))
			KEY_P:
				var fi2: int = _fight_at(t + 2.0)
				_jump_fight(maxi(0, (fi2 if fi2 >= 0 else _next_fight(t)) - 1))
			_:
				if ev.keycode >= KEY_1 and ev.keycode <= KEY_9:
					_jump_fight(ev.keycode - KEY_1)
		_apply(t)
	elif ev is InputEventMouseButton:
		if ev.button_index == MOUSE_BUTTON_LEFT:
			dragging = ev.pressed
		elif ev.button_index == MOUSE_BUTTON_WHEEL_UP:
			orbit_dist = maxf(1.5, orbit_dist * 0.9)
		elif ev.button_index == MOUSE_BUTTON_WHEEL_DOWN:
			orbit_dist = minf(60.0, orbit_dist * 1.1)
	elif ev is InputEventMouseMotion and dragging:
		cam_mode = 1
		orbit_yaw -= ev.relative.x * 0.008
		orbit_pitch = clampf(orbit_pitch - ev.relative.y * 0.006, -1.4, 0.3)


func _next_fight(tt: float) -> int:
	for fi in rp["fights"].size():
		if float(rp["fights"][fi]["t"]) > tt:
			return fi
	return rp["fights"].size() - 1


func _process(dt: float) -> void:
	if not dump_times.is_empty():
		_dump()
		return
	if Input.is_key_pressed(KEY_W):
		bot_pitch = clampf(bot_pitch - dt * 0.8, -1.3, 0.4)
	if Input.is_key_pressed(KEY_S):
		bot_pitch = clampf(bot_pitch + dt * 0.8, -1.3, 0.4)
	if Input.is_key_pressed(KEY_UP):
		orbit_pitch = clampf(orbit_pitch - dt, -1.4, 0.3)
	if Input.is_key_pressed(KEY_DOWN):
		orbit_pitch = clampf(orbit_pitch + dt, -1.4, 0.3)
	if playing:
		t += dt * rate
		if t >= float(rp["length"]):
			t = float(rp["length"])
			playing = false
	_apply(t)


func _dump() -> void:
	# headless check (tests/replay_test.py): the room's interpolated state at the asked times, one JSON line each
	var out := []
	for tt in dump_times:
		_apply(tt)
		var cs := {}
		var caps := {}
		var body := {}
		for key in chars:
			for a in chars[key].get("active", []):
				if not chars[key]["node"].visible:
					continue
				var q0: Vector3 = a[0]
				var q1: Vector3 = a[1]
				caps.get_or_add(key, []).append([[-q0.x, q0.y, q0.z], [-q1.x, q1.y, q1.z], a[2], a[3], a[4]])
			if dump_body and chars[key]["node"].visible:
				for a in chars[key].get("body", []):
					var q0: Vector3 = a[0]
					var q1: Vector3 = a[1]
					body.get_or_add(key, []).append([[-q0.x, q0.y, q0.z], [-q1.x, q1.y, q1.z], a[2]])
		for key in chars:
			var n: Node3D = chars[key]["node"]
			if n.visible:
				cs[key] = [snappedf(-n.position.x, 0.001), snappedf(n.position.y, 0.001), snappedf(n.position.z, 0.001),
					snappedf(-n.rotation.y, 0.001)]          # back in DSR coordinates
		var surf := {}
		for mn in map_nodes:
			var k := 0
			for mi in (mn as Node3D).find_children("*", "MeshInstance3D", true, false):
				k += (mi as MeshInstance3D).mesh.get_surface_count()
			surf[(mn as Node3D).name] = k
		var row := {"t": tt, "chars": cs, "caps": caps, "map_surfaces": surf}
		if dump_body:
			row["body"] = body
		out.append(row)
	print("REPLAY_DUMP " + JSON.stringify(out))
	dump_times.clear()
	get_tree().quit()
