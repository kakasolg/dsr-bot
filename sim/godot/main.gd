extends Node3D
## Stage 0 practice room (MoKa M1109-47/50): bonfire, lever in a niche, gate, a player driven by an Xbox pad
## (the bot's ViGEm pad or MoKa's) or by UDP input, and a camera that follows.
##
## Coordinates are DSR world coordinates of the Sunlight Altar area (m10_01), so data/spots.json positions carry over.
## Godot rotation.y == DSR heading (+0x4 angle): facing world angle atan2(dx, dz) = heading + PI.
## cam_yaw == DSR ChrFollowCam yaw: atan2(forward.x, forward.z).
##
## Every value is tagged with where it comes from:
##   [game]  read from the DSR game files      [meas]  measured in DSR (motion.py, P-135 …)
##   [guess] made up for this room — replace with a game value or a measurement before trusting it

# ── Level (DSR m10_01 Sunlight Altar area) ─────────────────────────────
const FLOOR_Y := 9.40                               # [game] lever o1200_1001 y 9.403
const BONFIRE := Vector3(24.35, 9.5, -22.2)         # [game] o0200_0001
const LEVER := Vector3(18.029, 9.403, -25.488)      # [game] o1200_1001
const LEVER_ROT_DEG := 120.0                        # [game] MSB rotate y
const GATE := Vector3(19.005, 9.404, -21.895)       # [game] o1201_1001 (taken to be the gate — [guess] which object)
const GATE_W := 4.0                                 # [guess]
const GATE_H := 4.0                                 # [guess]
const START := Vector3(23.8, 9.5, -23.0)            # [meas] spots.json altar-bonfire stand
const START_HEADING := -2.5393                      # [meas] same

# ── Lever action (ObjActParam row 1200, o1200.flver dummy 191) ─────────
const ACT_POINT_LOCAL := Vector3(0, 0, 1.182)       # [game] dummy 191
const ACT_DIST := 0.90                              # [game] MaxActionDistance 90 — cm is [guess]
const ACT_PLAYER_DEG := 45.0                        # [game] MaxPlayerAngle
const ACT_OBJECT_DEG := 45.0                        # [game] MaxObjectAngle — measured from the lever origin is [guess]
const GATE_OPEN_S := 3.0                            # [guess]

# ── Player movement (motion.py Params) ─────────────────────────────────
const DEAD := 0.4          # [meas] stick below this doesn't move (P-135: 0.25–0.35 doesn't move)
const WALK_HI := 0.7       # [meas]
const V_WALK := 1.64       # [meas] m/s
const V_JOG := 3.42        # [meas] m/s
const V_RUN := 3.98        # [meas] m/s, B held
const TURN := 10.0         # [meas] rad/s upper bound (10 Hz frames can't resolve faster)
const TAU_UP := 0.215      # [meas] s
const TAU_DOWN := 0.10     # [meas] s
const RADIUS := 0.35       # [guess] player capsule
const HEIGHT := 1.7        # [guess]

# ── Camera ──────────────────────────────────────────────────────────────
const CAM_DIST := 4.0      # [game] LockCamParam camDistTarget (lock-on camera; free camera is [guess] the same)
const CAM_ORG_Y := 1.42    # [game] LockCamParam chrOrgOffset_Y
const CAM_FOV := 43.0      # [game] LockCamParam VerticalFieldOfView, every row (Godot's default 75° made the body big, the map small and the ramp steep — MoKa 11-09)
const MIRROR := true       # show the picture as DSR does (_build_mirror); the numbers stay DSR's either way
const CAM_PITCH := -0.25   # [guess] rad
const CAM_TURN := 2.5      # [guess] rad/s at full right stick
const CAM_FOLLOW := 8.0    # [guess] 1/s position smoothing

# ── Actions (sim/godot/actions.json ← sim/build_actions.py ← DSR player TAE) ──
const ROLL_DIST := 2.8         # [guess] m a roll travels — to be measured in DSR
const ROLL_MOVE_S := 0.6       # [guess] s it takes
const BACKSTEP_DIST := 1.6     # [guess]
const BACKSTEP_MOVE_S := 0.4   # [guess]
const B_TAP_S := 0.25          # [guess] B released before this = roll / backstep, held longer = run
const MODEL_PATH := "res://assets/UAL1_Standard.glb"    # CC0 Quaternius (not in git — sim/README.md)
const LIB2_PATH := "res://assets/UAL2_Standard.glb"

# ── Stage 1·2: camera, lock-on, buffer, hits (Perplexity build order, MoKa M1109-52/53) ──
const LOCK_RANGE := 15.0       # [game] LockCamParam chrLockRangeMaxRadius
const CAM_MIN := 0.6           # [guess] closest the camera retracts to near a wall
const LOCK_CAM_TURN := 6.0     # [guess] 1/s camera yaw follow while locked on
const WEAPON_IN := 0.5         # [guess] fallback weapon segment (no weapon model), m in front of the body
const WEAPON_OUT := 1.9        # [guess]
const WEAPON_R := 0.2          # [guess]
# Equipment (MoKa M1109-54): DSR weapon / shield models, local only (sim/flver_glb.py → assets/, gitignored).
# Hitboxes, hitstop and damage come from actions.json "hit" (AtkParam_Pc) and "equip" (EquipParamWeapon) — [game].
# How a model sits in the Quaternius hand is [guess]: hand_r / hand_l rest axes are y = along the fingers,
# z = character forward, x = up (right) / down (left); DSR weapon models have the blade along -Y, grip at the origin.
const RIGHT_GLB := "res://assets/WP_A_0266.glb"    # Claymore (EquipParamWeapon 301000, WeaponModel 266)
const LEFT_GLB := "res://assets/WP_A_1521.glb"     # Wooden Shield (1400000, WeaponModel 1521)
# CC0 stand-ins (MoKa M1110-10: "Quaternius 공개 사용 하고 무기도 공개에서 찾아서 최대 한 유사한거"): Quaternius Medieval
# Weapons (CC0, assets/cc0/License.txt). Used only when the DSR model above is missing (a fresh clone / cloud). The weapon
# node stays where the DSR model would be, so the hit capsules (DSR dummy points in that node's space) are the same;
# the CC0 mesh inside is turned blade −Y like DSR's and scaled so its tip is the farthest DSR dummy [look only].
const CC0_RIGHT := "res://assets/cc0/Claymore.fbx"   # blade +Y, grip at the origin, tip y 6.27
const CC0_RIGHT_TIP := 6.27
const CC0_LEFT := "res://assets/cc0/Shield_Round.fbx"  # face +Z, Ø 2.0
const CC0_LEFT_D := 0.6                               # [guess] Wooden Shield diameter, m
const GRIP_R := Vector3(-0.02, 0.08, 0.0)          # [guess] grip point in hand_r space (into the fist, palm side)
const GRIP_L := Vector3(0.03, 0.07, 0.0)           # [guess] shield handle in hand_l space
const SHIELD_OUT := -0.15                          # [guess] shield moved off the forearm toward its face side (sign from renders — the model is mirrored)
const PLAYER_HP := 849         # [meas] the 11-09 character (VIT 22)
const STAGGER_S := 0.5         # [guess] player hit reaction
const DUMMY_POS := Vector3(26.5, 9.4, -26.0)   # training dummy — not in DSR
const DUMMY_R := 0.4           # [guess]
# 내 칼이 맞히는 상대 몸 두께 (MoKa 11-09 "칼 길이가 너무 길어서 사기 수준"): 몸 충돌 0.4를 그대로 쓰면 AtkParam 반지름 0.4와 합쳐
# 칼끝 0.8 m 밖까지 맞음 — 약공이 중심 2.4 m에서 늘 맞았다. 게임 블랙박스 (souls/weapons.py CLAYMORE): 1.8 m 9/14 · 2.0 m 6/15 ·
# 2.2 m 3/8 · 2.4 m 3/19. 이 값은 그 경계에 맞춘 [guess] (DSR이 실제로 어느 몸 캡슐로 재는지는 모름)
const BODY_HIT_R := 0.0
const DUMMY_H := 1.8           # [guess]
const DUMMY_HP := 600          # [guess]
const DUMMY_EVERY := 3.0       # [guess] s per swing while the player is close
const DUMMY_WINDUP := 0.7      # [guess] telegraph
const DUMMY_ACTIVE := 0.15     # [guess]
const DUMMY_REACH := 1.4       # [guess] hit sphere centre in front of it
const DUMMY_HIT_R := 0.6       # [guess]
const DUMMY_DMG := 120         # [guess]

