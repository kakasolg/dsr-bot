---------------------------- MODULE PadFreeze ----------------------------
(***************************************************************************)
(* control.Pad freeze / unfreeze and the shared pad state, at the level of *)
(* the `with self._lock:` blocks.  One TLA+ action = one lock block of     *)
(* control.py (line numbers: file as of commit 9eb185e).  A method with    *)
(* several lock blocks (Pad.press) is several actions; nothing outside a   *)
(* lock block is merged into one, except the unlocked emptiness check of   *)
(* release_due (:484), which only skips an empty pass.                     *)
(*                                                                         *)
(* Threads (roles, not Python thread names):                               *)
(*   h  the quit-out holder: watch.Escape.fire -> quitout.quit_out         *)
(*      (Script "quit"), or a holder that taps (Script "tapper", K3: no    *)
(*      such caller exists today)                                          *)
(*   o  souls/guardkeep.GuardKeep thread: keep_guard / unkeep              *)
(*   n  the decision loop (nav.Mover, duel): sprint, guard, tap, hold,     *)
(*      neutral, release_due                                               *)
(*   e  watch.Escape._nudge: freeze(take=False) -> neutral -> unfreeze     *)
(*                                                                         *)
(* Time is abstracted: Tick lets _force_until pass, a young sprint hold    *)
(* age past SPRINT_MIN_HOLD_S, and a scheduled release come due, each in   *)
(* any order.  pad.dev = the report on the real (ViGEm) device; a write    *)
(* from a thread that is not the freeze holder goes to _NullPad and leaves *)
(* pad.dev unchanged (Pad.pad property, :215-221).  Pad.epoch is not a     *)
(* variable: its one reader that matters (nav.Mover._resync) is folded     *)
(* into the ghost syncB / syncLB ("n's last request came after the last    *)
(* epoch bump").                                                           *)
(*                                                                         *)
(* Variant:                                                                *)
(*   "current"       the code as it is                                     *)
(*   "block"         while frozen, a non-holder's call changes nothing     *)
(*                   (no shared state, no epoch); freeze/unfreeze excepted *)
(*   "ownerNeutral"  the holder's neutral() releases everything and keeps  *)
(*                   no guard / young-sprint intent                        *)
(*   "both"          block + ownerNeutral                                  *)
(*   "minimal"       block + freeze() also drops the keep / guard intents  *)
(*                   (_force_until, _kept, _guard_want); neutral unchanged *)
(***************************************************************************)
EXTENDS Naturals

CONSTANTS Variant, Script, MaxOps, UseNudge, NGuard, NTap, NHold

Thr  == {"h", "o", "n", "e"}
Btn  == {"LB", "B", "A"}
None == "none"

VARIABLES
    pad,   \* [owner: _frozen_by, dev: buttons on the device, fg: force_guard, kept: _kept, gw: _guard_want,
           \*  bs: _b_since "none" | "young" | "old", due: _due  button -> "no" | "pending" | "ripe"]
    g,     \* ghosts: [hHeld: buttons h holds through Pad.press, wantB / wantLB: n's last sprint / guard request,
           \*  syncB / syncLB: that request reached the device side (writable, no epoch bump since),
           \*  newer: buttons whose device press is newer than their release reservation,
           \*  kill: a release_due let go of such a newer press,
           \*  frozenA: the A reservation came from a tap that went to _NullPad (made while another thread held the freeze),
           \*  killFrozen: kill by such a reservation]
    pc,    \* program counter per thread
    ops    \* [o, n: calls made so far (each <= MaxOps), nb: calls o/n made while another thread held the freeze]

vars == <<pad, g, pc, ops>>

W(t)          == pad.owner \in {None, t}                   \* t's writes reach the device
Blocked(t)    == Variant \in {"block", "both", "minimal"} /\ ~W(t)
OwnerNeutral  == Variant \in {"ownerNeutral", "both"}
ClearOnFreeze == Variant = "minimal"
Out(t, d)     == IF W(t) THEN d ELSE pad.dev
Held(t)       == W(t) /\ "LB" \in pad.dev                  \* guard_held() :528, _NullPad wButtons = 0
Desync        == [g EXCEPT !.syncB = FALSE, !.syncLB = FALSE]

Init ==
    /\ pad = [owner |-> None, dev |-> {}, fg |-> FALSE, kept |-> FALSE, gw |-> FALSE, bs |-> "none",
              due |-> [b \in Btn |-> "no"]]
    /\ g = [hHeld |-> {}, wantB |-> FALSE, syncB |-> FALSE, wantLB |-> FALSE, syncLB |-> FALSE,
            newer |-> {}, kill |-> FALSE, frozenA |-> FALSE, killFrozen |-> FALSE]
    /\ pc = [t \in Thr |-> IF t = "e" /\ ~UseNudge THEN "done" ELSE "idle"]
    /\ ops = [o |-> 0, n |-> 0, nb |-> 0]

-----------------------------------------------------------------------------
(* Pad methods — each is one lock block *)

\* control.py:231-243 freeze(take); :233-235 = refused (take=False, another holder)
Freeze(t, take) ==
    IF ~take /\ pad.owner \notin {None, t}
    THEN UNCHANGED <<pad, g>>
    ELSE /\ pad' = [pad EXCEPT !.owner = t, !.dev = {}, !.bs = "none", !.due = [b \in Btn |-> "no"],
                               !.fg = IF ClearOnFreeze THEN FALSE ELSE @,
                               !.kept = IF ClearOnFreeze THEN FALSE ELSE @,
                               !.gw = IF ClearOnFreeze THEN FALSE ELSE @]
         /\ g' = [Desync EXCEPT !.newer = {}, !.frozenA = FALSE]

\* control.py:248-254 unfreeze: only the holder lifts it; epoch bump → Mover resyncs
Unfreeze(t) ==
    IF pad.owner # t
    THEN UNCHANGED <<pad, g>>
    ELSE /\ pad' = [pad EXCEPT !.owner = None]
         /\ g' = Desync

\* control.py:420-435 neutral
Neutral(t) ==
    IF Blocked(t) THEN UNCHANGED <<pad, g>>
    ELSE /\ g' = [Desync EXCEPT !.newer = IF W(t) THEN {} ELSE @]
         /\ IF OwnerNeutral /\ pad.owner = t
            THEN pad' = [pad EXCEPT !.dev = {}, !.gw = FALSE, !.bs = "none", !.due["B"] = "no"]
            ELSE LET young == pad.bs = "young"
                     d     == (IF pad.fg THEN {"LB"} ELSE {}) \cup (IF young THEN {"B"} ELSE {})
                 IN pad' = [pad EXCEPT !.dev = Out(t, d),                          \* :423 reset, :425-426, :429-430
                                       !.gw = FALSE,                               \* :424
                                       !.due["B"] = IF young THEN "pending" ELSE "no",   \* :428, :431
                                       !.bs = IF young THEN "young" ELSE "none"]   \* :433

\* control.py:507-514 keep_guard(until in the future)
KeepGuard(t) ==
    IF Blocked(t) THEN UNCHANGED <<pad, g>>
    ELSE /\ pad' = IF Held(t)
                   THEN [pad EXCEPT !.fg = TRUE]                                    \* :508-510
                   ELSE [pad EXCEPT !.fg = TRUE, !.dev = Out(t, @ \cup {"LB"}), !.kept = TRUE]   \* :511-513
         /\ UNCHANGED g

\* control.py:518-524 unkeep
Unkeep(t) ==
    IF Blocked(t) \/ ~pad.kept \/ pad.fg THEN UNCHANGED <<pad, g>>
    ELSE /\ pad' = [pad EXCEPT !.kept = FALSE, !.dev = IF ~pad.gw /\ Held(t) THEN @ \ {"LB"} ELSE @]
         /\ UNCHANGED g

\* control.py:531-539 hold(LB, on) = guard(on).  n's request is recorded even when the call is blocked (Mover.guard_on)
Guard(t, on) ==
    /\ pad' = IF Blocked(t) THEN pad
              ELSE [pad EXCEPT !.gw = on, !.kept = IF on THEN FALSE ELSE @,
                               !.dev = IF ~on /\ pad.fg THEN @                     \* :536-537 early return
                                       ELSE Out(t, IF on THEN @ \cup {"LB"} ELSE @ \ {"LB"})]
    /\ g' = [g EXCEPT !.wantLB = on, !.syncLB = W(t)]

\* control.py:611-625 sprint(on).  n's request is recorded even when the call is blocked (Mover.mode)
Sprint(t, on) ==
    /\ pad' = IF Blocked(t) THEN pad
              ELSE IF on
              THEN [pad EXCEPT !.due["B"] = "no",                                  \* :613
                               !.bs = IF @ = "none" THEN "young" ELSE @,           \* :614-615
                               !.dev = IF pad.bs = "none" THEN Out(t, @ \cup {"B"}) ELSE @]   \* :616-617
              ELSE IF pad.bs = "young"
              THEN [pad EXCEPT !.due["B"] = "pending"]                             \* :619-622
              ELSE [pad EXCEPT !.bs = "none", !.dev = Out(t, @ \ {"B"})]           \* :623-625
    /\ g' = [g EXCEPT !.wantB = on, !.syncB = W(t)]

\* control.py:462-467 tap(A) (release_stick :460-461 only for R1 — not modelled)
Tap(t) ==
    IF Blocked(t) THEN UNCHANGED <<pad, g>>
    ELSE /\ pad' = [pad EXCEPT !.dev = Out(t, @ \cup {"A"}), !.due["A"] = "pending"]
         /\ g' = [g EXCEPT !.newer = @ \ {"A"}, !.frozenA = ~W(t)]

\* control.py:484 (unlocked emptiness check) + :486-495 release_due
ReleaseDue(t) ==
    IF Blocked(t) THEN UNCHANGED <<pad, g>>
    ELSE LET done == {b \in Btn : pad.due[b] = "ripe"}
         IN /\ pad' = [pad EXCEPT !.dev = Out(t, @ \ done),
                                  !.due = [b \in Btn |-> IF b \in done THEN "no" ELSE pad.due[b]],
                                  !.bs = IF "B" \in done THEN "none" ELSE @]
            /\ g' = [g EXCEPT !.kill = @ \/ (W(t) /\ done \cap g.newer \cap pad.dev # {}),
                              !.killFrozen = @ \/ (W(t) /\ g.frozenA /\ "A" \in done \cap g.newer \cap pad.dev),
                              !.newer = @ \ done,
                              !.frozenA = IF "A" \in done THEN FALSE ELSE @]

\* control.py:531-539 hold(A, on) — the generic hold path (button is not LB): press / release, _due untouched.
\* "A" stands for any button that is both tapped and held, e.g. Y: two_hand_toggle tap :551, two_hand_right hold :630/:634
HoldA(t, on) ==
    IF Blocked(t) THEN UNCHANGED <<pad, g>>
    ELSE /\ pad' = [pad EXCEPT !.dev = Out(t, IF on THEN @ \cup {"A"} ELSE @ \ {"A"})]
         /\ g' = [g EXCEPT !.newer = IF ~W(t) THEN @
                                     ELSE IF on THEN (IF pad.due["A"] # "no" THEN @ \cup {"A"} ELSE @)
                                     ELSE @ \ {"A"}]

\* control.py:472-474 press(A): first lock block
PressDown(t) ==
    /\ pad' = [pad EXCEPT !.dev = Out(t, @ \cup {"A"})]
    /\ g' = [g EXCEPT !.hHeld = @ \cup {"A"},
                      !.newer = IF W(t) /\ pad.due["A"] # "no" THEN @ \cup {"A"} ELSE @]

\* control.py:478-480 press(A): second lock block (in finally) — the :476 sleep between holds no lock
PressUp(t) ==
    /\ pad' = [pad EXCEPT !.dev = Out(t, @ \ {"A"})]
    /\ g' = [g EXCEPT !.hHeld = @ \ {"A"}, !.newer = IF W(t) THEN @ \ {"A"} ELSE @]

-----------------------------------------------------------------------------
(* Threads *)

Go(t, from, to) == pc[t] = from /\ pc' = [pc EXCEPT ![t] = to] /\ UNCHANGED ops

\* watch.py:291 freeze → quitout.py:158 neutral → quitout._press (Pad.press) → watch.py:308 neutral → :309 unfreeze
hFreeze    == Go("h", "idle", IF Script = "quit" THEN "n1" ELSE "tp") /\ Freeze("h", TRUE)
hNeutral1  == Go("h", "n1", "pd") /\ Neutral("h")
hTap       == Go("h", "tp", "pd") /\ Tap("h")
hPressDown == Go("h", "pd", "pu") /\ PressDown("h")
hPressUp   == Go("h", "pu", "n2") /\ PressUp("h")
hNeutral2  == Go("h", "n2", "uf") /\ Neutral("h")
hUnfreeze  == Go("h", "uf", "done") /\ Unfreeze("h")

\* watch.py:233 freeze(take=False) → (move, not modelled) → :242 neutral → :243 unfreeze
eFreeze    == /\ pc["e"] = "idle"
              /\ pc' = [pc EXCEPT !["e"] = IF pad.owner \in {None, "e"} THEN "en" ELSE "done"]
              /\ Freeze("e", FALSE) /\ UNCHANGED ops
eNeutral   == Go("e", "en", "eu") /\ Neutral("e")
eUnfreeze  == Go("e", "eu", "done") /\ Unfreeze("e")

\* the call bound: every o / n call (also one that changes nothing) uses one of MaxOps
Step(t) == /\ ops[t] < MaxOps
           /\ ops' = [ops EXCEPT ![t] = @ + 1, !.nb = IF pad.owner \notin {None, t} THEN @ + 1 ELSE @]
           /\ UNCHANGED pc

oKeepGuard  == Step("o") /\ KeepGuard("o")
oUnkeep     == Step("o") /\ Unkeep("o")
nSprintOn   == Step("n") /\ Sprint("n", TRUE)
nSprintOff  == Step("n") /\ Sprint("n", FALSE)
nGuardOn    == NGuard /\ Step("n") /\ Guard("n", TRUE)
nGuardOff   == NGuard /\ Step("n") /\ Guard("n", FALSE)
nTap        == NTap /\ Step("n") /\ Tap("n")
nHoldOn     == NHold /\ Step("n") /\ HoldA("n", TRUE)
nHoldOff    == NHold /\ Step("n") /\ HoldA("n", FALSE)
nReleaseDue == Step("n") /\ ReleaseDue("n")
nNeutral    == Step("n") /\ Neutral("n")

TickGuard == pad.fg /\ pad' = [pad EXCEPT !.fg = FALSE] /\ UNCHANGED <<g, pc, ops>>
TickBAge  == pad.bs = "young" /\ pad' = [pad EXCEPT !.bs = "old"] /\ UNCHANGED <<g, pc, ops>>
TickDue   == \E b \in Btn : pad.due[b] = "pending" /\ pad' = [pad EXCEPT !.due[b] = "ripe"] /\ UNCHANGED <<g, pc, ops>>

Next == \/ hFreeze \/ hNeutral1 \/ hTap \/ hPressDown \/ hPressUp \/ hNeutral2 \/ hUnfreeze
        \/ eFreeze \/ eNeutral \/ eUnfreeze
        \/ oKeepGuard \/ oUnkeep
        \/ nSprintOn \/ nSprintOff \/ nGuardOn \/ nGuardOff \/ nTap \/ nHoldOn \/ nHoldOff \/ nReleaseDue \/ nNeutral
        \/ TickGuard \/ TickBAge \/ TickDue

Spec == Init /\ [][Next]_vars

-----------------------------------------------------------------------------
(* Safety properties (invariants) *)

TypeOK ==
    /\ pad.owner \in Thr \cup {None} /\ pad.dev \subseteq Btn /\ pad.bs \in {"none", "young", "old"}
    /\ pad.due \in [Btn -> {"no", "pending", "ripe"}] /\ g.hHeld \subseteq Btn /\ g.newer \subseteq Btn

Menu == Script = "quit" /\ pc["h"] \in {"pd", "pu", "n2"}

\* S1 (K1 + K2): in the quit-out's menu window (after quit_out's first neutral, before the closing neutral) the device
\* carries only what the holder itself holds
S1_MenuClean == Menu => pad.dev \subseteq g.hHeld
\* S1b (K2 alone): the same window, B only — so TLC can't answer with the LB (K1) trace
S1b_MenuNoB  == Menu => "B" \notin pad.dev

