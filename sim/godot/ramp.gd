extends "res://main.gd"
## Firelink ramp in the practice room (MoKa M1109-65): the six ramp foes on the real map, for the bot to play against.
##
## Built on main.gd (player movement, DSR action timings, light attack hit capsules, lock-on, camera, UDP link) — this
## script swaps the altar room for the ramp: map (assets/m10_02_00_00.glb, mirrored back to game coordinates),
## floor = the Firelink NavMesh (no other collision: off the NavMesh you fall), and six foes instead of the dummy.
## Data: assets/ramp_scene.json (sim/ramp_scene.py). Tags: [game] game files · [meas] measured on 11-09 · [guess].
##
## Foe behaviour, kept small and named:
##   wake      player within the foe's wake distance (#4: same level too) → it turns on for good
##   approach  walks / runs to the player along the bot's NavMesh graph (A*, re-planned every 0.5 s — MoKa M1109-66);
##             straight at the player only off the NavMesh [guess: DSR's own route choice isn't read]
##   attack    one of its TAE attacks by distance — lunges (3005 3006 3010) beyond 3 m, swings (3000 3003, 3001 after
##             3000) inside [meas: the distances the 11-09 runs started them at]; the hit is the AtkParam_Npc capsule
##             on the model's own weapon dummies inside the TAE window [game]; damage = AtkParam physical [game] —
##             matches the HP drops of the 11-09 Claymore run (#2 3005 210 vs −208, 3000 165 vs −160)
##   guard     after an attack, 40 % a 3500 shield stance for 1.0–1.6 s [meas: often seen; share is a guess];
##             the player's hits from the front are blocked [guess]
##   firebomb  #5 stays on its spot and throws (3008) every 3.6 s at the player's spot; it lands 2.5 s after the
##             throw starts: −109, −30 when the player guards [meas]
## Player additions: guard (LB / UDP "lb" / K key), stamina, Estus (X) heals at 1.0 s [guess], death.

const SCENE := "res://assets/ramp_scene.json"   # `-- --scene=arena` → assets/arena_scene.json (sim/arena_scene.py, M1109-75)
const MAP_GLB := "res://assets/m10_02_00_00.glb"
const SK_GLB := "D:/dev/tools/assets/sketchfab_ds_map/dark_souls_map.glb"   # RAMP_SK_COLLISION=1 (local only)
const CHR_MODELS_PATH := "../../data/gamefiles/chr_models.json"
const FOE_R := 0.4             # [guess] foe body capsule radius (hit test and collision)
const FOE_H := 1.7             # [guess]
const MAX_SP := 98.0           # [meas] END 14 (radar 11-09; 11-11 memory +0x3FC). Scene "player_max_sp" overrides (END table: PDF 8-7)
# ── 스태미나 (MoKa M1111-03/05, 11-11 타이타나이트 데몬 앞 실측) ──────────────────────
#  · 회복 초당 45 — 6종 무기·지구력 14/40 모두 같음 [meas]. 동작 중엔 안 참 (손 뗀 뒤 0.05~1.3 s 지나 오름 = 동작 끝)
#  · 공격 한 타 = 그 무기 BehaviorParam StaminaCost (actions.json hit.stamina) [game] — 실측 20·25·30·60과 같음
#  · 공격 스태미나는 누른 순간이 아니라 칼날 판정 즈음 빠짐 (롱소드: 0.4 s까지 98, 0.6 s 78, 맞은 때 0.57 s) [meas]
#  · 0보다 크면 공격·구르기가 나가고 0 아래로 내려감 (98→…→18→−2) [meas]
#  · 구르기 30 · 백스텝 20 [meas]. 방어구·무게 영향은 46%·23%에서 없음, 무거운 장비는 안 잼 (M1111-06, 향후 과제)
const SP_REGEN := 45.0         # [meas] per s
const SP_REGEN_GUARD := 15.0   # [guess]
const SP_COST := {"light": 25.0, "light2": 25.0, "roll": 30.0, "backstep": 20.0}   # roll/backstep [meas]; light = fallback only [guess]
const GUARD_COST := 30.0       # [guess] per blocked hit
const GUARD_DEG := 60.0        # [guess] half-angle the shield covers
const ESTUS := 10              # [meas] status 11-09
const ESTUS_HEAL := 350        # [meas] ≈ +346 seen 11-09 (capped at max HP)
const ESTUS_AT := 1.0          # [guess] s into the drink
const THINK_S := Vector2(0.3, 0.9)   # [guess] pause between a foe's actions
const LUNGE_M := 3.0           # [meas] lunges started at 3.5–5.7 m, swings at 0.85–2.5 m (11-09)
const ENGAGE_M := 6.0          # [meas] lunges started up to 5.7 m
const GUARD_SHARE := 0.4       # [guess]
# CC0 foe stand-in (MoKa M1110-10): when the DSR foe model (assets/c2540.glb …) is missing — a fresh clone / cloud — the foe is
# the Quaternius UAL body with a Quaternius Medieval Weapons sword / spear in hand_r. What stays DSR: the foe's timings
# (TAE windows, clip lengths from chr_models.json) and its hit capsule sizes: AtkParam_Npc radius, and the reach = the DSR
# dummy's distance along the weapon (c2540 dummy 11/20 0.56/0.64 m on R_Weapon) laid along the stand-in blade (hand_r +Z).
# The swing path is the UAL clip, time-warped so its blade-forward moment falls mid TAE window [stand-in].
const UAL_FOE := "res://assets/UAL1_Standard.glb"
const UAL_FOE2 := "res://assets/UAL2_Standard.glb"
const CC0_FOE_SWORD := ["res://assets/cc0/Sword.fbx", 4.63]    # blade +Y from the grip, tip y [import AABB]
const CC0_FOE_SPEAR := ["res://assets/cc0/Spear.fbx", 0.0]     # tip read at load (AABB)
const UAL_CLIPS := {"a00_0000": "Sword_Idle", "a00_0200": "Walk", "a00_0500": "Jog_Fwd", "attack": "ual2/Sword_Regular_A",
	"attack2": "ual2/Sword_Regular_B", "lunge": "ual2/Sword_Dash", "throw": "ual2/OverhandThrow", "guard": "ual2/Idle_Shield",
	"step": "Walk", "stagger": "Hit_Chest", "dead": "Death01"}
const UAL_CONTACT := {"ual2/Sword_Regular_A": 0.575, "ual2/Sword_Regular_B": 0.475, "ual2/Sword_Dash": 0.6}   # [stand-in] fraction
const FOE_STAGGER := "2005"    # [meas] the hit reaction seen after a Claymore light (2004–2006)

var sc := {}
var chr_models := {}
var foes := []                 # see _build_foes
var bombs := []                # {t, at: Vector3, from: Vector3, node}
var guard := false
var max_sp := MAX_SP
var sp := MAX_SP
var sp_due := {}               # attack stamina still to take: {"act": name, "at": s, "cost": SP} — taken at the blade window
var guard_breaks := 0          # blocked hits that emptied SP (arena, M1109-76)
var guard_blocks := 0          # player hits a foe's shield took (arena) — block rate = guard_blocks / player_hits
var turn_n := -1               # arena "turns": the foe whose turn it is to attack (MoKa 11-10)
var estus_left := ESTUS
var estus_done := false
var dead := false
var lock_foe := -1
var hit_set := {}              # foes this swing already hit
var rng := RandomNumberGenerator.new()
var centroids := []            # NavMesh triangle centroids (ramp_scene.json) — foe path waypoints
var ground_grid := {}          # Vector2i(1 m cell) → [[a, b, c], …] NavMesh triangles (+ #5's pad)
const WALL_LAYER := 2           # physics layer of the room's walls (player only)
const SAME_FLOOR_DY := 0.8     # [guess] above this height difference a foe keeps walking its route instead of
                               # swinging (6th room run: #6 swung 125 s from a ledge 1.5 m above the player)
const FOOT_R := 0.3            # [guess] how far from its centre a body still stands on an edge
const FALL_DEATH_S := 2.0      # [guess] in the air this long = fell to death (≈ 20 m)
const REPATH_S := 0.5          # [guess] how often a chasing foe re-plans its NavMesh route
const STEP_UP := 0.45          # [guess] highest step a body walks up


func _ready() -> void:
	var path := SCENE
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--scene="):
			path = "res://assets/%s_scene.json" % arg.substr(8)
	var f := FileAccess.open(path, FileAccess.READ)
	if f == null:
		push_error("%s missing — python sim/ramp_scene.py / sim/arena_scene.py" % path)
		return
	sc = JSON.parse_string(f.get_as_text())
	# 최대 스태미나: 장면 "player_max_sp" 또는 `-- --max-sp=160` (지구력 40, PDF 8-7) — 없으면 지구력 14의 98
	max_sp = float(sc.get("player_max_sp", MAX_SP))
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--max-sp="):
			max_sp = float(arg.substr(9))
	sp = max_sp
	var fm :=FileAccess.open(ProjectSettings.globalize_path("res://").path_join(CHR_MODELS_PATH), FileAccess.READ)
	if fm:
		chr_models = JSON.parse_string(fm.get_as_text())
	rng.seed = int(OS.get_environment("RAMP_SEED")) if OS.get_environment("RAMP_SEED") != "" else 1109
	super._ready()
	var s: Array = sc["start"]
	player.position = Vector3(s[0], s[1], s[2])
	heading = float(sc["start_heading"])
	player.rotation.y = heading
	cam_yaw = heading + PI
	for arg in OS.get_cmdline_user_args():
		if arg.begins_with("--shots="):
			_shots.call_deferred(arg.substr(8))
	player_hp = PLAYER_HP
	player.collision_mask = 1 | WALL_LAYER


