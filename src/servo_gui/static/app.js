// Zeroth-01 single-servo test GUI — 3D viewer + controls.
// Click a part of the pinned CAD model, set the test interval, run the test.
// The orange gauge shows the [min, max] range; the needle follows the live
// position streamed from the backend (hardware or simulation).

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const $ = id => document.getElementById(id);
const api = {
  get: p => fetch(p).then(r => r.json()),
  post: async (p, body) => {
    const r = await fetch(p, { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body ?? {}) });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail ?? r.statusText);
    return data;
  },
};

// ---------------------------------------------------------------- log

let serverLog = [];
const clientLog = [];
function renderLog() {
  $('log').textContent =
    [...serverLog.map(l => l.msg), ...clientLog].join('\n');
  $('log').scrollTop = $('log').scrollHeight;
}
function clientMsg(msg) {
  clientLog.push('· ' + msg);
  while (clientLog.length > 10) clientLog.shift();
  renderLog();
}

// ---------------------------------------------------------------- scene

const canvas = $('c');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
const scene = new THREE.Scene();
scene.background = new THREE.Color(0x14171c);
const camera = new THREE.PerspectiveCamera(50, 1, 0.001, 100);
camera.position.set(0.5, 0.4, 0.5);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;

scene.add(new THREE.HemisphereLight(0xdde3ec, 0x30363f, 1.1));
const key = new THREE.DirectionalLight(0xffffff, 1.6);
key.position.set(1, 2, 1.5);
scene.add(key);
const fill = new THREE.DirectionalLight(0xaabbdd, 0.6);
fill.position.set(-1.5, 0.5, -1);
scene.add(fill);
const grid = new THREE.GridHelper(1, 20, 0x3a4454, 0x242b36);
scene.add(grid);

