"""Static/quasi-static stance checks for taught-in demo poses (MuJoCo, zbot-cad).

Servos are modelled as torque-limited PD position holds (sys-ID damping/armature/
friction from sim/assets/zbot-cad/actuators). Angles are the demo's servo degrees
(qpos 0 = servo zero, as in the walking task). `settle()` drops the robot onto the
floor in a pose and reports whether it stays up.
"""
import json
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
ASSET = ROOT / "sim/assets/zbot-cad"
META = json.loads((ASSET / "metadata.json").read_text())["joint_name_to_metadata"]
ACT = {p.stem: json.loads(p.read_text()) for p in (ASSET / "actuators").glob("*.json")}
KP, KD = 30.0, 0.6           # Nm/rad, Nm/(rad/s) — stiff hold, roughly a P-register of 32


def load(mass_scale=1.0, right_sole=None, left_sole=None):
    spec = mujoco.MjSpec.from_file(str(ASSET / "robot.mjcf"))
    spec.worldbody.add_geom(name="floor", type=mujoco.mjtGeom.mjGEOM_PLANE, size=[2, 2, 0.1],
                            condim=6, friction=[0.8, 0.02, 0.01])
    m = spec.compile()
    m.opt.timestep = 0.001
    # stiff, hard contact: the default 0.02 s contact time constant makes the floor ~6x softer than a
    # printed foot on a floor and a one-leg stance tips from contact compliance alone
    for g in range(m.ngeom):
        if m.geom_contype[g] or m.geom_conaffinity[g]:
            m.geom_solref[g] = [0.004, 1.0]
            m.geom_solimp[g] = [0.95, 0.99, 0.001, 0.5, 2.0]
    jn = [mujoco.mj_id2name(m, mujoco.mjtObj.mjOBJ_JOINT, j) for j in range(m.njnt)]
    tmax = np.zeros(m.nu)
    for a in range(m.nu):
        j = m.actuator_trnid[a, 0]
        name = jn[j]
        d = ACT[META[name]["actuator_type"]]
        tmax[a] = d["max_torque"]
        dof = m.jnt_dofadr[j]
        m.dof_damping[dof] = d["damping"]
        m.dof_armature[dof] = d["armature"]
        m.dof_frictionloss[dof] = d["frictionloss"]
    for gname, sole in (("Right_Foot_collision_box", right_sole), ("Left_Foot_collision_box", left_sole)):
        if not sole:                     # (y_outer, y_inner) of the sole in the ankle frame, metres
            continue
        g = mujoco.mj_name2id(m, mujoco.mjtObj.mjOBJ_GEOM, gname)
        y0, y1 = sole
        m.geom_pos[g][1] = 0.5 * (y0 + y1)
        m.geom_size[g][1] = 0.5 * abs(y1 - y0)
        m.geom_rbound[g] = float(np.linalg.norm(m.geom_size[g]))        # broadphase bounds follow the new size
        m.geom_aabb[g][3:] = m.geom_size[g]
    m.body_mass[:] *= mass_scale
    m.actuator_ctrllimited[:] = 0
    m.actuator_gear[:, 0] = 1.0
    return m, tmax