# ── World ───────────────────────────────────────────────────────────────
func _build_world() -> void:
	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.55, 0.6, 0.68)
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(0.75, 0.75, 0.75)
	e.ambient_light_energy = 0.9
	env.environment = e
	add_child(env)
	var sun := DirectionalLight3D.new()
	sun.rotation = Vector3(deg_to_rad(-55), deg_to_rad(35), 0)
	# 그림자 (M1111-29, Perplexity 1단계): 4분할, 60 m 안만 — 계단 단·벽 모서리가 읽히게
	sun.shadow_enabled = true
	sun.directional_shadow_mode = DirectionalLight3D.SHADOW_PARALLEL_4_SPLITS
	sun.directional_shadow_max_distance = 60.0
	sun.shadow_bias = 0.03
	sun.shadow_normal_bias = 0.5
	add_child(sun)
	if sc.has("flat"):
		# the flat arena (M1109-75): a plain floor the size of its NavMesh square, a line every 2 m to read distances
		var hf := float(sc["flat"])
		var fl := MeshInstance3D.new()
		var pm := PlaneMesh.new()
		pm.size = Vector2(2.0 * hf, 2.0 * hf)
		var fm := StandardMaterial3D.new()
		fm.albedo_color = Color(0.42, 0.42, 0.4)
		pm.material = fm
		fl.mesh = pm
		add_child(fl)
		var gm := StandardMaterial3D.new()
		gm.albedo_color = Color(0.3, 0.3, 0.3)
		var x := -hf
		while x <= hf + 0.01:
			for horiz in [true, false]:
				var ln := MeshInstance3D.new()
				var bm := BoxMesh.new()
				bm.size = Vector3(2.0 * hf, 0.01, 0.03) if horiz else Vector3(0.03, 0.01, 2.0 * hf)
				bm.material = gm
				ln.mesh = bm
				ln.position = Vector3(0, 0.005, x) if horiz else Vector3(x, 0.005, 0)
				add_child(ln)
			x += 2.0
	elif ResourceLoader.exists(MAP_GLB) and not _natural_on():
		var m: Node3D = load(MAP_GLB).instantiate()
		m.scale = Vector3(-1, 1, 1)                 # the glb is mirrored (Godot x = −game x); the room is game coords
		add_child(m)
		# RAMP_MAP_COLLISION=1: the map's visual meshes as collision too — off by default: the first bot run (11-09
		# 17:43) stuck at the foot of the ramp steps (−29.4, −57.1, 45.2) for 5 min; visual steps are not the game's slope
		if OS.get_environment("RAMP_MAP_COLLISION") == "1":
			var mf := PackedVector3Array()
			for mi in m.find_children("*", "MeshInstance3D", true, false):
				var mesh: Mesh = (mi as MeshInstance3D).mesh
				if mesh == null:
					continue
				var g: Transform3D = (mi as Node3D).global_transform
				for v in mesh.get_faces():
					mf.append(g * v)
			if mf.size() > 0:
				var ms := ConcavePolygonShape3D.new()
				ms.set_faces(mf)
				ms.backface_collision = true
				var mb := StaticBody3D.new()
				var mcs := CollisionShape3D.new()
				mcs.shape = ms
				mb.add_child(mcs)
				add_child(mb)
				print("ramp: map collision %d triangles" % (mf.size() / 3))
	# floor: the NavMesh triangles as a height lookup, not as physics — the 4th room run (11-09 18:00) stuck 3 min at
	# (−24.9, −47.2, 29.5) where two NavMesh layers lie 0.2 m apart and the upper sheet's edge stopped the capsule like
	# a lip. Bodies stand on the highest triangle at most STEP_UP above their feet and fall when there is none (_ground)
	var nav: Dictionary = sc["nav"]
	var vs: Array = nav["v"]
	var ti := 0
	for tri in nav["t"]:
		var q := []
		for k in 3:
			var p: Array = vs[int(tri[k])]
			q.append(Vector3(p[0], p[1], p[2]))
		_grid_add(q[0], q[1], q[2], ti)
		ti += 1
	# floor patches (burg_scene.py floor_patches, M1111-32): strips along a recorded walk where the NavMesh has no floor
	for tri in sc.get("floor_patch", []):
		_grid_add(Vector3(tri[0][0], tri[0][1], tri[0][2]), Vector3(tri[1][0], tri[1][1], tri[1][2]),
			Vector3(tri[2][0], tri[2][1], tri[2][2]), -1)
	for c in sc.get("centroid", []):
		centroids.append(Vector3(c[0], c[1], c[2]))
	var faces := PackedVector3Array()
	# RAMP_SK_COLLISION=<glb> (or 1 = SK_GLB): the Sketchfab "Dark Souls Map" (9S, CC BY-NC, local only, MoKa M1111-21) —
	# made from the game's collision, so steps should be slopes, unlike the visual map (RAMP_MAP_COLLISION, stuck 11-09).
	# Its "Firelink Shrine" area replaces the NavMesh-edge walls, player only; the floor stays the NavMesh lookup.
	var sk := OS.get_environment("RAMP_SK_COLLISION")
	if sk == "" and sc.get("sk_walls", false):
		sk = "1"                              # scene asks for the Sketchfab walls (burg_scene.py, M1111-27)
	if sk == "0":
		sk = ""                               # RAMP_SK_COLLISION=0: off even when the scene asks
	var sk_area := String(sc.get("sk_area", "Firelink Shrine"))
	var sk_file := SK_GLB if sk == "" or sk == "1" else sk
	var sk_missing := sk != "" and not FileAccess.file_exists(sk_file)
	if sk_missing:
		# a fresh clone (cloud) has no Sketchfab file (local only on [win]) → the scene's NavMesh-edge walls instead
		# (sim/scene_walls.py `edge_walls`, same rule as ramp_scene.py's `walls`), not two engine errors and no walls
		print("ramp: Sketchfab walls asked but %s is not here — using the scene's edge_walls (%d)" % [sk_file, sc.get("edge_walls", []).size()])
		sk = ""
	var natural := _natural_on()
	var sk_all := PackedVector3Array() if sk == "" and not natural else _sk_faces(SK_GLB if sk == "" or sk == "1" else sk, sk_area)
	if sc.has("sk_cut") and sk_all.size() > 0:
		sk_all = _sk_cut(sk_all, sc["sk_cut"])
	var sk_faces := sk_all if sk != "" else PackedVector3Array()
	# RAMP_LOOK=natural (MoKa M1111-23): DSR 화면용 맵 대신 Sketchfab 지형 모양에 고도 노이즈 질감(바위·풀·흙)만 입힘
	if natural and sk_all.size() > 0:
		_natural_look(sk_all)
	# walls only: floors / ceilings (|normal.y| > 0.6) and low risers (top < 0.5 m above the NavMesh floor) are dropped —
	# with every face the first try (11-11) stuck at the ramp's foot (−29.7, −56.5, 43.6): the model has 0.2 m step
	# boards there next to a slope, and a 0.2 m riser stops the capsule like the visual map's steps did on 11-09
	var kept := 0
	var crossed := 0
	for k in range(0, sk_faces.size(), 3):
		var a: Vector3 = sk_faces[k]
		var b: Vector3 = sk_faces[k + 1]
		var c: Vector3 = sk_faces[k + 2]
		var nrm := (b - a).cross(c - a)
		if nrm.length() < 1e-6 or absf(nrm.normalized().y) > 0.6:
			continue
		var top := maxf(a.y, maxf(b.y, c.y))
		# 0.5 m보다 낮은 면(계단 디딤판 앞면·연석)은 높이와 상관없이 뺌 — 11-11 성벽 마을 통 굴리는 계단 아래
		# (53.5, 0.9, −114.3): NavMesh 밖으로 삐져나온 0.2 m 계단 앞면은 아래 NavMesh가 없어서 위 검사로 안 빠지고 캡슐을 막음
		if top - minf(a.y, minf(b.y, c.y)) < 0.5:
			continue
		var g := _ground(Vector3((a.x + b.x + c.x) / 3.0, top, (a.z + b.z + c.z) / 3.0), 0.0)
		if not is_nan(g) and top - g < 0.5:
			continue
		# NavMesh 바닥 위에 서 있는 면은 뺌: 게임 NavMesh는 진짜 벽에서 ~0.4 m 떨어져 끝나니(ramp_scene WALL_OUT), 면 발치
		# (무게중심·세 변 중점, 바닥 +0.3 m)에 NavMesh 바닥이 있으면 게임에선 지나다니는 자리. 11-11 성벽 마을 계단 아래
		# (52~55, 0.9, −116~−112): 높이 2 m·3.6×2.1 m 상자 모양 면을 NavMesh 경로가 관통 — 물체 충돌로 추정, 확인 안 함
		var bot := minf(a.y, minf(b.y, c.y))
		var on_floor := false
		for q in [(a + b + c) / 3.0, (a + b) * 0.5, (b + c) * 0.5, (c + a) * 0.5]:
			var g2 := _ground(Vector3(q.x, bot + 0.3, q.z), 0.6)
			if not is_nan(g2) and absf(g2 - bot) < 0.4:
				on_floor = true
				break
		if on_floor:
			crossed += 1
			continue
		faces.append_array(PackedVector3Array([a, b, c]))
		kept += 1
	if sk_faces.size() > 0:
		print("ramp: Sketchfab walls kept %d of %d triangles (%d dropped: standing on NavMesh floor)" % [kept, sk_faces.size() / 3, crossed])
		# 보기용: 실제로 막는 벽만 반투명으로 그림 (M1111-22 "나한테 보여 줘봐"); 자연 질감(RAMP_LOOK=natural)일 땐 안 그림
	if sk_faces.size() > 0 and not natural:
		var am := ArrayMesh.new()
		var arr := []
		arr.resize(Mesh.ARRAY_MAX)
		arr[Mesh.ARRAY_VERTEX] = faces
		am.add_surface_from_arrays(Mesh.PRIMITIVE_TRIANGLES, arr)
		var wm := StandardMaterial3D.new()
		wm.albedo_color = Color(0.45, 0.75, 1.0, 0.28)
		wm.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
		wm.cull_mode = BaseMaterial3D.CULL_DISABLED
		wm.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
		var wmi := MeshInstance3D.new()
		wmi.mesh = am
		wmi.material_override = wm
		add_child(wmi)
	# walls on open NavMesh edges with no floor beyond (sim/ramp_scene.py), 2.8 m high; edges with floor below stay open
	for w in ([] if sk_faces.size() > 0 else (sc.get("edge_walls", []) if sk_missing else sc.get("walls", []))):
		var a := Vector3(w[0], w[1] - 0.3, w[2])
		var b2 := Vector3(w[3], w[4] - 0.3, w[5])
		var up := Vector3(0, 2.8, 0)
		faces.append_array(PackedVector3Array([a, b2, b2 + up, a, b2 + up, a + up]))
	var shape := ConcavePolygonShape3D.new()
	shape.set_faces(faces)
	shape.backface_collision = true
	var sb := StaticBody3D.new()
	sb.collision_layer = WALL_LAYER          # walls stop the player only — foes walk NavMesh routes (MoKa M1109-66: #4
	sb.collision_mask = 0                    # stuck 0.3 m from its spot on a wall corner its centroid route cut)
	var cs := CollisionShape3D.new()
	cs.shape = shape
	sb.add_child(cs)
	add_child(sb)
	var b: Array = sc["bonfire"]
	var bf := MeshInstance3D.new()
	var cyl := CylinderMesh.new()
	cyl.top_radius = 0.1
	cyl.bottom_radius = 0.4
	cyl.height = 0.6
	var bmat := StandardMaterial3D.new()
	bmat.albedo_color = Color(1.0, 0.5, 0.1)
	bmat.emission_enabled = true
	bmat.emission = Color(1.0, 0.4, 0.05)
	cyl.material = bmat
	bf.mesh = cyl
	bf.position = Vector3(b[0], b[1] + 0.3, b[2])
	add_child(bf)
	# main.gd's altar objects aren't built; its code still touches gate / lever_basis
	gate = AnimatableBody3D.new()
	add_child(gate)
	_build_ladders()
	_build_elevators()


func _check_prompt() -> void:
	prompt = false
	prompt_why = ""


# ── Foes ────────────────────────────────────────────────────────────────
func _build_dummy() -> void:
	super._build_dummy()
	# the dummy stays as main.gd's lock-on proxy: invisible, no collision, moved onto the locked foe each frame
	dummy.visible = false
	dummy_body.collision_layer = 0
	dummy_body.collision_mask = 0
	dummy.position = Vector3(0, -500, 0)
	dummy_hp = 0
	_build_foes()


func _build_foes() -> void:
	var cols := [Color(0.85, 0.25, 0.2), Color(0.9, 0.45, 0.1)]
	for fd in sc["foes"]:
		var body := CharacterBody3D.new()
		var cs := CollisionShape3D.new()
		var cap := CapsuleShape3D.new()
		cap.radius = FOE_R
		cap.height = FOE_H
		cs.shape = cap
		cs.position.y = FOE_H / 2.0
		body.add_child(cs)
		var p: Array = fd["pos"]
		if not fd.get("floor", true):                   # no NavMesh under the spawn (#5) → a 3 m pad [guess size]
			var pad_body := _box(Vector3(3.0, 0.3, 3.0), Vector3(p[0], p[1] - 0.15, p[2]), 0.0, Color(0.45, 0.4, 0.35))
			(pad_body as StaticBody3D).collision_layer = WALL_LAYER
			var c0 := Vector3(p[0], p[1], p[2])
			_grid_add(c0 + Vector3(-1.5, 0, -1.5), c0 + Vector3(1.5, 0, -1.5), c0 + Vector3(1.5, 0, 1.5))
			_grid_add(c0 + Vector3(-1.5, 0, -1.5), c0 + Vector3(1.5, 0, 1.5), c0 + Vector3(-1.5, 0, 1.5))
		body.position = Vector3(p[0], p[1], p[2])
		body.rotation.y = float(fd["heading"])
		body.floor_snap_length = 0.6
		add_child(body)
		var model: String = fd["model"]
		var ual := false
		var ap: AnimationPlayer = null
		var sk: Skeleton3D = null
		if ResourceLoader.exists("res://assets/%s.glb" % model):
			var m: Node3D = load("res://assets/%s.glb" % model).instantiate()
			m.scale = Vector3(-1, 1, 1)             # mirrored glb back to game coordinates; faces −Z like the room
			body.add_child(m)
			var want: Array = fd["masks"].map(func(x): return int(x))
			for mi in m.find_children("*", "MeshInstance3D", true, false):
				var nm := String(mi.name)
				if nm.begins_with("mask"):
					mi.visible = nm.substr(4, 2).to_int() in want
			var aps := m.find_children("*", "AnimationPlayer", true, false)
			var sks := m.find_children("*", "Skeleton3D", true, false)
			ap = aps[0] if aps.size() > 0 else null
			sk = sks[0] if sks.size() > 0 else null
		elif ResourceLoader.exists(UAL_FOE):
			ual = true
			var m: Node3D = load(UAL_FOE).instantiate()
			m.rotation.y = PI                       # glTF faces +Z, the room's forward is −Z (as the player, main.gd)
			if MIRROR:
				m.scale = Vector3(-1, 1, 1)
			body.add_child(m)
			var aps := m.find_children("*", "AnimationPlayer", true, false)
			var sks := m.find_children("*", "Skeleton3D", true, false)
			ap = aps[0] if aps.size() > 0 else null
			sk = sks[0] if sks.size() > 0 else null
			if ap and ResourceLoader.exists(UAL_FOE2):
				var m2: Node = load(UAL_FOE2).instantiate()
				var ap2 := m2.find_children("*", "AnimationPlayer", true, false)
				if ap2.size() > 0:
					ap.add_animation_library("ual2", ap2[0].get_animation_library(""))
				m2.free()
			if sk:
				_ual_weapon(sk, _ual_reach(fd))
		var lbl := Label3D.new()
		lbl.billboard = BaseMaterial3D.BILLBOARD_ENABLED
		lbl.no_depth_test = true
		lbl.font_size = 26
		lbl.pixel_size = 0.004
		lbl.position.y = 2.1
		if MIRROR:
			lbl.scale = Vector3(-1, 1, 1)             # the picture is flipped (main.gd _build_mirror) — keep the text readable
		body.add_child(lbl)
		foes.append({"d": fd, "n": int(fd["n"]), "body": body, "ap": ap, "sk": sk, "label": lbl,
			"hp": int(fd["max_hp"]), "state": "idle", "t": 0.0, "anim": -1, "clip": "", "len": 0.0,
			"woke": false, "hit_done": false, "prev_caps": [], "wait": 0.0, "throw_t": 0.0,
			"sp": float(fd.get("max_sp", 0)), "swing_key": -1.0, "react_at": 0.0, "will_guard": false,
			"heading": float(fd["heading"]), "col": cols[0], "rm": 0.0, "path": [], "repath": 0.0, "air": 0.0,
			"ual": ual})


func _ual_reach(fd: Dictionary) -> float:
	# longest DSR weapon dummy offset this foe's attacks use (the blade tip's distance along the weapon bone) [game]
	var dm: Dictionary = chr_models.get(String(fd["model"]), {}).get("dummies", {})
	var r := 0.0
	for ws in fd["attacks"].values():
		for w in ws:
			for h in w.get("hit", []):
				for k in [str(int(h["from"])), str(int(h["to"]))]:
					if dm.has(k) and String(dm[k][0]["bone"]).to_lower().contains("weapon"):
						var o: Array = dm[k][0]["offset"]
						r = maxf(r, Vector3(o[0], o[1], o[2]).length())
	return r if r > 0.0 else 0.6


