# Practice room camera for watching a bot run — Perplexity answer (2026-11-11, MoKa M1111-33)

MoKa: "카메라 무빙이 이상해서, 후반부에 뭐가 어떻게 되는지 따라 가기가 힘들어." Asked in the built-in browser (Perplexity, 43
sources, 13:15). The question was generic: no repo and no game name. It described the room camera as it is (`main.gd`
`_update_camera`): orbit 4 m behind the head, fixed pitch −0.25 rad, FOV 43, yaw only from the right stick, smoothing toward the
target at rate 8/s, a ray that snaps the camera in to 0.6 m when a wall is in the way. Below is a condensed summary, not a copy.
Its numbers are starting values it proposes, not Godot defaults and not measured here.

## Its main point
The camera has no operator. Yaw changes only from the right stick, and the bot never moves the right stick, so the camera keeps
its starting direction. On later legs the character walks toward or across the camera. More smoothing will not fix that. Fix the
yaw first.

## Ranked by effort vs gain (its table, condensed)
| # | Change | Effort | Gain | Starting values |
|---|---|---|---|---|
| 1 | Auto-recenter yaw behind the travel direction | low–medium | very high | moving > 0.2 m/s; start turning at 12° off held 0.25 s, stop under 5°; ≤ 90°/s, response ~0.3 s |
| 2 | Follow the body root, not the head; vertical damping separate from horizontal | low | high on stairs | horizontal 0.12–0.18 s, vertical 0.3–0.45 s |
| 3 | Look ahead along the route; aim partly at the next point | medium | high | 0.6–0.9 s ahead, 1–3 m, aim 25–35 % toward it |
| 4 | Volume sweep instead of a ray; snap in, ease back out | medium | high in narrow places | sphere 0.15–0.25 m, margin 0.05–0.10 m, ease out over 0.4–0.7 s |
| 5 | Framing | low | medium–high | FOV 55–60°, pitch down 18–22°, body a little below centre |
| 6 | Ladder and tight-corridor modes | medium | high where they happen | side / three-quarter view on ladders, corridor-aligned yaw, 0.5–0.8 s blends |
| 7 | North-up minimap: position, heading, trail, next goal, floor | medium | high for long runs | — |
| 8 | Fade walls between camera and body instead of zooming in | medium–high | high | fade 0.15–0.25 s, back 0.35–0.6 s |
| 9 | A few authored overview shots (bridges, switchbacks, ladders) | medium–high | high at those spots | hold ≥ 3–5 s |
| 10 | Automatic shot choice | high | varies | only after the rest |

## Details worth keeping
- Heading to follow, in order: smoothed route tangent (the route is known), else smoothed velocity, else the last good heading.
  Not the model's facing (turning in place, strafing). Keep the turn direction through near-180° reversals. If a human touches
  the right stick, pause the recentering for 1.5–2 s.
- Look-ahead: sample along the path polyline, not a straight line through walls. Frame the next meaningful thing (stair landing,
  bridge entrance, ladder top), not the far goal.
- Walls: keep safety (no camera inside geometry) and readability apart. If the free distance stays under ~1.5 m for 0.3 s, try
  ±15° / ±30° side offsets, or a corridor / side view, or fade the occluder. Keep the chosen side ~1 s so avoidance itself
  doesn't swing the camera. In Godot, SpringArm3D with Camera3D as a direct child sweeps the camera's near-plane pyramid; an
  explicit SphereShape3D also works; ShapeCast3D for a custom controller.
- Stairs: follow the overall slope, not each step. Vertical deadband 0.05–0.10 m, but let large drops or climbs (> 0.5–0.8 m)
  catch up fast.
- Ladders: an explicit state, not velocity. Fixed yaw relative to the ladder, side or three-quarter view, level horizon, aim
  toward the exit. Enter 0.3–0.5 s before mounting and stay until 0.5 s after stepping off.
- Blend (0.5–0.8 s) when both views show the same place. Cut when a blend would pass through walls, after a teleport or seek, or
  for an overview. Don't flip between cameras on small score differences: hold each shot 3–5 s.