class Sim:
    def __init__(self, mass_scale=1.0, kp=KP, kd=KD, right_sole=None, left_sole=None):
        self.m, self.tmax = load(mass_scale, right_sole, left_sole)
        self.d = mujoco.MjData(self.m)
        self.kp, self.kd = kp, kd
        self.act_j = [self.m.actuator_trnid[a, 0] for a in range(self.m.nu)]
        self.names = [mujoco.mj_id2name(self.m, mujoco.mjtObj.mjOBJ_JOINT, j) for j in self.act_j]
        self.qadr = [self.m.jnt_qposadr[j] for j in self.act_j]
        self.vadr = [self.m.jnt_dofadr[j] for j in self.act_j]
        self.target = np.zeros(self.m.nu)
        self.feet = {s: [g for g in range(self.m.ngeom) if mujoco.mj_id2name(self.m, mujoco.mjtObj.mjOBJ_GEOM, g).startswith(s + "_Foot")]
                     for s in ("Left", "Right")}
        self.floor = mujoco.mj_name2id(self.m, mujoco.mjtObj.mjOBJ_GEOM, "floor")
        self.total_mass = self.m.body_mass.sum()

    def set_pose_deg(self, angles):
        for i, n in enumerate(self.names):
            self.target[i] = np.radians(angles.get(n, 0.0))

    def reset(self, angles, stance="Right"):
        """drop the robot onto the floor with the `stance` sole lying flat (any pitch AND roll)"""
        self.set_pose_deg(angles)
        mujoco.mj_resetData(self.m, self.d)
        for i, a in enumerate(self.qadr):
            self.d.qpos[a] = self.target[i]
        self.d.qpos[2] = 0.5
        self.d.qpos[3:7] = [1, 0, 0, 0]
        mujoco.mj_forward(self.m, self.d)
        n = support_margin(self, stance)[3]           # sole normal in the base frame -> world up
        ax = np.cross(n, [0, 0, 1.0])
        s_, c_ = np.linalg.norm(ax), n[2]
        ang = np.arctan2(s_, c_)
        ax = ax / s_ if s_ > 1e-9 else np.array([0, 0, 1.0])
        self.d.qpos[3:7] = [np.cos(ang / 2), *(np.sin(ang / 2) * ax)]
        mujoco.mj_forward(self.m, self.d)
        # lower until feet touch: place base so lowest foot geom point is at z=0
        low = self.lowest()
        self.d.qpos[2] += 0.002 - low
        mujoco.mj_forward(self.m, self.d)

    def flat_pitch(self):
        """base pitch (rad) that lays both feet flat for the current joint targets"""
        def tilt(p):
            self.d.qpos[3:7] = [np.cos(p / 2), 0, np.sin(p / 2), 0]
            mujoco.mj_forward(self.m, self.d)
            return sum(1 - abs(self.d.geom_xmat[g].reshape(3, 3)[2, 2]) for gs in self.feet.values() for g in gs[:1])
        lo, hi = -0.8, 0.8
        for _ in range(50):
            a, b = lo + 0.382 * (hi - lo), lo + 0.618 * (hi - lo)
            lo, hi = (lo, b) if tilt(a) < tilt(b) else (a, hi)
        return 0.5 * (lo + hi)

    def lowest(self):
        z = 9
        for side in self.feet.values():
            for g in side:
                R = self.d.geom_xmat[g].reshape(3, 3)
                ext = np.abs(R[2]) @ self.m.geom_size[g] if self.m.geom_type[g] == mujoco.mjtGeom.mjGEOM_BOX else self.m.geom_size[g][0]
                z = min(z, self.d.geom_xpos[g][2] - ext)
        return z

    def step(self, n=1):
        for _ in range(n):
            q = self.d.qpos[self.qadr]
            v = self.d.qvel[self.vadr]
            tau = np.clip(self.kp * (self.target - q) - self.kd * v, -self.tmax, self.tmax)
            self.d.ctrl[:] = tau
            mujoco.mj_step(self.m, self.d)

    def com(self):
        return self.d.subtree_com[1].copy()

    def foot_load(self):
        """vertical contact force per foot (N)"""
        out = {"Left": 0.0, "Right": 0.0}
        f6 = np.zeros(6)
        for c in range(self.d.ncon):
            con = self.d.contact[c]
            for side, gs in self.feet.items():
                if con.geom1 in gs or con.geom2 in gs:
                    mujoco.mj_contactForce(self.m, self.d, c, f6)
                    out[side] += f6[0]
        return out

    def tilt_deg(self):
        R = self.d.xmat[1].reshape(3, 3)
        return float(np.degrees(np.arccos(np.clip(R[2, 2], -1, 1))))

    def settle(self, angles, t=2.0, stance="Right"):
        self.reset(angles, stance)
        self.step(int(t / self.m.opt.timestep))
        return self.report()

    def report(self):
        fl = self.foot_load()
        return dict(h=float(self.d.qpos[2]), tilt=self.tilt_deg(), load=fl,
                    vel=float(np.linalg.norm(self.d.qvel[:6])),
                    sat=float(np.max(np.abs(self.d.ctrl) / self.tmax)))