func _ual_weapon(sk: Skeleton3D, reach: float) -> void:
	# look only: a CC0 sword (spear past 1.2 m) on hand_r, blade (+Y) → hand +Z, tip at the DSR reach
	var w: Array = CC0_FOE_SPEAR if reach > 1.2 else CC0_FOE_SWORD
	if not ResourceLoader.exists(String(w[0])):
		return
	var ba := BoneAttachment3D.new()
	ba.bone_name = "hand_r"
	sk.add_child(ba)
	var mdl: Node3D = load(String(w[0])).instantiate()
	var tip := float(w[1])
	if tip <= 0.0:
		for mi in mdl.find_children("*", "MeshInstance3D", true, false):
			tip = maxf(tip, (mi as MeshInstance3D).get_aabb().end.y)
	var sc := reach / maxf(tip, 0.01)
	mdl.transform = Transform3D(Basis(Vector3(1, 0, 0), Vector3(0, 0, 1), Vector3(0, -1, 0)).scaled(Vector3.ONE * sc), Vector3.ZERO)
	ba.add_child(mdl)


func _ual_clip(fo: Dictionary, aid: int, state: String) -> String:
	if state == "attack":
		var lunges: Array = [3005, 3006, 3010]
		for x in fo["d"].get("lunge", []):
			lunges.append(int(x))
		if aid in lunges:
			return UAL_CLIPS["lunge"]
		return UAL_CLIPS["attack2"] if aid % 2 == 1 else UAL_CLIPS["attack"]
	return String(UAL_CLIPS.get(state, "Sword_Idle"))


func _clip_name(fo: Dictionary, aid: int) -> String:
	# the axe row plays the a01 set (TAE 3040–3044 are a01 only) [game]; otherwise a00
	var mdl: Dictionary = chr_models.get(String(fo["d"]["model"]), {})
	var anims: Dictionary = mdl.get("anims", {})
	var axe: bool = int(fo["d"]["npc"]) == 254001
	var a01 := "a01_%04d" % aid
	if axe and anims.has(a01):
		return a01
	return "a00_%04d" % aid


func _play(fo: Dictionary, aid: int, state: String) -> void:
	fo["state"] = state
	fo["holding"] = false
	fo["t"] = 0.0
	fo["anim"] = aid
	fo["hit_done"] = false
	fo["prev_caps"] = []
	var clip := _clip_name(fo, aid)
	var mdl: Dictionary = chr_models.get(String(fo["d"]["model"]), {})
	var ai: Dictionary = mdl.get("anims", {}).get(clip, {})
	fo["len"] = float(ai.get("duration", 1.5))
	var rme: Variant = ai.get("root_motion_end")
	fo["rm"] = maxf(0.0, -float(rme[2])) if rme is Array and state == "attack" else 0.0    # model faces −Z
	# steps (701 back, 702 / 703 sideways): the whole root motion, signed — x right, z back [game hkx; sign of x: guess]
	fo["rmv"] = Vector2(float(rme[0]), float(rme[2])) if rme is Array and state == "step" else Vector2.ZERO
	fo["clip"] = clip
	var ap: AnimationPlayer = fo["ap"]
	if fo.get("ual", false) and ap:
		var uc := _ual_clip(fo, aid, state)
		ap.speed_scale = 1.0
		var wins: Array = fo["d"]["attacks"].get(str(aid), [])
		if state == "attack" and UAL_CONTACT.has(uc) and wins.size() > 0 and ap.has_animation(uc):
			var mid := (float(wins[0]["start"]) + float(wins[0]["end"])) / 2.0
			ap.speed_scale = UAL_CONTACT[uc] * ap.get_animation(uc).length / maxf(mid, 0.05)
		if ap.has_animation(uc):
			ap.play(uc, 0.1)
		return
	if ap and ap.has_animation(clip):
		ap.play(clip, 0.1)


func _loop(fo: Dictionary, clip: String) -> void:
	var ap: AnimationPlayer = fo["ap"]
	if fo.get("ual", false):
		clip = String(UAL_CLIPS.get(clip, "Sword_Idle"))
		if ap:
			ap.speed_scale = 1.0
	if ap and ap.has_animation(clip) and ap.current_animation != clip:
		ap.play(clip, 0.15)
		ap.get_animation(clip).loop_mode = Animation.LOOP_LINEAR


func _foe_step(fo: Dictionary, dt: float) -> void:
	var body: CharacterBody3D = fo["body"]
	var fd: Dictionary = fo["d"]
	fo["t"] += dt
	var to_p := player.position - body.position
	var dist := Vector2(to_p.x, to_p.z).length()
	var face := atan2(to_p.x, to_p.z)               # world angle to the player
	var vel := Vector3.ZERO
	if fo["state"] == "dead":
		if body.position.y > float(fd["pos"][1]) - 40.0:
			_gravity(body, dt, Vector3.ZERO)
		return
	if not fo["woke"]:
		var lvl_ok: bool = not fd.has("same_level") or absf(to_p.y) < float(fd["same_level"])
		# arena: nobody wakes before the player moves off the start (1st/2nd arena run: both woke at 14 m while the bot was
		# still loading and killed the standing player; the pad's heartbeat arrives seconds before the bot plays)
		var ready := not sc.has("flat") or Vector2(player.position.x - float(sc["start"][0]),
				player.position.z - float(sc["start"][2])).length() > 0.5
		if dist <= float(fd["wake"]) and lvl_ok and not dead and ready:
			fo["woke"] = true
			fo["wait"] = rng.randf_range(THINK_S.x, THINK_S.y)
		_gravity(body, dt, Vector3.ZERO)
		return
	match fo["state"]:
		"idle", "move":
			_turn(fo, face, dt, 6.0)
			fo["wait"] = float(fo["wait"]) - dt
			fo["holding"] = false
			if dead:
				_loop(fo, "a00_0000")
				fo["anim"] = -1
			elif _aggro(fo, dist):
				pass
			elif not _turn_ok(fo):
				vel = _hold(fo, dist, face)
			elif fd.get("stay", false) and dist > 2.5:
				fo["anim"] = -1
				_loop(fo, "a00_0000")
				var th: Dictionary = fd["throw"]
				fo["throw_t"] = float(fo["throw_t"]) + dt
				if float(fo["throw_t"]) >= float(th["every"]) and dist <= float(fd["wake"]) + 2.0:
					fo["throw_t"] = 0.0
					_play(fo, 3008, "throw")
					bombs.append({"t": 0.0, "from": body.position + Vector3(0, 1.6, 0), "at": Vector3.INF, "node": null,
						"src": fo["n"]})
			elif (dist > float(fd.get("lunge_m", LUNGE_M)) and (dist > float(fd.get("engage_m", ENGAGE_M)) or float(fo["wait"]) > 0.0)) \
					or absf(to_p.y) > SAME_FLOOR_DY:
				# chase along the NavMesh (MoKa M1109-66): path every REPATH_S, walk at the next waypoint; off the
				# NavMesh (the player on #5's pad) or no route → straight at the player, stopping at a drop
				var v: float = float(sc["run_v"]) if dist > 4.0 else float(sc["walk_v"])
				fo["repath"] = float(fo["repath"]) - dt
				if float(fo["repath"]) <= 0.0:
					fo["repath"] = REPATH_S
					fo["path"] = _nav_path(body.position, player.position)
				var path: Array = fo["path"]
				while path.size() > 1 and Vector2(path[0].x - body.position.x, path[0].z - body.position.z).length() < 0.7:
					path.pop_front()
				var fwd := Vector3(sin(face), 0, cos(face))
				if path.size() > 0:
					var to_w: Vector3 = path[0] - body.position
					to_w.y = 0.0
					if to_w.length() > 0.05:
						fwd = to_w.normalized()
						_turn(fo, atan2(fwd.x, fwd.z), dt, 8.0)
					vel = fwd * v
				elif _floor_ahead(body.position, fwd):
					vel = fwd * v
				fo["anim"] = 2255                            # [meas] what the radar shows for a walking hollow
				_loop(fo, "a00_0500" if v > 2.0 else "a00_0200")
				fo["state"] = "move"
			elif float(fo["wait"]) <= 0.0:
				_play(fo, _pick_attack(fo, dist), "attack")
			else:
				fo["anim"] = -1
				_loop(fo, "a00_0000")
		"step":
			var rv: Vector2 = fo["rmv"]
			if float(fo["t"]) < float(fo["len"]) and rv != Vector2.ZERO:
				var hh := float(fo["heading"])
				var fw := Vector3(sin(hh + PI), 0, cos(hh + PI))
				var rt := Vector3(cos(hh), 0, -sin(hh))
				var dv := (rt * rv.x - fw * rv.y) / maxf(float(fo["len"]), 0.1)
				if _floor_ahead(body.position, dv.normalized()):
					vel = dv
			if float(fo["t"]) >= float(fo["len"]):
				fo["state"] = "idle"
				fo["wait"] = _think(fo) * 0.5
		"attack", "throw":
			if float(fo["t"]) < 0.4:
				_turn(fo, face, dt, 4.0)                    # [guess] tracking in the wind-up
			# the clip's root motion [game] (hkx, chr_models.json root_motion_end: 3006 lunge 6.8 m) spread evenly
			# over the clip [guess: the real curve isn't read]; stops at a drop
			var rm: float = float(fo["rm"])
			if rm > 0.0 and float(fo["t"]) < float(fo["len"]):
				var hf := float(fo["heading"]) + PI
				var fwd2 := Vector3(sin(hf), 0, cos(hf))
				if _floor_ahead(body.position, fwd2):
					vel = fwd2 * (rm / maxf(float(fo["len"]), 0.1))
			if fo["state"] == "attack":
				_foe_hits(fo)
			if float(fo["t"]) >= float(fo["len"]):
				var ap := fo["anim"] as int
				var nxt := int(fd.get("combo", {}).get(str(ap), 0))
				if fd.has("lunge"):
					# arena foes (M1109-75): a follow-up from the scene's combo table, else a step away, else the shield [guess shares]
					if nxt > 0 and dist < 3.0 and rng.randf() < float(fd["combo_share"]):
						_play(fo, nxt, "attack")
					elif not fd["steps"].is_empty() and rng.randf() < float(fd["step_after_attack"]):
						_play(fo, _step_id(fd), "step")
					elif int(fd["guard_clip"]) > 0 and rng.randf() < float(fd["guard_share"]):
						_play(fo, int(fd["guard_clip"]), "guard")
						fo["len"] = rng.randf_range(float(fd["guard_s"][0]), float(fd["guard_s"][1]))
					else:
						fo["state"] = "idle"
						fo["wait"] = _think(fo)
				elif ap == 3000 and dist < 2.5 and rng.randf() < 0.5:
					_play(fo, 3001, "attack")                # [meas] 3000 → 3001 seen back to back
				elif rng.randf() < GUARD_SHARE and not fd.get("stay", false):
					_play(fo, 3500, "guard")
					fo["len"] = rng.randf_range(1.0, 1.6)
				else:
					fo["state"] = "idle"
					fo["wait"] = rng.randf_range(THINK_S.x, THINK_S.y)
		"guard":
			_turn(fo, face, dt, 6.0)
			if fd.has("lunge") and dist > 2.0 and _turn_ok(fo):   # arena shield foe walks in behind its shield [guess]
				vel = Vector3(sin(face), 0, cos(face)) * float(sc["walk_v"])
			elif not _turn_ok(fo) and dist < float(sc["turns"]["hold_m"]) - 0.6:
				vel = -Vector3(sin(face), 0, cos(face)) * float(sc["walk_v"])   # not its turn: backs off behind the shield
			if float(fo["t"]) >= float(fo["len"]):
				fo["state"] = "idle"
				fo["wait"] = rng.randf_range(THINK_S.x, THINK_S.y)
		"stagger":
			if float(fo["t"]) >= float(fo["len"]):
				fo["state"] = "idle"
				fo["wait"] = rng.randf_range(THINK_S.x, THINK_S.y)
				# arena: 맞고 차례를 넘긴 놈은 백스텝으로 빠지고, 아니면 바로 방패 (MoKa 11-10) [guess]
				if bool(fo.get("retreat", false)) and not fd.get("steps", {}).is_empty():
					fo["retreat"] = false
					_play(fo, int(fd["steps"]["back"]), "step")
				elif int(fd.get("guard_clip", 0)) > 0 and rng.randf() < float(fd.get("guard_after_stagger", 0.0)):
					_play(fo, int(fd["guard_clip"]), "guard")
					fo["len"] = rng.randf_range(float(fd["guard_s"][0]), float(fd["guard_s"][1]))
	fo["air"] = 0.0 if _gravity(body, dt, vel) else float(fo["air"]) + dt
	# fell off (like #5 on 11-09): FALL_DEATH_S in the air. Not "15 m under the spawn" — that killed #4 and #6 walking
	# down the ramp after the bot (7th room run, 11-09 18:59)
	if float(fo["air"]) > FALL_DEATH_S and fo["hp"] > 0:
		fo["hp"] = 0
		_die(fo)


# ── 교대 공격 (MoKa 11-10 "하나가 hp줄면 뒤로 빠지고, 다음 몹이 뒤에 있다가, 교대로 들어 가잖아?") ─────────────────
#  scene "turns" (arena_scene.py TURNS) 있을 때만: 한 번에 한 놈이 공격 차례. 차례 놈이 죽거나 깨어 있지 않으면 가장 가까운
#  산 놈에게. 차례가 아닌 놈은 hold_m에서 방패 들고 대기 (_hold). 에스트 캐치는 _aggro에서 먼저 → 둘 다 달려듦.
func _turn_ok(fo: Dictionary) -> bool:
	if not sc.has("turns"):
		return true
	for f in foes:
		if int(f["n"]) == turn_n and int(f["hp"]) > 0 and bool(f["woke"]):
			return int(fo["n"]) == turn_n
	turn_n = _nearest_foe(-1)
	return int(fo["n"]) == turn_n