# ── Link ────────────────────────────────────────────────────────────────
const STATE_PORT := 47811  # state out (JSON per physics frame) → sim/godot_link.py
const INPUT_PORT := 47812  # UDP input in {"lx","ly","rx","a","b"} — headless tests without a pad

var player: CharacterBody3D
var cam: Camera3D
var mirror_view: SubViewport   # the camera's view, shown flipped (_build_mirror)
var gate: AnimatableBody3D
var prompt_label: Label
var info_label: Label
var lever_basis: Basis

var heading := START_HEADING
var speed := 0.0
var cam_yaw := 0.0
var anim := -1
var actions := {}            # name → DSR windows (actions.json)
var act_name := ""           # current action, "" = none
var act_t := 0.0             # s since it started (= DSR anim_time)
var act_dir := 0.0           # world angle the action moves along
var b_down_t := -1.0
var btn_was := {}
var anim_player: AnimationPlayer
var loco_clip := ""
var lever_pulled := false
var gate_open := 0.0          # 0 closed … 1 open
var prompt := false
var prompt_why := ""
var t := 0.0

var lock := false
var queued := {}            # "r" / "roll" → time pressed (kept until the DSR cancel time, then run)
var log_ev := []            # last inputs: {k, in, buffered, exec}
var hit_done := false       # this swing already hit the dummy (one hit per swing)
var hitstop := 0.0
var player_hp := PLAYER_HP
var stagger := 0.0
var player_hits := 0
var dodged := 0
var dummy: Node3D
var dummy_body: StaticBody3D
var dummy_arm: Node3D
var dummy_mat: StandardMaterial3D
var dummy_hp := DUMMY_HP
var dummy_t := 0.0
var dummy_phase := "idle"
var dummy_heading := 0.0
var dummy_hit_done := false
var dummy_flash := 0.0
var slow := false
var overlay := true
var dbg_mesh: ImmediateMesh
var cam_dist := CAM_DIST
var speed_dir := 0.0
var speed_dir_set := false
var equip := {}              # actions.json "equip": right / left weapon rows and model dummies
var weapon_node: Node3D      # right-hand weapon model (null → fallback segment)
var prev_caps := []          # last frame's hit capsules [[p0, p1, r], …] for the swept test

var udp_out := PacketPeerUDP.new()
var udp_in := PacketPeerUDP.new()
var net_in := {"lx": 0.0, "ly": 0.0, "rx": 0.0, "a": false, "b": false, "rb": false, "x": false, "r3": false, "slow": false, "ov": false}
var net_in_t := -10.0


func _ready() -> void:
	lever_basis = Basis(Vector3.UP, deg_to_rad(LEVER_ROT_DEG))
	var f := FileAccess.open("res://actions.json", FileAccess.READ)
	if f:
		var j: Dictionary = JSON.parse_string(f.get_as_text())
		actions = j["actions"]
		equip = j.get("equip", {})
	_build_world()
	_build_player()
	_build_dummy()
	_build_debug()
	_build_ui()
	cam_yaw = heading + PI          # camera starts behind the player
	udp_out.set_dest_address("127.0.0.1", STATE_PORT)
	udp_in.bind(INPUT_PORT, "127.0.0.1")


# ── World ───────────────────────────────────────────────────────────────
func _box(size: Vector3, pos: Vector3, rot_y: float, color: Color, body := true) -> Node3D:
	var mi := MeshInstance3D.new()
	var bm := BoxMesh.new()
	bm.size = size
	var mat := StandardMaterial3D.new()
	mat.albedo_color = color
	bm.material = mat
	mi.mesh = bm
	if not body:
		mi.position = pos
		mi.rotation.y = rot_y
		add_child(mi)
		return mi
	var sb := StaticBody3D.new()
	var cs := CollisionShape3D.new()
	var sh := BoxShape3D.new()
	sh.size = size
	cs.shape = sh
	sb.add_child(cs)
	sb.add_child(mi)
	sb.position = pos
	sb.rotation.y = rot_y
	add_child(sb)
	return sb