function resize() {
  const { clientWidth: w, clientHeight: h } = canvas.parentElement;
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
new ResizeObserver(resize).observe(canvas.parentElement);

renderer.setAnimationLoop(() => {
  controls.update();
  renderer.render(scene, camera);
});

// ---------------------------------------------------------------- model

let modelRoot = null;

async function loadModel() {
  const s = await api.get('/api/status');
  if (!s.model_present) { $('dropHint').classList.remove('hidden'); return; }
  $('dropHint').classList.add('hidden');
  const gltf = await new GLTFLoader().loadAsync('/model');
  if (modelRoot) scene.remove(modelRoot);
  modelRoot = gltf.scene;
  modelRoot.rotation.x = -Math.PI / 2;   // OnShape exports Z-up, three.js is Y-up
  scene.add(modelRoot);
  modelRoot.updateWorldMatrix(true, true);
  nodeIndex.clear();
  modelRoot.traverse(o => {
    if (o.name && !nodeIndex.has(fullKey(o.name)))
      nodeIndex.set(fullKey(o.name), o);
  });

  const box = new THREE.Box3().setFromObject(modelRoot);
  const center = box.getCenter(new THREE.Vector3());
  const diag = box.getSize(new THREE.Vector3()).length();
  camera.near = diag / 1000;
  camera.far = diag * 50;
  camera.position.copy(center)
    .add(new THREE.Vector3(diag * 0.8, diag * 0.5, diag * 0.8));
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  grid.position.y = box.min.y;
  grid.scale.setScalar(Math.max(1, diag * 2));
  clientMsg('CAD model loaded (pinned OnShape version, see resources/cad/VERSION.md)');
  buildRig();
}

// ---------------------------------------------------------------- selection

const raycaster = new THREE.Raycaster();
let selected = null;
let currentJoint = null;   // CAD revolute joint matching the selection, if any

// CAD/GLB name matching. GLTFLoader sanitizes spaces to underscores; the GLB
// keeps "<n>" instance suffixes except for the first instance ("<1>" dropped).
// Duplicate instance names exist upstream, so match suffix-exact first.
const fullKey = s => s.toLowerCase().replace(/[\s_]+/g, '_');
const normName = s => fullKey(s).replace(/_?<\d+>$/, '');
const nodeIndex = new Map();   // fullKey(name) -> Object3D

const findNode = occ =>
  nodeIndex.get(fullKey(occ))                            // exact incl. <n>
  ?? nodeIndex.get(fullKey(occ).replace(/_?<1>$/, ''))   // first instance
  ?? nodeIndex.get(normName(occ));                       // base name

function findJoint(obj) {
  const full = fullKey(obj?.name || '');
  if (!full) return null;
  // tier 1: clicked node IS one of the joint's occurrences (suffix-exact)
  const exact = joints.find(j => j.occurrences.some(o => {
    const of = fullKey(o);
    return of === full || of.replace(/_?<1>$/, '') === full;
  }));
  if (exact) return exact;
  // tier 2: base-name match / joint name contained in the node name
  const n = normName(obj.name);
  return joints.find(j =>
    j.occurrences.some(o => normName(o) === n) ||
    n.includes(normName(j.name))) ?? null;
}

// climb past unnamed nodes and generic glTF names (mesh_12_1, node_5, ...)
// up to the real part/occurrence name from the CAD assembly
const GENERIC_NAME = /^(mesh[_\d]*|node[_\d]*|faces[_\d]*|primitive[_\d]*)$/i;
const nearestNamed = o => {
  while (o && o !== scene && (!o.name || GENERIC_NAME.test(o.name)))
    o = o.parent;
  return (o === scene || !o) ? null : o;
};

function setHighlight(root, on) {
  root?.traverse(m => {
    if (!m.isMesh) return;
    if (on) {
      if (!m.userData.origMat) m.userData.origMat = m.material;
      m.material = m.material.clone();
      if (m.material.emissive) {
        m.material.emissive.setHex(0xff8c1a);
        m.material.emissiveIntensity = 0.45;
      }
    } else if (m.userData.origMat) {
      m.material.dispose();
      m.material = m.userData.origMat;
      delete m.userData.origMat;
    }
  });
}

function select(obj) {
  setHighlight(selected, false);
  selected = obj;
  setHighlight(selected, true);
  const has = !!selected;
  currentJoint = has ? findJoint(selected) : null;
  $('axis').disabled = !!currentJoint;   // axis comes from the CAD joint
  $('selName').textContent = has
    ? (selected.name || '(unnamed)')
      + (currentJoint ? `  ·  ⚙ ${currentJoint.name}` : '')
    : 'nothing selected';
  if (currentJoint)
    clientMsg(`CAD joint "${currentJoint.name}" — axis & center from OnShape`);
  const hasPivot = !!(currentJoint && pivots.has(currentJoint.name));
  $('poseRow').classList.toggle('hidden', !hasPivot);
  if (hasPivot) syncPoseUI(jointAngles.get(currentJoint.name) ?? 0);
  $('saveLimits').disabled = !currentJoint;
  const lims = currentJoint && jointLimits[currentJoint.name];
  if (lims) {
    $('minDeg').value = lims.min_deg;
    $('maxDeg').value = lims.max_deg;
    clientMsg(`limits from config: [${lims.min_deg}, ${lims.max_deg}]° `
      + `(${lims.set === 'mirrored' ? 'mirrored from other side' : 'direct'})`);
  }
  $('selParent').disabled = !has || nearestNamed(selected.parent) === null
    || selected.parent === modelRoot;
  $('selClear').disabled = !has;
  $('saveMap').disabled = !has;
  if (has && mapping[selected.name]) {
    const m = mapping[selected.name];
    $('servoId').value = m.servo_id;
    $('servoModel').value = m.servo_model;
    if (m.axis) $('axis').value = m.axis;
    clientMsg(`mapping: "${selected.name}" -> ID ${m.servo_id}`);
  }
  updateGauge();
}

let downXY = null;
canvas.addEventListener('pointerdown', e => { downXY = [e.clientX, e.clientY]; });
canvas.addEventListener('pointerup', e => {
  if (!downXY || Math.hypot(e.clientX - downXY[0], e.clientY - downXY[1]) > 5)
    return;                                     // it was an orbit drag
  downXY = null;
  if (!modelRoot) return;
  const r = canvas.getBoundingClientRect();
  raycaster.setFromCamera(new THREE.Vector2(
    ((e.clientX - r.left) / r.width) * 2 - 1,
    -((e.clientY - r.top) / r.height) * 2 + 1), camera);
  const hit = raycaster.intersectObject(modelRoot, true)[0];
  select(hit ? nearestNamed(hit.object) : null);
});
$('selParent').onclick = () =>
  selected && select(nearestNamed(selected.parent));
$('selClear').onclick = () => select(null);

// ---------------------------------------------------------------- gauge

const gauge = new THREE.Group();
gauge.visible = false;
scene.add(gauge);
let needle = null, sector = null, gaugeR = 0.05;

// ring plane orientation: the ring's local +Z (its normal) is mapped onto the
// chosen axis of the SELECTED PART's own frame — so the gauge follows however
// the servo is mounted. Pick the axis that matches the output shaft.
const AXIS_QUAT = {
  Z: new THREE.Quaternion(),
  Y: new THREE.Quaternion().setFromEuler(new THREE.Euler(-Math.PI / 2, 0, 0)),
  X: new THREE.Quaternion().setFromEuler(new THREE.Euler(0, Math.PI / 2, 0)),
};

function updateGauge() {
  gauge.clear();
  needle = sector = null;
  if (!selected) { gauge.visible = false; return; }

  const box = new THREE.Box3().setFromObject(selected);
  const center = box.getCenter(new THREE.Vector3());
  gaugeR = Math.max(box.getSize(new THREE.Vector3()).length() * 0.75, 0.02);
  if (currentJoint && pivots.has(currentJoint.name)) {
    // rig-mounted: the gauge lives in the frame of the joint's parent link,
    // so it follows ancestor joints but not the joint's own rotation
    const info = pivots.get(currentJoint.name);
    info.parentObj.add(gauge);
    gauge.position.copy(info.posLocal);
    gauge.quaternion.copy(info.quatLocal);
    gaugeR = Math.max(info.radius, 0.02);
  } else if (currentJoint && modelRoot) {
    // exact axis & rotation center from the CAD revolute mate
    scene.add(gauge);
    const pos = new THREE.Vector3(...currentJoint.origin)
      .applyMatrix4(modelRoot.matrixWorld);
    const axisW = new THREE.Vector3(...currentJoint.axis)
      .transformDirection(modelRoot.matrixWorld);
    gauge.position.copy(pos);

    // zero reference (0° of the interval) = direction from the joint center
    // toward the moving part in its CAD pose — the CAD pose IS the mount/
    // center pose per our calibration convention
    const limbIdx = currentJoint.occurrences
      .findIndex(o => !/motor/i.test(o));
    const limbObj = limbIdx >= 0
      ? findNode(currentJoint.occurrences[limbIdx]) : null;
    let zero = null;
    if (limbObj) {
      const lb = new THREE.Box3().setFromObject(limbObj);
      gaugeR = Math.max(lb.getSize(new THREE.Vector3()).length() * 0.55, gaugeR);
      const d = lb.getCenter(new THREE.Vector3()).sub(pos);
      d.addScaledVector(axisW, -d.dot(axisW));   // project into ring plane
      if (d.length() > 0.015) zero = d.normalize();
    }
    if (!zero && currentJoint.xaxes) {           // fallback: mate connector X
      const x = new THREE.Vector3(
        ...currentJoint.xaxes[limbIdx >= 0 ? limbIdx : 0])
        .transformDirection(modelRoot.matrixWorld);
      x.addScaledVector(axisW, -x.dot(axisW));
      if (x.length() > 1e-3) zero = x.normalize();
    }
    if (zero) {
      const y = new THREE.Vector3().crossVectors(axisW, zero);
      gauge.quaternion.setFromRotationMatrix(
        new THREE.Matrix4().makeBasis(zero, y, axisW));
    } else {
      gauge.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), axisW);
    }
  } else {
    // fallback: part bounding-box center + manually chosen part-frame axis
    scene.add(gauge);
    gauge.position.copy(center);
    gauge.quaternion
      .copy(selected.getWorldQuaternion(new THREE.Quaternion()))
      .multiply(AXIS_QUAT[$('axis').value]);
  }

  const lo = THREE.MathUtils.degToRad(+$('minDeg').value);
  const hi = THREE.MathUtils.degToRad(+$('maxDeg').value);
  if (hi > lo) {
    sector = new THREE.Mesh(
      new THREE.CircleGeometry(gaugeR, 64, lo, hi - lo),
      new THREE.MeshBasicMaterial({ color: 0xff8c1a, transparent: true,
        opacity: 0.3, side: THREE.DoubleSide, depthWrite: false }));
    gauge.add(sector);
    for (const a of [lo, hi]) {
      const g = new THREE.BufferGeometry().setFromPoints([
        new THREE.Vector3(), new THREE.Vector3(Math.cos(a), Math.sin(a), 0)
          .multiplyScalar(gaugeR)]);
      gauge.add(new THREE.Line(g,
        new THREE.LineBasicMaterial({ color: 0xffb066 })));
    }
  }
  const ringPts = new THREE.EllipseCurve(0, 0, gaugeR, gaugeR).getPoints(96)
    .map(p => new THREE.Vector3(p.x, p.y, 0));
  gauge.add(new THREE.LineLoop(
    new THREE.BufferGeometry().setFromPoints(ringPts),
    new THREE.LineBasicMaterial({ color: 0x4a5568 })));

  // zero marker = center / mount position (tick 2048)
  const zg = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(gaugeR * 0.85, 0, 0),
    new THREE.Vector3(gaugeR * 1.12, 0, 0)]);
  gauge.add(new THREE.Line(zg,
    new THREE.LineBasicMaterial({ color: 0x8b96a8 })));

  needle = new THREE.Group();
  const ng = new THREE.BufferGeometry().setFromPoints([
    new THREE.Vector3(), new THREE.Vector3(gaugeR * 1.1, 0, 0)]);
  needle.add(new THREE.Line(ng,
    new THREE.LineBasicMaterial({ color: 0xffffff })));
  gauge.add(needle);
  gauge.visible = true;
}
for (const id of ['minDeg', 'maxDeg', 'axis'])
  $(id).addEventListener('input', updateGauge);

