"""Camera motion capture -> arm joint angles.

The browser runs the pose detector on the webcam image (MediaPipe Pose) and
sends the 33 *world* landmarks (metres, hip-centred, x right / y down / z away
from the camera — a right-handed system). This module turns them into the
robot's shoulder/elbow angles; the engine then clamps them to the joint limits.

Body frame (from the landmarks themselves, so the person may turn and lean):
    lat  shoulder line, pointing to the person's LEFT
    up   spine, hips -> shoulders (shoulders only: camera vertical, if the hips
         are out of view — the usual webcam case)
    fwd  = lat x up, the direction the person faces

Robot frame (CAD): X = robot-left, Y = back (the head camera looks along -Y),
Z = up. Left/right arm of the person drive the same-named robot arm, so the
robot moves "like me" (mirror=True gives mirror-image control instead).

Arm kinematics (hardware/joint axes from the CAD joints file): the pitch axis
is X, yaw and elbow are parallel hinges along Y that pitch swings through the
sagittal plane:

    upper arm  d = Rx(p) Ry(phi_u) (0,0,-1),   phi_u = -yaw
    forearm    f = Rx(p) Ry(phi_f) (0,0,-1),   phi_f = phi_u + elbow
    p = +pitch (right arm) / -pitch (left arm)    [CAD axis +X / -X]

Positive yaw therefore abducts the left arm and adducts the right one, and
forward is positive pitch on the left, negative on the right — the same signs
the limits in hardware/joint_limits.json and demos/wave.json already use.
"""

import math

NOSE, L_SH, R_SH, L_EL, R_EL, L_WR, R_WR, L_HIP, R_HIP = 0, 11, 12, 13, 14, 15, 16, 23, 24
MIN_VIS = 0.5          # landmark visibility needed for an arm to be used
HIP_VIS = 0.5          # ... and for the hips to define the spine
PITCH_MIN_XY = 0.2     # upper arm (nearly) along the pitch axis: pitch undefined
FOREARM_MIN_PLANE = 0.25   # forearm (nearly) out of the arm plane: elbow undefined

ARM = {"left": (L_SH, L_EL, L_WR), "right": (R_SH, R_EL, R_WR)}


def _sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def _dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def _len(a): return math.sqrt(_dot(a, a))
def _cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
                          a[0] * b[1] - a[1] * b[0])


def _unit(a):
    n = _len(a)
    return None if n < 1e-6 else (a[0] / n, a[1] / n, a[2] / n)


def wrap(deg: float) -> float:
    """Into (-180, 180]."""
    d = (deg + 180.0) % 360.0 - 180.0
    return 180.0 if d == -180.0 else d


def _excess(deg: float, lim) -> float:
    if not lim:
        return 0.0
    return max(0.0, lim["min_deg"] - deg, deg - lim["max_deg"])


def body_frame(lm):
    """(lat, up, fwd, hips_ok) from the landmarks, or None if the shoulders are not seen."""
    if lm[L_SH][3] < MIN_VIS or lm[R_SH][3] < MIN_VIS:
        return None
    ls, rs = lm[L_SH][:3], lm[R_SH][:3]
    lat = _unit(_sub(ls, rs))
    if lat is None:
        return None
    mid_sh = tuple((a + b) / 2 for a, b in zip(ls, rs))
    hips_ok = lm[L_HIP][3] >= HIP_VIS and lm[R_HIP][3] >= HIP_VIS
    if hips_ok:
        mid_hip = tuple((a + b) / 2 for a, b in zip(lm[L_HIP][:3], lm[R_HIP][:3]))
        up = _unit(_sub(mid_sh, mid_hip))
    else:
        up = (0.0, -1.0, 0.0)                  # camera vertical (y points down)
    if up is None:
        return None
    k = _dot(up, lat)                          # square the frame: spine _|_ shoulder line
    up = _unit((up[0] - k * lat[0], up[1] - k * lat[1], up[2] - k * lat[2]))
    if up is None:
        return None
    return lat, up, _cross(lat, up), hips_ok


def torso_twist(lm) -> float | None:
    """Shoulder line vs hip line about the spine, deg (+ = shoulders turned to the
    person's left of the hips). None unless both lines are visible."""
    fr = body_frame(lm)
    if fr is None or not fr[3]:
        return None
    lat, up, _, _ = fr
    hl = _unit(_sub(lm[L_HIP][:3], lm[R_HIP][:3]))
    if hl is None:
        return None
    # signed angle of lat relative to the hip line, about the spine
    return math.degrees(math.atan2(_dot(_cross(hl, lat), up), _dot(hl, lat)))