func _build_world() -> void:
	var sun := DirectionalLight3D.new()
	sun.rotation = Vector3(-0.9, 0.6, 0)
	add_child(sun)
	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.35, 0.4, 0.5)
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(0.5, 0.5, 0.5)
	env.environment = e
	add_child(env)

	# floor [guess] 30 x 30 around the area
	_box(Vector3(30, 0.2, 30), Vector3(21, FLOOR_Y - 0.1, -24), 0.0, Color(0.42, 0.4, 0.37))

	# Wall line through the lever niche and the gate. The lever faces f = (sin 120°, cos 120°); the wall runs along w,
	# 0.5 m behind the lever origin [guess]. The gate (0.95 m further back along f) is cut into the same line [guess].
	var f := lever_basis.z
	var w := Vector3(f.z, 0, -f.x).normalized()
	var wall_rot := atan2(w.x, w.z) - PI / 2.0        # box local X along w
	var wall_c := LEVER - f * 0.5
	var stone := Color(0.55, 0.52, 0.47)
	# niche side pillars [guess]: 0.6 m out from the wall, 0.8 m each side of the lever
	for s in [-1.0, 1.0]:
		_box(Vector3(0.4, 3.0, 0.6), wall_c + w * (0.8 * s) + f * 0.3 + Vector3(0, 1.5, 0), wall_rot, stone)
	# wall segments: from the niche away from the gate (8 m) and from the niche to the gate edge
	var to_gate := (GATE - LEVER)
	var gate_along := to_gate.dot(w)                 # distance along the wall from lever to gate centre
	var gs := signf(gate_along)
	_box(Vector3(8.0, 4.0, 0.5), wall_c - w * (gs * 4.6) + Vector3(0, 2, 0), wall_rot, stone)
	var mid_len := absf(gate_along) - GATE_W / 2.0 - 0.6
	if mid_len > 0.1:
		_box(Vector3(mid_len, 4.0, 0.5), wall_c + w * (gs * (0.6 + mid_len / 2.0)) + Vector3(0, 2, 0), wall_rot, stone)
	var gate_c := wall_c + w * gate_along
	_box(Vector3(6.0, 4.0, 0.5), gate_c + w * (gs * (GATE_W / 2.0 + 3.0)) + Vector3(0, 2, 0), wall_rot, stone)

	# gate (moves up when the lever is pulled)
	gate = AnimatableBody3D.new()
	var gcs := CollisionShape3D.new()
	var gsh := BoxShape3D.new()
	gsh.size = Vector3(GATE_W, GATE_H, 0.2)
	gcs.shape = gsh
	gate.add_child(gcs)
	var gmi := MeshInstance3D.new()
	var gbm := BoxMesh.new()
	gbm.size = gsh.size
	var gmat := StandardMaterial3D.new()
	gmat.albedo_color = Color(0.3, 0.25, 0.15)
	gbm.material = gmat
	gmi.mesh = gbm
	gate.add_child(gmi)
	gate.position = Vector3(gate_c.x, FLOOR_Y + GATE_H / 2.0, gate_c.z)
	gate.rotation.y = wall_rot
	add_child(gate)

	# lever: base + handle, facing f
	_box(Vector3(0.4, 0.5, 0.3), LEVER + Vector3(0, 0.25, 0), deg_to_rad(LEVER_ROT_DEG), Color(0.2, 0.2, 0.22), false)
	_box(Vector3(0.08, 0.9, 0.08), LEVER + f * 0.2 + Vector3(0, 0.75, 0), deg_to_rad(LEVER_ROT_DEG), Color(0.6, 0.6, 0.65), false)
	# action point marker (flat disc of radius ACT_DIST) — visible aid, not in the game
	var disc := MeshInstance3D.new()
	var cyl := CylinderMesh.new()
	cyl.top_radius = ACT_DIST
	cyl.bottom_radius = ACT_DIST
	cyl.height = 0.01
	var dmat := StandardMaterial3D.new()
	dmat.albedo_color = Color(0.2, 0.6, 1.0, 0.35)
	dmat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	cyl.material = dmat
	disc.mesh = cyl
	disc.position = act_point() + Vector3(0, 0.02, 0)
	add_child(disc)

	# bonfire
	var bf := MeshInstance3D.new()
	var bcyl := CylinderMesh.new()
	bcyl.top_radius = 0.1
	bcyl.bottom_radius = 0.4
	bcyl.height = 0.6
	var bmat := StandardMaterial3D.new()
	bmat.albedo_color = Color(1.0, 0.5, 0.1)
	bmat.emission_enabled = true
	bmat.emission = Color(1.0, 0.4, 0.05)
	bcyl.material = bmat
	bf.mesh = bcyl
	bf.position = BONFIRE + Vector3(0, 0.3, 0)
	add_child(bf)


func act_point() -> Vector3:
	return LEVER + lever_basis * ACT_POINT_LOCAL


func _build_player() -> void:
	player = CharacterBody3D.new()
	var cs := CollisionShape3D.new()
	var cap := CapsuleShape3D.new()
	cap.radius = RADIUS
	cap.height = HEIGHT
	cs.shape = cap
	cs.position.y = HEIGHT / 2.0
	player.add_child(cs)
	var body := MeshInstance3D.new()
	var cm := CapsuleMesh.new()
	cm.radius = RADIUS
	cm.height = HEIGHT
	var pm := StandardMaterial3D.new()
	pm.albedo_color = Color(0.25, 0.3, 0.6)
	cm.material = pm
	body.mesh = cm
	body.position.y = HEIGHT / 2.0
	player.add_child(body)
	var nose := MeshInstance3D.new()          # shows the facing (-Z = forward)
	var nb := BoxMesh.new()
	nb.size = Vector3(0.15, 0.15, 0.5)
	var nm := StandardMaterial3D.new()
	nm.albedo_color = Color(1, 0.9, 0.2)
	nb.material = nm
	nose.mesh = nb
	nose.position = Vector3(0, 1.4, -0.35)
	player.add_child(nose)
	if ResourceLoader.exists(MODEL_PATH):
		var model: Node3D = load(MODEL_PATH).instantiate()
		model.rotation.y = PI                 # glTF faces +Z, the room's forward is -Z
		if MIRROR:
			# a right-handed model in DSR's left-handed numbers holds the sword on the game's left; mirrored here and
			# again by the picture, it is right-handed on screen and its weapon swings on DSR's side (foes: ramp.gd)
			model.scale = Vector3(-1, 1, 1)
		player.add_child(model)
		var aps := model.find_children("*", "AnimationPlayer", true, false)
		if aps.size() > 0:
			anim_player = aps[0]
			if ResourceLoader.exists(LIB2_PATH):
				var m2: Node = load(LIB2_PATH).instantiate()
				var ap2 := m2.find_children("*", "AnimationPlayer", true, false)
				if ap2.size() > 0:
					anim_player.add_animation_library("ual2", ap2[0].get_animation_library(""))
				m2.queue_free()
			body.visible = false
			nose.visible = false
			_attach_equipment(model)
	player.position = START
	player.rotation.y = heading
	add_child(player)
	cam = Camera3D.new()
	cam.fov = CAM_FOV
	if MIRROR:
		_build_mirror()
		mirror_view.add_child(cam)
	else:
		add_child(cam)
	cam.current = true


