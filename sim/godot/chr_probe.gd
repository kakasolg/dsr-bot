extends Node3D
# Render one character glb in chosen animations to a PNG sheet (MoKa M1109-57 check: skin, facing, which clip is what).
#   godot --path sim/godot res://chr_probe.tscn -- --glb=res://assets/c2540.glb --clips=a00_3000,a00_2050 --steps=6
#         --out=<png> [--masks=0,2]
# Rows = clips, columns = evenly spaced times over each clip. Camera looks from +X (side view) and the model's own
# forward is drawn as a red arrow (the node's −Z, which the replay turns to the recorded heading).

var cells := []


func _bone_dump(glb: String, clips: PackedStringArray, at: PackedStringArray) -> void:
	# --bones=t1,t2,… : world position of every skeleton bone for each clip at each time, as Godot plays the glb
	# (tests/chr_glb_test.py compares them with the Havok transforms the glb was built from)
	var m: Node3D = load(glb).instantiate()
	add_child(m)
	var sk: Skeleton3D = m.find_children("*", "Skeleton3D", true, false)[0]
	var ap: AnimationPlayer = m.find_children("*", "AnimationPlayer", true, false)[0]
	var out := []
	for clip in clips:
		for s in at:
			ap.play(clip)
			ap.seek(float(s), true)
			ap.pause()
			ap.advance(0.0)
			var bones := {}
			for i in sk.get_bone_count():
				var p := sk.global_transform * sk.get_bone_global_pose(i).origin
				bones[sk.get_bone_name(i)] = [p.x, p.y, p.z]
			out.append({"clip": clip, "t": float(s), "bones": bones})
	print("BONE_DUMP ", JSON.stringify(out))
	get_tree().quit()


func _ready() -> void:
	var args := {}
	for a in OS.get_cmdline_user_args():
		var kv := a.trim_prefix("--").split("=", true, 1)
		args[kv[0]] = kv[1] if kv.size() > 1 else ""
	var clips: PackedStringArray = String(args.get("clips", "a00_0000")).split(",")
	var steps := int(args.get("steps", "6"))
	if args.has("bones"):
		_bone_dump(String(args.get("glb", "res://assets/c2540.glb")), clips, String(args["bones"]).split(","))
		return
	var masks: PackedStringArray = String(args.get("masks", "0,2")).split(",")
	var view := String(args.get("view", "side"))
	var sz := Vector2i(220, 300)
	get_window().size = Vector2i(sz.x * steps, sz.y * clips.size())
	var env := WorldEnvironment.new()
	var e := Environment.new()
	e.background_mode = Environment.BG_COLOR
	e.background_color = Color(0.82, 0.84, 0.88)
	e.ambient_light_source = Environment.AMBIENT_SOURCE_COLOR
	e.ambient_light_color = Color(0.7, 0.7, 0.7)
	env.environment = e
	add_child(env)
	var sun := DirectionalLight3D.new()
	sun.rotation = Vector3(-0.9, 0.6, 0)
	add_child(sun)
	await get_tree().process_frame
	var img_all := Image.create(sz.x * steps, sz.y * clips.size(), false, Image.FORMAT_RGBA8)
	for r in clips.size():
		for c in steps:
			var vp := SubViewport.new()
			vp.size = sz
			vp.render_target_update_mode = SubViewport.UPDATE_ONCE
			vp.own_world_3d = true
			add_child(vp)
			var w := WorldEnvironment.new()
			w.environment = e
			vp.add_child(w)
			var l := DirectionalLight3D.new()
			l.rotation = Vector3(-0.9, 0.6, 0)
			vp.add_child(l)
			var m: Node3D = load(String(args.get("glb", "res://assets/c2540.glb"))).instantiate()
			vp.add_child(m)
			for mi in m.find_children("*", "MeshInstance3D", true, false):
				var nm := String(mi.name)
				if nm.begins_with("mask"):
					mi.visible = nm.substr(4, 2).to_int() in Array(masks).map(func(x): return int(x))
			var arrow := MeshInstance3D.new()
			var bm := BoxMesh.new()
			bm.size = Vector3(0.04, 0.04, 0.8)
			arrow.mesh = bm
			var am := StandardMaterial3D.new()
			am.albedo_color = Color(0.9, 0.1, 0.1)
			arrow.material_override = am
			arrow.position = Vector3(0, 0.05, -0.4)
			vp.add_child(arrow)
			var ap: AnimationPlayer = m.find_children("*", "AnimationPlayer", true, false)[0]
			var clip := clips[r]
			var at := 0.0
			if ap.has_animation(clip):
				var an := ap.get_animation(clip)
				at = an.length * float(c) / float(maxi(steps - 1, 1))
				ap.play(clip)
				ap.seek(at, true)
				ap.pause()
			var cam := Camera3D.new()
			cam.fov = 40
			if view == "front":
				cam.position = Vector3(0, 1.1, -4.2)
			else:
				cam.position = Vector3(4.2, 1.1, 0)
			vp.add_child(cam)
			cam.look_at(Vector3(0, 0.9, 0))
			cam.current = true
			var lab := Label.new()
			lab.text = "%s %.2fs" % [clip, at]
			lab.add_theme_color_override("font_color", Color.BLACK)
			vp.add_child(lab)
			await RenderingServer.frame_post_draw
			await RenderingServer.frame_post_draw
			var im := vp.get_texture().get_image()
			im.convert(Image.FORMAT_RGBA8)
			img_all.blit_rect(im, Rect2i(Vector2i.ZERO, sz), Vector2i(c * sz.x, r * sz.y))
			vp.queue_free()
	img_all.save_png(String(args.get("out", "user://chr_probe.png")))
	print("CHR_PROBE saved ", args.get("out", ""))
	get_tree().quit()