def _to_robot(v, fr, mirror: bool, flip_fwd: bool):
    lat, up, fwd, _ = fr
    sx = -1.0 if mirror else 1.0
    sy = 1.0 if flip_fwd else -1.0             # robot Y = back = -fwd
    return (sx * _dot(v, lat), sy * _dot(v, fwd), _dot(v, up))


def _arm(side: str, u, w, lim, st: dict):
    """Joint angles for one arm from the upper-arm / forearm direction in the
    robot frame. `st` keeps the last pitch (hint when it is undefined)."""
    out, hit = {}, []
    d = _unit(u)
    if d is None:
        return out, hit
    dx, dy, dz = d
    sgn = -1.0 if side == "left" else 1.0      # p_eff = sgn * pitch
    phi = math.degrees(math.asin(max(-1.0, min(1.0, -dx))))
    defined = math.hypot(dy, dz) >= PITCH_MIN_XY
    if defined:
        p_a = math.degrees(math.atan2(dy, -dz))
    else:
        p_a = st.get("p_eff", 0.0)             # arm sideways: keep the last pitch
    # the same direction has a second (p+180, 180-phi) decomposition: take the
    # one that needs less clamping (an arm raised past the shoulder, say)
    cands = [(p_a, phi), (wrap(p_a + 180.0), wrap(180.0 - phi))]
    def cost(c):
        p_eff, ph = c
        return (_excess(sgn * p_eff, lim.get(f"{side}_shoulder_pitch"))
                + _excess(-ph, lim.get(f"{side}_shoulder_yaw")))
    p_eff, ph = min(cands, key=cost)
    st["p_eff"] = p_eff
    pitch, yaw = sgn * p_eff, -ph
    if defined:
        out[f"{side}_shoulder_pitch"] = pitch
    out[f"{side}_shoulder_yaw"] = yaw
    f = _unit(w)
    if f is not None and (defined or "p_eff" in st):
        c, s = math.cos(math.radians(p_eff)), math.sin(math.radians(p_eff))
        fx, fy, fz = f[0], f[1] * c + f[2] * s, -f[1] * s + f[2] * c   # Rx(-p) f
        if math.hypot(fx, fz) >= FOREARM_MIN_PLANE:
            phi_f = math.degrees(math.atan2(-fx, -fz))
            out[f"{side}_elbow_yaw"] = wrap(phi_f - ph)
    for j, v in list(out.items()):
        L = lim.get(j)
        if L and _excess(v, L) > 0:
            hit.append(j)
            out[j] = max(L["min_deg"], min(L["max_deg"], v))
    return out, hit


def arm_angles(lm, limits: dict, state: dict | None = None, mirror: bool = False,
               flip_forward: bool = False):
    """lm: 33 x [x, y, z, visibility] world landmarks.
    Returns (angles {joint: deg, CAD frame, clamped to `limits`}, info).
    Arms that are not visible are simply absent (the robot holds them)."""
    state = state if state is not None else {}
    info = {"tracked": False, "hips": False, "twist_deg": None, "clamped": []}
    if not isinstance(lm, (list, tuple)) or len(lm) < 33:
        return {}, info
    fr = body_frame(lm)
    if fr is None:
        return {}, info
    info.update(tracked=True, hips=fr[3], twist_deg=_round(torso_twist(lm)))
    angles = {}
    for human in ("left", "right"):
        robot = ({"left": "right", "right": "left"}[human]) if mirror else human
        s_i, e_i, w_i = ARM[human]
        if min(lm[s_i][3], lm[e_i][3], lm[w_i][3]) < MIN_VIS:
            continue
        u = _to_robot(_sub(lm[e_i][:3], lm[s_i][:3]), fr, mirror, flip_forward)
        w = _to_robot(_sub(lm[w_i][:3], lm[e_i][:3]), fr, mirror, flip_forward)
        out, hit = _arm(robot, u, w, limits, state.setdefault(robot, {}))
        angles.update(out)
        info["clamped"] += hit
    return {j: round(v, 1) for j, v in angles.items()}, info


def _round(v):
    return None if v is None else round(v, 1)
