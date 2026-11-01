"""Hand-over logic of sim/tools/train_chain.py (unattended curriculum)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sim" / "tools"))
import train_chain as C                                          # noqa: E402


def ev(step, falls, tr, hf=0.4):
    return {"step": step, "score": 0.7, "passed": False, "failed": ["highfreq_share"],
            "metrics": {"falls": falls, "tracking_ratio": tr, "highfreq_share": hf, "jerk_p99": 0.086}}


def test_walks_needs_two_clean_evals_in_a_row():
    assert not C.walks([ev(1, 0, 0.8)])
    assert not C.walks([ev(1, 0, 0.8), ev(2, 1, 0.9)])
    assert not C.walks([ev(1, 0, 0.8), ev(2, 0, 0.65)])
    assert C.walks([ev(1, 0, 0.75), ev(2, 0, 0.71)])
    assert not C.walks([ev(1, 0, 0.75), {"step": 2, "score": 0.0, "passed": False, "error": "x"}])


def test_pick_walking_and_calm():
    hist = [ev(1, 0, 0.6, 0.30), ev(2, 1, 0.95, 0.10), ev(3, 0, 0.8, 0.40), ev(4, 0, 0.5, 0.05)]
    assert C.pick(hist, "walking")["step"] == 3          # no falls, best tracking
    assert C.pick(hist, "calm")["step"] == 1             # no falls, tracking >= 0.6, least > 5 Hz
    assert C.pick([ev(1, 2, 0.9)], "walking") is None


def test_overrides_replace_and_add(monkeypatch):
    monkeypatch.setattr(C.W, "overrides", lambda run: ["a=1", "action_jerk_penalty=-0.1", "b=x"])
    assert C.overrides("r", {"action_jerk_penalty": -1.0, "new": 2}) == ["a=1", "action_jerk_penalty=-1.0", "b=x",
                                                                         "new=2"]


def test_v6_stops_on_collapse_or_success(monkeypatch):
    st = C.STAGES[1]
    monkeypatch.setattr(C, "history", lambda run: [ev(1, 0, 0.8)])
    monkeypatch.setattr(C, "done", lambda run: None)
    assert C.ready(st) == (False, "")
    monkeypatch.setattr(C, "done", lambda run: {"reason": "tracking collapsed (below 30% ...)"})
    assert C.ready(st)[1].startswith("STOP")
    monkeypatch.setattr(C, "done", lambda run: {"reason": "stagnation"})
    assert C.ready(st)[0]
    h = ev(1, 0, 0.8); h["failed"] = ["tracking_ratio"]
    monkeypatch.setattr(C, "history", lambda run: [h])
    assert C.ready(st)[1].startswith("STOP: jitter criteria met")


def sev(step, falls, tr, real):
    e = ev(step, falls, tr)
    e["metrics"]["real_step_share"] = real
    return e


def test_speed_curriculum_hand_over_and_pick(monkeypatch):
    assert C.steps_walk([sev(1, 0, 0.7, 0.6), sev(2, 0, 0.65, 0.55)])
    assert not C.steps_walk([sev(1, 0, 0.7, 0.6), sev(2, 0, 0.9, 0.3)])        # walks, but hops again
    hist = [sev(1, 0, 0.9, 0.2), sev(2, 0, 0.7, 0.8), sev(3, 1, 0.95, 0.9), sev(4, 0, 0.5, 0.9)]
    assert C.pick(hist, "steps")["step"] == 2                                    # no fall, stepping, best tracking
    falling = [sev(1, 2, 3.1, 0.9), sev(2, 1, 1.1, 0.9), sev(3, 1, 0.4, 0.9), sev(4, 0, 2.0, 0.3)]
    assert C.pick(falling, "steps")["step"] == 2                                 # none fall-free while stepping: fewest
    first, second = C.SPEED[0], C.SPEED[1]
    assert C.ready(first)[0] and "fixed start" in C.ready(first)[1]
    monkeypatch.setattr(C, "history", lambda run: [sev(1, 0, 0.2, 0.9)])
    monkeypatch.setattr(C, "done", lambda run: None)
    assert C.ready(second) == (False, "")
    monkeypatch.setattr(C, "done", lambda run: {"reason": "tracking collapsed (...)"})
    assert C.ready(second)[1].startswith("STOP")


def test_stand_stage_hands_over_when_fall_free(monkeypatch):
    C.STAGE_PICK.update({st["run"]: st["pick"] for st in C.SPEED3})
    stand, first_speed = C.SPEED3[0], C.SPEED3[1]
    assert C.ready(stand)[0]                                                     # fixed start from v13 1455
    assert stand["set"]["speed_zero_prob"] == 1.0 and stand["set"]["stride_reward"] == 0.0
    assert first_speed["set"]["stride_reward"] == 15.0 and first_speed["set"]["target_speed_max"] == 0.03
    monkeypatch.setattr(C, "done", lambda run: None)
    monkeypatch.setattr(C, "history", lambda run: [sev(1, 0, float("nan"), 0.8), sev(2, 1, float("nan"), 0.8)])
    assert C.ready(first_speed) == (False, "")
    monkeypatch.setattr(C, "history", lambda run: [sev(1, 0, float("nan"), 0.8), sev(2, 0, float("nan"), 0.7)])
    assert C.ready(first_speed)[0]


def test_bootstrap_hands_over_once_it_survives_and_steps(monkeypatch):
    C.STAGE_PICK.update({st["run"]: st["pick"] for st in C.BOOT})
    st = C.BOOT[0]
    monkeypatch.setattr(C, "done", lambda run: None)
    monkeypatch.setattr(C, "history", lambda run: [sev(1, 4, 1.0, 0.6), sev(2, 5, 1.0, 0.6)])
    assert C.ready(st) == (False, "")
    hist = [sev(1, 4, 1.0, 0.6), sev(2, 3, 1.2, 0.7)]
    monkeypatch.setattr(C, "history", lambda run: hist)
    assert C.ready(st)[0]
    assert C.pick(hist, "boot")["step"] == 2                                     # fewest falls
    assert st["set"]["naive_velocity_scale"] == 0.0 and st["set"]["track_window_s"] == 0.8