# The room keeps DSR's numbers (positions, headings, camera yaw — what the bot reads), but DSR is left-handed and Godot
# right-handed, so drawn as is the room is the game's mirror image (MoKa 11-09: "연습장은 좌측으로 올라가네"). The camera
# renders into a SubViewport (same World3D) and the picture is shown flipped left-right; the HUD stays unflipped.
func _build_mirror() -> void:
	mirror_view = SubViewport.new()
	mirror_view.size = get_viewport().get_visible_rect().size
	mirror_view.render_target_update_mode = SubViewport.UPDATE_ALWAYS
	add_child(mirror_view)
	var layer := CanvasLayer.new()
	layer.layer = -1
	add_child(layer)
	var tr := TextureRect.new()
	tr.texture = mirror_view.get_texture()
	tr.flip_h = true
	tr.set_anchors_preset(Control.PRESET_FULL_RECT)
	tr.stretch_mode = TextureRect.STRETCH_SCALE
	tr.expand_mode = TextureRect.EXPAND_IGNORE_SIZE
	layer.add_child(tr)
	get_viewport().size_changed.connect(func(): mirror_view.size = get_viewport().get_visible_rect().size)


func _attach_equipment(model: Node3D) -> void:
	var sks := model.find_children("*", "Skeleton3D", true, false)
	if sks.is_empty():
		return
	var sk: Skeleton3D = sks[0]
	# right: weapon -Y (blade) → hand +Z (forward in the rest pose), weapon X (blade width) → hand X
	if ResourceLoader.exists(RIGHT_GLB) or ResourceLoader.exists(CC0_RIGHT):
		var ba := BoneAttachment3D.new()
		ba.bone_name = "hand_r"
		sk.add_child(ba)
		if ResourceLoader.exists(RIGHT_GLB):
			weapon_node = load(RIGHT_GLB).instantiate()
		else:
			weapon_node = Node3D.new()
			var cc: Node3D = load(CC0_RIGHT).instantiate()
			var reach := 0.0
			for k in equip.get("right", {}).get("dummies", {}):
				var d: Array = equip["right"]["dummies"][k]
				reach = maxf(reach, Vector3(float(d[0]), float(d[1]), float(d[2])).length())   # 100 = tip, 1.28 m (WP_A_0266)
			var sc := (reach if reach > 0.0 else 1.3) / CC0_RIGHT_TIP
			cc.transform = Transform3D(Basis(Vector3(1, 0, 0), PI).scaled(Vector3(sc, sc, sc)), Vector3.ZERO)
			weapon_node.add_child(cc)
		weapon_node.transform = Transform3D(Basis(Vector3(1, 0, 0), Vector3(0, 0, -1), Vector3(0, 1, 0)), GRIP_R)
		ba.add_child(weapon_node)
	# left: shield front (+Z) → away from the palm (hand -X), shield X → along the arm (hand Y)
	if ResourceLoader.exists(LEFT_GLB) or ResourceLoader.exists(CC0_LEFT):
		var bl := BoneAttachment3D.new()
		bl.bone_name = "hand_l"
		sk.add_child(bl)
		var sh: Node3D
		if ResourceLoader.exists(LEFT_GLB):
			sh = load(LEFT_GLB).instantiate()
		else:
			sh = Node3D.new()
			var cs: Node3D = load(CC0_LEFT).instantiate()
			cs.scale = Vector3.ONE * (CC0_LEFT_D / 2.0)
			sh.add_child(cs)
		var b := Basis(Vector3(0, 0, -1), Vector3(0, 1, 0), Vector3(1, 0, 0))
		var grip := Vector3(0.0079, 0.0075, -0.1509)       # [game] WP_A_1521 dummy 100–130 (the handle)
		# MoKa 11-09 "방패 든 팔쪽이 뭔가 부자연 스러워": 예전 basis는 방패 뒷면(손잡이)이 바깥, 90° 누움 → 앞면 = 손 +X, 위 = 손 +Y;
		# 팔이 방패 앞으로 나와 보여 SHIELD_OUT 만큼 옮김 — 방향·크기는 렌더를 보고 맞춤 [guess]
		sh.transform = Transform3D(b, GRIP_L - b * grip + Vector3(SHIELD_OUT, 0, 0))
		bl.add_child(sh)


func _build_ui() -> void:
	var layer := CanvasLayer.new()
	add_child(layer)
	prompt_label = Label.new()
	prompt_label.add_theme_font_size_override("font_size", 28)
	prompt_label.anchor_left = 0.5
	prompt_label.anchor_right = 0.5
	prompt_label.anchor_top = 0.82
	prompt_label.position = Vector2(-120, 0)
	layer.add_child(prompt_label)
	info_label = Label.new()
	info_label.position = Vector2(12, 12)
	info_label.add_theme_font_size_override("font_size", 16)
	layer.add_child(info_label)


# ── Input ───────────────────────────────────────────────────────────────
func _read_input() -> Dictionary:
	while udp_in.get_available_packet_count() > 0:
		var pkt := udp_in.get_packet().get_string_from_utf8()
		var d = JSON.parse_string(pkt)
		if d is Dictionary:
			for k in d:
				net_in[k] = d[k]
			net_in_t = t
	if t - net_in_t < 0.5:
		return net_in.duplicate()
	# pads: take the device with the largest left stick (the bot's ViGEm pad or MoKa's)
	var best := {"lx": 0.0, "ly": 0.0, "rx": 0.0, "a": false, "b": false, "rb": false, "x": false, "r3": false, "slow": false, "ov": false}
	var best_m := -1.0
	for dev in Input.get_connected_joypads():
		var lx := Input.get_joy_axis(dev, JOY_AXIS_LEFT_X)
		var ly := -Input.get_joy_axis(dev, JOY_AXIS_LEFT_Y)    # up = forward
		var m := Vector2(lx, ly).length()
		if m > best_m or Input.is_joy_button_pressed(dev, JOY_BUTTON_A):
			best_m = m
			best = {"lx": lx, "ly": ly, "rx": Input.get_joy_axis(dev, JOY_AXIS_RIGHT_X),
				"a": Input.is_joy_button_pressed(dev, JOY_BUTTON_A), "b": Input.is_joy_button_pressed(dev, JOY_BUTTON_B),
				"rb": Input.is_joy_button_pressed(dev, JOY_BUTTON_RIGHT_SHOULDER), "x": Input.is_joy_button_pressed(dev, JOY_BUTTON_X),
				"r3": Input.is_joy_button_pressed(dev, JOY_BUTTON_RIGHT_STICK), "slow": false, "ov": false}
	# keyboard (MoKa trying it by hand): WASD move (Shift = walk), arrows camera, E = A
	var kx := float(Input.is_physical_key_pressed(KEY_D)) - float(Input.is_physical_key_pressed(KEY_A))
	var ky := float(Input.is_physical_key_pressed(KEY_W)) - float(Input.is_physical_key_pressed(KEY_S))
	if kx != 0.0 or ky != 0.0:
		var k := Vector2(kx, ky).normalized() * (0.55 if Input.is_physical_key_pressed(KEY_SHIFT) else 1.0)
		best["lx"] = k.x
		best["ly"] = k.y
	var kr := float(Input.is_physical_key_pressed(KEY_RIGHT)) - float(Input.is_physical_key_pressed(KEY_LEFT))
	if kr != 0.0:
		best["rx"] = kr
	if Input.is_physical_key_pressed(KEY_E):
		best["a"] = true
	if Input.is_physical_key_pressed(KEY_SPACE):
		best["b"] = true
	if Input.is_physical_key_pressed(KEY_J):
		best["rb"] = true
	if Input.is_physical_key_pressed(KEY_R):
		best["x"] = true
	if Input.is_physical_key_pressed(KEY_Q):
		best["r3"] = true
	if Input.is_physical_key_pressed(KEY_T):
		best["slow"] = true
	if Input.is_physical_key_pressed(KEY_F1):
		best["ov"] = true
	if MIRROR:
		# what MoKa sees is flipped, so a stick / key to the right must mean the picture's right; the bot's UDP input
		# above stays as is (it reads DSR's numbers, not the picture)
		best["lx"] = -float(best["lx"])
		best["rx"] = -float(best["rx"])
	return best