func _nearest_foe(skip: int) -> int:
	var best := -1
	var bd := INF
	for f in foes:
		if int(f["n"]) == skip or int(f["hp"]) <= 0 or not bool(f["woke"]):
			continue
		var d := ((f["body"] as Node3D).position - player.position).length()
		if d < bd:
			bd = d
			best = int(f["n"])
	return best


func _pass_turn(fo: Dictionary) -> void:
	var nx := _nearest_foe(int(fo["n"]))
	if nx >= 0:
		turn_n = nx


func _hold(fo: Dictionary, dist: float, face: float) -> Vector3:
	var tr: Dictionary = sc["turns"]
	var want := float(tr["hold_m"])
	var body: CharacterBody3D = fo["body"]
	if absf(dist - want) > 0.6:
		var dir := Vector3(sin(face), 0, cos(face)) * (1.0 if dist > want else -1.0)
		fo["anim"] = 2255
		_loop(fo, "a00_0500" if dist > want + 3.0 else "a00_0200")
		fo["state"] = "move"
		if _floor_ahead(body.position, dir):
			return dir * (float(sc["run_v"]) if dist > want + 3.0 else float(sc["walk_v"]))
		return Vector3.ZERO
	var gc := int(fo["d"].get("guard_clip", 0))
	if bool(tr.get("hold_guard", false)) and gc > 0:
		fo["holding"] = true                       # counts as a guard in _weapon_hits
		fo["anim"] = gc
		_loop(fo, "guard" if fo.get("ual", false) else _clip_name(fo, gc))
	else:
		fo["anim"] = -1
		_loop(fo, "a00_0000")
	fo["state"] = "idle"
	return Vector3.ZERO


func _think(fo: Dictionary) -> float:
	var ts: Array = fo["d"].get("think_s", [THINK_S.x, THINK_S.y])
	return rng.randf_range(float(ts[0]), float(ts[1]))


func _step_id(fd: Dictionary) -> int:
	var st: Dictionary = fd["steps"]
	if rng.randf() < 0.6:
		return int(st["back"])
	return int(st["left"] if rng.randf() < 0.5 else st["right"])


# Arena foes "attack well" (MoKa M1109-75) — switches from the scene file, each a [guess] of how a DSR foe presses:
#   punish_estus  the player starts an Estus sip within this many m → attack now (a lunge from afar) — MoKa M1109-71
#                 "에스트 캐치", seen from the graveyard skeletons 11-09 [meas]
#   steps         the player starts a swing within 3 m → sometimes a step back / sideways (its 701–703) instead of trading
#   punish_whiff  the player's swing is in its recovery and out of reach → no think pause before the next attack
# Returns true when it started something this frame.
func _aggro(fo: Dictionary, dist: float) -> bool:
	var fd: Dictionary = fo["d"]
	if not fd.has("lunge") or dead:
		return false
	if act_name == "estus" and act_t < 0.6 and dist <= float(fd["punish_estus"]):
		_play(fo, _pick_attack(fo, dist) if dist <= float(fd["lunge_m"]) else int(fd["lunge"][0]), "attack")
		return true
	var swinging := act_name.begins_with("light") or act_name.begins_with("heavy")
	# ── 내 휘두름을 보고 방패를 든다 (MoKa 11-09 "병사들이 왜 이렇게 못 막아? 방패 막는 타이밍 너무 않좋잖아") ──────────
	#  전엔 자기 공격 뒤에만 (guard_share) 또는 걸어 들어올 때만 들었다 — 내 칼을 보고 드는 일이 없었음.
	#  휘두를 때마다 한 번 정함: guard_vs_swing 확률로, 휘두름 시작 guard_react_s 뒤 방패 → 칼날 창 (클레이모어 0.67–0.80 s [game])
	#  끝 + 0.3 s까지 유지. 자기 공격·휘청 중엔 못 듦. 값은 [guess]
	if swinging and int(fd["guard_clip"]) > 0 and dist < float(fd.get("guard_react_m", 3.2)):
		var key := snappedf(t - act_t, 0.01)
		if absf(float(fo["swing_key"]) - key) > 0.05:
			fo["swing_key"] = key
			var rs: Array = fd.get("guard_react_s", [0.15, 0.3])
			fo["react_at"] = rng.randf_range(float(rs[0]), float(rs[1]))
			fo["will_guard"] = rng.randf() < float(fd.get("guard_vs_swing", 0.0)) and float(fo["sp"]) > 0.0
		if bool(fo["will_guard"]) and act_t >= float(fo["react_at"]):
			var win: Array = actions[act_name]["attack"]
			var until: float = (float(win[-1][1]) if not win.is_empty() else 1.0) + 0.3
			_play(fo, int(fd["guard_clip"]), "guard")
			fo["len"] = maxf(until - act_t, 0.4)
			fo["will_guard"] = false
			return true
	if swinging and act_t < 0.25 and dist < 3.0 and not fd["steps"].is_empty() and rng.randf() < float(fd["step_vs_swing"]) * 0.2:
		_play(fo, _step_id(fd), "step")
		return true
	if bool(fd["punish_whiff"]) and swinging and act_t > 0.6 and dist > 1.8 and dist < float(fd["engage_m"]):
		fo["wait"] = 0.0
	return false


func _grid_add(a: Vector3, b: Vector3, c: Vector3, idx := -1) -> void:
	var lo := Vector2i(floori(minf(a.x, minf(b.x, c.x))), floori(minf(a.z, minf(b.z, c.z))))
	var hi := Vector2i(floori(maxf(a.x, maxf(b.x, c.x))), floori(maxf(a.z, maxf(b.z, c.z))))
	for i in range(lo.x, hi.x + 1):
		for j in range(lo.y, hi.y + 1):
			var k := Vector2i(i, j)
			if not ground_grid.has(k):
				ground_grid[k] = []
			ground_grid[k].append([a, b, c, idx])


var shot_mode := false


func _update_camera(dt: float) -> void:
	if not shot_mode:
		super._update_camera(dt)
		_update_view(dt)


# ── Viewer camera (MoKa M1111-34) ─────────────────────────────────────────
# What the window shows: view_cam, driven by CamDirector (follow + sections + ladder side shot). The play camera `cam` keeps
# moving exactly as before and stays what cam_yaw / the bot's stick and the lock-on proxy read — it is only not drawn.
# `-- --cam=play` or F2 shows the play camera instead.
const VIEW_R := 0.25          # [guess] m sphere kept clear of walls around the viewer camera
const VIEW_MIN := 0.6         # [guess] closest it comes to the look point
const VIEW_RECOVER := 2.0     # [guess] 1/s the arm grows back after a wall pulled it in (≈ 0.5 s)
var view_cam: Camera3D
var director                  # cam_director.gd (preloaded: no class_name cache needed headless)
var view_on := true
var view_key := false
var view_arm := -1.0
var view_side := 0.0          # ladder shot side chosen at its start (1 / -1), 0 = not chosen
var view_info := {}
var view_shape := SphereShape3D.new()
const VIEW_FAN := [Vector2(0, 0), Vector2(0, 0.35), Vector2(0, 0.7), Vector2(0, 1.0), Vector2(0.5, 0), Vector2(-0.5, 0),
	Vector2(0.5, 0.35), Vector2(-0.5, 0.35), Vector2(1.0, 0.35), Vector2(-1.0, 0.35), Vector2(0.5, 0.7), Vector2(-0.5, 0.7)]
	# (swing rad around up, raise rad) tried when the arm is blocked [guess]
const VIEW_FAN_SLACK := 0.3   # [guess] m short of the full arm before the fan is tried
const VIEW_FAN_COST := 0.8    # [guess] m of clearance one radian of change must buy
const VIEW_FAN_RATE := 3.0    # [guess] 1/s toward the chosen direction
var view_fan := Vector2.ZERO
var view_snap_dir := ""
var view_snap_every := 4.0
var view_snap_next := 2.0


func _build_view() -> void:
	for arg in OS.get_cmdline_user_args():
		if arg == "--cam=play":
			view_on = false
		if arg.begins_with("--view-snaps="):
			var parts := arg.substr(13).split(",")
			view_snap_dir = parts[0]
			if parts.size() > 1:
				view_snap_every = float(parts[1])
	view_cam = Camera3D.new()
	view_cam.fov = CAM_FOV
	cam.get_parent().add_child(view_cam)
	director = preload("res://cam_director.gd").new()
	var L := []
	for i in sc.get("ladders", []).size():
		L.append(_ladder(i))
	director.setup(sc.get("cam_path", []), L, cam_yaw)
	view_shape.radius = VIEW_R
	(view_cam if view_on else cam).current = true


func _view_clear(org: Vector3, want: Vector3) -> float:
	# how far from org toward want a VIEW_R sphere gets before a wall (m); a start already inside a wall → VIEW_MIN
	var space := get_world_3d().direct_space_state
	var qp := PhysicsShapeQueryParameters3D.new()
	qp.shape = view_shape
	qp.collision_mask = 1 | WALL_LAYER
	qp.exclude = [player.get_rid()]
	qp.transform = Transform3D(Basis(), org)
	if not space.intersect_shape(qp, 1).is_empty():      # cast_motion ignores shapes the start already overlaps
		return VIEW_MIN
	qp.motion = want - org
	var r := space.cast_motion(qp)
	return maxf(VIEW_MIN, org.distance_to(want) * float(r[0]))


func _view_turn(dir: Vector3, o: Vector2) -> Vector3:
	# dir swung o.x rad around up and raised o.y rad (elevation capped below straight down-looking)
	var az := atan2(dir.x, dir.z) + o.x
	var el := clampf(asin(clampf(dir.y, -1.0, 1.0)) + o.y, -0.6, 1.35)
	return Vector3(cos(el) * sin(az), sin(el), cos(el) * cos(az))


func _update_view(dt: float) -> void:
	if director == null:
		_build_view()
	var f2 := Input.is_physical_key_pressed(KEY_F2)
	if f2 and not view_key:
		view_on = not view_on
		(view_cam if view_on else cam).current = true
	view_key = f2
	var w: Dictionary = director.step(dt, player.position, int(lad.get("i", -1)) if not lad.is_empty() else -1)
	var want: Vector3 = w["pos"]
	var look: Vector3 = w["look"]
	if w["mode"] == "ladder" and not w["blending"] and not (w["alt"] as Dictionary).is_empty():
		if view_side == 0.0:          # pick the side with more room once, then keep it (no flipping mid-climb)
			view_side = 1.0 if _view_clear(look, want) >= _view_clear(look, w["alt"]["pos"]) - 0.3 else -1.0
		if view_side < 0.0:
			want = w["alt"]["pos"]
	elif w["mode"] == "follow":
		view_side = 0.0
	var full := look.distance_to(want)
	var dir0 := (want - look).normalized() if full > 1e-3 else Vector3.BACK
	# blocked → fan of sphere casts (Uncharted 3: find free space): raise and/or swing the arm toward the most open direction,
	# moved there smoothly; back to (0, 0) once the wanted direction is clear again
	var fan_want := Vector2.ZERO
	if _view_clear(look, want) < full - VIEW_FAN_SLACK:
		var best := -INF
		for o in VIEW_FAN:
			var c := _view_clear(look, look + _view_turn(dir0, o) * full)
			var score := minf(c, full) - VIEW_FAN_COST * (absf(o.x) + absf(o.y))
			if score > best:
				best = score
				fan_want = o
	view_fan = view_fan.lerp(fan_want, 1.0 - exp(-VIEW_FAN_RATE * dt))
	var dir := _view_turn(dir0, view_fan)
	var clear := minf(full, _view_clear(look, look + dir * full))
	view_arm = clear if view_arm < 0.0 or clear < view_arm else lerpf(view_arm, clear, 1.0 - exp(-VIEW_RECOVER * dt))
	var pos := look + dir * view_arm
	view_cam.position = pos
	if pos.distance_to(look) > 1e-3 and absf(dir.y) < 0.999:
		view_cam.look_at(look, Vector3.UP)
	director.shown = {"pos": pos, "look": look}
	if view_snap_dir != "" and t >= view_snap_next and DisplayServer.get_name() != "headless":
		# `-- --view-snaps=<dir>[,<s>]`: what the window shows every <s> s (default 4) → <dir>/view_<t>.png (camera check)
		view_snap_next = t + view_snap_every
		var im := get_viewport().get_texture().get_image()
		im.save_png(view_snap_dir.path_join("view_%05.1f_%s.png" % [t, w["mode"] if w["mode"] == "ladder" else w["prof"]]))
	view_info = {"on": view_on, "mode": w["mode"], "prof": w["prof"], "idx": w["idx"], "pull": snappedf(full - view_arm, 0.01),
		"switches": director.switches}


func _shots(spec: String) -> void:
	# `-- --shots=<views.json>`: still pictures from fixed cameras, a contact sheet, then quit (M1111-29 계단 확인).
	# views.json = {"out": png, "views": [{"at": [x,y,z], "from": [x,y,z], "label": ""}…]}, game coordinates
	var d: Dictionary = JSON.parse_string(FileAccess.get_file_as_string(spec))
	shot_mode = true                       # _update_camera leaves the room camera alone
	cam.current = true
	info_label.visible = false
	cam.far = 500
	var sz := Vector2i(800, 500)
	var cols := 4
	var vs: Array = d["views"]
	var sheet := Image.create(sz.x * cols, sz.y * int(ceil(vs.size() / float(cols))), false, Image.FORMAT_RGBA8)
	get_window().size = sz
	for i in vs.size():
		var v: Dictionary = vs[i]
		var at := Vector3(v["at"][0], v["at"][1], v["at"][2])
		cam.position = Vector3(v["from"][0], v["from"][1], v["from"][2])
		cam.look_at(at, Vector3.UP)
		for _f in 4:
			await RenderingServer.frame_post_draw
		var im := get_viewport().get_texture().get_image()
		im.convert(Image.FORMAT_RGBA8)
		im.resize(sz.x, sz.y)
		sheet.blit_rect(im, Rect2i(Vector2i.ZERO, sz), Vector2i((i % cols) * sz.x, (i / cols) * sz.y))
	sheet.save_png(String(d["out"]))
	print("ramp: shots saved ", d["out"])
	get_tree().quit()


