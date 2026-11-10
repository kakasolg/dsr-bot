"""Ragdoll capsules of a character .hkx → JSON (MoKa M1109-59, hitbox step 1: body capsule candidates).

  <havok python> sim/hkx_ragdoll.py <chr>.hkx            → prints JSON to stdout

Runs under a separate Python that has `soulstruct-havok` (1.2.2) — not the project venv, so the project's
soulstruct 2.3.2 stays as it is. sim/chr_glb.py calls this through HAVOK_PYTHON.

Out: [{rag, bone, a, b, r}] — one per ragdoll rigid body with a capsule shape: its two end points in model space
(DSR coordinates, reference pose, not mirrored), the radius, and the animation bone it follows (the ragdoll → animation
SkeletonMapper's first simple mapping for that ragdoll bone).
These are the ragdoll's physics capsules. Whether DSR also uses them as the hurtbox is not known (DS3 does, per
DS3 Codex; nothing found for DS1) — so they are candidates.
"""
import json
import sys

from soulstruct.havok.core import HKX


def _mat(t) -> list:
    """hkTransform as 16 floats: three rotation columns (x, y, z, pad) then the translation (x, y, z, 1)."""
    c = [t[0:3], t[4:7], t[8:11]]
    return [[c[0][i], c[1][i], c[2][i], t[12 + i]] for i in range(3)]


def _apply(m, v) -> list:
    return [m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2] + m[i][3] for i in range(3)]


def main() -> None:
    h = HKX.from_path(sys.argv[1])
    named = {v.name: v.variant for v in h.root.namedVariants}
    rag = named["RagdollInstance"]
    rag_names = [b.name for b in rag.skeleton.bones]
    to_anim = {}
    for v in h.root.namedVariants:
        if v.name != "SkeletonMapper":
            continue
        m = v.variant.mapping
        if m.skeletonA.name != rag.skeleton.name:
            continue
        for s in m.simpleMappings:
            to_anim.setdefault(m.skeletonA.bones[s.boneA].name, m.skeletonB.bones[s.boneB].name)
    out = []
    for bi, ri in enumerate(rag.boneToRigidBodyMap):
        if ri < 0:
            continue
        rb = rag.rigidBodies[ri]
        sh = rb.collidable.shape
        if type(sh).__name__ != "hkpCapsuleShape":
            out.append({"rag": rag_names[bi], "skipped": type(sh).__name__})
            continue
        m = _mat(rb.motion.motionState.transform)
        out.append({"rag": rag_names[bi], "bone": to_anim.get(rag_names[bi]),
                    "a": [round(x, 5) for x in _apply(m, list(sh.vertexA)[:3])],
                    "b": [round(x, 5) for x in _apply(m, list(sh.vertexB)[:3])],
                    "r": round(float(sh.radius), 5)})
    print(json.dumps(out))


if __name__ == "__main__":
    main()