# ── Frame ───────────────────────────────────────────────────────────────
func _pressed(inp: Dictionary, k: String) -> bool:
	var now: bool = inp.get(k, false)
	var was: bool = btn_was.get(k, false)
	btn_was[k] = now
	return now and not was


func _in(wins: Array, at: float) -> bool:
	for w in wins:
		if at >= float(w[0]) and at < float(w[1]):
			return true
	return false


func _log(k: String, buffered: bool, accepted := true) -> void:
	log_ev.append({"k": k, "in": snappedf(t, 0.001), "buffered": buffered, "accepted": accepted, "exec": null})
	if log_ev.size() > 8:
		log_ev.pop_front()


func _log_exec(k: String) -> void:
	for i in range(log_ev.size() - 1, -1, -1):
		if log_ev[i]["k"] == k and log_ev[i]["accepted"] and log_ev[i]["exec"] == null:
			log_ev[i]["exec"] = snappedf(t, 0.001)
			return


func _target_angle() -> float:
	return atan2(dummy.position.x - player.position.x, dummy.position.z - player.position.z)


func _start(name: String, dir_angle: float) -> void:
	if not actions.has(name):
		return
	act_name = name
	act_t = 0.0
	act_dir = dir_angle
	anim = int(actions[name]["anim"])
	speed = 0.0
	hit_done = false
	prev_caps = []
	if anim_player:
		var a: Dictionary = actions[name]
		var clip := String(a["clip"]) if String(a["lib"]) == "" else "%s/%s" % [a["lib"], a["clip"]]
		if anim_player.has_animation(clip):
			var length := anim_player.get_animation(clip).length
			var until := float(a["clip_until"])
			if name == "backstep":
				anim_player.play_backwards(clip, 0.1)
			else:
				anim_player.play(clip, 0.1)
			anim_player.speed_scale = length / maxf(until, 0.1)
			loco_clip = ""


func _clip_rate() -> void:
	# Attack clips: two-segment time warp so the clip's blade-forward moment (clip_contact) lands in the middle of the
	# DSR attack window; frozen during hitstop. Other actions keep the one rate _start set.
	var a: Dictionary = actions.get(act_name, {})
	if anim_player == null or not a.has("clip_contact") or not a["attack"].size():
		return
	var clip := String(a["clip"]) if String(a["lib"]) == "" else "%s/%s" % [a["lib"], a["clip"]]
	if not anim_player.has_animation(clip):
		return
	var length := anim_player.get_animation(clip).length
	var c := float(a["clip_contact"]) * length
	var w: Array = a["attack"][0]
	var mid := (float(w[0]) + float(w[1])) / 2.0
	var until := maxf(float(a["clip_until"]), mid + 0.1)
	if hitstop > 0.0:
		anim_player.speed_scale = 0.0
	elif act_t < mid:
		anim_player.speed_scale = c / mid
	else:
		anim_player.speed_scale = (length - c) / (until - mid)


func _end_action() -> void:
	act_name = ""
	anim = -1
	queued.clear()
	prev_caps = []
	if anim_player:
		anim_player.speed_scale = 1.0


func _exec(kind: String, m: float, want: float) -> void:
	# Run a pressed (or buffered) input: roll / backstep for B, the next light attack for R.
	var prev := act_name
	_end_action()
	_log_exec(kind)
	if kind == "roll":
		if m >= DEAD:
			heading = wrapf(want - PI, -PI, PI)
			_start("roll", want)
		else:
			_start("backstep", heading)               # backward = facing + PI, facing = heading + PI
	elif kind == "r":
		if lock:
			heading = wrapf(_target_angle() - PI, -PI, PI)
		_start("light2" if prev == "light" else "light", heading + PI)


func _queue(kind: String) -> void:
	# A press during an action: kept if the action's DSR input window is open (or it has none — [guess]).
	var a: Dictionary = actions[act_name]
	var wins: Array = a["input_r"] if kind == "r" else a["input_roll"]
	var ok := wins.is_empty() or _in(wins, act_t)
	_log(kind, true, ok)
	if ok and not queued.has(kind):
		queued[kind] = t


