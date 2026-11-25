#!/usr/bin/env python3
# Usage (repo root): ~/Documents/stash/ksim-zbot/.venv/bin/python sim/tools/hw_kin_yaw.py <dir with slow2.ds/.meta.json from a collect_dataset sim run>
# Compares the body yaw a rigid robot with a fixed left foot would have (from joint angles alone) with the
# integrated gyro_y, in the sim (validation, truth known) and in the 22.11. hardware logs of servo_rubber23_step3315.
# Predicted body yaw if the left (stance) foot keeps its world yaw and the robot is rigid: from joint angles only.
import json,numpy as np,mujoco,sys,glob
from mujoco_scenes.mjcf import load_mjmodel
S=sys.argv[1]
M=load_mjmodel('sim/assets/zbot-cad-tpu/robot.mjcf',scene='smooth'); D=mujoco.MjData(M)
h0=np.load(sorted(glob.glob('sim/policies/servo_rubber23_step3315/hw_logs_2026-11-22/*.npz'))[0],allow_pickle=True)
J=json.loads(str(h0['meta']))['joints']; adr=[M.jnt_qposadr[mujoco.mj_name2id(M,mujoco.mjtObj.mjOBJ_JOINT,j)] for j in J]
lf=mujoco.mj_name2id(M,mujoco.mjtObj.mjOBJ_BODY,'left_ankle_pitch_link')
def yaw(R): return np.degrees(np.arctan2(R[1,0],R[0,0]))
def rel_yaw(q, quat=(1,0,0,0)):
    D.qpos[:]=0; D.qpos[3:7]=quat; D.qpos[2]=0.4
    for a,v in zip(adr,q): D.qpos[a]=v
    mujoco.mj_kinematics(M,D); return yaw(D.xmat[lf].reshape(3,3))-yaw(D.xmat[1].reshape(3,3))
T=[0,5,10,15,20,25,30]
print('t[s]                 '+' '.join(f'{t*0.02:6.2f}' for t in T))
# --- validate on sim (truth known)
m=json.load(open(f'{S}/slow2.meta.json')); fp=np.memmap(f'{S}/slow2.ds',dtype=np.float32,mode='r',shape=(m['num_samples'],m['total_size']))
c={};o=0
for n,sh in zip(m['names'],m['shapes']): s=int(np.prod(sh)); c[n]=(o,s,tuple(sh)); o+=s
g=lambda n: np.asarray(fp[:,c[n][0]:c[n][0]+c[n][1]]).reshape((m['num_samples'],)+c[n][2])
v=np.abs(g('timestep')).sum(1)>0; qp=g('qpos')[v]; jq=g('obs.joint_position_observation')[v]; gy=np.degrees(g('obs.sensor_observation_imu_gyro')[v][...,1])
P=[];TB=[];TF=[];G=[]
for e in range(qp.shape[0]):
    r=np.array([rel_yaw(jq[e,t]) for t in T]); P.append(-(r-r[0]))
    tb=[];tf=[]
    for t in T:
        D.qpos[:]=qp[e,t]; mujoco.mj_kinematics(M,D); tb.append(yaw(D.xmat[1].reshape(3,3))); tf.append(yaw(D.xmat[lf].reshape(3,3)))
    TB.append(np.array(tb)-tb[0]); TF.append(np.array(tf)-tf[0])
    gi=np.concatenate([[0],np.cumsum(0.5*(gy[e,1:]+gy[e,:-1])*0.02)]); G.append(gi[T])
for lbl,A in (('SIM rigid pred (foot fixed)',P),('SIM true foot yaw',TF),('SIM pred + foot yaw',np.array(P)+np.array(TF)),('SIM true body yaw',TB),('SIM integrated gyro_y',G)):
    print(f'{lbl:28s}'+' '.join(f'{x:6.1f}' for x in np.mean(A,0)))
# --- hardware
P=[];G=[]
for f in sorted(glob.glob('sim/policies/servo_rubber23_step3315/hw_logs_2026-11-22/*.npz')):
    h=np.load(f,allow_pickle=True); q=h['obs'][:,4:20]; t=h['t']-h['t'][0]; gg=np.degrees(h['obs'][:,40])
    r=np.array([rel_yaw(q[k]) for k in T]); P.append(-(r-r[0]))
    gi=np.concatenate([[0],np.cumsum(0.5*(gg[1:]+gg[:-1])*np.diff(t))]); G.append(gi[T])
    print(f'  HW {f[-35:-21]} rigid pred'+' '.join(f'{x:6.1f}' for x in P[-1])+'  | gyro '+' '.join(f'{x:6.1f}' for x in G[-1]))
print(f'{"HW rigid pred (foot fixed)":28s}'+' '.join(f'{x:6.1f}' for x in np.mean(P,0)))
print(f'{"HW integrated gyro_y":28s}'+' '.join(f'{x:6.1f}' for x in np.mean(G,0)))