// ---------------------------------------------------------------- pose rig
// Kinematic tree from the CAD data: FASTENED mates merge parts into rigid
// links, REVOLUTE mates connect the links. Each articulable joint gets a
// pivot Group at its CAD origin — rotating the pivot poses the whole distal
// chain around the true joint axis.
const pivots = new Map();       // joint name -> rig info
const jointAngles = new Map();  // joint name -> deg

function setJointAngle(name, deg) {
  const p = pivots.get(name);
  if (!p) return;
  jointAngles.set(name, deg);
  p.pivot.quaternion.setFromAxisAngle(p.axisLocal,
    THREE.MathUtils.degToRad(deg));
}

function resetPose() {
  for (const name of pivots.keys()) setJointAngle(name, 0);
}

function buildRig() {
  pivots.clear();
  jointAngles.clear();
  if (!modelRoot || !joints.length) return;
  modelRoot.updateWorldMatrix(true, true);

  // rigid links = union-find over fastened part pairs
  const uf = new Map();
  const add = k => { if (!uf.has(k)) uf.set(k, k); };
  const rep = k => {
    add(k);
    let r = k;
    while (uf.get(r) !== r) r = uf.get(r);
    while (uf.get(k) !== r) { const n = uf.get(k); uf.set(k, r); k = n; }
    return r;
  };
  const union = (a, b) => { uf.set(rep(a), rep(b)); };
  for (const [a, b] of fastened)
    if (a !== '?' && b !== '?') union(fullKey(a), fullKey(b));
  for (const j of joints) j.occurrences.forEach(o => add(fullKey(o)));

  const members = new Map();
  for (const k of uf.keys()) {
    const r = rep(k);
    if (!members.has(r)) members.set(r, []);
    members.get(r).push(k);
  }

  // root link = the one containing the torso
  let rootRep = null;
  for (const k of uf.keys())
    if (k.includes('torso')) { rootRep = rep(k); break; }
  if (!rootRep)
    rootRep = [...members.entries()]
      .sort((a, b) => b[1].length - a[1].length)[0][0];

  const groupPivot = new Map();
  const visited = new Set([rootRep]);
  let progress = true;
  while (progress) {
    progress = false;
    for (const j of joints) {
      if (pivots.has(j.name) || j.occurrences.length < 2) continue;
      const ra = rep(fullKey(j.occurrences[0]));
      const rb = rep(fullKey(j.occurrences[1]));
      if (ra === rb) continue;
      let pr, cr;
      if (visited.has(ra) && !visited.has(rb)) { pr = ra; cr = rb; }
      else if (visited.has(rb) && !visited.has(ra)) { pr = rb; cr = ra; }
      else continue;

      const parentObj = groupPivot.get(pr) ?? modelRoot;
      parentObj.updateWorldMatrix(true, false);

      // rest-pose data (world frame) for pivot + gauge placement
      const originW = modelRoot.localToWorld(new THREE.Vector3(...j.origin));
      const axisW = new THREE.Vector3(...j.axis)
        .transformDirection(modelRoot.matrixWorld);
      const childNodes = (members.get(cr) ?? [])
        .map(k => findNode(k)).filter(Boolean);
      const box = new THREE.Box3();
      childNodes.forEach(n => box.expandByObject(n));

      // 0° reference = toward the moving chain (CAD pose = mount pose)
      let zeroW = null;
      if (!box.isEmpty()) {
        const d = box.getCenter(new THREE.Vector3()).sub(originW);
        d.addScaledVector(axisW, -d.dot(axisW));
        if (d.length() > 0.015) zeroW = d.normalize();
      }
      if (!zeroW && j.xaxes) {
        const x = new THREE.Vector3(...j.xaxes[0])
          .transformDirection(modelRoot.matrixWorld);
        x.addScaledVector(axisW, -x.dot(axisW));
        if (x.length() > 1e-3) zeroW = x.normalize();
      }
      const quatW = new THREE.Quaternion();
      if (zeroW) {
        const y = new THREE.Vector3().crossVectors(axisW, zeroW);
        quatW.setFromRotationMatrix(
          new THREE.Matrix4().makeBasis(zeroW, y, axisW));
      } else {
        quatW.setFromUnitVectors(new THREE.Vector3(0, 0, 1), axisW);
      }

      const pivot = new THREE.Group();
      pivot.name = 'pivot:' + j.name;
      parentObj.add(pivot);
      pivot.position.copy(parentObj.worldToLocal(originW.clone()));
      childNodes.forEach(n => pivot.attach(n));

      const pq = parentObj.getWorldQuaternion(new THREE.Quaternion());
      pivots.set(j.name, {
        pivot, parentObj,
        axisLocal: new THREE.Vector3(...j.axis).normalize(),
        posLocal: parentObj.worldToLocal(originW.clone()),
        quatLocal: pq.invert().multiply(quatW),
        radius: box.isEmpty() ? 0.05
          : Math.max(box.getSize(new THREE.Vector3()).length() * 0.4, 0.02),
      });
      groupPivot.set(cr, pivot);
      visited.add(cr);
      progress = true;
    }
  }
  if (pivots.size)
    clientMsg(`pose rig ready: ${pivots.size}/${joints.length} joints articulable`);
}