func _physics_process(dt: float) -> void:
	t += dt
	var inp := _read_input()
	var lx: float = inp["lx"]
	var ly: float = inp["ly"]
	var m := minf(Vector2(lx, ly).length(), 1.0)
	var want := cam_actual_yaw() + atan2(lx, ly)      # world angle the stick points to (the camera as drawn, like DSR)

	if _pressed(inp, "slow"):
		slow = not slow
		Engine.time_scale = 0.25 if slow else 1.0
	if _pressed(inp, "ov"):
		overlay = not overlay
	if _pressed(inp, "r3"):
		lock = (not lock) and dummy_hp > 0 and player.position.distance_to(dummy.position) <= LOCK_RANGE
	if lock and (dummy_hp <= 0 or player.position.distance_to(dummy.position) > LOCK_RANGE):
		lock = false

	if lock:
		cam_yaw = wrapf(cam_yaw + wrapf(_target_angle() - cam_yaw, -PI, PI) * (1.0 - exp(-LOCK_CAM_TURN * dt)), -PI, PI)
	else:
		cam_yaw = wrapf(cam_yaw - float(inp["rx"]) * CAM_TURN * dt, -PI, PI)
	_check_prompt()

	# B: tap = roll (stick held) / backstep (no stick); hold = run
	var b: bool = inp["b"]
	var tap_b := false
	if b and b_down_t < 0.0:
		b_down_t = t
	elif not b and b_down_t >= 0.0:
		tap_b = t - b_down_t < B_TAP_S
		b_down_t = -1.0
	var running := b and b_down_t >= 0.0 and t - b_down_t >= B_TAP_S
	var pressed_a := _pressed(inp, "a")
	var pressed_rb := _pressed(inp, "rb")
	var pressed_x := _pressed(inp, "x")

	if hitstop > 0.0:
		hitstop -= dt
	if stagger > 0.0:
		stagger -= dt
		if pressed_rb or tap_b:
			_log("r" if pressed_rb else "roll", false, false)     # inputs during a hit reaction are dropped
	elif act_name != "":
		if pressed_rb:
			_queue("r")
		if tap_b:
			_queue("roll")
		if hitstop <= 0.0:
			act_t += dt
		_clip_rate()
		var a: Dictionary = actions[act_name]
		var cm = a["cancel_move"]
		var cr = a["cancel_r"]
		var cro = a["cancel_roll"]
		if queued.has("roll") and cro != null and act_t >= float(cro):
			_exec("roll", m, want)
		elif queued.has("r") and cr != null and act_t >= float(cr):
			_exec("r", m, want)
		elif act_t >= float(a["length"]):
			var nxt := "roll" if queued.has("roll") else ("r" if queued.has("r") else "")
			if nxt != "":
				_exec(nxt, m, want)
			else:
				_end_action()
		elif cm != null and act_t >= float(cm) and m >= DEAD and queued.is_empty():
			_end_action()
	else:
		if tap_b:
			_log("roll", false)
			_exec("roll", m, want)
		elif pressed_rb:
			_log("r", false)
			_exec("r", m, want)
		elif pressed_a and prompt:
			lever_pulled = true
			_start("lever", heading + PI)
		elif pressed_x:
			_start("estus", heading + PI)

	var target_v := 0.0
	var vel := Vector3.ZERO
	if stagger > 0.0:
		pass
	elif act_name != "":
		var a: Dictionary = actions[act_name]
		if not _in(a["no_turn"], act_t):              # DSR lets an action turn outside its "disable turning" window
			var aim := NAN
			if lock and not act_name.begins_with("roll") and act_name != "backstep":
				aim = _target_angle()
			elif m >= DEAD:
				aim = want
			if not is_nan(aim):
				var d0 := wrapf(aim - (heading + PI), -PI, PI)
				heading = wrapf(heading + clampf(d0, -TURN * dt, TURN * dt), -PI, PI)
		var dist := 0.0
		var dur := 1.0
		var dir := act_dir
		if act_name.begins_with("roll"):
			dist = ROLL_DIST
			dur = ROLL_MOVE_S
		elif act_name == "backstep":
			dist = BACKSTEP_DIST
			dur = BACKSTEP_MOVE_S
		if act_t < dur and dist > 0.0 and hitstop <= 0.0:
			vel = Vector3(sin(dir), 0, cos(dir)) * (dist / dur)
	elif m >= DEAD:
		target_v = V_RUN if running else (V_WALK if m < WALK_HI else V_JOG)
		var aim := _target_angle() if (lock and not running) else want      # locked on: face the target, strafe
		var d := wrapf(aim - (heading + PI), -PI, PI)
		heading = wrapf(heading + clampf(d, -TURN * dt, TURN * dt), -PI, PI)
	if act_name == "" and stagger <= 0.0:
		var tau := TAU_UP if target_v > speed else TAU_DOWN
		speed += (target_v - speed) * (1.0 - exp(-dt / tau))
		var move_angle := want if (lock and m >= DEAD and not running) else heading + PI
		if m < DEAD:
			move_angle = heading + PI if not lock else (speed_dir if speed_dir_set else heading + PI)
		else:
			speed_dir = move_angle
			speed_dir_set = true
		vel = Vector3(sin(move_angle), 0, cos(move_angle)) * speed
	player.velocity.x = vel.x
	player.velocity.z = vel.z
	player.velocity.y = 0.0 if player.is_on_floor() else player.velocity.y - 9.8 * dt
	player.rotation.y = heading
	player.move_and_slide()

	_weapon_hits()
	_dummy_step(dt)

	if lever_pulled and gate_open < 1.0:
		gate_open = minf(1.0, gate_open + dt / GATE_OPEN_S)
		gate.position.y = FLOOR_Y + GATE_H / 2.0 + gate_open * (GATE_H - 0.2)

	_animate()
	_update_camera(dt)
	_draw_debug()
	_send_state()
	prompt_label.text = "Ⓐ Pull lever" if prompt else ""
	var p := player.position
	var flags := ""
	if act_name != "":
		var a: Dictionary = actions[act_name]
		flags = "%s %d  t %.2f%s%s%s  queued %s" % [act_name, anim, act_t, "  INVINCIBLE" if _in(a["invincible"], act_t) else "",
			"  no-turn" if _in(a["no_turn"], act_t) else "", "  HIT" if _in(a["attack"], act_t) else "", queued.keys()]
	elif stagger > 0.0:
		flags = "STAGGER %.2f" % stagger
	var logs := ""
	for e in log_ev.slice(maxi(0, log_ev.size() - 4)):
		logs += "  %s in %.2f%s%s" % [e["k"], e["in"], " buf" if e["buffered"] else "", (" → %.2f" % e["exec"]) if e["exec"] != null else (" dropped" if not e["accepted"] else " …")]
	info_label.text = "pos %.2f %.2f %.2f  heading %.3f  cam_yaw %.3f  cam %.1f m\nbonfire-rel %.2f %.2f  prompt %s %s\nlever %s  gate %.0f%%   HP %d  dummy %d (%s)  lock %s  hits %d dodged %d%s\n%s\ninputs:%s" % [
		p.x, p.y, p.z, heading, cam_yaw, cam_dist, p.x - BONFIRE.x, p.z - BONFIRE.z, prompt, prompt_why, lever_pulled, gate_open * 100,
		player_hp, dummy_hp, dummy_phase, lock, player_hits, dodged, "  SLOW x0.25" if slow else "", flags, logs]


# ── Hits ────────────────────────────────────────────────────────────────
func _weapon_seg() -> Array:
	var f := Vector3(sin(heading + PI), 0, cos(heading + PI))
	var base := player.position + Vector3(0, 1.2, 0)
	return [base + f * WEAPON_IN, base + f * WEAPON_OUT]


func _dummy_axis() -> Array:
	return [dummy.position + Vector3(0, DUMMY_R, 0), dummy.position + Vector3(0, DUMMY_H - DUMMY_R, 0)]


func _seg_dist(a0: Vector3, a1: Vector3, b0: Vector3, b1: Vector3) -> float:
	var c := Geometry3D.get_closest_points_between_segments(a0, a1, b0, b1)
	return c[0].distance_to(c[1])


