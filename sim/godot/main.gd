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
const PULL_ANIM := 8000                             # [game] PlayerActionAnimation
const PULL_S := 2.0                                 # [guess] how long the pull locks the player
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
const CAM_PITCH := -0.25   # [guess] rad
const CAM_TURN := 2.5      # [guess] rad/s at full right stick
const CAM_FOLLOW := 8.0    # [guess] 1/s position smoothing

# ── Link ────────────────────────────────────────────────────────────────
const STATE_PORT := 47811  # state out (JSON per physics frame) → sim/godot_link.py
const INPUT_PORT := 47812  # UDP input in {"lx","ly","rx","a","b"} — headless tests without a pad

var player: CharacterBody3D
var cam: Camera3D
var gate: AnimatableBody3D
var prompt_label: Label
var info_label: Label
var lever_basis: Basis

var heading := START_HEADING
var speed := 0.0
var cam_yaw := 0.0
var anim := -1
var action_left := 0.0
var lever_pulled := false
var gate_open := 0.0          # 0 closed … 1 open
var prompt := false
var prompt_why := ""
var a_was_down := false
var t := 0.0

var udp_out := PacketPeerUDP.new()
var udp_in := PacketPeerUDP.new()
var net_in := {"lx": 0.0, "ly": 0.0, "rx": 0.0, "a": false, "b": false}
var net_in_t := -10.0


func _ready() -> void:
	lever_basis = Basis(Vector3.UP, deg_to_rad(LEVER_ROT_DEG))
	_build_world()
	_build_player()
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
	player.position = START
	player.rotation.y = heading
	add_child(player)
	cam = Camera3D.new()
	add_child(cam)
	cam.current = true


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
	var best := {"lx": 0.0, "ly": 0.0, "rx": 0.0, "a": false, "b": false}
	var best_m := -1.0
	for dev in Input.get_connected_joypads():
		var lx := Input.get_joy_axis(dev, JOY_AXIS_LEFT_X)
		var ly := -Input.get_joy_axis(dev, JOY_AXIS_LEFT_Y)    # up = forward
		var m := Vector2(lx, ly).length()
		if m > best_m or Input.is_joy_button_pressed(dev, JOY_BUTTON_A):
			best_m = m
			best = {"lx": lx, "ly": ly, "rx": Input.get_joy_axis(dev, JOY_AXIS_RIGHT_X),
				"a": Input.is_joy_button_pressed(dev, JOY_BUTTON_A), "b": Input.is_joy_button_pressed(dev, JOY_BUTTON_B)}
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
	return best


# ── Frame ───────────────────────────────────────────────────────────────
func _physics_process(dt: float) -> void:
	t += dt
	var inp := _read_input()
	var lx: float = inp["lx"]
	var ly: float = inp["ly"]
	var m := minf(Vector2(lx, ly).length(), 1.0)

	cam_yaw = wrapf(cam_yaw - float(inp["rx"]) * CAM_TURN * dt, -PI, PI)

	var target_v := 0.0
	if action_left > 0.0:
		action_left -= dt
		if action_left <= 0.0:
			anim = -1
	elif m >= DEAD:
		target_v = V_RUN if inp["b"] else (V_WALK if m < WALK_HI else V_JOG)
		var want := cam_actual_yaw() + atan2(lx, ly)           # world angle the stick points to (the camera as drawn, like DSR)
		var face := heading + PI                               # world angle the body faces
		var d := wrapf(want - face, -PI, PI)
		face += clampf(d, -TURN * dt, TURN * dt)
		heading = wrapf(face - PI, -PI, PI)
	var tau := TAU_UP if target_v > speed else TAU_DOWN
	speed += (target_v - speed) * (1.0 - exp(-dt / tau))
	var face_dir := Vector3(sin(heading + PI), 0, cos(heading + PI))
	player.velocity.x = face_dir.x * speed
	player.velocity.z = face_dir.z * speed
	player.velocity.y = 0.0 if player.is_on_floor() else player.velocity.y - 9.8 * dt
	player.rotation.y = heading
	player.move_and_slide()

	_check_prompt()
	var a_down: bool = inp["a"]
	if a_down and not a_was_down and prompt and action_left <= 0.0:
		lever_pulled = true
		anim = PULL_ANIM
		action_left = PULL_S
		speed = 0.0
	a_was_down = a_down
	if lever_pulled and gate_open < 1.0:
		gate_open = minf(1.0, gate_open + dt / GATE_OPEN_S)
		gate.position.y = FLOOR_Y + GATE_H / 2.0 + gate_open * (GATE_H - 0.2)

	_update_camera(dt)
	_send_state()
	prompt_label.text = "Ⓐ Pull lever" if prompt else ""
	var p := player.position
	info_label.text = "pos %.2f %.2f %.2f  heading %.3f  cam_yaw %.3f\nbonfire-rel %.2f %.2f  prompt %s %s\nlever %s  gate %.0f%%" % [
		p.x, p.y, p.z, heading, cam_yaw, p.x - BONFIRE.x, p.z - BONFIRE.z, prompt, prompt_why, lever_pulled, gate_open * 100]


func _check_prompt() -> void:
	prompt = false
	if lever_pulled:
		prompt_why = "(pulled)"
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
	cam.position = cam.position.lerp(want, 1.0 - exp(-CAM_FOLLOW * dt)) if t > 0.05 else want
	cam.look_at(org, Vector3.UP)


func cam_actual_yaw() -> float:
	var cf := -cam.global_transform.basis.z
	return atan2(cf.x, cf.z)


func _send_state() -> void:
	var p := player.position
	var d := {"t": t, "x": p.x, "y": p.y, "z": p.z, "heading": heading, "anim": anim, "speed": speed,
		"cam_yaw": cam_actual_yaw(), "prompt": prompt, "prompt_text": "Pull lever" if prompt else "",
		"prompt_why": prompt_why, "lever": lever_pulled, "gate_open": gate_open}
	udp_out.put_packet(JSON.stringify(d).to_utf8_buffer())