- Godot interpolation (physics interpolation, `get_global_transform_interpolated`) removes sampling jitter. It is a different
  job from deliberate camera lag. Reset histories after a teleport.
- Phantom Camera addon: virtual cameras with priorities and transitions. Route look-ahead and the "which shot" logic stay ours.
- Measure on the same hard stretches with each change alone: time facing against travel, time occluded, time under 1.5 m,
  number of switches; and ask the viewer where the character is and what it does next.

## How this maps to the room (not built, not checked)
- Its formula remark (`exp(-8·dt)` used as the lerp weight would be wrong) doesn't apply. `main.gd` already uses
  `1 − exp(−CAM_FOLLOW·dt)`.
- Recentering (#1) applies to the walk demos and bot runs alike. The bot steers relative to the camera (`Moves.stick_to` uses
  `cam_yaw`), so turning the camera on its own also changes how the bot's stick maps to the world. The bot reads the yaw every
  tick, so it should cope, but that is to be checked. Also: DSR itself does not auto-turn this way (CAM_* are LockCamParam
  values), so a "viewer camera" may be better as a separate mode than a change to the play camera.
- Look-ahead (#3): `burg_walk.py` knows each leg's path; the room doesn't. It would need the path sent over the input port, or
  scene `legs`.
- Ladders (#6): the room has an explicit ladder state now (`ramp.gd` `_ladder_*`), so a ladder view can hang on it.
- Minimap (#7): the scene has the NavMesh and route — enough for a 2D overlay in a SubViewport.

## Follow-up: real cases (same thread, 208 sources, MoKa "이런 경우엔 일반적으로 어떻게 하는지 사례를 찾아 달라고 해")
It first corrected itself: the delays, deadzones and speeds in the first answer were its own starting values, not taken from
shipped cameras. Public sources usually describe modes and principles, not tuning numbers.

| Case | What it does | Source it named |
|---|---|---|
| Trackmania GPS / MediaTracker | A recorded ghost shows how to drive a track. The replay and the camera are edited apart. Map authors place spatial triggers that switch to a section camera (loops, wallrides); top view and "aim at the car" exist. Hard geometry gets a section camera, not a smarter chase solver | Nadeo docs, Trackmania wiki |
| Valve SourceTV | An auto-director picks the shot type and position from events (kills, bomb); fixed shots allowed; a human can override. Wall handling not documented | Valve Developer Community |
| Dota 2 spectator | Directed Camera, Player View and Hero Chase are separate modes; minimap with direction arrows; override returns to the mode after a short delay | Valve DotaTV / HUD update |
| Gran Turismo 7 / GT Sophy | Replays have their own presentation layer (car choice, music-timed cuts); Sophy's races were shown with several cameras and replays | Polyphony manual, Sony AI supplement |
| TF2 deathcam | A short, composed "this is what killed you" shot (zoom to the killer, freeze, name and HP), not a replay | TF2 wiki (Valve commentary) |
| Dark Souls bloodstain / ghosts | Recorded actions replayed in the world; no dedicated camera documented | PC manual, DS3 community docs |
| Tomb Raider (GDC 2013, Remi Lacoste) | Exploration camera moves back behind the character as it moves, adapts to height and turns corners, also while climbing, with no right stick; it contrasts this with a camera that stays at its first angle until the stick moves. Closer camera indoors, special set-ups for custom climbs, falls and interactions. No numbers published | GDC Vault, talk transcript |
| Journey (GDC 2014, John Nesky, "50 Camera Mistakes") | Extra probes ("whiskers") see obstacles coming and compress gradually; sphere checks; slopes vs side walls treated differently; a thin column is not a collision; constraints ranked | GDC Vault, secondary talk summary |
| A Hat in Time | Objects between camera and player fade; the player shows as a silhouette behind walls | VICE interview |
| GDC "Juicing Your Cameras With Math" | Stairs as the example of bad rigid following; vertical handled apart from horizontal; follow height only after landing; frame-rate-independent smoothing | GDC talk transcript |
| MineRL | Humans watch the agent's own first-person view (`env.render()`); no separate chase camera | MineRL docs |
| Unity ML-Agents / Godot RL Agents | The agent's sensor cameras are not the viewer camera; no spectator camera prescribed | Unity docs, Godot RL Agents paper |
| Gazebo | Follow (keep an offset) and Track (turn to face) are separate controls with separate gains; offset in the robot's frame or the world frame | Gazebo Rendering docs |
| Isaac Sim / Isaac Lab | Camera on the robot plus a second viewport with an outside view, side by side | NVIDIA docs |
| CARLA | Explicit choice: Rigid (sensor), SpringArm (eased, collision-aware), SpringArmGhost (no collision, passes walls), free spectator, overhead example view | CARLA docs |
| TASVideos | Publishes the game's own output frame by frame; no camera reinterpretation | Encoder guidelines |

Common across the cases: replayed action and camera presentation are separate; a few simple view modes instead of one camera
that does everything; follow position and aim are separate controls; cameras per place or state (Tomb Raider, Trackmania); a
wide view next to the close one (Dota minimap, Isaac two views, CARLA overhead). Less exposed: predictive obstacle handling and
fading (third-person game talks, A Hat in Time). Rare or not found: published recenter numbers; a fully automatic director that
handles any indoor level, ladder and wall on its own.

Its order for a small team (its synthesis, not a survey): (1) a hands-off follow camera like Tomb Raider's; (2) a few modes and
route zones — default follow, corridor-aligned, ladder side view, overview; (3) an orientation aid apart from the main camera —
route map or outside view; (4) pick a wall policy on purpose — collision-bound chase, or a "ghost" camera that may pass walls
plus fading; (5) for a fixed, repeatable run, a few route marks and camera keys (Trackmania-style) beat a clever online shot
scorer; (6) event-driven directing only when several subjects compete.

How this maps to the room (not built, not checked): our runs are fixed and repeatable (scene `legs`, ladders, named spots), so
(5) fits — e.g. a camera mode per leg kind or per spot (ladder state already exists). Our follow is world-frame offset with yaw
from the stick only, i.e. Gazebo's "world-frame follow" with no Track; Tomb Raider's behaviour is what's missing.

## Follow-up 2: Tomb Raider-style follow + Trackmania-style section cameras in depth (same thread, MoKa "더 자세하게 … 장점과 단점 … 사용자 평가도")
Condensed. It separates documented facts, reported opinions and its own recommendations; so does this summary.

### How shipped games and tools build it (documented)
- **Uncharted 3** (Naughty Dog, Game Connection 2011, Gregory & McIntosh) is the closest match to the whole combination:
  - A procedural follow camera: auto-rotation while traversing, **none in combat** so it doesn't fight aiming, sphere-cast fans
    to find free space, a critically damped spring.
  - Designer cameras placed in the level (fixed, pivot, spline, animated), plus **designer overrides of the follow camera's
    preferred angle**.
  - Priority: ordinary procedural < designer cameras < special (aim, death). New cameras fade in over the ones below.
  - Admitted problem: collision was solved per camera, so **blends could clip walls**. They proposed a final collision pass after
    blending.
- **Tomb Raider** (GDC 2013): hands-off follow is the base. It is closer indoors, and custom climbs, falls and interactions get
  their own cameras. No volume format, priority rule or numbers were published. Players complain about its **hand-held shake and
  wobble**, which is separate from the auto-follow.
- **Trackmania**: spatial triggers plus camera blocks/keyframes over a recorded ghost. That fits a fixed route. It is not a general
  blending system for overlapping volumes.
- **Super Mario 3D Land / 3D World** (Iwata Asks): a "parallel camera" with a fixed direction and distance per course, so players
  get lost less and don't need to master the camera. A section can keep a world-fixed direction instead of orbiting. They also
  shaped levels around the camera (avoided small tunnels and pillars). We can't do that, because our level is imported.
- **Hollow Knight** (from mod source, not from the developer): camera lock areas limit or pan the camera. So a zone can change
  limits without being a new shot.
- **God of War 2018 / Ragnarök**: documented settings (attack recentering, strafe assist, sway, shake, motion-reduction presets).
  BotW/TotK: no developer documentation found.
- **Tools**: none of these supplies the zone manager, hysteresis or collision-safe blends.
  - Cinemachine: virtual cameras, priorities, blends; ClearShot "Activate After" / "Min Duration"; Deoccluder with separate
    avoid/recover damping.
  - Unreal: overlap volume → `SetViewTargetWithBlend`, back to the pawn on exit. This is naive when zones overlap.
  - Godot **Phantom Camera**: the highest priority wins and a tween runs on change. `inactive_update_mode = ALWAYS` keeps the follow
    camera tracking while another shot is active.

### Its recommended shape (its opinion)
- **Two zone kinds.** Prefer the first; most sections need a preferred direction, not a different camera.
  - Follow-profile zones change the follow camera's settings (preferred yaw, limits, pitch, distance, height damping,
    look-ahead). For corridors, bridges, stairs.
  - Shot-override zones replace it (fixed, pivot, rail). For ladder shafts, switchbacks, the worst spots.
- **One director owns the final camera.** Order: manual inspect > special shot > ladder/difficult shot > section profile > default
  follow.
- **Hysteresis:**

  | Rule | Starting value |
  |---|---|
  | Enter a zone | after 0.15–0.25 s inside |
  | Leave a zone | only past an outer volume 0.5–1 m bigger, for 0.25–0.4 s |
  | Hold an authored shot | ≥ 2–3 s |
  | Equal priority | keep the current one |
  | Blend in / back | 0.5–0.8 s / 0.7–1.0 s |

  Eligibility = inside the region **and** on the right route segment. Stacked stairs and switchbacks are close in space but far
  along the route.
- **Handing back:** keep the follow camera updating while hidden. Hand back to the **current route direction**, not the yaw from
  before the zone.
- **Collision:** check the blended camera against walls, not only the two ends. Cut when no safe, readable path exists.
- **Logging:** log the active zone, profile/shot, blend state, collision correction and route segment.

### Pros and cons (its table, condensed)
| | Pros | Cons / failure modes |
|---|---|---|
| Hands-off follow | Always tied to the character; little authoring; copes with small route changes | Needless orbiting; wrong heading when strafing or backtracking; stair bounce; wall squeeze; can be uncomfortable |
| Section cameras | Reliable framing of a known action; show height, scale, destination | Authoring and testing per section; can hide deviations; a switch can make travel look reversed; breaks when geometry changes |
| Combination | General coverage plus targeted fixes; fewer authored shots | Arbitration complexity; stale follow state; flicker at zone borders; solvers fighting; clipping during blends; turning toward the next flight too early |

### What players and critics say (reported opinions; selected examples, not a survey)
- **Auto-recentering.** The main complaint is that it fights what the player is doing. Elden Ring Steam/Reddit threads describe
  moving one way, looking another, and the camera pulling back. Uncharted turned it off in combat for the same reason.
- **Motion sickness.**
  - Elden Ring players report nausea from floating, delayed recentering; one says turning auto-adjust off helped.
  - Tomb Raider players report discomfort from shake/wobble, also in cutscenes.
  - So assistance, lag/rotation and decorative shake are three different things.
- **Fixed/authored cameras.**
  - For: Resident Evil fans praise composed framing, scale and controlled reveals. A press piece suggests mixing a few fixed views
    into a behind-the-character game.
  - Against: Eurogamer (RE) "cinematic but often frustrating" (partly the controls). IGN (Mario 3D World): restricted viewpoints
    make depth and position hard to judge. Players report missed jumps.
- **Help for players.** Nintendo designed hands-off cameras so players need not master the camera. A BotW player who can't use the
  right hand asked for recentering, which is an accessibility need.

### Which complaints remain when watching a bot (its table)
| Complaint | Watching a bot | So |
|---|---|---|
| Camera fights the right stick | mostly gone (no viewer input) | follow can be stronger |
| Camera changes move-relative controls | gone if the run doesn't depend on the camera | keep presentation out of the simulation |
| Hides the next action | stays | frame the current action and the next spot together |
| A switch makes travel look reversed | stays | keep landmarks / screen direction / route reference |
| Fixed angle hides height or depth | stays | oblique angles, shadows, landing cues, overview |
| Shake, orbiting, slow catch-up uncomfortable | stays (TR cutscene reports) | reduced-motion option |
| Too many switches tire | stays | minimum hold, few overrides |
| Authored shot wrong after route change | stays | check eligibility, keep follow as fallback |

It found **no controlled viewer studies** of this exact combination, so it has to be tried with the viewer.

### Settings teams ship / it suggests
- God of War Ragnarök ships motion-reduction presets, separate shake and sway sliders, cinematic smoothing, a centre dot, and
  recentering modes including off.
- Its suggestion for a viewer, three presets:
  - readable replay: follow + section profiles + a few shots + route inset;
  - reduced motion: no shake/roll, fewer orbits, stable section headings;
  - reference: plain consistent follow.
- Plus toggles: authored shots, follow strength, transition style, overview inset, and manual inspect with "resume auto camera".

### How this maps to the room (not built, not checked)
- **"Camera changes move-relative controls" does not disappear for us.** Our bot steers relative to the camera (`Moves.stick_to`
  reads `cam_yaw`), so a viewer camera that turns on its own changes how the bot's stick maps to the world. Two ways out: a
  separate viewer camera (the bot keeps steering by the play camera's yaw), or check that the bot copes with a turning camera.
- **Route segment identity already exists:** scene `legs` names and the ladder state. Section zones can be keyed to leg index plus
  position, not only to boxes.
- **Smallest first step it suggests:** one reliable follow; profile zones for one corridor, stairs and bridge; one replacement shot
  for the worst ladder; hysteresis; a clipping check on the blended camera; a route inset; a reduced-motion preset.

## Follow-up 3: Godot difficulty and resources for the smallest first step (same thread, MoKa "고도 엔진에서 구현하는 난이도와 필요 리소스를 받기 쉬운지 한번더 확인해줘")
Condensed. Effort numbers are Perplexity's own estimates for one developer, not measurements. The Phantom Camera lines were
also checked by [win] on GitHub (ramokz/phantom-camera) on 11-11.

### Difficulty per piece (its estimates, first usable version)
| Piece | How in plain GDScript | Difficulty | Time |
|---|---|---|---|
| Hands-off follow | anchor + route/velocity heading, yaw controller, separate XYZ damping | medium | 4–8 h |
| Corridor / stairs / bridge profiles | data records changing yaw, distance, pitch, damping | low–medium | 3–6 h |
| Ladder side shot | shot from the ladder ends + a side vector | low–medium | 2–4 h |
| Priority + hysteresis | one resolver, entry/keep bounds, timers | medium | 3–6 h |
| Shot transitions | one transition clock, interruptible blend | medium | 2–4 h |
| Collision checks | sphere sweep + endpoint overlap + fallback | medium–high | 6–12 h |
| Route inset | 2D drawing of the route on XZ | low | 2–4 h |
| Reduced-motion preset | profile overrides | low | 1–2 h |
| Headless tests / logging | fixed-step solver tests, zone tests | medium | 4–8 h |

Total: about 4–7 developer-days for a testable first pass plus 1–3 days of tuning per route. A same-day prototype is possible
but is not clipping-safe.

### Engine points it raised (documented in Godot docs, per its sources)
- Everything needed is built in (shape sweeps, overlap queries, Area3D, SubViewport). No addon is required.
- Zones: for a few code-made zones on a fixed route, a plain box test per tick is simpler than Area3D (no physics-event timing,
  works for a plain Node3D, easy headless). Area3D `priority` is about physics overrides, not camera choice.
- Collision: `cast_motion()` ignores shapes already overlapping the query, so pair it with `intersect_shape()`/`collide_shape()`.
  SpringArm3D moves its child itself — don't let it and a director both own the camera. A concave triangle mesh has no inside.
- Transitions: an explicit clock is easier than Tween for pause/seek/interrupt and tests.
- Physics interpolation: keep one update path first; reset after cuts and teleports.
- `--headless` disables rendering: camera logic and physics queries can be tested headless, framing and clipping cannot.

### Phantom Camera (addon)
- Its findings: v0.11.0.4 (2026-10-27), MIT, GDScript, min Godot 4.4; release notes fix a Godot 4.7.1 autoload/manager issue;
  active maintenance; the FAQ still calls it early-stage. Can create cameras from code, but needs the plugin/autoload bootstrap.
  No documented headless support. 3D look-ahead not released (2D only).
- [win] GitHub check: same version and licence; open issue #665 "Node not found: PhantomCameraManager" on Godot 4.7 waits for a
  Godot-side fix; #651 plugin not working on 4.6.3-mono.
- What it would not replace: route-based recentering, zone eligibility/hysteresis, ladder logic, seek-safe state, final collision
  check of the blended pose, the inset, headless asserts.

### Other resources (licences as listed)
JeanKouss Third Person Camera (MIT, Godot 4.0 listing), DynamicMinimap (MIT, 4.6), Mini Map (MIT, 4.1, 2D), Godot RTS Kit (MIT,
tested on 4.7.1), official Godot demos (MIT) and docs (third-person spring-arm tutorial, ShapeCast3D, PhysicsDirectSpaceState3D,
physics interpolation, SubViewport). Code references only; nothing needs downloading for the first step.

### Its recommendation
Write the first version ourselves: FollowSolver → ZoneResolver → TransitionState → CameraCollision → one presenter that alone
writes the Camera3D; 2D route inset; math box zones; shape queries directly. Reconsider Phantom Camera only for many authored
shots / editor workflows.

### For the room (not built, not checked)
- Our room has no addons and is built in code and tested headless; this matches "write it ourselves".
- Our bot steers by `cam_yaw`, so the new camera should be a separate viewer camera (the play camera keeps its yaw), or the
  presenter must not change `cam_yaw`.
- Leg index + ladder state already give the route segment for zone eligibility.

## Built (MoKa M1111-34 "직접 구현으로 만들어", 11-11)
- `sim/godot/cam_director.gd`: hands-off follow toward the planned route 5 m ahead (travel direction when off the route), sections
  corridor / stairs / bridge from scene `cam_path` (legs by name, stairs by slope, runs < 4 points merged), enter 0.25 s / hold
  1.5 s, ladder side shot with 0.7 s blends and hand-back to the route direction. All numbers [guess].
- `ramp.gd` `_update_view`: a separate viewer camera; sphere (0.25 m) check from the look point, snaps in, grows back over ~0.5 s;
  the play camera and `cam_yaw` are unchanged, so the bot steers as before. F2 / `--cam=play`, `--view-snaps=<dir>,<s>`.
- Checked: `tests/godot_viewcam_test.py` (director rules on made-up routes, headless) and a headless room walk Taurus bridge →
  demon (7 legs arrived, 26 section changes, shortest hold 1.5 s, always on the route). Not checked: how it looks to a viewer.
- Windowed walk 1 (20261111_134853 snaps, before the fan): in one frame out of 31 (44 s, stair foot near ②), the wall pulled the
  camera into the body (48 % of the screen body-coloured). Fix: when the arm is blocked, a fan of 12 sphere casts (swing ±0.5/1.0 rad,
  raise 0.35/0.7/1.0 rad), eased toward the most open one (Uncharted 3 free-space idea). Windowed walk 2 (20261111_135629): 7 legs
  arrived in 182 s, 26 section changes, shortest hold 1.5 s, always on the route, 0 of 46 frames > 20 % body. Burg bonfire ladder:
  side shot while climbing up and down. Judged from saved frames by [win], not yet by MoKa.
