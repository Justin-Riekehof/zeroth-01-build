"""Decision logic of sim/tools/calm_watch.py (when a training run may end)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sim" / "tools"))
import calm_watch as W                                           # noqa: E402


def h(score, passed=False):
    return {"score": score, "passed": passed}


def test_keeps_training_while_the_score_improves():
    hist = [h(s) for s in (0.40, 0.45, 0.52, 0.58, 0.63, 0.70)]
    assert W.decide(hist) is None


def test_stops_on_stagnation_only_after_a_full_window():
    assert W.decide([h(0.5), h(0.5), h(0.5)]) is None                          # too early to say
    hist = [h(s) for s in (0.40, 0.55, 0.60, 0.60, 0.601, 0.598, 0.60)]       # nothing better than 0.60 for 4 evals
    assert "stagnation" in W.decide(hist)
    hist = [h(s) for s in (0.40, 0.55, 0.60, 0.60, 0.601, 0.598, 0.64)]       # +6 % in the window: still learning
    assert W.decide(hist) is None


def test_gate_must_pass_twice_in_a_row():
    assert W.decide([h(0.9, True)]) is None
    assert W.decide([h(0.9, True), h(0.8, False)]) is None
    assert "respected" in W.decide([h(0.7), h(0.95, True), h(0.96, True)])


def test_passing_wins_over_stagnation():
    hist = [h(0.9), h(0.9), h(0.9), h(0.9), h(0.9, True), h(0.9, True)]
    assert "respected" in W.decide(hist)


def test_stops_when_a_walking_run_stops_walking():
    t = lambda tr, step: {"score": 0.73, "passed": False, "step": step, "metrics": {"tracking_ratio": tr}}
    v3 = [t(tr, s) for tr, s in ((0.45, 680), (0.47, 725), (0.30, 765), (0.23, 810), (0.19, 850))]   # servo_ctrl_v3
    assert "tracking collapsed" in W.decide(v3, window=6, min_iters=400)
    assert W.decide(v3[:4], window=6, min_iters=400) is None                   # one eval below the floor is not enough
    never = [t(tr, s) for tr, s in ((0.0, 0), (0.05, 40), (0.1, 80), (0.1, 120))]   # from scratch: never walked yet
    assert W.decide(never) is None
    assert W.decide([t(0.5, 0), {"score": 0.0, "passed": False, "step": 40, "error": "x"}, t(0.1, 80)]) is None
    assert W.decide(v3, window=6, min_iters=400, collapse_after=300) is None     # grace period for a gait change


def test_no_stagnation_before_min_iters():
    flat = [{"score": 0.3, "passed": False, "step": s} for s in range(0, 400, 40)]       # 10 flat evals over 360 its
    assert W.decide(flat, window=6, min_iters=600) is None
    flat += [{"score": 0.3, "passed": False, "step": s} for s in range(400, 700, 40)]
    assert "stagnation" in W.decide(flat, window=6, min_iters=600)


def test_assets_come_from_the_runs_launch_line(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "T", tmp_path)
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    (tmp_path / "a" / "launch.sh").write_text("GPU=0 ASSETS=zbot-cad-tpu /x/train_backpack.sh a servo_model=True\n")
    (tmp_path / "b" / "launch.sh").write_text("GPU=1 /x/train_backpack.sh b servo_model=True\n")
    assert W.assets("a") == "zbot-cad-tpu" and W.assets("b") == "zbot-cad"


def test_failed_evaluation_is_not_recorded():
    src = (Path(__file__).resolve().parents[2] / "sim" / "tools" / "calm_watch.py").read_text()
    i = src.index("res = evaluate(run, latest)")
    assert src.index('if "error" in res:', i) < src.index("history.append(res)", i)


def test_stops_a_run_that_never_stands():
    fell = lambda step: {"score": 0.09, "passed": False, "step": step, "metrics": {"falls": 16, "error": "every episode fell"}}
    assert W.decide([fell(s) for s in range(45, 290, 40)][:5], window=6, min_iters=800) is None
    assert "never stands" in W.decide([fell(s) for s in range(45, 330, 40)], window=6, min_iters=800)
    early = [fell(s) for s in range(0, 240, 40)]
    assert W.decide(early, window=6, min_iters=800) is None                      # only 200 iterations: too early