func _nav_under(p: Vector3) -> Vector2:
	# NavMesh under p.xz closest in height to p.y (within 1 m): (height, normal.y); (NAN, 0) when none
	var best := Vector2(NAN, 0.0)
	for tri in ground_grid.get(Vector2i(floori(p.x), floori(p.z)), []):
		var a: Vector3 = tri[0]
		var b: Vector3 = tri[1]
		var c: Vector3 = tri[2]
		var d := (b.z - c.z) * (a.x - c.x) + (c.x - b.x) * (a.z - c.z)
		if absf(d) < 1e-9:
			continue
		var l1 := ((b.z - c.z) * (p.x - c.x) + (c.x - b.x) * (p.z - c.z)) / d
		var l2 := ((c.z - a.z) * (p.x - c.x) + (a.x - c.x) * (p.z - c.z)) / d
		var l3 := 1.0 - l1 - l2
		if l1 < -1e-4 or l2 < -1e-4 or l3 < -1e-4:
			continue
		var h := l1 * a.y + l2 * b.y + l3 * c.y
		if absf(h - p.y) < 1.0 and (is_nan(best.x) or absf(h - p.y) < absf(best.x - p.y)):
			best = Vector2(h, absf((b - a).cross(c - a).normalized().y))
	return best


func _stair_mask(a: Vector3, b: Vector3, c: Vector3) -> float:
	# 계단 면 표시 (M1111-29): 그 자리 게임 NavMesh가 비탈(경사 > ~17°, 계단 = 0.4–0.7)이고 면이 그 NavMesh에 붙어 있으면 계단.
	# Sketchfab 경로 위 계단은 대부분 경사판(11-11 회색 확인) — 경사판·평평한 디딤판·0.5 m 안 앞면 모두 1. 손으로 그린 구역 없음
	var n := (b - a).cross(c - a)
	if n.length() < 1e-6:
		return 0.0
	var ny := absf(n.normalized().y)
	var cen := (a + b + c) / 3.0
	var top := maxf(a.y, maxf(b.y, c.y))
	var bot := minf(a.y, minf(b.y, c.y))
	var nav := _nav_under(Vector3(cen.x, cen.y, cen.z))
	if is_nan(nav.x) or nav.y > 0.955:          # no NavMesh or NavMesh flatter than ~17°
		return 0.0
	if absf(nav.x - cen.y) > 0.45:
		return 0.0
	if ny > 0.5 or top - bot < 0.5:             # slab / tread (sloped or flat) or a short riser
		return 1.0
	return 0.0


func _natural_on() -> bool:
	# 기본 = 자연 질감 (MoKa M1111-24 "자연 질감으로 기본으로 해"); RAMP_LOOK=dsr → 예전 DSR 화면 맵. Sketchfab 파일이 없으면
	# (클라우드·새 클론) 그릴 지형이 없으니 DSR 맵(있으면) 쪽으로
	return OS.get_environment("RAMP_LOOK") != "dsr" and FileAccess.file_exists(SK_GLB)


func _natural_look(tris: PackedVector3Array) -> void:
	# look only (no collision): the Sketchfab area with natural_ground.gdshader; the axis swap flips winding → b, c swapped
	var st := SurfaceTool.new()
	st.begin(Mesh.PRIMITIVE_TRIANGLES)
	st.set_smooth_group(-1)                  # 면마다 평평한 법선 — 기본(0)은 같은 자리 꼭짓점 법선을 섞어 계단 단을 뭉갬 (Perplexity 11-11)
	var stairs := 0
	for k in range(0, tris.size(), 3):
		var col := Color(_stair_mask(tris[k], tris[k + 1], tris[k + 2]), 0, 0, 1)
		stairs += int(col.r > 0.5)
		for q in [tris[k], tris[k + 2], tris[k + 1]]:
			st.set_color(col)
			st.add_vertex(q)
	st.generate_normals()
	if OS.get_environment("RAMP_LOOK") == "grey":
		# 진단용 (M1111-29, Perplexity 1단계): 질감 없는 회색 — 계단이 단인지 비탈인지 모양만 봄
		var gm := StandardMaterial3D.new()
		gm.albedo_color = Color(0.6, 0.6, 0.6)
		gm.roughness = 1.0
		gm.cull_mode = BaseMaterial3D.CULL_DISABLED
		var gmi := MeshInstance3D.new()
		gmi.mesh = st.commit()
		gmi.material_override = gm
		add_child(gmi)
		return
	var sm := ShaderMaterial.new()
	sm.shader = load("res://natural_ground.gdshader")
	var specs := {"noise_fine": [FastNoiseLite.TYPE_SIMPLEX_SMOOTH, 0.02, 5, false],
			"noise_large": [FastNoiseLite.TYPE_SIMPLEX_SMOOTH, 0.006, 3, false],
			"noise_cells": [FastNoiseLite.TYPE_CELLULAR, 0.03, 1, true]}
	for key in specs:
		var sp: Array = specs[key]
		var fn := FastNoiseLite.new()
		fn.noise_type = sp[0]
		fn.frequency = sp[1]
		fn.fractal_octaves = sp[2]
		if sp[3]:
			fn.cellular_return_type = FastNoiseLite.RETURN_DISTANCE2_SUB
		var nt := NoiseTexture2D.new()
		nt.width = 512
		nt.height = 512
		nt.seamless = true
		nt.noise = fn
		sm.set_shader_parameter(key, nt)
	var mi := MeshInstance3D.new()
	mi.mesh = st.commit()
	mi.material_override = sm
	add_child(mi)
	print("ramp: natural look on %d Sketchfab triangles, %d marked stairs" % [tris.size() / 3, stairs])


func _sk_cut(faces: PackedVector3Array, boxes: Array) -> PackedVector3Array:
	# scene "sk_cut": [[x0, y0, z0, x1, y1, z1], …] — Sketchfab triangles whose centre is inside a box are dropped from both the
	# walls and the look. For model parts that move in the game but are fixed in the model (the parish elevator car / its
	# door at the top, M1111-35: the room's own car replaces them)
	var out := PackedVector3Array()
	var cut := 0
	for k in range(0, faces.size(), 3):
		var m := (faces[k] + faces[k + 1] + faces[k + 2]) / 3.0
		var inside := false
		for bx in boxes:
			if m.x >= float(bx[0]) and m.y >= float(bx[1]) and m.z >= float(bx[2]) and m.x <= float(bx[3]) and m.y <= float(bx[4]) and m.z <= float(bx[5]):
				inside = true
				break
		if inside:
			cut += 1
		else:
			out.append_array(PackedVector3Array([faces[k], faces[k + 1], faces[k + 2]]))
	print("ramp: sk_cut dropped %d Sketchfab triangles" % cut)
	return out


func _sk_faces(file: String, area: String) -> PackedVector3Array:
	# one area of the Sketchfab map as triangles in room (= game) coordinates. Inside the area node the model's local
	# (a, b, c) = game (z, y, x), offset 0 (checked against the NavMesh 11-11, M1111-19); the nodes above it are ignored
	var out := PackedVector3Array()
	var doc := GLTFDocument.new()
	var st := GLTFState.new()
	if doc.append_from_file(file, st) != OK:
		push_error("ramp: Sketchfab map not loaded: " + file)
		return out
	var root := doc.generate_scene(st)
	var to_room := Transform3D(Basis(Vector3(0, 0, 1), Vector3(0, 1, 0), Vector3(1, 0, 0)), Vector3.ZERO)
	for one in area.split("|"):            # "Firelink Shrine|Undead Burg" — several areas, same game coordinates (M1111-31)
		var node := root.find_child(one, true, false) as Node3D
		if node == null:
			push_error("ramp: no area " + one)
			continue
		for mi in node.find_children("*", "MeshInstance3D", true, false):
			var mesh: Mesh = (mi as MeshInstance3D).mesh
			if mesh == null:
				continue
			# mesh → area node local: the transforms between them, without the area node's own (×1301 display scale)
			var t := Transform3D.IDENTITY
			var n: Node = mi
			while n != node:
				t = (n as Node3D).transform * t
				n = n.get_parent()
			var g := to_room * t
			for v in mesh.get_faces():
				out.append(g * v)
	root.free()
	print("ramp: Sketchfab collision %d triangles (%s)" % [out.size() / 3, area])
	return out


func _ground(p: Vector3, up: float = STEP_UP) -> float:
	# highest floor under p.xz that is at most `up` above p.y; NAN when none
	var best := NAN
	for tri in ground_grid.get(Vector2i(floori(p.x), floori(p.z)), []):
		var a: Vector3 = tri[0]
		var b: Vector3 = tri[1]
		var c: Vector3 = tri[2]
		var d := (b.z - c.z) * (a.x - c.x) + (c.x - b.x) * (a.z - c.z)
		if absf(d) < 1e-9:
			continue
		var l1 := ((b.z - c.z) * (p.x - c.x) + (c.x - b.x) * (p.z - c.z)) / d
		var l2 := ((c.z - a.z) * (p.x - c.x) + (a.x - c.x) * (p.z - c.z)) / d
		var l3 := 1.0 - l1 - l2
		if l1 < -1e-4 or l2 < -1e-4 or l3 < -1e-4:
			continue
		var h := l1 * a.y + l2 * b.y + l3 * c.y
		if h <= p.y + up and (is_nan(best) or h > best):
			best = h
	for e in elevs:                           # an elevator car is floor where it is now (M1111-35)
		var h2 := float(e["y"])
		if _on_car(e, p) and h2 <= p.y + up and (is_nan(best) or h2 > best):
			best = h2
	return best


func _tri_at(p: Vector3) -> int:
	# the NavMesh triangle the feet stand on: highest one at most 0.6 m above them, within 2 m below; −1 = none / the pad
	var best := -1
	var bh := -INF
	for tri in ground_grid.get(Vector2i(floori(p.x), floori(p.z)), []):
		var a: Vector3 = tri[0]
		var b: Vector3 = tri[1]
		var c: Vector3 = tri[2]
		var d := (b.z - c.z) * (a.x - c.x) + (c.x - b.x) * (a.z - c.z)
		if absf(d) < 1e-9:
			continue
		var l1 := ((b.z - c.z) * (p.x - c.x) + (c.x - b.x) * (p.z - c.z)) / d
		var l2 := ((c.z - a.z) * (p.x - c.x) + (a.x - c.x) * (p.z - c.z)) / d
		var l3 := 1.0 - l1 - l2
		if l1 < -1e-3 or l2 < -1e-3 or l3 < -1e-3:
			continue
		var h := l1 * a.y + l2 * b.y + l3 * c.y
		if h <= p.y + 0.6 and h >= p.y - 2.0 and h > bh and int(tri[3]) >= 0:
			bh = h
			best = int(tri[3])
	return best


func _nav_path(from: Vector3, to: Vector3) -> Array:
	# A* on the bot's NavMesh graph (ramp_scene.json "graph", navmesh.graph()) from the foe's triangle to the
	# player's → triangle centroids, then the player's spot. [] when either stands off the NavMesh or no route
	var s := _tri_at(from)
	var g := _tri_at(to)
	if s < 0 or g < 0 or centroids.is_empty():
		return []
	if s == g:
		return [to]
	var graph: Array = sc["graph"]
	var cost := {s: 0.0}
	var prev := {}
	var heap := [[centroids[s].distance_to(centroids[g]), s]]
	var done := {}
	while not heap.is_empty():
		var cur: int = _heap_pop(heap)[1]
		if cur == g:
			break
		if done.has(cur):
			continue
		done[cur] = true
		for e in graph[cur]:
			var nx := int(e[0])
			var nc: float = float(cost[cur]) + float(e[1])
			if nc < float(cost.get(nx, INF)):
				cost[nx] = nc
				prev[nx] = cur
				_heap_push(heap, [nc + centroids[nx].distance_to(centroids[g]), nx])
	if not prev.has(g):
		return []
	var seq := [g]
	while seq[-1] != s:
		seq.append(prev[seq[-1]])
	seq.reverse()
	var out := []
	for i in range(1, seq.size()):
		out.append(centroids[seq[i]])
	out.append(to)
	return out


func _heap_push(h: Array, item: Array) -> void:
	h.append(item)
	var i := h.size() - 1
	while i > 0:
		var p := (i - 1) / 2
		if float(h[p][0]) <= float(h[i][0]):
			break
		var tmp: Array = h[p]
		h[p] = h[i]
		h[i] = tmp
		i = p


func _heap_pop(h: Array) -> Array:
	var top: Array = h[0]
	var last: Array = h.pop_back()
	if h.size() > 0:
		h[0] = last
		var i := 0
		while true:
			var l := 2 * i + 1
			var r := l + 1
			var m := i
			if l < h.size() and float(h[l][0]) < float(h[m][0]):
				m = l
			if r < h.size() and float(h[r][0]) < float(h[m][0]):
				m = r
			if m == i:
				break
			var tmp: Array = h[m]
			h[m] = h[i]
			h[i] = tmp
			i = m
	return top