// ---------------------------------------------------------------- live (SSE)

let mapping = {};
let joints = [];
let fastened = [];
let jointLimits = {};   // joint name -> {min_deg, max_deg, set} from repo config
let servoIds = {};      // joint name -> bus ID from hardware/servo_ids.json

new EventSource('/api/stream').onmessage = e => {
  const live = JSON.parse(e.data);
  serverLog = live.log ?? [];
  renderLog();
  $('phase').textContent = live.phase;
  $('posDeg').textContent = live.deg != null
    ? (live.deg >= 0 ? '+' : '') + live.deg.toFixed(1) + ' °' : '–';
  $('run').disabled = live.running;
  $('center').disabled = live.running;
  $('stop').disabled = !live.running;
  $('groupRun').disabled = $('groupCenter').disabled = live.running;
  if (needle && live.deg != null)
    needle.rotation.z = THREE.MathUtils.degToRad(live.deg);
  // animate the posed joint with the live servo position during a run
  if (live.running && live.deg != null
      && currentJoint && pivots.has(currentJoint.name)) {
    setJointAngle(currentJoint.name, live.deg);
    syncPoseUI(live.deg);
  }
  // group runs stream all joint positions — animate the whole rig
  if (live.multi) {
    for (const [j, deg] of Object.entries(live.multi)) {
      if (pivots.has(j)) setJointAngle(j, deg);
      if (currentJoint?.name === j) {
        if (needle) needle.rotation.z = THREE.MathUtils.degToRad(deg);
        syncPoseUI(deg);
      }
    }
  }
};