def center_pose():
    c = json.loads((ROOT / "hardware/center_pose.json").read_text())
    return dict(c)


# ---------------------------------------------------------------- kinematic support check
def sole_corners(sim, side):
    """world positions of the 4 bottom corners of the foot's flat collision box (the real contact patch)"""
    m, d = sim.m, sim.d
    g = next(g for g in sim.feet[side] if m.geom_type[g] == mujoco.mjtGeom.mjGEOM_BOX)
    hx, hy, hz = m.geom_size[g]
    R = d.geom_xmat[g].reshape(3, 3)
    pts = [d.geom_xpos[g] + R @ np.array([sx * hx, sy * hy, -hz]) for sy in (-1, 1) for sx in (-1, 1)]
    return np.array(pts)   # (-x,-y), (+x,-y), (-x,+y), (+x,+y)


def d_geom_z(sim, g):
    return sim.d.geom_xmat[g].reshape(3, 3)[:, 2].copy()


def support_margin(sim, side):
    """Static margin of the CoM over one foot, assuming the sole lies flat on the floor.
    Returns (margin_x, margin_y, com_in_sole_frame, up) - positive margin = inside.
    Uses the current kinematics (sim.d) with base at identity."""
    P = sole_corners(sim, side)
    c = P.mean(0)
    # sole axes: long axis (x) along the two capsules, normal from plane fit
    u, s, vt = np.linalg.svd(P - c)
    n = vt[2]
    zb = d_geom_z(sim, sim.feet[side][0])      # box z axis = sole normal pointing up (out of the foot)
    if n @ zb < 0:
        n = -n
    # long axis of the sole = along the capsules (P[0] -> P[1])
    ex = P[1] - P[0]
    ex = ex - n * (ex @ n)
    ex /= np.linalg.norm(ex)
    xb = sim.d.geom_xmat[sim.feet[side][0]].reshape(3, 3)[:, 0]   # box +x = toe direction
    if ex @ xb < 0:
        ex = -ex
    ey = np.cross(n, ex)
    Q = np.stack([(P - c) @ ex, (P - c) @ ey], 1)
    com = sim.com()
    rel = com - c
    cx, cy = rel @ ex, rel @ ey
    mx = min(cx - Q[:, 0].min(), Q[:, 0].max() - cx)
    my = min(cy - Q[:, 1].min(), Q[:, 1].max() - cy)
    return mx, my, (cx, cy, rel @ n), n


def fk(sim, angles):
    sim.set_pose_deg(angles)
    mujoco.mj_resetData(sim.m, sim.d)
    for i, a in enumerate(sim.qadr):
        sim.d.qpos[a] = sim.target[i]
    sim.d.qpos[3:7] = [1, 0, 0, 0]
    mujoco.mj_forward(sim.m, sim.d)


def sole_xy(sim, side="Right"):
    """CoM position (x forward, y left, metres) relative to the sole centre, in the sole plane"""
    return support_margin(sim, side)[2][:2]


def sole_xy_world(sim, side="Right"):
    """CoM offset from the sole centre measured on the REAL floor plane: (along the foot's horizontal
    long axis, lateral to the left), metres. Unlike sole_xy it sees the foot tipping."""
    P = sole_corners(sim, side)
    c = P.mean(0)
    xb = sim.d.geom_xmat[sim.feet[side][0]].reshape(3, 3)[:, 0].copy()
    ex = np.array([xb[0], xb[1], 0.0]); ex /= np.linalg.norm(ex)
    ey = np.array([-ex[1], ex[0], 0.0])
    r = sim.com() - c
    return np.array([r @ ex, r @ ey])