func _stand(body: CharacterBody3D) -> bool:
	# after move_and_slide: put the feet on the floor when they reached it (or are within STEP_UP below it)
	# a body has a radius: floor under any of five points within FOOT_R holds it (8th room run: #6 started a swing over
	# the gap between two NavMesh pieces and fell through)
	var h := NAN
	for o in [Vector3.ZERO, Vector3(FOOT_R, 0, 0), Vector3(-FOOT_R, 0, 0), Vector3(0, 0, FOOT_R), Vector3(0, 0, -FOOT_R)]:
		var hh := _ground(body.position + o)
		if not is_nan(hh) and (is_nan(h) or hh > h):
			h = hh
	if not is_nan(h) and body.position.y <= h + 0.08:
		body.position.y = h
		body.velocity.y = 0.0
		return true
	return false


func _gravity(body: CharacterBody3D, dt: float, vel: Vector3) -> bool:
	body.velocity.x = vel.x
	body.velocity.z = vel.z
	body.velocity.y -= 9.8 * dt
	body.move_and_slide()
	return _stand(body)


func _floor_ahead(pos: Vector3, fwd: Vector3) -> bool:
	var h := _ground(pos + fwd * 0.8)
	return not is_nan(h) and h > pos.y - 1.5


func _turn(fo: Dictionary, face: float, dt: float, rate: float) -> void:
	var want := wrapf(face - PI, -PI, PI)            # heading convention: facing = heading + PI
	var d := wrapf(want - float(fo["heading"]), -PI, PI)
	fo["heading"] = wrapf(float(fo["heading"]) + clampf(d, -rate * dt, rate * dt), -PI, PI)
	(fo["body"] as Node3D).rotation.y = fo["heading"]


func _pick_attack(fo: Dictionary, dist: float) -> int:
	var have: Dictionary = fo["d"]["attacks"]
	var lunge := [3005, 3006, 3010]
	var swing := [3000, 3003]
	if fo["d"].has("lunge"):                            # arena foes: the scene's lists (sim/arena_scene.py)
		var fd: Dictionary = fo["d"]
		var near: Array = fd["swing"]
		if not fd["long"].is_empty() and rng.randf() < float(fd["long_share"]):
			near = fd["long"]
		var pool2: Array = (fd["lunge"] if dist > float(fd["lunge_m"]) else near).filter(func(a): return have.has(str(int(a))))
		return int(pool2[rng.randi_range(0, pool2.size() - 1)]) if not pool2.is_empty() else int(fd["swing"][0])
	if int(fo["d"]["npc"]) == 255010:
		lunge = [3005]                                 # [meas] #2: 3005 at 2.4–4.6 m, 3000 / 3004 close
		swing = [3000, 3004]
	var pool := (lunge if dist > LUNGE_M else swing).filter(func(a): return have.has(str(a)))
	if pool.is_empty():
		pool = [3000]
	return int(pool[rng.randi_range(0, pool.size() - 1)])


func _foe_caps(fo: Dictionary) -> Array:
	# this frame's AtkParam_Npc capsules [[p0, p1, r, physical], …] while the clip time is inside a TAE window
	var out := []
	var sk: Skeleton3D = fo["sk"]
	if sk == null:
		return out
	var mdl: Dictionary = chr_models.get(String(fo["d"]["model"]), {})
	var dm: Dictionary = mdl.get("dummies", {})
	var wins: Array = fo["d"]["attacks"].get(str(int(fo["anim"])), [])
	var at: float = fo["t"]
	for w in wins:
		if at < float(w["start"]) or at > float(w["end"]) or not w.has("hit"):
			continue
		if sk.has_method("force_update_all_bone_transforms"):
			sk.force_update_all_bone_transforms()
		for h in w["hit"]:
			var p0: Variant = _dmy(sk, dm, str(int(h["from"])))
			var p1: Variant = _dmy(sk, dm, str(int(h["to"])))
			if p0 != null and p1 != null:
				out.append([p0, p1, float(h["radius"]), int(w.get("physical", 100)), float(w.get("stamina", -1.0))])
	return out


func _dmy(sk: Skeleton3D, dm: Dictionary, id: String):
	if not dm.has(id):
		return null
	var d: Dictionary = dm[id][0]
	if sk.find_bone(String(d["bone"])) < 0 and sk.find_bone("hand_r") >= 0:
		# UAL stand-in: a hand dummy = hand_r; a weapon dummy = its DSR distance along the blade (hand_r +Z) [stand-in path]
		var hb := sk.find_bone("hand_r")
		var o2: Array = d["offset"]
		var along := Vector3(0, 0, Vector3(o2[0], o2[1], o2[2]).length()) if String(d["bone"]).to_lower().contains("weapon") else Vector3.ZERO
		return sk.global_transform * (sk.get_bone_global_pose(hb) * along)
	var bi := sk.find_bone(String(d["bone"]))
	if bi < 0:
		return null
	var o: Array = d["offset"]
	return sk.global_transform * (sk.get_bone_global_pose(bi) * Vector3(o[0], o[1], o[2]))


func _foe_hits(fo: Dictionary) -> void:
	var caps := _foe_caps(fo)
	var tests := []
	var prev: Array = fo["prev_caps"]
	for i in caps.size():
		tests.append(caps[i])
		if prev.size() == caps.size():
			tests.append([prev[i][0], caps[i][0], caps[i][2], caps[i][3], caps[i][4]])
			tests.append([prev[i][1], caps[i][1], caps[i][2], caps[i][3], caps[i][4]])
	fo["prev_caps"] = caps
	if fo["hit_done"] or dead or tests.is_empty():
		return
	var pax := [player.position + Vector3(0, RADIUS, 0), player.position + Vector3(0, HEIGHT - RADIUS, 0)]
	for sg in tests:
		if _seg_dist(sg[0], sg[1], pax[0], pax[1]) <= float(sg[2]) + RADIUS:
			fo["hit_done"] = true
			var hp0 := player_hp
			_player_hit(int(sg[3]), (fo["body"] as Node3D).position, false, float(sg[4]))
			if player_hp < hp0 and anim == 2000:                 # a real hit (not blocked, not dodged)
				_hit_mark(sg[0], sg[1], pax[0], pax[1], RADIUS, _player_sk(), "me", hp0 - player_hp)
			return


func _player_hit(dmg: int, from: Vector3, bomb: bool, sp_hit: float = -1.0) -> void:
	if act_name != "" and _in(actions[act_name]["invincible"], act_t):
		dodged += 1
		return
	var to_src := atan2(from.x - player.position.x, from.z - player.position.z)
	var facing_src := absf(rad_to_deg(wrapf(to_src - (heading + PI), -PI, PI))) <= GUARD_DEG
	if guard and facing_src and act_name == "":
		if bomb:
			dmg = int(sc["foes"][4]["throw"]["dmg_guard"])
		else:
			# 막을 때 스태미나 = 그 공격의 StaminaAttackPower × (1 − 방패 안정성 / 100) [game 값, 공식은 guess], 방패를 넘어오는
			# 피해 = 피해 × (1 − 물리 컷 / 100) (나무 방패 88 %) [game 값, 공식 guess]. MoKa M1109-76: "큰 중갑 병사는 휘두르면
			# 방패로 막아도 스테미나가 다 달아서 2타 맞을 확률이 매우 높아" — 중기사 3000 80 → 45, 3001 140 → 78 (둘이면 98 을 넘음)
			# sp_hit < 0 (램프 방: 창에 stamina 없음) → 예전 그대로 고정 GUARD_COST, 관통 피해 없음
			var lf: Dictionary = equip.get("left", {})
			if sp_hit < 0.0:
				sp -= GUARD_COST
			else:
				sp -= sp_hit * (1.0 - float(lf.get("guard_stamina_defense", 0)) / 100.0)
				var chip := int(round(dmg * (1.0 - float(lf.get("physical_guard_pct", 100.0)) / 100.0)))
				player_hp = maxi(0, player_hp - chip)
				if player_hp <= 0:
					dead = true
			if sp > 0.0:
				return
			sp = 0.0
			guard_breaks += 1                                 # guard broken [guess]: long stagger, the next swing lands
			stagger = 1.2
			anim = 2000
			return
	player_hp = maxi(0, player_hp - dmg)
	_end_action()
	stagger = STAGGER_S
	anim = 2000
	if player_hp <= 0:
		dead = true


func _die(fo: Dictionary) -> void:
	_play(fo, 2205, "dead")
	(fo["body"] as CharacterBody3D).collision_layer = 0
	fo["anim"] = 2205


# ── Player hits on foes ─────────────────────────────────────────────────
func _weapon_hits() -> void:
	if act_name == "" or not actions[act_name]["attack"].size() or not _in(actions[act_name]["attack"], act_t):
		prev_caps = []
		hit_set.clear()
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
	for fo in foes:
		if fo["hp"] <= 0 or hit_set.has(fo["n"]):
			continue
		var bp: Vector3 = (fo["body"] as Node3D).position
		var ax := [bp + Vector3(0, FOE_R, 0), bp + Vector3(0, FOE_H - FOE_R, 0)]
		for sg in tests:
			if _seg_dist(sg[0], sg[1], ax[0], ax[1]) <= float(sg[2]) + BODY_HIT_R:
				hit_set[fo["n"]] = true                    # one hit per swing per foe; a swing can hit several
				player_hits += 1
				fo["woke"] = true
				var to_pl := atan2(player.position.x - bp.x, player.position.z - bp.z)
				var front := absf(rad_to_deg(wrapf(to_pl - (float(fo["heading"]) + PI), -PI, PI))) <= GUARD_DEG
				# 적 방어력 (arena 만): 피해 = a² / (a + 물리 방어) [NpcParam PhysicalDefense = game, 공식 guess] — 없으면 그대로
				var raw := _hit_damage()
				var pdef := float(fo["d"].get("phys_def", 0))
				var dmg := int(round(raw * raw / (raw + pdef))) if pdef > 0.0 else raw
				if (fo["state"] == "guard" or bool(fo.get("holding", false))) and front:
					hitstop = 0.12                          # [guess] shield bounce
					guard_blocks += 1
					# 막은 적의 기력 (arena: max_sp 있을 때): 막을 때마다 guard_sp_cost [guess], 0이면 가드 깨짐 → 휘청
					if float(fo["d"].get("max_sp", 0)) > 0.0:
						fo["sp"] = float(fo["sp"]) - float(fo["d"].get("guard_sp_cost", 40))
						if float(fo["sp"]) <= 0.0:
							fo["sp"] = 0.0
							_play(fo, int(FOE_STAGGER), "stagger")
							fo["len"] = maxf(float(fo["len"]), 1.2)
					var cut := float(fo["d"].get("guard_cut", 100))
					fo["hp"] = maxi(0, int(fo["hp"]) - int(round(dmg * (1.0 - cut / 100.0))))   # NpcParam PhysicalGuardCutRate [game]
					if fo["hp"] <= 0:
						_die(fo)
					break
				fo["hp"] = maxi(0, int(fo["hp"]) - dmg)
				_hit_mark(sg[0], sg[1], ax[0], ax[1], BODY_HIT_R, fo["sk"], "#%d" % int(fo["n"]), dmg)
				hitstop = float(actions[act_name].get("hit", {}).get("hitstop", 0.06))
				if fo["hp"] <= 0:
					_die(fo)
				else:
					if sc.has("turns") and int(fo["n"]) == turn_n and rng.randf() < float(sc["turns"]["back_on_hit"]):
						fo["retreat"] = true                # backs off after the stagger, the next foe comes in
						_pass_turn(fo)
					if rng.randf() < float(fo["d"].get("stagger_share", 1.0)):
						_play(fo, int(FOE_STAGGER), "stagger")
					elif bool(fo.get("retreat", false)) and not fo["d"].get("steps", {}).is_empty():
						fo["retreat"] = false
						_play(fo, int(fo["d"]["steps"]["back"]), "step")
				break


func _dummy_step(dt: float) -> void:
	for fo in foes:
		_foe_step(fo, dt)
		var lbl: Label3D = fo["label"]
		lbl.text = "#%d %s %d" % [fo["n"], fo["state"], fo["hp"]]
		lbl.visible = overlay
	_bombs_step(dt)


func _bombs_step(dt: float) -> void:
	if bombs.is_empty():
		return
	var th: Dictionary = sc["foes"][4]["throw"]
	for b in bombs.duplicate():
		b["t"] = float(b["t"]) + dt
		if b["at"] == Vector3.INF and float(b["t"]) >= 1.0:          # [guess] release 1.0 s in, aimed at the player then
			b["at"] = player.position
			var mi := MeshInstance3D.new()
			var sm := SphereMesh.new()
			sm.radius = 0.12
			sm.height = 0.24
			var m := StandardMaterial3D.new()
			m.albedo_color = Color(1.0, 0.5, 0.1)
			m.emission_enabled = true
			m.emission = Color(1.0, 0.4, 0.1)
			sm.material = m
			mi.mesh = sm
			add_child(mi)
			b["node"] = mi
		if b["node"] != null:
			var u := clampf((float(b["t"]) - 1.0) / (float(th["land"]) - 1.0), 0.0, 1.0)
			var at: Vector3 = b["at"]
			var from: Vector3 = b["from"]
			(b["node"] as Node3D).position = from.lerp(at, u) + Vector3(0, 4.0 * u * (1.0 - u), 0)
		if float(b["t"]) >= float(th["land"]):
			var at2: Vector3 = b["at"]
			if at2 != Vector3.INF and Vector2(player.position.x - at2.x, player.position.z - at2.z).length() <= float(th["radius"]) \
					and absf(player.position.y - at2.y) < 2.0 and not dead:
				_player_hit(int(th["dmg"]), b["from"], true)
			if b["node"] != null:
				(b["node"] as Node).queue_free()
			bombs.erase(b)