function syncPoseUI(deg) {
  $('poseSlider').value = deg;
  $('poseVal').textContent = (deg >= 0 ? '+' : '') + (+deg).toFixed(1) + '°';
}

// ---------------------------------------------------------------- controls

async function refreshStatus() {
  const s = await api.get('/api/status');
  $('connState').textContent = s.connected
    ? 'connected: ' + s.port : 'not connected';
  $('connect').disabled = s.connected;
  $('disconnect').disabled = !s.connected;
  $('simulate').checked = !s.connected;  // connected -> real hardware by default
  // bus operations are hardware-only — no point offering them unconnected
  $('scan').disabled = $('setId').disabled = !s.connected;
  if (!s.connected) $('scanResult').textContent = 'connect first (hardware only)';
}

async function refreshPorts() {
  const ports = await api.get('/api/ports');
  $('port').innerHTML = ports.length
    ? ports.map(p => `<option value="${p.device}">${p.device} — ${p.description}</option>`).join('')
    : '<option value="">no USB serial port</option>';
}

const guard = fn => async (...args) => {
  try { await fn(...args); } catch (err) { clientMsg('ERROR: ' + err.message); }
};

$('refreshPorts').onclick = guard(refreshPorts);
$('connect').onclick = guard(async () => {
  await api.post('/api/connect', { port: $('port').value || null });
  await refreshStatus();
});
$('disconnect').onclick = guard(async () => {
  await api.post('/api/disconnect');
  await refreshStatus();
});
function renderGroup() {
  const entries = Object.entries(servoIds).sort((a, b) => a[1] - b[1]);
  $('groupList').innerHTML = entries.length
    ? entries.map(([j, id]) => {
        const lim = jointLimits[j];
        const range = lim ? ` [${lim.min_deg}, ${lim.max_deg}]°` : ' (no limits!)';
        return `<label class="check"><input type="checkbox" class="gsel" `
          + `value="${j}"> ${String(id).padStart(2)} · ${j}${range}</label>`;
      }).join('')
    : '<span class="muted">no servo IDs configured (hardware/servo_ids.json)</span>';
}
const selectedJoints = () =>
  [...document.querySelectorAll('.gsel:checked')].map(c => c.value);