def calibrate(sim, angles, tune=None, t=8.0, gain=0.4, stance="Right", ctrl_dt=0.05):
    """Find servo targets that make the settled (compliant) robot stand with the CoM over the
    sole centre: integrates the tuned joints until the quasi-static CoP/CoM error vanishes.
    Returns the adjusted angles."""
    tune = tune or {"right_hip_yaw": 1, "right_ankle_pitch": 0}
    ang = dict(angles)
    old_damp = sim.m.dof_damping[:6].copy()
    sim.m.dof_damping[:6] = [60, 60, 60, 8, 8, 8]       # slow the tipping so the integrator can chase it
    sim.reset(ang, stance)
    n_ctrl = int(ctrl_dt / sim.m.opt.timestep)
    # sensitivities d(cx,cy)/d(joint deg) from kinematics around the start pose
    sens = {}
    for j, comp in tune.items():
        a2 = dict(ang); a2[j] = a2.get(j, 0.0) + 1.0
        fk(sim, ang); c0 = np.array(sole_xy(sim, stance))
        fk(sim, a2); c1 = np.array(sole_xy(sim, stance))
        sens[j] = (c1 - c0)[comp]
    sim.reset(ang, stance)
    hist = []
    for k in range(int(t / ctrl_dt)):
        sim.step(n_ctrl)
        if k * ctrl_dt < 0.5:
            continue
        c = sole_xy_world(sim, stance)
        for j, comp in tune.items():
            if abs(sens[j]) > 1e-6:
                ang[j] = ang.get(j, 0.0) - gain * c[comp] / sens[j] * 0.5
        sim.set_pose_deg(ang)
        sim.target[:] = sim.target     # (targets applied directly)
        hist.append((c[0], c[1], sim.tilt_deg(), ang.get("right_hip_yaw", 0)))
    sim.m.dof_damping[:6] = old_damp
    return ang, hist


# ---------------------------------------------------------------- servo-like playback
TICK_DEG = 360.0 / 4096.0


class Player:
    """Plays demo steps like the Pi does: every joint of a step starts together and runs toward its goal
    with the step's speed (ticks/s) and acc (units of 100 ticks/s^2), independently of the others."""

    def __init__(self, sim, stance="Right"):
        self.s = sim
        self.stance = stance
        self.v = np.zeros(sim.m.nu)
        self.log = []
        self.fell = None

    def _servo_step(self, goal, vmax, amax, dt):
        s = self.s
        x = s.target
        d = goal - x
        want = np.sign(d) * np.minimum(vmax, np.sqrt(2 * amax * np.abs(d)))
        dv = np.clip(want - self.v, -amax * dt, amax * dt)
        self.v += dv
        x = x + self.v * dt
        crossed = (np.sign(goal - x) != np.sign(d)) & (np.abs(d) > 0)
        x[crossed] = goal[crossed]; self.v[crossed] = 0
        s.target = x

    def move(self, angles, speed, acc, hold_s=0.0, tol_deg=0.5, max_s=30.0):
        s = self.s
        goal = s.target.copy()
        for i, n in enumerate(s.names):
            if n in angles:
                goal[i] = np.radians(angles[n])
        vmax = np.radians(speed * TICK_DEG) * np.ones(s.m.nu)
        amax = np.radians(acc * 100 * TICK_DEG)
        dt = s.m.opt.timestep
        t = 0.0
        while True:
            self._servo_step(goal, vmax, amax, dt)
            s.step(1)
            t += dt
            if int(round(t / dt)) % 50 == 0:
                self.record(t)
                if self.fell:
                    return False
            if np.all(np.abs(goal - s.target) < 1e-6) and t > 0.1:
                break
            if t > max_s:
                break
        t_end = t + hold_s
        while t < t_end:
            s.step(1); t += dt
            if int(round(t / dt)) % 50 == 0:
                self.record(t)
                if self.fell:
                    return False
        return True

    def record(self, t):
        s = self.s
        tilt = s.tilt_deg()
        c = sole_xy_world(s, self.stance)
        self.log.append((t, tilt, c[0], c[1], s.foot_load()))
        if s.d.qpos[2] < 0.15 or tilt > 80:
            self.fell = f"fell (tilt {tilt:.0f}, h {s.d.qpos[2]:.2f})"


def start_standing(sim, angles=None, t=1.0, stance="Right"):
    ang = angles or center_pose()
    sim.reset(ang, stance)
    sim.step(int(t / sim.m.opt.timestep))
    return Player(sim, stance)