# ── Player additions ────────────────────────────────────────────────────
func _read_input() -> Dictionary:
	var r := super._read_input()
	var lb: bool = r.get("lb", false)
	if t - net_in_t >= 0.5:
		for dev in Input.get_connected_joypads():
			lb = lb or Input.is_joy_button_pressed(dev, JOY_BUTTON_LEFT_SHOULDER)
		lb = lb or Input.is_physical_key_pressed(KEY_K)
	guard = lb and not dead
	if dead:
		for k in ["lx", "ly", "a", "b", "rb", "x"]:
			r[k] = 0.0 if k in ["lx", "ly"] else false
	return r


func _start(name: String, dir_angle: float) -> void:
	if name == "estus":
		if estus_left <= 0:
			return
		estus_left -= 1
		estus_done = false
	var a: Dictionary = actions.get(name, {})
	var hit_sp := float((a.get("hit", {}) as Dictionary).get("stamina", -1.0)) if a.has("hit") else -1.0
	if hit_sp >= 0.0 or SP_COST.has(name):
		if sp <= 0.0:
			return
		if hit_sp >= 0.0 and a["attack"].size():
			sp_due = {"act": name, "at": float(a["attack"][0][0]), "cost": hit_sp}
		else:
			sp -= float(SP_COST[name]) if hit_sp < 0.0 else hit_sp
	super._start(name, dir_angle)


func _target_angle() -> float:
	if lock_foe >= 0:
		var bp: Vector3 = (foes[lock_foe]["body"] as Node3D).position
		return atan2(bp.x - player.position.x, bp.z - player.position.z)
	return super._target_angle()


func _physics_process(dt: float) -> void:
	if sc.is_empty():
		return
	if not lad.is_empty() or _ladder_try_mount():
		_ladder_frame(dt)
		return
	_marks_step(dt)
	_foe_sp_step(dt)
	# lock-on proxy: main.gd locks onto `dummy`. Not locked: keep it on the live foe in range nearest the camera's
	# centre, so R3 grabs that one (DSR: "R3 grabs the enemy nearest camera center" — souls/moves.py lock_target) [game rule,
	# the angle-only pick is a guess]
	var best := -1
	var bd := 1e9
	if lock and lock_foe >= 0 and foes[lock_foe]["hp"] > 0:
		best = lock_foe
	else:
		var cy := cam_actual_yaw()
		for i in foes.size():
			if foes[i]["hp"] <= 0:
				continue
			var fp: Vector3 = (foes[i]["body"] as Node3D).position
			if player.position.distance_to(fp) > LOCK_RANGE:
				continue
			var off := absf(wrapf(atan2(fp.x - player.position.x, fp.z - player.position.z) - cy, -PI, PI))
			if off < bd:
				bd = off
				best = i
	lock_foe = best
	if best >= 0:
		dummy.position = (foes[best]["body"] as Node3D).position
		dummy_hp = int(foes[best]["hp"])
	else:
		dummy.position = Vector3(0, -500, 0)
		dummy_hp = 0
	if not sp_due.is_empty():
		if act_name != String(sp_due["act"]):
			sp_due = {}            # cut before the blade (hit reaction, roll cancel) → not taken [guess]
		elif act_t >= float(sp_due["at"]):
			sp -= float(sp_due["cost"])
			sp_due = {}
	sp = minf(max_sp, sp + (SP_REGEN_GUARD if guard else SP_REGEN) * dt * (0.0 if act_name != "" else 1.0))
	if act_name == "estus" and not estus_done and act_t >= ESTUS_AT:
		estus_done = true
		player_hp = mini(PLAYER_HP, player_hp + ESTUS_HEAL)
	super._physics_process(dt)
	_stand(player)
	_elev_step(dt)
	if act_name == "" and stagger <= 0.0 and anim == 2000:
		anim = -1                                  # hit reaction over (main.gd only resets anim on its own actions)


# 가드 자세 (MoKa 11-09 "방패가 몸통 앞부분과 정렬이 되야 하는데 … 방패 든 팔쪽이 뭔가 부자연 스러워"): 전엔 가드해도
# 서기·걷기 클립 그대로라 방패가 허리 옆에 늘어져 있었다 (막기 판정은 몸 앞 GUARD_DEG 원뿔만 봄 — 방패 모델 위치와 무관).
# 이제 가드 중엔 Quaternius UAL2 Idle_Shield (왼팔을 몸 앞으로) — 모양만 [guess], DSR 가드 애니 아님. 걸으면서 막을 땐 미끄러지듯 보임
const GUARD_CLIP := "ual2/Idle_Shield"     # glb "Idle_Shield_Loop" — Godot drops the _Loop suffix on import


func _animate() -> void:
	if not lad.is_empty():
		return                                   # _ladder_pose drives the clip
	if guard and anim_player != null and act_name == "" and stagger <= 0.0 and anim_player.has_animation(GUARD_CLIP):
		if loco_clip != GUARD_CLIP or not anim_player.is_playing():
			anim_player.play(GUARD_CLIP, 0.12)
			loco_clip = GUARD_CLIP
		anim_player.speed_scale = 1.0
		return
	super._animate()


# ── 맞은 부위를 빨갛게 (MoKa M1109-78 "hit가 되면 그 부위가 red로 표시") ──────────────────────────────
#  맞은 자리 = 공격 캡슐과 몸 축 (세로 캡슐 [guess])의 가장 가까운 점을 몸 표면으로 옮긴 곳. 그 점에서 가장 가까운 뼈에 붙인
#  빨간 공 (HIT_MARK_S 동안 옅어짐) — 몸과 같이 움직임. 판정이 몸을 세로 캡슐 하나로 보니 "부위"는 그 점의 높이·방향이 정함
#  (DSR 부위 판정 아님). 막은 공격·회피는 표시 안 함. 마지막 표시는 state "hit_marks"에 (누가, 뼈, 피해)
const HIT_MARK_S := 0.8
const HIT_MARK_R := 0.12
var marks := []          # [node, ttl, material]
var hit_marks := []      # last few: [who, bone, dmg, t]
var _psk: Skeleton3D = null


func _player_sk() -> Skeleton3D:
	if _psk == null:
		var sks := player.find_children("*", "Skeleton3D", true, false)
		if not sks.is_empty():
			_psk = sks[0]
	return _psk


func _hit_mark(a0: Vector3, a1: Vector3, b0: Vector3, b1: Vector3, r: float, sk: Skeleton3D, who: String, dmg: int) -> void:
	var c := Geometry3D.get_closest_points_between_segments(a0, a1, b0, b1)
	var out: Vector3 = c[0] - c[1]
	var at: Vector3 = c[1] + (out.normalized() * r if out.length() > 0.01 else Vector3.ZERO)
	var parent: Node3D = self
	var bone := "-"
	if sk != null and sk.get_bone_count() > 0:
		var best := 1e9
		var bi := -1
		for i in sk.get_bone_count():
			var bn := sk.get_bone_name(i).to_lower()
			if "cloth" in bn or "armor" in bn or "dmy" in bn or "sfx" in bn:     # DSR cloth / armour plates — not a body part
				continue
			var d := (sk.global_transform * sk.get_bone_global_pose(i).origin).distance_to(at)
			if d < best:
				best = d
				bi = i
		bone = sk.get_bone_name(maxi(bi, 0))
		var ba := BoneAttachment3D.new()
		ba.bone_name = bone
		sk.add_child(ba)
		parent = ba
	var m := MeshInstance3D.new()
	var sm := SphereMesh.new()
	sm.radius = HIT_MARK_R
	sm.height = 2.0 * HIT_MARK_R
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(1, 0, 0, 0.85)
	mat.transparency = BaseMaterial3D.TRANSPARENCY_ALPHA
	mat.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	mat.no_depth_test = true                    # seen through the body / shield
	sm.material = mat
	m.mesh = sm
	parent.add_child(m)
	m.global_position = at
	marks.append([parent if parent != self else m, HIT_MARK_S, mat])
	hit_marks.append([who, bone, dmg, snappedf(t, 0.01)])
	if hit_marks.size() > 6:
		hit_marks.pop_front()


func _foe_sp_step(dt: float) -> void:
	for fo in foes:
		var mx := float(fo["d"].get("max_sp", 0))
		if mx > 0.0 and fo["state"] != "guard":
			fo["sp"] = minf(mx, float(fo["sp"]) + float(fo["d"].get("sp_regen", 30.0)) * dt)


func _marks_step(dt: float) -> void:
	for mk in marks.duplicate():
		mk[1] = float(mk[1]) - dt
		(mk[2] as StandardMaterial3D).albedo_color.a = clampf(float(mk[1]) / HIT_MARK_S, 0.0, 1.0) * 0.85
		if float(mk[1]) <= 0.0:
			(mk[0] as Node).queue_free()
			marks.erase(mk)


func _send_state() -> void:
	var p := player.position
	var fl := []
	for fo in foes:
		var bp: Vector3 = (fo["body"] as Node3D).position
		fl.append({"ptr": 1000 + int(fo["n"]), "n": fo["n"], "npc": int(fo["d"]["npc"]), "team": 6, "hp": fo["hp"],
			"max_hp": int(fo["d"]["max_hp"]), "x": bp.x, "y": bp.y, "z": bp.z, "heading": fo["heading"],
			"anim": fo["anim"], "anim_time": fo["t"], "state": fo["state"], "woke": fo["woke"], "sp": fo["sp"]})
	var d := {"t": t, "x": p.x, "y": p.y, "z": p.z, "heading": heading, "anim": anim, "speed": speed,
		"cam_yaw": cam_actual_yaw(), "action": act_name, "anim_time": act_t if act_name != "" else null,
		"invincible": act_name != "" and _in(actions[act_name]["invincible"], act_t),
		"lock": lock, "lock_ptr": (1000 + int(foes[lock_foe]["n"])) if (lock and lock_foe >= 0) else 0,
		"hp": player_hp, "max_hp": PLAYER_HP, "sp": sp, "max_sp": max_sp, "estus": estus_left, "guard": guard,
		"stagger": stagger > 0.0, "dead": dead, "player_hits": player_hits, "dodged": dodged, "guard_breaks": guard_breaks, "guard_blocks": guard_blocks, "turn": turn_n, "hit_marks": hit_marks, "foes": fl,
		"bombs": bombs.size(), "scene": sc.get("name", "ramp"), "ladder": String(lad.get("phase", "")), "view": view_info,
		"elevator": String(elevs[0]["state"]) if not elevs.is_empty() else ""}
	udp_out.put_packet(JSON.stringify(d).to_utf8_buffer())
	info_label.text = String(sc.get("name", "ramp")) + "  t %.1f  pos %.1f %.1f %.1f  HP %d  SP %d  estus %d  guard %s  lock #%s%s\n%s" % [t, p.x, p.y, p.z,
		player_hp, sp, estus_left, guard, str(foes[lock_foe]["n"]) if (lock and lock_foe >= 0) else "-",
		"  DEAD" if dead else "", ("%s %.2f" % [act_name, act_t]) if act_name != "" else (("ladder %s %d" % [lad["phase"], anim]) if not lad.is_empty() else "")]
	if not view_info.is_empty():
		info_label.text += "\ncam %s · %s%s  (F2)" % ["view" if view_on else "play", view_info["mode"] if view_info["mode"] == "ladder" else view_info["prof"],
			"" if view_info["idx"] >= 0 else " · off route"]


# ── 사다리 (MoKa M1111-30 "사다리도 만들고 캐릭터가 올라가고, 내려 가는것도 다크 소울과 유사한 메카니즘으로") ──────────
#  DSR 방식: 사다리 앞(아래) 또는 위 가장자리에서 사다리 쪽을 보고 A → 붙음 (아래 7010 / 위 7020). 붙은 뒤 스틱 위·아래로
#  한 칸씩 (7011·7012 / 7021·7022 번갈아), 스틱을 놓으면 그 자리에 매달려 있음, 꼭대기 근처에서 위로 밀면 올라섬 (7013),
#  바닥 근처에서 아래로 밀면 내려섬 (7023). 내려가는 중 B를 누르고 있으면 미끄러져 내려감. 매달린 동안 공격·구르기·에스트 없음.
#  숫자 = 실제 게임 녹화 트랙 (0.5 s 간격): 타우로스 사다리 오르기 10-11 174753 · 10-12 000026 / 000208, 성벽 마을 화톳불
#  사다리 내려가기·오르기 10-13 043024 · 181000. 애니 번호·길이는 c0000 TAE [game]. 몸 모양은 Quaternius ClimbUp_1m을 빌림 [stand-in]
#
#  ── 알려진 한계 ──────────────────────────────
#   · 한 칸 0.5 s·0.62 m는 0.5 s 간격 녹화에서 잰 평균 — TAE 7011 길이 1.17 s와 다름 (녹화 간격이 애니 전환을 다 못 봄) [meas]
#   · 미끄러져 내려가기 (7030, 4 m/s)는 녹화 없음 [guess]. 매달린 채 맞아서 떨어지기는 안 만듦
#   · 잡는 거리 0.9 m·각도 45°는 [guess] (봇은 35° 넘게 벗어나면 돌아선 뒤 A — souls/missions.py LADDER_FACE_DEG)
const LADDER_STEP_S := 0.5          # [meas] 7011↔7012 / 7021↔7022 every ~0.5 s
const LADDER_STEP_M := 0.62         # [meas] ~1.25 m/s up (16.35→23.35 in 5.6 s) and down
const LADDER_MOUNT_BOT_S := 0.5     # [meas] 7010 → first climb anim 0.5 s later, +0.5 m
const LADDER_MOUNT_BOT_DY := 0.5
const LADDER_MOUNT_TOP_S := 2.0     # [meas] 7020 → first down anim 2.0 s later, −2.0 m, body turned to face the ladder
const LADDER_MOUNT_TOP_DY := 2.0
const LADDER_EXIT_TOP_AT := 1.0     # [meas] 7013 starts ~1.0 m below the top floor
const LADDER_EXIT_TOP_S := 1.0      # [meas] 7013 → free 1.0–1.5 s
const LADDER_EXIT_TOP_FWD := 0.9    # [meas] ends ~0.9 m past the rung line, on the top floor
const LADDER_EXIT_BOT_AT := 0.4     # [meas] 7023 starts 0.1–0.4 m above the floor
const LADDER_EXIT_BOT_S := 1.0      # [meas] 7023 → free ~1.0 s
const LADDER_SLIDE_V := 4.0         # [guess] B held going down
const LADDER_SLIDE_ANIM := 7030     # [guess] TAE has 7030–7038; which one is the slide is not checked
const LADDER_GRAB_M := 0.9          # [guess]
const LADDER_GRAB_DEG := 45.0       # [guess]
const LADDER_TOP_OFF := 0.85        # [meas] top stand = rung line + face × 0.85 (10-13 Burg bonfire ladder)
const LADDER_PLANE := 0.35          # [guess] rails this far ahead of the climber's centre
const CLIMB_CLIP := "ual2/ClimbUp_1m"
var lad := {}                       # ladder in use: {"i", "phase", "pt", "from", "y0", "par"}