$('groupAll').onclick = () => {
  const boxes = [...document.querySelectorAll('.gsel')];
  const all = boxes.length && boxes.every(b => b.checked);
  boxes.forEach(b => { b.checked = !all; });
};
$('groupCenter').onclick = guard(async () => {
  const js = selectedJoints();
  if (!js.length) { clientMsg('no servos selected'); return; }
  clientLog.length = 0;
  await api.post('/api/group/center', {
    joints: js,
    speed: Math.min(+$('speed').value, 500),
    acc: +$('acc').value,
    simulate: $('simulate').checked,
  });
});
$('groupRun').onclick = guard(async () => {
  const js = selectedJoints();
  if (!js.length) { clientMsg('no servos selected'); return; }
  clientLog.length = 0;
  await api.post('/api/group/test', {
    joints: js,
    mode: $('groupMode').value,
    speed: +$('speed').value,
    acc: +$('acc').value,
    cycles: +$('cycles').value,
    simulate: $('simulate').checked,
  });
});
$('scan').onclick = guard(async () => {
  $('scanResult').textContent = 'scanning IDs 1–60 …';
  const r = await api.get('/api/scan').catch(e => {
    $('scanResult').textContent = '';
    throw e;
  });
  $('scanResult').textContent = r.found.length
    ? 'found: ' + r.found.map(f => `ID ${f.id} (model ${f.model})`).join(' · ')
    : 'no servos found — check power, cabling, jumper';
});
$('setId').onclick = guard(async () => {
  const oldId = +$('oldId').value, newId = +$('newId').value;
  const r = await api.post('/api/set_id', { old_id: oldId, new_id: newId });
  clientMsg(`ID ${oldId} -> ${newId} written (model ${r.model}, persistent)`);
  $('servoId').value = newId;
  $('oldId').value = 1;                  // ready for the next factory servo
  $('newId').value = newId + 1;
});
$('ping').onclick = guard(async () => {
  if ($('simulate').checked) { clientMsg('simulation — ping skipped'); return; }
  const r = await api.post('/api/ping', { servo_id: +$('servoId').value });
  clientMsg(`ping ok, model ${r.model}`);
});
$('saveMap').onclick = guard(async () => {
  if (!selected) return;
  const entry = { servo_id: +$('servoId').value,
    servo_model: $('servoModel').value, axis: $('axis').value };
  const r = await api.post('/api/mapping', { node: selected.name, ...entry,
    joint: currentJoint?.name ?? null });
  servoIds = r.servo_ids ?? servoIds;
  renderGroup();
  clientMsg(`mapping saved: "${selected.name}" -> ID ${entry.servo_id}`
    + (currentJoint
      ? ` (+ group config: ${currentJoint.name} -> ID ${entry.servo_id})`
      : ' (no CAD joint — group config unchanged)'));
});
$('run').onclick = guard(async () => {
  clientLog.length = 0;
  const lims = currentJoint && jointLimits[currentJoint.name];
  if (lims && (+$('minDeg').value < lims.min_deg
            || +$('maxDeg').value > lims.max_deg))
    clientMsg(`note: interval exceeds configured limits `
      + `[${lims.min_deg}, ${lims.max_deg}]° — the server will clamp it`);
  await api.post('/api/test', {
    servo_id: +$('servoId').value,
    servo_model: $('servoModel').value,
    min_deg: +$('minDeg').value,
    max_deg: +$('maxDeg').value,
    speed: +$('speed').value,
    acc: +$('acc').value,
    cycles: +$('cycles').value,
    simulate: $('simulate').checked,
    node: selected?.name ?? null,
    joint: currentJoint?.name ?? null,
  });
});
$('saveLimits').onclick = guard(async () => {
  if (!currentJoint) return;
  const r = await api.post('/api/limits', {
    joint: currentJoint.name,
    min_deg: +$('minDeg').value,
    max_deg: +$('maxDeg').value,
    symmetric: $('symmetric').checked,
  });
  jointLimits = r.limits;
  renderGroup();
  clientMsg(`limits saved for "${currentJoint.name}"`
    + (r.mirrored ? ` + mirrored to "${r.mirrored}"` : '')
    + (r.skipped ? ` — "${r.skipped}" kept its own direct values` : ''));
});
$('poseSlider').addEventListener('input', () => {
  if (!currentJoint) return;
  const v = +$('poseSlider').value;
  setJointAngle(currentJoint.name, v);
  syncPoseUI(v);
});
$('poseReset').onclick = () => {
  resetPose();
  syncPoseUI(0);
};
$('center').onclick = guard(async () => {
  clientLog.length = 0;
  await api.post('/api/center', {
    servo_id: +$('servoId').value,
    speed: Math.min(+$('speed').value, 500),   // gentle move for assembly
    acc: +$('acc').value,
    simulate: $('simulate').checked,
  });
});
$('stop').onclick = guard(() => api.post('/api/stop'));

