"""Camera motion capture kinematics (zbot_core.mocap): landmarks -> arm angles.

Landmarks are synthesized with the robot's own forward kinematics (CAD joint
axes), so a round trip proves the inverse is consistent; the 'natural pose'
tests pin the sign conventions to what the limits and demos/wave.json use."""
import json
import math
from pathlib import Path

import pytest

from zbot_core.mocap import arm_angles, wrap

LIMITS = json.loads((Path(__file__).resolve().parents[3] / "hardware" / "joint_limits.json").read_text())


def rx(p, v):
    c, s = math.cos(math.radians(p)), math.sin(math.radians(p))
    return (v[0], v[1] * c - v[2] * s, v[1] * s + v[2] * c)


def ry(a, v):
    c, s = math.cos(math.radians(a)), math.sin(math.radians(a))
    return (v[0] * c + v[2] * s, v[1], -v[0] * s + v[2] * c)


def fk(side, pitch, yaw, elbow):
    """Upper-arm / forearm direction in the robot frame (X left, Y back, Z up)."""
    p = -pitch if side == "left" else pitch
    phi_u = -yaw
    down = (0.0, 0.0, -1.0)
    return rx(p, ry(phi_u, down)), rx(p, ry(phi_u + elbow, down))


def person(arms: dict, hips=True, facing=1):
    """33 world landmarks of a person facing the camera (lat = +x, up = -y, fwd = -z)
    holding the given robot arm angles {side: (pitch, yaw, elbow)}."""
    lm = [[0.0, 0.0, 0.0, 0.0] for _ in range(33)]

    def put(i, v, vis=1.0):
        lm[i] = [v[0], v[1], v[2], vis]

    def mp(v):                       # robot frame -> camera world (X left=+x, Z up=-y, Y back=+z)
        return (v[0], -v[2], v[1])

    put(11, (0.2, -0.5, 0)); put(12, (-0.2, -0.5, 0))
    put(23, (0.1, 0, 0), 1.0 if hips else 0.1); put(24, (-0.1, 0, 0), 1.0 if hips else 0.1)
    for side, (i_s, i_e, i_w) in {"left": (11, 13, 15), "right": (12, 14, 16)}.items():
        if side not in arms:
            continue
        sh = lm[i_s][:3]
        u, f = fk(side, *arms[side])
        el = tuple(a + 0.3 * b for a, b in zip(sh, mp(u)))
        wr = tuple(a + 0.25 * b for a, b in zip(el, mp(f)))
        put(i_e, el); put(i_w, wr)
    return lm


def angles(arms, **kw):
    return arm_angles(person(arms, **{k: v for k, v in kw.items() if k == "hips"}), LIMITS,
                      **{k: v for k, v in kw.items() if k != "hips"})


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("hips", [True, False])
@pytest.mark.parametrize("pitch,yaw,elbow", [
    (0, 0, 0), (30, 20, 40), (-30, 10, 30), (45, -10, 60), (60, 30, -20), (-45, 25, 50)])
def test_roundtrip(side, hips, pitch, yaw, elbow):
    # the elbow flexes the other way on the left (limits: left -95..70, right -60..100)
    elbow = -elbow if side == "left" else elbow
    a, info = angles({side: (pitch, yaw if side == "left" else -yaw, elbow)}, hips=hips)
    assert info["tracked"] and info["clamped"] == []
    want = {f"{side}_shoulder_pitch": pitch, f"{side}_shoulder_yaw": yaw if side == "left" else -yaw,
            f"{side}_elbow_yaw": elbow}
    for j, v in want.items():
        if j.endswith("pitch") and abs(yaw) > 80:
            continue
        assert a[j] == pytest.approx(v, abs=0.2), (j, a)


def test_arm_down_is_zero():
    a, _ = angles({"left": (0, 0, 0), "right": (0, 0, 0)})
    assert all(abs(v) < 0.2 for v in a.values()) and len(a) == 6


