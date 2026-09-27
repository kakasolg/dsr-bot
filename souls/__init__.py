"""DSR bot — layer structure. A lower layer knows nothing about the layers above it. Details in ../LAYERS.md.

  Layer 0 game link       control.py · dsr_telemetry.py · env.py · nav.py · navmesh.py · quitout.py · farm.py (directly under bot/)
  Layer 1 basic moves     moves.py      buttons·timing
  Layer 2 weapon usage    weapons.py    per-weapon reach·chaining·heavy attacks
  Layer 3 enemy handling  foes.py(data) · duel.py(one enemy)
  Layer 4 playbooks       field.py(field) · watch.py(escape·bloodstains)   — bosses are in ../boss/
  Layer 5 missions        missions.py   → ../run.py
"""