// ---------------------------------------------------------------- upload

const vp = $('viewport');
vp.addEventListener('dragover', e => { e.preventDefault(); vp.classList.add('dragover'); });
vp.addEventListener('dragleave', () => vp.classList.remove('dragover'));
vp.addEventListener('drop', guard(async e => {
  e.preventDefault();
  vp.classList.remove('dragover');
  const file = e.dataTransfer.files[0];
  if (!file?.name.endsWith('.glb')) { clientMsg('please drop a .glb file'); return; }
  clientMsg(`uploading ${file.name} (${(file.size / 1e6).toFixed(1)} MB) ...`);
  const r = await fetch('/api/model', { method: 'PUT', body: file });
  if (!r.ok) throw new Error((await r.json()).detail ?? r.statusText);
  await loadModel();
}));

// ---------------------------------------------------------------- init

guard(async () => {
  await Promise.all([refreshPorts(), refreshStatus()]);
  mapping = await api.get('/api/mapping');
  jointLimits = await api.get('/api/limits');
  servoIds = await api.get('/api/servo_ids');
  renderGroup();
  const jr = await api.get('/api/joints');
  joints = jr.joints ?? [];
  fastened = jr.fastened ?? [];
  if (joints.length) clientMsg(`${joints.length} CAD joints loaded (pinned version)`);
  await loadModel();
})();