def test_left_arm_out_to_the_side():
    # person's left arm raised sideways: left yaw positive, right arm untouched
    a, _ = angles({"left": (0, 35, 0), "right": (0, 0, 0)})
    assert a["left_shoulder_yaw"] == pytest.approx(35, abs=0.2)
    assert abs(a["right_shoulder_yaw"]) < 0.2


def test_right_arm_out_to_the_side_is_negative():
    a, _ = angles({"right": (0, -40, 0)})      # same sign as the right wave in demos/wave.json
    assert a["right_shoulder_yaw"] == pytest.approx(-40, abs=0.2)


def test_arm_forward_signs():
    # both arms swung forward (-Y): left pitch +, right pitch - (mirrored axes)
    a, _ = angles({"left": (40, 0, 0), "right": (-40, 0, 0)})
    assert a["left_shoulder_pitch"] == pytest.approx(40, abs=0.2)
    assert a["right_shoulder_pitch"] == pytest.approx(-40, abs=0.2)
    lm = person({"left": (40, 0, 0)})
    assert lm[13][2] < lm[11][2]               # elbow nearer the camera than the shoulder = forward


def test_clamped_to_limits_and_reported():
    # arm straight out sideways (90 deg) exceeds the +-45 deg shoulder yaw
    a, info = angles({"left": (0, 90, 0)})
    hi = LIMITS["left_shoulder_yaw"]["max_deg"]
    assert a["left_shoulder_yaw"] == hi
    assert "left_shoulder_yaw" in info["clamped"]
    for j, v in a.items():
        assert LIMITS[j]["min_deg"] <= v <= LIMITS[j]["max_deg"]


def test_untracked_arm_is_omitted():
    lm = person({"left": (10, 10, 10), "right": (10, -10, 10)})
    lm[14][3] = 0.1                            # right elbow not visible
    a, _ = arm_angles(lm, LIMITS)
    assert any(j.startswith("left_") for j in a) and not any(j.startswith("right_") for j in a)


def test_no_person():
    assert arm_angles([[0, 0, 0, 0]] * 33, LIMITS)[0] == {}
    assert arm_angles([], LIMITS)[0] == {}


def test_mirror_swaps_arms_and_keeps_outward():
    a, _ = angles({"left": (0, 30, 0)}, mirror=True)       # my left arm out -> robot RIGHT arm out
    assert a["right_shoulder_yaw"] == pytest.approx(-30, abs=0.2) and "left_shoulder_yaw" not in a


def test_flip_forward():
    a, _ = angles({"left": (40, 0, 0)}, flip_forward=True)
    assert a["left_shoulder_pitch"] == pytest.approx(-40, abs=0.2)


def test_turned_body_still_works():
    """Shoulders rotated 60 deg about the vertical: angles are body-relative."""
    lm = person({"left": (30, 20, 0)})
    c, s = math.cos(math.radians(60)), math.sin(math.radians(60))
    for p in lm:
        p[0], p[2] = p[0] * c + p[2] * s, -p[0] * s + p[2] * c
    a, _ = arm_angles(lm, LIMITS)
    assert a["left_shoulder_pitch"] == pytest.approx(30, abs=0.3)
    assert a["left_shoulder_yaw"] == pytest.approx(20, abs=0.3)


def test_wave_pose():
    """demos/wave.json right arm: shoulder yaw -57, elbow ~112 -> forearm up."""
    a, info = angles({"right": (0, -57, 112)})
    assert a["right_shoulder_yaw"] == LIMITS["right_shoulder_yaw"]["min_deg"]   # -50: limited
    assert a["right_elbow_yaw"] == LIMITS["right_elbow_yaw"]["max_deg"]         # 100: limited
    assert set(info["clamped"]) == {"right_shoulder_yaw", "right_elbow_yaw"}


def test_wrap():
    assert wrap(190) == -170 and wrap(-180) == 180
