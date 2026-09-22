#!/usr/bin/env python3
"""Export a walking-policy checkpoint for the robot: TensorFlow SavedModel (the same xax export the trainer writes as
checkpoints/tf_model), ONNX (onnxruntime on the Pi) and a metadata JSON describing the observation vector, the
joint/servo order and the action semantics. Loads the actor straight from the checkpoint archive (members
model/config), no task object needed.
Usage: JAX_PLATFORMS=cpu python sim/tools/export_policy.py <ckpt.bin> <outdir> [assets=zbot-cad]"""
import io, json, shutil, subprocess, sys, tarfile
from pathlib import Path
import equinox as eqx, jax, jax.numpy as jnp, numpy as np
from omegaconf import OmegaConf
ROOT = Path(__file__).resolve().parents[2]; sys.path.insert(0, str(ROOT))
from sim.train.walking import ZbotModel, NUM_INPUTS, NUM_OUTPUTS  # noqa: E402
from xax.nn.export import export  # noqa: E402

ckpt, out = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(); assets = sys.argv[3] if len(sys.argv) > 3 else "zbot-cad"
with tarfile.open(ckpt, "r:gz") as tar:
    cfg = OmegaConf.create(tar.extractfile("config").read().decode()); model_bytes = tar.extractfile("model").read()
heading_obs = bool(cfg.get("heading_obs", False)); action_scale = float(cfg.get("action_scale", 1.0)); n_in = NUM_INPUTS + (2 if heading_obs else 0)
model = eqx.tree_deserialise_leaves(io.BytesIO(model_bytes), ZbotModel(jax.random.PRNGKey(0), num_inputs=n_in))
def policy(flat_obs: jnp.ndarray) -> jnp.ndarray:          # deterministic action = distribution mode (= mean)
    return model.actor.call_flat_obs(flat_obs).mode()
out.mkdir(parents=True, exist_ok=True); shutil.rmtree(out / "tf_model", ignore_errors=True)
export(jax.vmap(policy), [(n_in,)], out / "tf_model")   # the SavedModel takes a batch dimension
# ONNX built directly from the actor MLP (tf2onnx 1.16 is broken on NumPy 2): Gemm/Relu stack, slice the mean half, tanh, x mean_scale
import onnx  # noqa: E402
from onnx import TensorProto, helper, numpy_helper  # noqa: E402
def mlp_to_onnx(actor, n_in: int, path: Path) -> None:
    nodes, inits, x = [], [], "obs"; layers = list(actor.mlp.layers)
    for i, layer in enumerate(layers):
        w, b = np.asarray(layer.weight, np.float32), np.asarray(layer.bias, np.float32)
        inits += [numpy_helper.from_array(w, f"W{i}"), numpy_helper.from_array(b, f"b{i}")]
        y = f"h{i}"; nodes.append(helper.make_node("Gemm", [x, f"W{i}", f"b{i}"], [y], transB=1))
        if i < len(layers) - 1: nodes.append(helper.make_node("Relu", [y], [f"a{i}"])); x = f"a{i}"
        else: x = y
    inits += [numpy_helper.from_array(np.array([0], np.int64), "s0"), numpy_helper.from_array(np.array([NUM_OUTPUTS], np.int64), "s1"),
              numpy_helper.from_array(np.array([1], np.int64), "ax"), numpy_helper.from_array(np.array(float(actor.mean_scale), np.float32), "mean_scale")]
    nodes += [helper.make_node("Slice", [x, "s0", "s1", "ax"], ["mean_raw"]), helper.make_node("Tanh", ["mean_raw"], ["mean_t"]),
              helper.make_node("Mul", ["mean_t", "mean_scale"], ["action"])]
    g = helper.make_graph(nodes, "zbot_walking_policy", [helper.make_tensor_value_info("obs", TensorProto.FLOAT, ["batch", n_in])],
                          [helper.make_tensor_value_info("action", TensorProto.FLOAT, ["batch", NUM_OUTPUTS])], inits)
    m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 17)], producer_name="sim/tools/export_policy.py"); m.ir_version = 9
    onnx.checker.check_model(m); onnx.save(m, str(path))
mlp_to_onnx(model.actor, n_in, out / "policy.onnx")
import onnxruntime as ort  # noqa: E402
sess = ort.InferenceSession(str(out / "policy.onnx")); x = np.random.randn(4, n_in).astype(np.float32)
y_onnx = sess.run(None, {sess.get_inputs()[0].name: x})[0]; y_jax = np.asarray(jax.vmap(policy)(jnp.asarray(x)))
err = float(np.abs(y_onnx - y_jax).max()); assert err < 1e-4, err
import mujoco  # noqa: E402
from mujoco_scenes.mjcf import load_mjmodel  # noqa: E402
mj = load_mjmodel(str(ROOT / "sim/assets" / assets / "robot.mjcf"), scene="smooth"); joints = [mj.joint(i).name for i in range(1, mj.njnt)]
meta = json.load(open(ROOT / "sim/assets" / assets / "metadata.json"))
layout = [("timestep_phase", 4, "gait clock [cos, sin] x2 (walking.py TimestepPhaseObservation)"), ("joint_pos", NUM_OUTPUTS, "joint angles rad, MuJoCo joint order, 0 = servo zero"),
          ("joint_vel", NUM_OUTPUTS, "joint velocities rad/s"), ("imu_acc", 3, "accelerometer m/s^2, IMU frame = body frame (x fwd, y left, z up)"),
          ("imu_gyro", 3, "gyro rad/s, same frame"), ("lin_vel_cmd", 2, "commanded forward/lateral speed m/s"), ("ang_vel_cmd", 1, "commanded yaw rate rad/s"),
          ("gait_freq_cmd", 1, "commanded gait frequency Hz"), ("last_action", NUM_OUTPUTS, "previous action")]
if heading_obs: layout.append(("heading", 2, "[cos psi, sin psi]: yaw relative to the start heading (IMU yaw zeroed at policy start)"))
task_keys = ["velocity_tracking", "gait_shaping", "target_speed_min", "target_speed_max", "heading_obs", "action_scale", "gait_freq_lower", "gait_freq_upper", "ctrl_dt"]
json.dump({"checkpoint": str(ckpt), "assets": assets, "task_config": {k: cfg.get(k) for k in task_keys if k in cfg},
           "input": {"size": n_in, "layout_in_order": [{"name": n, "size": s, "meaning": m} for n, s, m in layout]},
           "output": {"size": NUM_OUTPUTS, "meaning": f"target joint angle rad (tanh-bounded, x action_scale={action_scale}), MuJoCo joint order, 0 = servo zero; a PD loop (sim: kp 16, kd 3) tracks it at {1/float(cfg.get('ctrl_dt', 0.02)):.0f} Hz"},
           "joint_order": joints, "servo_ids": {j: meta["joint_name_to_metadata"][j]["id"] for j in joints},
           "actuator_types": {j: meta["joint_name_to_metadata"][j]["actuator_type"] for j in joints}, "onnx_vs_jax_max_abs_diff": err,
           "files": ["policy.onnx", "tf_model/", "ckpt.bin", "policy_meta.json"]}, open(out / "policy_meta.json", "w"), indent=1)
shutil.copy(ckpt, out / "ckpt.bin")
print(f"exported -> {out}  inputs {n_in} (heading_obs={heading_obs})  outputs {NUM_OUTPUTS}  onnx/jax diff {err:.2e}")