func _weapon_caps() -> Array:
	# This frame's hit capsules [[p0, p1, radius], …]: AtkParam_Pc Hitbox start/end model points = dummy ids on the
	# weapon model, placed by the weapon node (the hand bone of the playing clip). No model → the old fallback segment.
	var a: Dictionary = actions.get(act_name, {})
	if weapon_node == null or not a.has("hit") or not equip.has("right"):
		var w := _weapon_seg()
		return [[w[0], w[1], WEAPON_R]]
	var dm: Dictionary = equip["right"]["dummies"]
	var out := []
	var g := weapon_node.global_transform
	for hb in a["hit"]["hitboxes"]:
		var k0 := str(int(hb["from"]))
		var k1 := str(int(hb["to"]))
		if not dm.has(k0) or not dm.has(k1):
			continue
		var d0: Array = dm[k0]
		var d1: Array = dm[k1]
		out.append([g * Vector3(d0[0], d0[1], d0[2]), g * Vector3(d1[0], d1[1], d1[2]), float(hb["radius"])])
	return out


func _hit_damage() -> int:
	# [game] weapon base physical × the attack's physical % — before stat scaling, upgrades and the target's defense
	var a: Dictionary = actions.get(act_name, {})
	if a.has("hit") and equip.has("right"):
		return int(round(float(equip["right"]["base_physical"]) * float(a["hit"]["physical_pct"]) / 100.0))
	return 150


func _weapon_hits() -> void:
	# Swept melee check per capsule: this frame's, last frame's, and the trail between them (both ends and middle).
	if act_name == "" or not actions[act_name]["attack"].size() or not _in(actions[act_name]["attack"], act_t):
		prev_caps = []
		return
	var caps := _weapon_caps()
	var tests := []
	for i in caps.size():
		var c: Array = caps[i]
		tests.append(c)
		if prev_caps.size() == caps.size():
			var p: Array = prev_caps[i]
			tests.append([p[0], c[0], c[2]])
			tests.append([p[1], c[1], c[2]])
			tests.append([(p[0] + p[1]) / 2.0, (c[0] + c[1]) / 2.0, c[2]])
	prev_caps = caps
	if hit_done or dummy_hp <= 0:
		return
	var ax := _dummy_axis()
	for sg in tests:
		if _seg_dist(sg[0], sg[1], ax[0], ax[1]) <= float(sg[2]) + BODY_HIT_R:
			hit_done = true                                   # one hit per swing
			player_hits += 1
			dummy_hp = maxi(0, dummy_hp - _hit_damage())
			hitstop = float(actions[act_name].get("hit", {}).get("hitstop", 0.06))
			dummy_flash = 0.15
			if dummy_phase == "windup":                       # a hit interrupts its telegraphed swing [guess]
				dummy_phase = "recover"
				dummy_t = 0.0
			return


func _dummy_step(dt: float) -> void:
	# Training dummy: faces the player, and when close swings every DUMMY_EVERY s — windup (telegraph), active, recover.
	if dummy_flash > 0.0:
		dummy_flash -= dt
	dummy_mat.albedo_color = Color(1, 1, 1) if dummy_flash > 0.0 else (Color(0.3, 0.3, 0.3) if dummy_hp <= 0 else (
		Color(0.9, 0.6, 0.1) if dummy_phase == "windup" else (Color(0.9, 0.1, 0.1) if dummy_phase == "active" else Color(0.55, 0.35, 0.2))))
	if dummy_hp <= 0:
		dummy_phase = "dead"
		return
	var to_p := player.position - dummy.position
	var close := Vector2(to_p.x, to_p.z).length() <= DUMMY_REACH + DUMMY_HIT_R + 1.0
	if dummy_phase == "idle" or dummy_phase == "recover":
		dummy_heading = wrapf(atan2(-to_p.x, -to_p.z), -PI, PI)      # face the player (heading convention)
		dummy.rotation.y = dummy_heading
	dummy_t += dt
	match dummy_phase:
		"idle":
			if close and dummy_t >= DUMMY_EVERY:
				dummy_phase = "windup"
				dummy_t = 0.0
		"windup":
			dummy_arm.rotation.x = lerpf(0.0, 1.2, minf(dummy_t / DUMMY_WINDUP, 1.0))
			if dummy_t >= DUMMY_WINDUP:
				dummy_phase = "active"
				dummy_t = 0.0
				dummy_hit_done = false
		"active":
			dummy_arm.rotation.x = -0.6
			if not dummy_hit_done:
				var c := _dummy_hit_centre()
				var pax := [player.position + Vector3(0, RADIUS, 0), player.position + Vector3(0, HEIGHT - RADIUS, 0)]
				var near := Geometry3D.get_closest_point_to_segment(c, pax[0], pax[1])
				if near.distance_to(c) <= DUMMY_HIT_R + RADIUS:
					dummy_hit_done = true
					var inv := act_name != "" and _in(actions[act_name]["invincible"], act_t)
					if inv:
						dodged += 1
					else:
						player_hp = maxi(0, player_hp - DUMMY_DMG)
						_end_action()                         # a hit cleans up the action: no hitbox / i-frames / queue left
						stagger = STAGGER_S
						if anim_player and anim_player.has_animation("Hit_Chest"):
							anim_player.play("Hit_Chest", 0.05)
							loco_clip = ""
			if dummy_t >= DUMMY_ACTIVE:
				dummy_phase = "recover"
				dummy_t = 0.0
		"recover":
			dummy_arm.rotation.x = lerpf(-0.6, 0.0, minf(dummy_t / 0.6, 1.0))
			if dummy_t >= 0.6:
				dummy_phase = "idle"


func _dummy_hit_centre() -> Vector3:
	var f := Vector3(sin(dummy_heading + PI), 0, cos(dummy_heading + PI))
	return dummy.position + f * DUMMY_REACH + Vector3(0, 1.0, 0)


func _animate() -> void:
	if anim_player == null or act_name != "" or stagger > 0.0:
		return
	var clip := "Idle"
	var sc := 1.0
	if speed > 3.7:
		clip = "Sprint"
	elif speed > 2.0:
		clip = "Jog_Fwd"
		sc = speed / 3.42
	elif speed > 0.3:
		clip = "Walk"
		sc = speed / 1.64
	if clip != loco_clip or not anim_player.is_playing():
		anim_player.play(clip, 0.2)
		loco_clip = clip
	anim_player.speed_scale = sc


# ── Debug overlay (F1) ──────────────────────────────────────────────────
func _line(a: Vector3, b: Vector3, c: Color) -> void:
	dbg_mesh.surface_set_color(c)
	dbg_mesh.surface_add_vertex(a)
	dbg_mesh.surface_set_color(c)
	dbg_mesh.surface_add_vertex(b)


func _ring(c0: Vector3, r: float, col: Color) -> void:
	for i in 16:
		var a0 := TAU * i / 16.0
		var a1 := TAU * (i + 1) / 16.0
		_line(c0 + Vector3(cos(a0), 0, sin(a0)) * r, c0 + Vector3(cos(a1), 0, sin(a1)) * r, col)


