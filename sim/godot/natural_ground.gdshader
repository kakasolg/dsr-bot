shader_type spatial;
// Natural-looking ground for the practice room (MoKa M1111-23: "지형 이미지 다크소울 것 쓰지 말고, 고도에서 자연스러운
// 질감 찾아봐"). Procedural only — Godot noise textures, no image files: triplanar noise in world space, steep faces rock
// (layered bands + cellular cracks), flat faces grass / moss / dirt by large-scale noise.
render_mode cull_disabled;

uniform sampler2D noise_fine : repeat_enable, filter_linear_mipmap;    // simplex fbm, seamless
uniform sampler2D noise_large : repeat_enable, filter_linear_mipmap;   // low-frequency patches
uniform sampler2D noise_cells : repeat_enable, filter_linear_mipmap;   // cellular distance → cracks / pebbles
uniform vec3 grass_col = vec3(0.26, 0.34, 0.15);
uniform vec3 moss_col = vec3(0.17, 0.24, 0.12);
uniform vec3 dirt_col = vec3(0.36, 0.29, 0.20);
uniform vec3 rock_col = vec3(0.47, 0.45, 0.41);
uniform vec3 rock_dark = vec3(0.27, 0.26, 0.25);
uniform vec3 tread_col = vec3(0.50, 0.48, 0.44);      // 계단 (M1111-29): 디딤판 밝은 돌
uniform vec3 riser_col = vec3(0.30, 0.29, 0.27);      // 앞면 어두운 돌
uniform float step_h = 0.22;                           // 단 높이 [guess] — 11-11 통 계단 Sketchfab 앞면 0.21–0.23 m

varying vec3 wpos;

void vertex() {
	wpos = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
}

float tri(sampler2D t, vec3 p, vec3 w, float s) {
	return texture(t, p.zy * s).r * w.x + texture(t, p.xz * s).r * w.y + texture(t, p.xy * s).r * w.z;
}

void fragment() {
	vec3 n = normalize((INV_VIEW_MATRIX * vec4(NORMAL, 0.0)).xyz);   // back faces already flipped toward the camera
	vec3 w = pow(abs(n), vec3(4.0));
	w /= (w.x + w.y + w.z);
	float fine = tri(noise_fine, wpos, w, 0.35);
	float fine2 = tri(noise_fine, wpos, w, 1.7);
	float big = tri(noise_large, wpos, w, 0.03);
	float cells = tri(noise_cells, wpos, w, 0.45);

	// rock: horizontal strata wobbling with noise, dark cracks along cell edges
	float band = sin(wpos.y * 3.1 + fine * 6.0) * 0.5 + 0.5;
	vec3 rock = mix(rock_dark, rock_col, 0.35 + 0.45 * band * fine + 0.2 * fine2);
	float crack = smoothstep(0.06, 0.0, cells);
	rock = mix(rock, rock_dark * 0.55, crack * 0.8);

	// ground: dirt ↔ grass by large patches, moss in the low-lying fine noise
	float g = smoothstep(0.35, 0.65, big + (fine - 0.5) * 0.35);
	vec3 ground = mix(dirt_col * (0.8 + 0.4 * fine2), grass_col * (0.75 + 0.5 * fine2), g);
	ground = mix(ground, moss_col, smoothstep(0.55, 0.8, fine) * 0.6);
	ground = mix(ground, rock_dark * 0.9, smoothstep(0.1, 0.0, cells) * (1.0 - g) * 0.6);   // pebbles in the dirt

	float flat_ = smoothstep(0.55, 0.85, n.y);
	vec3 col = mix(rock, ground, flat_);

	// 계단 (COLOR.r, ramp.gd _stair_mask): 풀·큰 얼룩 없이 조용한 돌. 경사판이면 높이 step_h마다 앞면(어두운 띠)·디딤판(밝음)·
	// 모서리(더 밝은 선)를 그려 단처럼 보이게 — 진짜 단이 아니라 칠한 것 (Perplexity: 비탈은 그림자·질감만으론 단이 안 생김)
	float stair = clamp(COLOR.r, 0.0, 1.0);
	float f = fract(wpos.y / step_h);
	float ramp_ = smoothstep(0.97, 0.9, n.y) * smoothstep(0.35, 0.5, n.y);      // 경사판만 줄무늬
	float riser = (1.0 - smoothstep(0.0, 0.35, f)) * ramp_;
	float nose = smoothstep(0.9, 1.0, f) * ramp_;
	vec3 stone = mix(riser_col, tread_col, smoothstep(0.4, 0.9, n.y)) * (0.92 + 0.12 * fine2);
	stone = mix(stone, riser_col * 0.85, riser);
	stone = mix(stone, tread_col * 1.15, nose * 0.6);
	col = mix(col, stone, stair);
	ALBEDO = col;
	ROUGHNESS = mix(0.85, 0.95, flat_);
	AO = 0.75 + 0.25 * fine;
}