\* S2 (K3): A is down on the device only while someone still means it (the holder's press, or a release still scheduled)
S2_NoOrphanA == "A" \in pad.dev => ("A" \in g.hHeld \/ pad.due["A"] # "no")

\* S3 hand-over: from its freeze until its unfreeze the quit-out holder keeps the pad (the nudge's unfreeze can't lift it)
S3_Handoff == pc["h"] \in {"n1", "tp", "pd", "pu", "n2", "uf"} => pad.owner = "h"

\* S4 recovery: once nobody holds the freeze, n's latest sprint / guard request — made after the last epoch bump, so
\* nav.Mover won't repeat it — is on the device
S4_ReSprint == (pad.owner = None /\ g.wantB /\ g.syncB) => "B" \in pad.dev
S4_ReGuard  == (pad.owner = None /\ g.wantLB /\ g.syncLB) => "LB" \in pad.dev

\* S5 (rewritten): a release reservation never lets go of a press made after it (old reservation kills a new input)
S5_StaleNoKill == ~g.kill
\* S5f: the freeze-made part of S5 — the killing reservation came from a call that went to _NullPad during a freeze
S5f_FrozenDueNoKill == ~g.killFrozen

\* S6 (informational): LB is down only while someone means it — S6_post only after the quit-out is over
S6_NoOrphanLB == "LB" \in pad.dev => (pad.gw \/ pad.kept \/ pad.fg)
S6_post == (pc["h"] = "done" /\ pad.owner = None) => S6_NoOrphanLB

-----------------------------------------------------------------------------
(* Reachability probes: each is EXPECTED to be violated.  A probe that holds means the matching property's   *)
(* interesting case is out of reach under that bound — the property was then not really checked.            *)

R1_menuAfterBlockedCall == ~(Menu /\ ops.nb >= 1)
R1_menuWithKeep         == ~(Menu /\ pad.fg)
R1_menuWithYoungB       == ~(Menu /\ pad.bs = "young")
R2_ripeAWhileFrozen     == ~(pad.owner = "h" /\ pad.due["A"] = "ripe" /\ "A" \in pad.dev /\ ops.n < MaxOps)
R3_nudgeUnfreezeLate    == ~(pc["e"] = "eu" /\ pad.owner = "h")
R4_resprintAfterQuit    == ~(pc["h"] = "done" /\ pad.owner = None /\ g.wantB /\ g.syncB /\ ops.nb >= 1)
R4_reguardAfterQuit     == ~(pc["h"] = "done" /\ pad.owner = None /\ g.wantLB /\ g.syncLB /\ ops.nb >= 1)
R5_newerPressRipe       == ~("A" \in g.newer /\ pad.due["A"] = "ripe" /\ ops.n < MaxOps)
R6_afterQuitWithKeep    == ~(pc["h"] = "done" /\ pad.owner = None /\ ops.nb >= 1 /\ pad.kept /\ ops.o < MaxOps)
=============================================================================