func _ladder(i: int) -> Dictionary:
	var L: Dictionary = sc["ladders"][i]
	var f := Vector3(float(L["face"][0]), 0, float(L["face"][1])).normalized()
	return {"at": Vector3(float(L["at"][0]), 0, float(L["at"][1])), "f": f, "bot": float(L["y_bot"]), "top": float(L["y_top"])}


func _build_ladders() -> void:
	if not sc.has("ladders"):
		return
	var wood := StandardMaterial3D.new()
	wood.albedo_color = Color(0.38, 0.27, 0.16)
	wood.roughness = 0.9
	for i in sc["ladders"].size():
		var L := _ladder(i)
		var f: Vector3 = L["f"]
		var right := Vector3(f.z, 0, -f.x)
		var base: Vector3 = L["at"] + f * LADDER_PLANE
		var y0: float = L["bot"]
		var y1: float = float(L["top"]) + 1.0          # rails stand up past the top floor as a handhold [guess]
		for sgn in [-1.0, 1.0]:
			var r := MeshInstance3D.new()
			var bm := BoxMesh.new()
			bm.size = Vector3(0.06, y1 - y0, 0.06)
			bm.material = wood
			r.mesh = bm
			add_child(r)
			r.position = base + right * 0.23 * sgn + Vector3(0, (y0 + y1) * 0.5, 0)
			r.rotation.y = atan2(f.x, f.z)
		var y := y0 + 0.3
		while y < float(L["top"]) + 0.2:
			var g := MeshInstance3D.new()
			var gm := BoxMesh.new()
			gm.size = Vector3(0.46, 0.04, 0.045)
			gm.material = wood
			g.mesh = gm
			add_child(g)
			g.position = base + Vector3(0, y, 0)
			g.rotation.y = atan2(f.x, f.z)
			y += 0.31                                     # two rungs per 0.62 m step [guess]
	print("ramp: %d ladders" % sc["ladders"].size())


func _ladder_try_mount() -> bool:
	if not sc.has("ladders") or act_name != "" or stagger > 0.0 or dead:
		return false
	var inp := _read_input()
	if not (bool(inp["a"]) and not btn_was.get("a", false)):
		return false
	var p := player.position
	var flat := Vector3(p.x, 0, p.z)
	var fw := Vector3(sin(heading + PI), 0, cos(heading + PI))
	for i in sc["ladders"].size():
		var L := _ladder(i)
		var f: Vector3 = L["f"]
		var at: Vector3 = L["at"]
		if flat.distance_to(at) < LADDER_GRAB_M and absf(p.y - float(L["bot"])) < 0.6 \
				and rad_to_deg(fw.angle_to(f)) < LADDER_GRAB_DEG:
			lad = {"i": i, "phase": "mount_bot", "pt": 0.0, "from": p, "y0": float(L["bot"]), "par": 0}
		elif flat.distance_to(at + f * LADDER_TOP_OFF) < LADDER_GRAB_M and absf(p.y - float(L["top"])) < 0.6 \
				and rad_to_deg(fw.angle_to(-f)) < LADDER_GRAB_DEG:
			lad = {"i": i, "phase": "mount_top", "pt": 0.0, "from": p, "y0": float(L["top"]), "par": 0}
		if not lad.is_empty():
			btn_was["a"] = true
			speed = 0.0
			lock = false
			print("ramp: ladder %d %s" % [i, lad["phase"]])
			return true
	return false


func _ladder_frame(dt: float) -> void:
	t += dt
	var inp := _read_input()
	btn_was["a"] = bool(inp["a"])
	cam_yaw = wrapf(cam_yaw - float(inp["rx"]) * CAM_TURN * dt, -PI, PI)
	var ly: float = inp["ly"]
	var b_held: bool = inp["b"]
	var L := _ladder(int(lad["i"]))
	var f: Vector3 = L["f"]
	var at: Vector3 = L["at"]
	var fr: Vector3 = lad["from"]
	var p := player.position
	lad["pt"] = float(lad["pt"]) + dt
	var k := 0.0
	match String(lad["phase"]):
		"mount_bot":
			anim = 7010
			k = minf(1.0, float(lad["pt"]) / LADDER_MOUNT_BOT_S)
			p = Vector3(lerpf(fr.x, at.x, k), float(lad["y0"]) + LADDER_MOUNT_BOT_DY * k, lerpf(fr.z, at.z, k))
			heading = atan2(f.x, f.z) - PI
			if k >= 1.0:
				_ladder_phase("on", p)
		"mount_top":
			anim = 7020
			k = minf(1.0, float(lad["pt"]) / LADDER_MOUNT_TOP_S)
			p = Vector3(lerpf(fr.x, at.x, k), float(lad["y0"]) - LADDER_MOUNT_TOP_DY * k, lerpf(fr.z, at.z, k))
			heading = lerp_angle(atan2(-f.x, -f.z) - PI, atan2(f.x, f.z) - PI, k)
			if k >= 1.0:
				_ladder_phase("on", p)
		"on":
			p = Vector3(at.x, p.y, at.z)
			if ly > 0.5:
				_ladder_phase("exit_top" if p.y >= float(L["top"]) - LADDER_EXIT_TOP_AT - 0.05 else "up", p)
			elif ly < -0.5:
				if b_held:
					_ladder_phase("slide", p)
				elif p.y - LADDER_STEP_M <= float(L["bot"]) + LADDER_EXIT_BOT_AT:
					_ladder_phase("exit_bot", p)
				else:
					_ladder_phase("down", p)
		"up", "down":
			var up := String(lad["phase"]) == "up"
			var even := int(lad["par"]) % 2 == 0
			anim = (7011 if even else 7012) if up else (7021 if even else 7022)
			k = minf(1.0, float(lad["pt"]) / LADDER_STEP_S)
			p.y = float(lad["y0"]) + (LADDER_STEP_M if up else -LADDER_STEP_M) * k
			if k >= 1.0:
				lad["par"] = int(lad["par"]) + 1
				_ladder_phase("on", p)
		"slide":
			anim = LADDER_SLIDE_ANIM
			p.y -= LADDER_SLIDE_V * dt
			if p.y <= float(L["bot"]) + LADDER_EXIT_BOT_AT:
				_ladder_phase("exit_bot", p)
			elif not b_held or ly > -0.5:
				_ladder_phase("on", p)
		"exit_top":
			anim = 7013
			k = minf(1.0, float(lad["pt"]) / LADDER_EXIT_TOP_S)
			var dst: Vector3 = at + f * LADDER_EXIT_TOP_FWD
			p = Vector3(lerpf(fr.x, dst.x, k), lerpf(fr.y, float(L["top"]), k), lerpf(fr.z, dst.z, k))
			if k >= 1.0:
				_ladder_off(p)
				return
		"exit_bot":
			anim = 7023
			k = minf(1.0, float(lad["pt"]) / LADDER_EXIT_BOT_S)
			p.y = lerpf(fr.y, float(L["bot"]), k)
			if k >= 1.0:
				_ladder_off(p)
				return
	player.position = p
	player.velocity = Vector3.ZERO
	player.rotation.y = heading
	_ladder_pose()
	_update_camera(dt)
	_draw_debug()
	_send_state()


func _ladder_phase(ph: String, p: Vector3) -> void:
	lad["phase"] = ph
	lad["pt"] = 0.0
	lad["from"] = p
	lad["y0"] = p.y


func _ladder_off(p: Vector3) -> void:
	player.position = p
	player.velocity = Vector3.ZERO
	print("ramp: ladder off at %.2f %.2f %.2f" % [p.x, p.y, p.z])
	lad = {}
	anim = -1
	speed = 0.0
	loco_clip = ""
	_stand(player)
	_send_state()


func _ladder_pose() -> void:
	# 모양만 [stand-in]: ClimbUp_1m 앞부분 (두 손을 위로 뻗은 자세)을 한 칸마다 앞뒤로, 올라서기 (7013)는 그 클립 끝까지
	if anim_player == null or not anim_player.has_animation(CLIMB_CLIP):
		return
	var length := anim_player.get_animation(CLIMB_CLIP).length
	if anim_player.current_animation != CLIMB_CLIP:
		anim_player.play(CLIMB_CLIP, 0.15)
		loco_clip = CLIMB_CLIP
	anim_player.speed_scale = 0.0
	var ph := String(lad["phase"])
	var pt := float(lad["pt"])
	var at := length * 0.10
	if ph == "up" or ph == "down":
		at = length * (0.10 + 0.10 * sin(PI * minf(1.0, pt / LADDER_STEP_S)))
	elif ph == "exit_top":
		at = length * lerpf(0.25, 1.0, minf(1.0, pt / LADDER_EXIT_TOP_S))
	elif ph == "mount_top":
		at = length * lerpf(0.9, 0.12, minf(1.0, pt / LADDER_MOUNT_TOP_S))
	elif ph == "exit_bot":
		at = length * 0.06
	anim_player.seek(at, true)


# ── 엘리베이터 (MoKa M1111-35 "데몬에서 엘리베이터 가서 타고 내려 와서 불의 제전으로") ──────────────────────────────
#  교구 → 불의 제전 엘리베이터. DSR: 바닥판에 올라서면 (발판 스위치) 잠깐 뒤 내려간다. 숫자 = 장면 "elevators"
#  (sim/burg_scene.py ELEVATORS, 11-11 탐색에서 잰 높이·가속·최고 속도 [meas], 대기·감속·바닥판 크기 [guess]).
#  바닥판은 그 순간의 높이에서 바닥이 된다 (_ground). 타고 있는 몸은 매 프레임 바닥판 높이로 옮긴다. 다시 올라가는 것,
#  반대편 칸, 위에서 부르는 스위치는 없다 — 내려가는 한 번만.
var elevs := []               # [{"d": row, "y", "v", "state": top | wait | down | bottom, "t", "node"}]


func _on_car(e: Dictionary, p: Vector3) -> bool:
	var d: Dictionary = e["d"]
	var hf := float(d["half"])
	return absf(p.x - float(d["at"][0])) <= hf and absf(p.z - float(d["at"][1])) <= hf


func _build_elevators() -> void:
	var metal := StandardMaterial3D.new()
	metal.albedo_color = Color(0.42, 0.4, 0.37)
	metal.roughness = 0.6
	metal.metallic = 0.4
	for d in sc.get("elevators", []):
		var hf := float(d["half"])
		var car := Node3D.new()
		var floor_m := MeshInstance3D.new()
		var bm := BoxMesh.new()
		bm.size = Vector3(hf * 2.0, 0.2, hf * 2.0)
		bm.material = metal
		floor_m.mesh = bm
		floor_m.position.y = -0.1
		car.add_child(floor_m)
		for k in 4:                            # corner posts so the car reads as a car [stand-in look]
			var post := MeshInstance3D.new()
			var pm := BoxMesh.new()
			pm.size = Vector3(0.12, 2.4, 0.12)
			pm.material = metal
			post.mesh = pm
			post.position = Vector3(hf * (1 if k % 2 == 0 else -1), 1.2, hf * (1 if k < 2 else -1))
			car.add_child(post)
		add_child(car)
		var y := float(d["y_top"])
		car.position = Vector3(float(d["at"][0]), y, float(d["at"][1]))
		elevs.append({"d": d, "y": y, "v": 0.0, "state": "top", "t": 0.0, "node": car})


func _elev_step(dt: float) -> void:
	for e in elevs:
		var d: Dictionary = e["d"]
		var y := float(e["y"])
		var riding := _on_car(e, player.position) and absf(player.position.y - y) < 0.3
		match String(e["state"]):
			"top":
				if riding:
					e["state"] = "wait"
					e["t"] = 0.0
			"wait":
				e["t"] = float(e["t"]) + dt
				if not riding:
					e["state"] = "top"
				elif float(e["t"]) >= float(d["wait"]):
					e["state"] = "down"
					print("ramp: elevator %s down" % d["name"])
			"down":
				var v := float(e["v"])
				var left := y - float(d["y_bot"])
				if v * v / (2.0 * float(d["decel"])) >= left:
					v = maxf(0.4, v - float(d["decel"]) * dt)
				else:
					v = minf(float(d["v_max"]), v + float(d["accel"]) * dt)
				y = maxf(float(d["y_bot"]), y - v * dt)
				e["v"] = v
				if y <= float(d["y_bot"]):
					e["state"] = "bottom"
					e["v"] = 0.0
					print("ramp: elevator %s bottom" % d["name"])
		e["y"] = y
		(e["node"] as Node3D).position.y = y
		if riding:
			player.position.y = y
			player.velocity.y = 0.0
