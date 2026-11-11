extends Node3D
## Sketchfab "Dark Souls Map" (9S, CC BY-NC, local only — D:/dev/tools/assets/sketchfab_ds_map) with the bot's walked path
## on top (MoKa M1111-19/20). Alignment, checked against the game NavMesh 11-11: inside each area node (child of RootNode)
## the model's local (a, b, c) = DSR (z, y, x), offset 0 — so the area node gets a fixed rotation and every node above it
## identity. Godot position = (−x, y, z) of a DSR position, as in replay.gd.
##
## Keys: mouse drag orbit · wheel zoom · W/A/S/D move the focus · Q/E focus down/up · 1–9 jump to a mark · T top view
## Godot args after "--":  --glb=<file>  --path=<json>  --shot=<png>  (--shot renders a few views and quits)

const DEFAULT_GLB := "D:/dev/tools/assets/sketchfab_ds_map/dark_souls_map.glb"
const DEFAULT_PATH := "../../data/replays/20261111_explore_path.json"
const SEG_COLORS := [Color(1, 0.2, 0.2), Color(1, 0.6, 0.1), Color(1, 0.95, 0.2), Color(0.3, 1, 0.3), Color(0.2, 0.8, 1),
		Color(0.9, 0.3, 1), Color(1, 1, 1)]

var cam: Camera3D
var focus := Vector3.ZERO
var yaw := 0.6
var pitch := -0.7
var dist := 60.0
var marks: Array = []
var dragging := false


func _g(p: Array) -> Vector3:
	return Vector3(-float(p[0]), float(p[1]), float(p[2]))


func _ready() -> void:
	var args := {}
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		args[kv[0]] = kv[1] if kv.size() > 1 else ""
	_load_map(String(args.get("glb", DEFAULT_GLB)))
	_load_path(String(args.get("path", ProjectSettings.globalize_path("res://").path_join(DEFAULT_PATH))))
	var sun := DirectionalLight3D.new()
	sun.rotation = Vector3(-1.0, 0.7, 0)
	sun.light_energy = 1.1
	add_child(sun)
	var env := WorldEnvironment.new()
	env.environment = Environment.new()
	env.environment.background_mode = Environment.BG_COLOR
	env.environment.background_color = Color(0.12, 0.13, 0.16)
	env.environment.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	env.environment.ambient_light_color = Color(0.55, 0.55, 0.6)
	add_child(env)
	cam = Camera3D.new()
	cam.far = 4000
	add_child(cam)
	if marks.size() > 0:
		focus = marks[0][1]
	_place_cam()
	if args.has("shot"):
		await _shots(String(args["shot"]))
		get_tree().quit()


func _load_map(file: String) -> void:
	var doc := GLTFDocument.new()
	var st := GLTFState.new()
	if doc.append_from_file(file, st) != OK:
		push_error("glb load failed: " + file)
		return
	var root := doc.generate_scene(st)
	add_child(root)
	var rn := root.find_child("RootNode", true, false)
	if rn == null:
		push_error("no RootNode")
		return
	# every node from the scene root down to RootNode: identity
	var n: Node = rn
	while n != null and n != self:
		if n is Node3D:
			(n as Node3D).transform = Transform3D.IDENTITY
		n = n.get_parent()
	# area nodes: local (a, b, c) = DSR (z, y, x) → Godot (−x, y, z) = (−c, b, a)
	var basis := Basis(Vector3(0, 0, 1), Vector3(0, 1, 0), Vector3(-1, 0, 0))
	var mat := StandardMaterial3D.new()
	mat.albedo_color = Color(0.62, 0.6, 0.55)
	mat.cull_mode = BaseMaterial3D.CULL_DISABLED
	for area in rn.get_children():
		if area is Node3D:
			(area as Node3D).transform = Transform3D(basis, Vector3.ZERO)
	for mi in root.find_children("*", "MeshInstance3D", true, false):
		var m := mi as MeshInstance3D
		m.material_override = mat


func _load_path(file: String) -> void:
	var f := FileAccess.open(file, FileAccess.READ)
	if f == null:
		push_error("path not found: " + file)
		return
	var d: Dictionary = JSON.parse_string(f.get_as_text())
	var i := 0
	for seg in d.get("segments", []):
		var col: Color = SEG_COLORS[i % SEG_COLORS.size()]
		var pts: Array = seg["pts"]
		var dashed: bool = String(seg["name"]).begins_with("manual")
		for k in range(pts.size() - 1):
			_rod(_g(pts[k]), _g(pts[k + 1]), col, 0.12 if dashed else 0.25)   # manual = points only, straight lines between
		for h in seg.get("hits", []):
			_ball(_g(h), Color(1, 0, 0), 0.8)
		i += 1
	var km := d.get("marks", {}) as Dictionary
	for name in km.keys():
		var p := _g(km[name])
		_ball(p, Color(0.2, 0.6, 1), 0.7)
		var lab := Label3D.new()
		lab.text = name
		lab.billboard = BaseMaterial3D.BILLBOARD_ENABLED
		lab.no_depth_test = true
		lab.pixel_size = 0.03
		lab.position = p + Vector3(0, 2.2, 0)
		lab.modulate = Color(0.6, 0.85, 1)
		add_child(lab)
		marks.append([name, p])


