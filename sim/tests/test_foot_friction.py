"""FootFrictionRandomizer: the sampled friction must reach the foot contacts, also in MJX where the training runs.

    ~/Documents/stash/ksim-zbot/.venv/bin/python -m pytest sim/tests -q      (from the repo root)
"""
import sys
from pathlib import Path

import jax
import mujoco
import numpy as np
import pytest
from mujoco import mjx

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sim.train.walking import FootFrictionRandomizer, ImuTiltRandomizer                # noqa: E402

ASSETS = ["zbot-cad-tpu", "zbot-cad-tpu-leftold", "zbot-cad"]


def load(assets):
    d = ROOT / "sim" / "assets" / assets
    xml = (d / "robot.mjcf").read_text().replace(
        "<worldbody>", '<worldbody><geom name="floor" type="plane" size="5 5 0.1" condim="3" group="3"/>', 1)
    xml = xml.replace("<compiler ", f'<compiler meshdir="{d}" ', 1)
    return mujoco.MjModel.from_xml_string(xml)


@pytest.mark.parametrize("assets", ASSETS)
def test_covers_the_range_on_all_foot_pairs(assets):
    m = load(assets)
    r = FootFrictionRandomizer(mu_lower=0.2, mu_upper=1.2)
    keys = jax.random.split(jax.random.PRNGKey(0), 200)
    mx = mjx.put_model(m)
    mus = np.stack([np.asarray(r(mx, k)["pair_friction"]) for k in keys])
    assert m.npair >= 2 and np.all(mus[..., :2] == mus[:, 0, 0, None, None])           # one mu per environment, all pairs
    assert 0.2 <= mus[..., 0].min() < 0.3 and 1.1 < mus[..., 0].max() <= 1.2
    assert np.all(mus[..., 2:] == np.asarray(mx.pair_friction)[..., 2:])               # spin and roll untouched


def test_reaches_the_contacts_in_mjx():
    m = load("zbot-cad-tpu")
    m.opt.cone = mujoco.mjtCone.mjCONE_PYRAMIDAL
    d = mujoco.MjData(m)
    d.qpos[2] = 0.30                                                                  # feet in the floor: contacts exist
    mx = mjx.put_model(m)
    r = FootFrictionRandomizer(mu_lower=0.3, mu_upper=0.3)
    mx = mx.tree_replace(r(mx, jax.random.PRNGKey(0)))
    dx = mjx.forward(mx, mjx.put_data(m, d))
    active = np.asarray(dx._impl.contact.dist) < 0 if hasattr(dx, "_impl") else np.asarray(dx.contact.dist) < 0
    fr = np.asarray(dx._impl.contact.friction if hasattr(dx, "_impl") else dx.contact.friction)[active]
    assert len(fr) and np.allclose(fr[:, :2], 0.3)


def test_can_be_set_on_a_plain_mjmodel():
    m = load("zbot-cad-tpu")                                                          # ksim's non-MJX path uses setattr
    m.pair_friction = FootFrictionRandomizer(mu_lower=0.3, mu_upper=0.3)(m, jax.random.PRNGKey(0))["pair_friction"]
    assert np.allclose(m.pair_friction[:, :2], 0.3)


def test_imu_tilt_reaches_the_accelerometer():
    m = load("zbot-cad-tpu")
    mx = mjx.put_model(m)
    r = ImuTiltRandomizer.from_site_name(m, "imu", 8.0)
    sid = r.site_id
    base = mujoco.MjData(m)
    mujoco.mj_forward(m, base)
    up0 = base.site_xmat[sid].reshape(3, 3)
    angles = []
    for k in jax.random.split(jax.random.PRNGKey(0), 200):
        q = np.asarray(r(mx, k)["site_quat"])
        assert np.allclose(np.delete(q, sid, 0), np.delete(np.asarray(mx.site_quat), sid, 0))    # other sites untouched
        assert abs(np.linalg.norm(q[sid]) - 1) < 1e-5
        m.site_quat[sid] = q[sid]
        d = mujoco.MjData(m)
        mujoco.mj_forward(m, d)
        rel = up0.T @ d.site_xmat[sid].reshape(3, 3)
        angles.append(np.degrees(np.arccos(np.clip((np.trace(rel) - 1) / 2, -1, 1))))
    assert 5.0 < max(angles) <= 8.01
    assert min(angles) < 1.5


def test_log_uniform_favours_low_friction():
    mx = mjx.put_model(load("zbot-cad-tpu"))
    r = FootFrictionRandomizer(mu_lower=0.1, mu_upper=1.5, log_uniform=True)
    mus = np.array([np.asarray(r(mx, k)["pair_friction"])[0, 0] for k in jax.random.split(jax.random.PRNGKey(0), 400)])
    assert mus.min() >= 0.1 - 1e-6 and mus.max() <= 1.5 + 1e-6
    assert 0.42 < np.mean(mus < 0.4) < 0.60                                            # ln 4 / ln 15 = 51 %