func _draw_debug() -> void:
	dbg_mesh.clear_surfaces()
	if not overlay:
		return
	dbg_mesh.surface_begin(Mesh.PRIMITIVE_LINES)
	var inv := act_name != "" and _in(actions[act_name]["invincible"], act_t)
	var pc := Color(0.2, 1, 0.3) if inv else Color(0.2, 0.8, 1)
	_ring(player.position + Vector3(0, 0.05, 0), RADIUS, pc)
	_ring(player.position + Vector3(0, HEIGHT - 0.1, 0), RADIUS, pc)
	if act_name != "" and actions[act_name]["attack"].size():
		var col := Color(1, 0, 0) if _in(actions[act_name]["attack"], act_t) else Color(0.5, 0.5, 0.5)
		for c in _weapon_caps():
			_line(c[0], c[1], col)
			_ring(c[0], c[2], col)
			_ring(c[1], c[2], col)
	var ax := _dummy_axis()
	_line(ax[0], ax[1], Color(1, 1, 0))
	_ring(dummy.position + Vector3(0, 0.05, 0), DUMMY_R, Color(1, 1, 0))
	if dummy_phase == "windup" or dummy_phase == "active":
		var c := _dummy_hit_centre()
		var col := Color(1, 0, 0) if dummy_phase == "active" else Color(1, 0.6, 0)
		_ring(c, DUMMY_HIT_R, col)
		_ring(c + Vector3(0, -0.5, 0), DUMMY_HIT_R * 0.8, col)
	dbg_mesh.surface_end()


func _build_dummy() -> void:
	dummy = Node3D.new()
	dummy_mat = StandardMaterial3D.new()
	dummy_mat.albedo_color = Color(0.55, 0.35, 0.2)
	var mi := MeshInstance3D.new()
	var cm := CapsuleMesh.new()
	cm.radius = DUMMY_R
	cm.height = DUMMY_H
	cm.material = dummy_mat
	mi.mesh = cm
	mi.position.y = DUMMY_H / 2.0
	dummy.add_child(mi)
	dummy_arm = Node3D.new()
	dummy_arm.position = Vector3(0, 1.4, 0)
	var arm := MeshInstance3D.new()
	var ab := BoxMesh.new()
	ab.size = Vector3(0.12, 0.12, DUMMY_REACH)
	ab.material = dummy_mat
	arm.mesh = ab
	arm.position = Vector3(0, 0, -DUMMY_REACH / 2.0)
	dummy_arm.add_child(arm)
	dummy.add_child(dummy_arm)
	dummy_body = StaticBody3D.new()
	var cs := CollisionShape3D.new()
	var sh := CapsuleShape3D.new()
	sh.radius = DUMMY_R
	sh.height = DUMMY_H
	cs.shape = sh
	cs.position.y = DUMMY_H / 2.0
	dummy_body.add_child(cs)
	dummy.add_child(dummy_body)
	dummy.position = DUMMY_POS
	add_child(dummy)


func _build_debug() -> void:
	dbg_mesh = ImmediateMesh.new()
	var mi := MeshInstance3D.new()
	mi.mesh = dbg_mesh
	var mat := StandardMaterial3D.new()
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.vertex_color_use_as_albedo = true
	mat.no_depth_test = true
	mi.material_override = mat
	add_child(mi)


func _check_prompt() -> void:
	prompt = false
	if lever_pulled or act_name != "":
		prompt_why = "(pulled)" if lever_pulled else "(busy)"
		return
	var ap := act_point()
	var p := player.position
	var dist := Vector2(p.x - ap.x, p.z - ap.z).length()
	var face := heading + PI
	var to_ap := atan2(ap.x - p.x, ap.z - p.z)
	var pa := absf(rad_to_deg(wrapf(to_ap - face, -PI, PI)))
	var obj_ang := absf(rad_to_deg(wrapf(atan2(p.x - LEVER.x, p.z - LEVER.z) - deg_to_rad(LEVER_ROT_DEG), -PI, PI)))
	prompt = dist <= ACT_DIST and pa <= ACT_PLAYER_DEG and obj_ang <= ACT_OBJECT_DEG
	prompt_why = "d %.2f pa %.0f oa %.0f" % [dist, pa, obj_ang]


func _update_camera(dt: float) -> void:
	var fwd := Vector3(sin(cam_yaw), 0, cos(cam_yaw))
	var org := player.position + Vector3(0, CAM_ORG_Y, 0)
	var want := org - fwd * CAM_DIST * cos(CAM_PITCH) + Vector3(0, -sin(CAM_PITCH) * CAM_DIST, 0)
	# spring arm: a wall between the body and the wanted camera spot pulls the camera in (characters don't block it)
	var q := PhysicsRayQueryParameters3D.create(org, want)
	q.exclude = [player.get_rid(), dummy_body.get_rid()]
	var hit := get_world_3d().direct_space_state.intersect_ray(q)
	var blocked := false
	if hit:
		var hp: Vector3 = hit["position"]
		var back: Vector3 = (org - hp).normalized()
		want = hp + back * 0.2
		if org.distance_to(want) < CAM_MIN:
			want = org - (org - want).normalized() * CAM_MIN
		blocked = true
	var lerped := cam.position.lerp(want, 1.0 - exp(-CAM_FOLLOW * dt)) if t > 0.05 else want
	# never let the smoothing leave the camera behind the wall: snap in when the wall is closer than the smoothed spot
	if blocked and org.distance_to(lerped) > org.distance_to(want):
		lerped = want
	cam.position = lerped
	cam_dist = org.distance_to(cam.position)
	cam.look_at(org, Vector3.UP)


func cam_actual_yaw() -> float:
	var cf := -cam.global_transform.basis.z
	return atan2(cf.x, cf.z)


func _send_state() -> void:
	var p := player.position
	var d := {"t": t, "x": p.x, "y": p.y, "z": p.z, "heading": heading, "anim": anim, "speed": speed,
		"cam_yaw": cam_actual_yaw(), "prompt": prompt, "prompt_text": "Pull lever" if prompt else "",
		"prompt_why": prompt_why, "lever": lever_pulled, "gate_open": gate_open,
		"action": act_name, "anim_time": act_t if act_name != "" else null,
		"invincible": act_name != "" and _in(actions[act_name]["invincible"], act_t),
		"no_turn": act_name != "" and _in(actions[act_name]["no_turn"], act_t),
		"hitbox": act_name != "" and _in(actions[act_name]["attack"], act_t),
		"lock": lock, "hp": player_hp, "stagger": stagger > 0.0, "queued": queued.keys(), "log": log_ev,
		"cam_dist": cam_dist, "player_hits": player_hits, "dodged": dodged, "slow": slow,
		"dummy": {"x": dummy.position.x, "y": dummy.position.y, "z": dummy.position.z, "hp": dummy_hp, "phase": dummy_phase,
			"heading": dummy_heading}}
	udp_out.put_packet(JSON.stringify(d).to_utf8_buffer())
