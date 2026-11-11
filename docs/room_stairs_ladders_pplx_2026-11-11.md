# Practice room stairs and ladders — Perplexity answer (2026-11-11, MoKa M1111-28)

Asked in the built-in browser (Perplexity, 60 sources, 11:58). The question was generic: no repo and no game name, only "a
collision-derived level mesh with no UVs, a triplanar noise shader, smeared stairs, missing ladders". Below is a condensed summary,
not a copy. Numbers are Perplexity's starting values, not measured here.

## Ranked by effort vs gain (its table, condensed)
| Technique | Effort | Gain | Limit |
|---|---|---|---|
| Neutral grey material + side view: are there treads/risers, or a ramp? | very low | needed diagnosis | — |
| Oblique DirectionalLight3D shadows, short shadow range | low | high if steps exist | depends on light direction |
| Stair-region mask: no grass/noise there, tread lighter than riser | low–medium | very high | needs region data or a classifier |
| Small-radius SSAO (~step size) | low | medium–high | screen-space artifacts |
| Procedural ladder (rails + rungs) from bottom/top + wall normal | low | very high | needs endpoints and facing |
| Edge strips / small bevels at tread–riser creases | medium | high | needs adjacency |
| Vertex-colour AO bake | medium–high | high on static | 3 vertices per triangle can't draw a thin edge band |
| Generate steps over a ramp | medium | very high if steps are missing | guessed step count, not recovered |
| SSIL | low setup | low–medium for stairs | indirect light, not an edge cue |

## Points it made
- Check geometry first: if the mesh is a ramp, shadows and materials can't make steps; if it has steps but reads smooth, fix
  normals/material contrast before rebuilding. Flat normals: `SurfaceTool.set_smooth_group(-1)` + `generate_normals()`.
- Shadows: `shadow_enabled`, `SHADOW_PARALLEL_4_SPLITS`, `directional_shadow_max_distance ≈ 60`, light across the steps; tune bias
  last. SSAO: `ssao_radius ≈ 0.35` for 0.15–0.25 m risers, intensity 1, power 1.4, `ssao_light_affect ≈ 0.15`; SSIL off.
- Classify stairs in two steps: is the triangle in a stair region (explicit volumes first; automatic = flat patches with
  repeated height steps along one direction), then tread (n.y > 0.9) / riser (|n.y| < 0.25). Orientation alone can't tell a tread
  from a landing. Pass the mask as vertex COLOR; read the world normal in `vertex()` (or `world_vertex_coords`).
- Stair branch of the shader: no grass, much less high-frequency noise, tread lighter than riser.
- Crease darkening: weld vertices, edge → triangles map, mark pairs with angle > ~35° inside stair regions, draw a thin dark strip
  slightly offset. Not every triangle edge (that just shows the collision mesh). Avoid `fwidth(NORMAL)` "curvature".
- Steps over a ramp = reconstruction: an explicit descriptor (bottom, top, run direction, width, target rise → N = round(H/h)),
  hide the ramp's visual patch, keep the ramp collision.
- Ladders: box rails 0.055 m and rungs 0.04 m every 0.28 m, half-width 0.23 m; needs a wall normal for orientation. Visual only, no
  rung colliders. CC0 options: Quaternius "Ladder" (Poly Pizza, low-poly) and Poly Haven "Ladder Sectioned 01" (29K tris); check
  each asset's licence.
- Climbing: a separate state with `MOTION_MODE_FLOATING`, no gravity, move along the bottom→top axis and snap sideways; top-out and
  bottom exits need their own transitions.
- Order it suggests: (1) diagnosis: grey material, hard normals, oblique sun, shadows; (2) stair masks + quiet stone + procedural
  ladders, collision unchanged; (3) SSAO, crease strips, climbing.

## How this maps to the room (not built, not checked)
- Our terrain = Sketchfab "Undead Burg" triangles. At the barrel stairs the mesh has real 0.2 m risers (seen in the face list
  11-11); other stairs not checked: ramp or steps is still to be seen with the grey-material check.
- Stair region without hand volumes: where the game NavMesh is sloped (normal.y < ~0.97) and the Sketchfab faces above it are
  flat treads / short risers. Our idea, not from the answer.
- Ladder data we have: Taurus ladder only (bottom 49.16, 15.97, −117.1, face +x, top y 24.5). Others: map MSB ladder objects.
- The room has no ladder climb; that is a separate piece (the Taurus plunge practice would need it).
