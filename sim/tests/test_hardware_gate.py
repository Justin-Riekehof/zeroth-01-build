"""sim/tools/hardware_gate.py: the targets the Pi sends (clamp + command rate limiter)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "sim" / "tools"))
import hardware_gate as G                                        # noqa: E402


def test_sent_targets_clamp_then_rate_limit():
    a = np.array([[[1.0, 0.0], [1.0, 0.0], [1.0, 0.0]]])          # 1 episode, 3 steps, 2 joints
    q0 = np.zeros((1, 2))
    s = G.sent_targets(a, q0, np.array([-1.0, -1.0]), np.array([0.5, 1.0]), np.array([0.2, 0.2]))
    np.testing.assert_allclose(s[0, :, 0], [0.2, 0.4, 0.5])     # rate limited, then clamped at the 0.5 limit
    np.testing.assert_allclose(s[0, :, 1], [0.0, 0.0, 0.0])


def test_run_config_reads_scalars(tmp_path):
    f = tmp_path / "config.yaml"
    f.write_text("cmd_rate_fraction: 0.7\nleg_servo_speed: 2000\nlist:\n  - 1\n")
    c = G.run_config(f)
    assert c["cmd_rate_fraction"] == "0.7" and c["leg_servo_speed"] == "2000"


def test_sent_targets_with_filter():
    a = np.ones((1, 3, 1))
    s = G.sent_targets(a, np.zeros((1, 1)), np.array([-5.0]), np.array([5.0]), np.array([9.0]), alpha=0.5)
    np.testing.assert_allclose(s[0, :, 0], [0.5, 0.75, 0.875])


def test_no_forward_command_drops_the_tracking_criterion():
    import math
    m = {"falls": 0, "target_out_share": 0, "margin_share": 0, "speed_leg_p99": 1, "speed_arm_p99": 1,
         "speed_over_share": 0, "speed_buffer_share": 0, "gap_mean": 0, "gap_p99": 0, "rate_mean": 0, "rate_p99": 0,
         "saturation_share": 0, "jerk_p99": 0, "highfreq_share": 0, "tracking_ratio": float("nan")}
    assert "tracking_ratio" not in [r[0] for r in G.verdict(m)]
    assert math.isfinite(G.score(m))