func _unshaded(c: Color) -> StandardMaterial3D:
	var m := StandardMaterial3D.new()
	m.albedo_color = c
	m.shading_mode = BaseMaterial3D.SHADING_MODE_UNSHADED
	m.no_depth_test = true          # the path stays visible through walls and roofs
	m.render_priority = 1
	return m


func _rod(a: Vector3, b: Vector3, c: Color, r: float) -> void:
	var len := a.distance_to(b)
	if len < 0.01:
		return
	var mesh := CylinderMesh.new()
	mesh.top_radius = r
	mesh.bottom_radius = r
	mesh.height = len
	mesh.radial_segments = 6
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.material_override = _unshaded(c)
	add_child(mi)
	mi.position = (a + b) * 0.5
	var up := (b - a).normalized()
	var side := up.cross(Vector3.FORWARD if absf(up.dot(Vector3.FORWARD)) < 0.9 else Vector3.RIGHT).normalized()
	mi.basis = Basis(side, up, side.cross(up))


func _ball(p: Vector3, c: Color, r: float) -> void:
	var mesh := SphereMesh.new()
	mesh.radius = r
	mesh.height = r * 2
	var mi := MeshInstance3D.new()
	mi.mesh = mesh
	mi.material_override = _unshaded(c)
	mi.position = p
	add_child(mi)


func _place_cam() -> void:
	var off := Vector3(cos(pitch) * sin(yaw), -sin(pitch), cos(pitch) * cos(yaw)) * dist
	cam.position = focus + off
	cam.look_at(focus, Vector3.UP if absf(pitch) < 1.55 else Vector3.FORWARD)


func _unhandled_input(e: InputEvent) -> void:
	if e is InputEventMouseButton:
		var mb := e as InputEventMouseButton
		if mb.button_index == MOUSE_BUTTON_LEFT:
			dragging = mb.pressed
		elif mb.button_index == MOUSE_BUTTON_WHEEL_UP and mb.pressed:
			dist = maxf(3.0, dist * 0.88)
		elif mb.button_index == MOUSE_BUTTON_WHEEL_DOWN and mb.pressed:
			dist = minf(1500.0, dist * 1.14)
		_place_cam()
	elif e is InputEventMouseMotion and dragging:
		var mm := e as InputEventMouseMotion
		yaw -= mm.relative.x * 0.008
		pitch = clampf(pitch - mm.relative.y * 0.008, -1.56, 1.2)
		_place_cam()
	elif e is InputEventKey and e.pressed:
		var k := (e as InputEventKey).keycode
		if k >= KEY_1 and k <= KEY_9 and k - KEY_1 < marks.size():
			focus = marks[k - KEY_1][1]
		elif k == KEY_T:
			pitch = -1.56
		_place_cam()


func _process(dt: float) -> void:
	var mv := Vector3.ZERO
	if Input.is_key_pressed(KEY_W): mv.z -= 1
	if Input.is_key_pressed(KEY_S): mv.z += 1
	if Input.is_key_pressed(KEY_A): mv.x -= 1
	if Input.is_key_pressed(KEY_D): mv.x += 1
	if Input.is_key_pressed(KEY_Q): mv.y -= 1
	if Input.is_key_pressed(KEY_E): mv.y += 1
	if mv != Vector3.ZERO:
		focus += Basis(Vector3.UP, yaw) * mv * dist * 0.6 * dt
		_place_cam()


func _shots(out: String) -> void:
	# overview top-down over the whole path, then an oblique view at each mark
	var views := [[Vector3(-17, -10, 45), -1.56, 0.0, 230.0], [Vector3(-17, -10, 45), -0.7, 2.4, 210.0]]
	for m in marks:
		views.append([m[1], -0.6, 0.6, 45.0])
	var sz := Vector2i(960, 600)
	var cols := 2
	var rows := int(ceil(views.size() / float(cols)))
	var sheet := Image.create(sz.x * cols, sz.y * rows, false, Image.FORMAT_RGBA8)
	get_window().size = sz
	for i in views.size():
		var v: Array = views[i]
		focus = v[0]
		pitch = v[1]
		yaw = v[2]
		dist = v[3]
		_place_cam()
		for _f in 3:
			await RenderingServer.frame_post_draw
		var im := get_viewport().get_texture().get_image()
		im.convert(Image.FORMAT_RGBA8)
		im.resize(sz.x, sz.y)
		sheet.blit_rect(im, Rect2i(Vector2i.ZERO, sz), Vector2i((i % cols) * sz.x, (i / cols) * sz.y))
	sheet.save_png(out)
	print("SK_VIEW saved ", out)
