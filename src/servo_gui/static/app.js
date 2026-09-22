// Zeroth-01 single-servo test GUI — 3D viewer + controls.
// Click a part of the pinned CAD model, set the test interval, run the test.
// The orange gauge shows the [min, max] range; the needle follows the live
// position streamed from the backend (hardware or simulation).

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';

const $ = id => document.getElementById(id);
// must match server.API_VERSION — mismatch means a stale backend is running
const EXPECTED_API = 20;
// must match the Pi service's API_VERSION (wireless mode)
const EXPECTED_PI_API = 8;
let staleWarned = false;
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

// wireless mode: this page talks straight to the Pi intent service (CORS
// is open there); base URL comes from hardware/connection.json via /api/status
let conn = { mode: 'usb', port: 'auto', pi_url: 'http://192.168.178.147:8460' };
const wireless = () => conn.mode === 'wireless';
// Timeouts are essential here: a halting/unplugged Pi leaves TCP connects
// hanging in SYN retries for MINUTES — without an abort, the status poll
// stalls and the UI never notices the Pi is gone (e.g. no shutdown banner).
// An error body is NOT data: a Pi too old for an endpoint answers 404 with
// {"detail": ...}, and silently using that as the payload corrupts whatever
// it feeds (limits!). Both verbs reject instead, callers decide what to do.
const piResult = async (r) => {
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail ?? r.statusText);
  return data;
};
const pi = {
  get: (p, timeoutMs = 4000) =>
    fetch(conn.pi_url + p, { signal: AbortSignal.timeout(timeoutMs) })
      .then(piResult),
  post: (p, body, timeoutMs = 8000) =>
    fetch(conn.pi_url + p, { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body ?? {}),
      signal: AbortSignal.timeout(timeoutMs) }).then(piResult),
};

// ---------------------------------------------------------------- log

let serverLog = [];
const clientLog = [];
function renderLog() {
  const el = $('log');
  // stick to the bottom only if the user is already there — otherwise leave
  // the scroll position alone so older lines can be read/copied
  const stick = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  el.textContent = [...serverLog.map(l => l.msg), ...clientLog].join('\n');
  if (stick) el.scrollTop = el.scrollHeight;
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

// ground-contact heuristic ("gravity feel"), display only, no physics:
// 1) SOLE ALIGNMENT — tilt the whole model (damped, anchored at the stance
//    foot) so the stance foot's sole lies FLUSH on the floor plane, i.e.
//    maximum contact area instead of a single corner touching.
// 2) VERTICAL SNAP — shift the model so the lowest foot rests on the floor.
// Stance foot = the lower one (with hysteresis). Feet may still slide
// horizontally and nothing tips over — that's where real physics would start.
let groundY = 0;
let footNodes = [];
let baseQuat = null;               // modelRoot orientation at load
let anchorXZ = null;   // torso XZ at load time — the model is re-centred there every frame while ground contact is on
const soleNormal = new Map();      // foot node -> sole normal in foot frame
const DOWN = new THREE.Vector3(0, -1, 0);
const groundBox = new THREE.Box3();
const _fb = new THREE.Box3();
const _q1 = new THREE.Quaternion(), _q2 = new THREE.Quaternion();
const _v1 = new THREE.Vector3();
const _m1 = new THREE.Matrix4(), _m2 = new THREE.Matrix4();
let stance = null;

function captureSoleNormals() {
  // at the calibrated rest pose both soles are flat on the ground, so the
  // world down-direction expressed in each foot's frame IS the sole normal
  soleNormal.clear();
  for (const f of footNodes) {
    f.updateWorldMatrix(true, false);
    soleNormal.set(f,
      DOWN.clone().applyQuaternion(f.getWorldQuaternion(_q1).invert()));
  }
}

renderer.setAnimationLoop(() => {
  controls.update();
  if (modelRoot && footNodes.length === 2 && $('groundSnap').checked) {
    // stance foot = lower foot, with 5 mm hysteresis against flip-flopping
    const mins = footNodes.map(f => {
      _fb.makeEmpty();
      _fb.expandByObject(f);
      return _fb.min.y;
    });
    const lower = mins[0] <= mins[1] ? 0 : 1;
    if (!stance || !footNodes.includes(stance)) stance = footNodes[lower];
    else {
      const si = footNodes.indexOf(stance);
      if (mins[1 - si] < mins[si] - 0.005) stance = footNodes[1 - si];
    }
    // tilt so the stance sole's normal points straight down (damped P-step),
    // rotating about the stance foot's contact point so it stays anchored
    const n = soleNormal.get(stance);
    if (n) {
      const nW = _v1.copy(n).applyQuaternion(stance.getWorldQuaternion(_q1));
      const delta = _q2.setFromUnitVectors(nW, DOWN);
      _q1.identity().slerp(delta, 0.25);           // damping
      _fb.makeEmpty();
      _fb.expandByObject(stance);
      const px = (_fb.min.x + _fb.max.x) / 2, py = _fb.min.y,
            pz = (_fb.min.z + _fb.max.z) / 2;
      _m1.makeTranslation(-px, -py, -pz);
      _m2.makeRotationFromQuaternion(_q1).multiply(_m1);
      _m1.makeTranslation(px, py, pz).multiply(_m2);
      modelRoot.applyMatrix4(_m1);
    }
    // vertical snap: lowest foot point onto the floor plane
    groundBox.makeEmpty();
    footNodes.forEach(f => groundBox.expandByObject(f));
    if (!groundBox.isEmpty()) {
      const dy = groundY - groundBox.min.y;
      if (Math.abs(dy) > 1e-5) modelRoot.position.y += dy;
    }
    // horizontal re-centring: the tilt about the stance foot (and every
    // stance change) walks the body sideways a little each frame, so over a
    // demo the model drifted away from the view centre. Keep the torso at
    // the XZ it had when the model was loaded.
    if (anchorXZ) {
      const tn = findNode('Torso <1>');
      if (tn) {
        tn.updateWorldMatrix(true, false);
        const w = tn.getWorldPosition(_v1);
        const dx = anchorXZ.x - w.x, dz = anchorXZ.z - w.z;
        if (Math.abs(dx) > 1e-5 || Math.abs(dz) > 1e-5) {
          modelRoot.position.x += dx; modelRoot.position.z += dz;
        }
      }
    }
  } else if (modelRoot && baseQuat
             && (modelRoot.position.lengthSq() > 1e-10
                 || !modelRoot.quaternion.equals(baseQuat))) {
    modelRoot.position.set(0, 0, 0);   // snap off -> original placement
    modelRoot.quaternion.copy(baseQuat);
    stance = null;
  }
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
  highlighted.clear();               // the old model's Object3Ds are gone
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
  groundY = box.min.y;                 // floor plane for the ground snap
  baseQuat = modelRoot.quaternion.clone();
  { const tn = findNode('Torso <1>'); anchorXZ = tn ? tn.getWorldPosition(new THREE.Vector3()) : center.clone(); }
  clientMsg('CAD model loaded (pinned OnShape version, see resources/cad/VERSION.md)');
  buildRig();
  footNodes = ['foot_left', 'foot_right'].map(findNode).filter(Boolean);
  captureSoleNormals();                // rest pose = soles flat on the ground
  select(null);                        // re-highlight on the NEW node objects
  await loadAttachments();             // own printed add-ons, torso-fixed
}

// ---------------------------------------------------------------- attachments
// Printed add-on parts (hardware/backpack_v2 ...) rendered as children of modelRoot.
// They live in the pinned model's own frame (assembly frame, Z-up, metres), and
// anything that is not part of a joint's chain stays with the root link = torso, so
// the pose rig, ground snap and calibration are untouched. The manifest can also
// hide original parts the build no longer has (old BackPack, battery, MilkV ...).
const attachRoots = new Map();   // set id -> Object3D
const attachLabels = new Map();  // fullKey(node name) -> human label (shown on click)
const nodeMatches = (o, pattern) => {
  const k = fullKey(o.name || ''), pk = fullKey(pattern);
  return !!k && (k === pk || k.startsWith(pk));
};
function attachmentLabelFor(obj) {
  for (let o = obj; o && o !== scene; o = o.parent) {
    const k = fullKey(o.name || '');
    if (!k) continue;
    if (attachLabels.has(k)) return attachLabels.get(k);
    for (const [key, label] of attachLabels) if (k.startsWith(key)) return label;
  }
  return null;
}
function setNodeVisible(root, pattern, on) {
  root.traverse(o => { if (nodeMatches(o, pattern)) o.visible = on; });
}
function paintNode(root, pattern, color, opacity = 1) {
  root.traverse(o => {
    if (!nodeMatches(o, pattern)) return;
    o.traverse(m => {
      if (!m.isMesh) return;
      m.material = new THREE.MeshStandardMaterial({
        color: new THREE.Color(color), roughness: .6, metalness: .05, flatShading: true,
        transparent: opacity < 1, opacity, depthWrite: opacity >= 1,
        side: opacity < 1 ? THREE.DoubleSide : THREE.FrontSide });
    });
  });
}
function checkRow(label, checked, swatch, onChange, extraClass = '') {
  const lab = document.createElement('label');
  lab.className = 'check ' + extraClass;
  const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = checked;
  cb.addEventListener('change', () => onChange(cb.checked));
  lab.appendChild(cb);
  if (swatch) { const sw = document.createElement('span'); sw.className = 'sw'; sw.style.background = swatch; lab.appendChild(sw); }
  lab.appendChild(document.createTextNode(label));
  return lab;
}
// fold state (sets, groups, the panel itself) survives reloads
const FOLD_KEY = 'zbot.fold.';
const foldGet = (key, dflt) => { try { const v = localStorage.getItem(FOLD_KEY + key); return v === null ? dflt : v === '1'; } catch (_) { return dflt; } };
const foldSet = (key, folded) => { try { localStorage.setItem(FOLD_KEY + key, folded ? '1' : '0'); } catch (_) {} };
// wrap a checkbox row in a header with a chevron that folds `wrap` (the row's container)
function foldable(wrap, row, key, dfltFolded) {
  const hdr = document.createElement('div'); hdr.className = 'fold-hdr';
  const btn = document.createElement('button'); btn.type = 'button'; btn.className = 'chev-btn';
  btn.textContent = '▾'; btn.title = 'fold / unfold';
  const apply = f => { wrap.classList.toggle('folded', f); btn.textContent = '▾'; };
  btn.addEventListener('click', e => { e.preventDefault(); const f = !wrap.classList.contains('folded'); apply(f); foldSet(key, f); });
  hdr.appendChild(btn); hdr.appendChild(row); wrap.appendChild(hdr);
  apply(foldGet(key, dfltFolded));
}
$('attachHead')?.addEventListener('click', () => {
  const sec = $('attachSection'); const f = !sec.classList.contains('folded');
  sec.classList.toggle('folded', f); foldSet('panel', f);
});
async function loadAttachments() {
  const list = $('attachList'), section = $('attachSection');
  section.classList.toggle('folded', foldGet('panel', false));
  if (!list || !modelRoot) return;
  list.innerHTML = '';
  for (const r of attachRoots.values()) r.parent?.remove(r);
  attachRoots.clear(); attachLabels.clear();
  let manifest;
  try { manifest = await api.get('/api/attachments'); } catch { manifest = { sets: [], hide: [] }; }
  const sets = manifest.sets ?? [], hides = manifest.hide ?? [];
  section.classList.toggle('hidden', !sets.length && !hides.length);
  for (const set of sets) {
    let gltf;
    try { gltf = await new GLTFLoader().loadAsync('/attachments/' + encodeURIComponent(set.file)); }
    catch (e) { clientMsg(`attachment "${set.label}" not loaded: ${e.message}`); continue; }
    const root = gltf.scene;
    root.name = 'attach:' + set.id;
    root.visible = set.visible !== false;
    modelRoot.add(root);
    attachRoots.set(set.id, root);
    const wrap = document.createElement('div'); wrap.className = 'attach-set';
    foldable(wrap, checkRow(set.label, root.visible, null, on => { root.visible = on; }), 'set.' + set.id, true);
    const parts = document.createElement('div'); parts.className = 'parts';
    const itemRow = (item, container) => {
      paintNode(root, item.node, item.color ?? '#999999', item.opacity ?? 1);
      const on = item.visible !== false;
      setNodeVisible(root, item.node, on);
      attachLabels.set(fullKey(item.node), item.label);
      const row = checkRow(item.label, on, item.color ?? '#999999', v => setNodeVisible(root, item.node, v));
      container.appendChild(row);
      return row.querySelector('input');
    };
    for (const part of set.parts ?? []) itemRow(part, parts);
    wrap.appendChild(parts);
    // groups (components, cables ...): one "all" checkbox + one row per item
    for (const grp of set.groups ?? []) {
      const gwrap = document.createElement('div'); gwrap.className = 'attach-group';
      const inner = document.createElement('div'); inner.className = 'parts';
      const boxes = [];
      const anyOn = (grp.items ?? []).some(i => i.visible !== false);
      foldable(gwrap, checkRow(grp.label, anyOn, null, v => {
        for (const [item, cb] of boxes) { cb.checked = v; setNodeVisible(root, item.node, v); }
      }, 'group'), 'group.' + (grp.id ?? set.id + '.' + grp.label), true);
      for (const item of grp.items ?? []) boxes.push([item, itemRow(item, inner)]);
      gwrap.appendChild(inner);
      wrap.appendChild(gwrap);
    }
    list.appendChild(wrap);
    clientMsg(`attachment "${set.label}" loaded (${set.file})`);
  }
  for (const h of hides) {
    const apply = on => {
      for (const pat of h.patterns ?? [])
        modelRoot.traverse(o => { if (!o.name?.startsWith('attach:') && nodeMatches(o, pat)) o.visible = !on; });
    };
    apply(h.default !== false);
    list.appendChild(checkRow(h.label, h.default !== false, null, apply));
  }
}
// torso see-through: clone the torso's materials once, then fade them
let torsoMats = null;
$('torsoXray')?.addEventListener('change', e => {
  const torso = findNode('Torso <1>'); if (!torso) return;
  if (!torsoMats) {
    torsoMats = [];
    torso.traverse(m => { if (m.isMesh) { m.material = m.material.clone(); torsoMats.push(m.material); } });
  }
  for (const mat of torsoMats) {
    mat.transparent = e.target.checked; mat.opacity = e.target.checked ? 0.3 : 1;
    mat.depthWrite = !e.target.checked; mat.needsUpdate = true;
  }
});

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

// The 3D view and the Servos list share ONE selection: a motor glowing orange
// in the model is exactly a checked box, in both directions. Clicking a motor
// part toggles it; parts that carry no configured servo cannot appear in the
// list and keep the plain "this is what I clicked" glow.
const highlighted = new Set();     // roots currently emissive

// canonical node of a joint = its motor part — that is what a list row means
function jointNode(name) {
  const j = joints.find(x => x.name === name);
  if (!j) return null;
  return findNode(j.occurrences.find(o => /motor/i.test(o)) ?? j.occurrences[0]);
}
const inServoList = j => !!j && servoIds[j.name] !== undefined;

function applyHighlights() {
  const want = new Set();
  for (const name of selectedJoints()) {
    const n = jointNode(name);
    if (n) want.add(n);
  }
  if (selected && !inServoList(currentJoint)) want.add(selected);
  for (const o of highlighted) if (!want.has(o)) setHighlight(o, false);
  for (const o of want) if (!highlighted.has(o)) setHighlight(o, true);
  highlighted.clear();
  for (const o of want) highlighted.add(o);
  $('selClear').disabled = !selected && !want.size;
  renderTorqueScope();
}

// Spell out what ✋ release / 🔒 lock will act on right now (same rule as
// torqueTargets: checked servos, else the clicked model joint, else all).
function renderTorqueScope() {
  const el = $('torqueScope');
  if (!el) return;
  const js = selectedJoints();
  el.textContent = 'release / lock act on: ' + (js.length
    ? `${js.length} selected servo${js.length > 1 ? 's' : ''}`
    : (currentJoint && servoIds[currentJoint.name] !== undefined)
      ? `clicked joint ${currentJoint.name}`
      : 'all servos');
}

// 3D click -> list checkbox (the list stays the single source of truth)
function toggleJointSelection(name) {
  const box = [...document.querySelectorAll('.gsel')]
    .find(c => c.value === name);
  if (!box) return;
  if (box.disabled) {                     // servo doesn't answer on the bus
    clientMsg(`${name} is not on the bus — cannot be selected`);
    return;
  }
  box.checked = !box.checked;
  clientMsg(`${name} ${box.checked ? 'selected' : 'deselected'} — `
    + `${selectedJoints().length} servo(s) selected`);
}

function select(obj, toggle = false) {
  selected = obj;
  const has = !!selected;
  currentJoint = has ? findJoint(selected) : null;
  if (toggle && inServoList(currentJoint))
    toggleJointSelection(currentJoint.name);
  $('axis').disabled = !!currentJoint;   // axis comes from the CAD joint
  const attachLabel = has ? attachmentLabelFor(selected) : null;
  $('selName').textContent = has
    ? (attachLabel ?? selected.name ?? '(unnamed)')
      + (currentJoint ? `  ·  ⚙ ${currentJoint.name}` : '')
    : 'nothing selected';
  if (attachLabel) clientMsg(`attachment: ${attachLabel}`);
  if (currentJoint)
    clientMsg(`CAD joint "${currentJoint.name}" — axis & center from OnShape`);
  const hasPivot = !!(currentJoint && pivots.has(currentJoint.name));
  $('poseRow').classList.toggle('hidden', !hasPivot);
  if (hasPivot) syncPoseUI(jointAngles.get(currentJoint.name) ?? 0);
  $('offsetRow').classList.toggle('hidden', !currentJoint);
  $('livePosRow').classList.toggle('hidden', !currentJoint);
  if (currentJoint) {
    $('offsetDeg').value = jointOffsets[currentJoint.name] ?? 0;
    $('zeroHere').disabled = !connected;
    $('livePos').textContent = connected ? '…' : '– (connect for live position)';
    if (jointOffsets[currentJoint.name])
      clientMsg(`mount offset from config: `
        + `${jointOffsets[currentJoint.name] >= 0 ? '+' : ''}`
        + `${jointOffsets[currentJoint.name]}°`);
  }
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
  $('saveMap').disabled = !has;
  const nodeMap = has ? mapping[selected.name] : null;
  if (nodeMap) {
    $('servoModel').value = nodeMap.servo_model;
    if (nodeMap.axis) $('axis').value = nodeMap.axis;
  }
  // servo ID: prefer the canonical joint -> ID config (hardware/servo_ids.json),
  // the one `set ID` / group runs use, so a configured ID is always retrieved;
  // fall back to the per-node mapping for non-joint parts
  const cfgId = currentJoint ? servoIds[currentJoint.name] : undefined;
  if (cfgId != null) {
    $('servoId').value = cfgId;
    clientMsg(`servo ID ${cfgId} for ${currentJoint.name} (from config)`);
  } else if (nodeMap) {
    $('servoId').value = nodeMap.servo_id;
    clientMsg(`mapping: "${selected.name}" -> ID ${nodeMap.servo_id}`);
  }
  updateGauge();
  applyHighlights();
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
  select(hit ? nearestNamed(hit.object) : null, true);
});
$('selParent').onclick = () =>
  selected && select(nearestNamed(selected.parent));
$('selClear').onclick = () => {
  document.querySelectorAll('.gsel:checked').forEach(c => { c.checked = false; });
  select(null);
};

// Reverse of servo_ids.json (id -> joint). Selecting the joint that carries a
// given bus ID keeps the 3D selection in sync with the ID you are operating on,
// so you never configure/test the wrong servo after changing the ID field.
const jointForId = id =>
  Object.entries(servoIds).find(([, i]) => i === id)?.[0];
function selectJointForId(id) {
  const node = jointNode(jointForId(id));
  if (node && node !== selected) select(node);   // activate, don't toggle
  return !!node;
}

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
  jointAngles.set(name, deg);      // servo-space angle (0 = real robot zero)
  // display-only mapping: modelZero shifts the rest pose onto the real robot's
  // zero; modelInvert flips joints whose real servo turns the other way
  const disp = (modelInvert[name] ? -deg : deg) + (modelZero[name] ?? 0);
  p.pivot.quaternion.setFromAxisAngle(p.axisLocal,
    THREE.MathUtils.degToRad(disp));
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
  // apply the model-zero corrections so the resting model matches the REAL
  // robot's zero pose (standing straight) instead of the CAD scene pose
  for (const name of pivots.keys())
    setJointAngle(name, jointAngles.get(name) ?? 0);
  if (pivots.size)
    clientMsg(`pose rig ready: ${pivots.size}/${joints.length} joints articulable`);
}

// ---------------------------------------------------------------- live (SSE)

let mapping = {};
let joints = [];
let fastened = [];
let jointLimits = {};   // joint name -> {min_deg, max_deg, set} from repo config
let servoIds = {};      // joint name -> bus ID from hardware/servo_ids.json
let jointOffsets = {};  // joint name -> mount offset deg (hardware/joint_offsets.json)
let modelZero = {};     // joint name -> display-only model zero correction (deg)
let centerPose = {};    // joint name -> deg: override of the center pose (all ⌂ center actions)
function renderCenterPose() {
  const row = $('centerPoseRow');
  const items = Object.entries(centerPose);
  if (!items.length) { row.classList.add('hidden'); return; }
  $('centerPoseVal').textContent = items.map(([j, d]) =>
    `${j.replace(/^(left|right)_/, m => m[0] === 'l' ? 'L·' : 'R·')} ${d > 0 ? '+' : ''}${d}°`).join(', ');
  row.classList.remove('hidden');
}
let modelInvert = {};   // joint name -> true if the model rig turns inverted
let availableIds = null; // Set of bus IDs present, or null = unknown (all enabled)
let connected = false;  // real hardware bus present (from /api/status)
let running = false;    // a run is in progress (from the SSE stream)

new EventSource('/api/stream').onmessage = e => {
  if (wireless()) return;    // the Pi status poll owns the UI in wireless mode
  const live = JSON.parse(e.data);
  running = live.running;
  serverLog = live.log ?? [];
  renderLog();
  $('phase').textContent = live.phase;
  $('posDeg').textContent = live.deg != null
    ? (live.deg >= 0 ? '+' : '') + live.deg.toFixed(1) + ' °' : '–';
  $('run').disabled = live.running;
  $('center').disabled = live.running;
  $('stop').disabled = !live.running;
  $('groupRun').disabled = $('groupCenter').disabled =
    $('groupRelease').disabled = $('demoPlay').disabled = live.running;
  // switching modes mid-run would hide the STOP that controls this machine
  $('modeUsb').disabled = $('modeWifi').disabled = live.running;
  // during a run the SSE stream owns the needle/pose; when idle the 250 ms live
  // poll owns them, so don't fight it here with a stale last-run angle
  if (live.running && needle && live.deg != null)
    needle.rotation.z = THREE.MathUtils.degToRad(live.deg);
  if (live.running && live.deg != null
      && currentJoint && pivots.has(currentJoint.name)) {
    setJointAngle(currentJoint.name, live.deg);
    syncPoseUI(live.deg);
  }
  // a run always re-attaches the model to the live twin
  if (live.running) exitStepPreview(false);
  // group runs stream all joint positions — animate the whole rig
  // (suppressed while a waypoint preview owns the model)
  if (live.multi && previewI === null) {
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

const fmtDeg = d => (d >= 0 ? '+' : '') + (+d).toFixed(1) + '°';

// Idle digital twin: mirror ONLY joints whose REAL position moved since the
// last sweep (hand-posing a released joint). Untouched joints keep their
// virtual slider pose (model-pose teach-in), and the ±1-encoder-count idle
// flicker (~0.1°) stays below the threshold — no ground-contact wobble.
let lastRealPose = null;
function mirrorMovedJoints(pose) {
  if (!pose) return;
  if (!lastRealPose) {
    // first sweep after (re)connect: FULL sync — the twin starts at reality,
    // not at the model's default center pose
    for (const [j, d] of Object.entries(pose)) {
      if (!pivots.has(j)) continue;
      setJointAngle(j, d);
      if (currentJoint?.name === j) syncPoseUI(d);
    }
  } else {
    for (const [j, d] of Object.entries(pose)) {
      if (!pivots.has(j) || lastRealPose[j] === undefined) continue;
      if (Math.abs(d - lastRealPose[j]) >= 0.15) {
        setJointAngle(j, d);
        if (currentJoint?.name === j) syncPoseUI(d);
      }
    }
  }
  lastRealPose = { ...(lastRealPose ?? {}), ...pose };
}

// Idle live position: while connected + not running + a joint is selected,
// poll the selected servo a few times a second. Shows the current angle (in
// CAD-frame, offset applied) and drives the gauge needle — so you can hand-turn
// the output and watch it, then "set current position as zero".
let usbPollN = 0;
async function livePoll() {
  try {
    // idle digital twin (USB): every 2nd tick, sweep the real pose and
    // mirror hand-moved joints (see mirrorMovedJoints for the rules)
    if (!wireless() && !connected) lastRealPose = null;  // next connect: full sync
    usbPollN = (usbPollN + 1) % 2;
    if (usbPollN === 0 && connected && !running && !wireless()
        && previewI === null) {
      const rp = await api.get('/api/robot_pose').catch(() => null);
      if (rp?.pose && connected && !running && previewI === null)
        mirrorMovedJoints(rp.pose);
    }
    const j = currentJoint;                 // capture: selection may change mid-await
    if (connected && !running && j && !wireless()) {
      const r = await api.get(`/api/servo_pos?servo_id=${+$('servoId').value}`
        + `&joint=${encodeURIComponent(j.name)}`);
      // discard if the selection changed or a run started while awaiting
      if (currentJoint === j && !running) {
        if (r.ok) {
          $('livePos').textContent = `${fmtDeg(r.deg)}  (tick ${r.ticks})`;
          if (needle) needle.rotation.z = THREE.MathUtils.degToRad(r.deg);
        } else if (!r.running) {
          $('livePos').textContent = r.reason === 'no_response'
            ? 'no response — wired & powered?' : '–';
        }
      }
    }
  } catch (_) { /* soft: keep last shown value */ }
  finally {
    setTimeout(livePoll, 250);
  }
}
livePoll();

// ---------------------------------------------------------------- controls

async function refreshStatus() {
  const s = await api.get('/api/status');
  $('buildTag').textContent =
    `— GUI v${EXPECTED_API} · backend v${s.api_version ?? '?'}`;
  const stale = (s.api_version ?? 0) !== EXPECTED_API;
  $('staleBanner').classList.toggle('hidden', !stale);
  if (stale && !staleWarned) {
    staleWarned = true;
    clientMsg(`⚠ BACKEND OUTDATED (v${s.api_version ?? '<7'}, frontend expects `
      + `v${EXPECTED_API}) — features WILL misbehave. Restart the server: `
      + `Ctrl+C, then "uv run server.py"`);
  }
  // pick up the persisted mode (connection.json) — also catches edits made
  // in another tab or directly in the file
  const prevMode = conn.mode;
  if (s.connection) conn = s.connection;
  if (conn.mode !== prevMode) applyMode();
  if (wireless()) return;      // the Pi poll owns the connection UI below
  const wasConnected = connected;
  connected = s.connected;
  $('connState').textContent = s.connected
    ? 'connected: ' + s.port : 'not connected';
  $('connect').disabled = s.connected;
  $('disconnect').disabled = !s.connected;
  if (s.connected !== wasConnected)      // don't override a manual toggle
    $('simulate').checked = !s.connected; // connected -> hardware by default
  // bus operations are hardware-only — no point offering them unconnected
  $('scan').disabled = $('setId').disabled = $('zeroHere').disabled = !s.connected;
  if (!s.connected) {
    $('scanResult').textContent = 'connect first (hardware only)';
    if (currentJoint) $('livePos').textContent = '– (connect for live position)';
    if (needle) needle.rotation.z = 0;   // drop any stale live angle
  }
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

// ------------------------------------------------------- operating mode
// USB (local): everything as before — bench tooling against the local bus.
// Wireless: this page is a pure client of the Pi intent service; bench
// sections are hidden, demos/stop/center/release go to the Pi, and a status
// poll (below) drives log/phase/3D pose instead of the local SSE stream.

function applyMode() {
  const wifi = wireless();
  document.body.classList.toggle('wireless', wifi);
  syncCamera();                // camera stream only while wireless + card open
  $('modeUsb').checked = !wifi;
  $('modeWifi').checked = wifi;
  refreshDemos().catch(() => {});
  refreshLimits().catch(() => {});
  if (wifi) {
    $('phase').textContent = 'idle';
    $('posDeg').textContent = '–';
    $('connState').textContent = `Pi ${conn.pi_url} — connecting …`;
    piApiWarned = false;
  }
}

$('modeUsb').onchange = $('modeWifi').onchange = async () => {
  const mode = $('modeWifi').checked ? 'wireless' : 'usb';
  try {
    // never switch away from a machine that is still moving — the STOP for
    // it would vanish. Covers Pi runs (piPoll sets `running`); the server
    // guards local runs authoritatively (POST below -> 400).
    if (running)
      throw new Error('a run is active — press STOP first, then switch');
    const r = await api.post('/api/connection', { mode });   // persist default
    conn = r.connection;
    applyMode();
    clientMsg(mode === 'wireless'
      ? `wireless mode — intents go to the Pi at ${conn.pi_url}`
      : 'USB mode — local bench tooling active');
    if (mode === 'usb') await refreshStatus();
  } catch (err) {
    clientMsg('ERROR: mode not switched — ' + err.message);
    $('modeUsb').checked = conn.mode !== 'wireless';    // revert the radios
    $('modeWifi').checked = conn.mode === 'wireless';
  }
};

// Joint limits are enforced wherever the motion runs: the repo copy in USB
// mode, the robot's own copy in wireless. Always show the ones that apply, so
// calibrating never edits a range the moving machine doesn't use.
let limitSeq = 0;
async function refreshLimits() {
  const seq = ++limitSeq;
  const wifi = wireless();
  const stale = () => seq !== limitSeq || wifi !== wireless();
  const repo = await api.get('/api/limits').catch(e => {
    clientMsg('repo limits unavailable: ' + e.message);
    return {};
  });
  if (stale()) return;
  if (!wifi) { jointLimits = repo; renderGroup(); return; }
  try {
    const robot = await pi.get('/limits');
    if (stale()) return;
    jointLimits = robot;
    // a stale deploy is invisible otherwise — and would silently clamp differently
    const drift = [...new Set([...Object.keys(repo), ...Object.keys(robot)])]
      .filter(j => repo[j]?.min_deg !== robot[j]?.min_deg
                || repo[j]?.max_deg !== robot[j]?.max_deg);
    if (drift.length)
      clientMsg(`limits differ repo ↔ robot for ${drift.length} joint(s): `
        + drift.slice(0, 4).join(', ') + (drift.length > 4 ? ', …' : '')
        + " — showing the robot's (enforced) values; save them again to align");
  } catch (e) {
    if (stale()) return;
    jointLimits = repo;
    clientMsg(`robot limits unavailable (${e.message}) — showing the repo `
      + 'values; a Pi service older than v6 cannot store limits');
  }
  renderGroup();
}

// demo list source follows the mode: repo (USB) vs. robot (wireless) — after
// a deploy both hold the same demos, but the robot's list is the truth there
let demoSeq = 0;    // discard out-of-order responses (a dead-Pi fetch can
                    // resolve seconds after the user already switched back)
async function refreshDemos() {
  const seq = ++demoSeq;
  const wifi = wireless();
  try {
    const r = wifi ? await pi.get('/demos') : await api.get('/api/demos');
    if (seq !== demoSeq || wifi !== wireless()) return;   // stale response
    demos = r.demos ?? [];
  } catch (e) {
    if (seq !== demoSeq || wifi !== wireless()) return;
    demos = [];
    clientMsg('demo list unavailable: ' + e.message);
  }
  renderDemoList();
}

// wireless status poll (~2.5 Hz): log, phase, bus state, live rig pose.
// Intents only ever cross the network — per-cycle setpoints never do.
let piApiWarned = false;
async function piPoll() {
  try {
    if (wireless()) {
      const s = await pi.get('/status');
      if (wireless()) {              // mode may have flipped mid-await
        if (shutdownAt && Date.now() - shutdownAt > 45000) {
          shutdownAt = null;         // still answering -> halt never happened
          clientMsg('⚠ shutdown did not take effect — the Pi is still up');
        }
        running = s.live.running;
        serverLog = s.live.log ?? [];
        renderLog();
        $('phase').textContent = s.live.phase;
        renderHead(s.head);
        renderBattery(s.battery);
        $('connState').textContent = `Pi ${conn.pi_url} — bus `
          + (s.bus.connected
             ? (s.bus.simulated ? 'SIMULATED' : `connected (${s.bus.port})`)
             : 'NOT connected');
        $('demoPlay').disabled = s.live.running;
        $('piCenter').disabled = s.live.running;
        // same rule as USB: no mode switch while the robot is moving
        $('modeUsb').disabled = $('modeWifi').disabled = s.live.running;
        if (s.api_version !== EXPECTED_PI_API && !piApiWarned) {
          piApiWarned = true;
          clientMsg(`⚠ Pi service v${s.api_version} — GUI expects `
            + `v${EXPECTED_PI_API}. Redeploy: src\\pi_service\\deploy\\deploy_pi.ps1`);
        }
        if (s.live.running) exitStepPreview(false);
        if (s.live.multi && previewI === null)
          for (const [j, deg] of Object.entries(s.live.multi))
            if (pivots.has(j)) setJointAngle(j, deg);
        // idle digital twin: sweep the real pose and mirror hand-moved
        // joints (suppressed during runs and while a step preview owns the
        // model; /robot_pose rejects during runs anyway)
        if (!s.bus.connected) lastRealPose = null;   // next connect: full sync
        if (!s.live.running && s.bus.connected && previewI === null) {
          const rp = await pi.get('/robot_pose').catch(() => null);
          if (rp?.pose && wireless() && !running && previewI === null) {
            mirrorMovedJoints(rp.pose);
            if (currentJoint && rp.pose[currentJoint.name] !== undefined)
              $('livePos').textContent = fmtDeg(rp.pose[currentJoint.name]);
          }
        }
      }
    }
  } catch (_) {
    if (wireless()) {
      lastRealPose = null;                       // next contact: full sync
      renderHead(null);
      renderBattery(null);
      if (shutdownAt) {
        const safe = Date.now() - shutdownAt >= SHUTDOWN_GRACE_MS;
        $('connState').textContent = `Pi ${conn.pi_url} — shutting down …`;
        if (safe && batteryHaltSeen) {
          $('batteryBannerState').textContent =
            'Pi is DOWN — cut the main switch now, then charge the pack.';
        } else if (safe && $('shutdownBanner').classList.contains('hidden')) {
          $('shutdownBanner').classList.remove('hidden');
          clientMsg('Pi is down — safe to cut the main switch (check the '
            + 'ACT LED).');
        }
      } else {
        $('connState').textContent = `Pi ${conn.pi_url} — UNREACHABLE `
          + '(service running? ProtonVPN "Allow LAN connections"?)';
      }
    }
  } finally {
    setTimeout(piPoll, 400);
  }
}
piPoll();

$('piStop').onclick = guard(() => pi.post('/stop'));

// ------------------------------------------------------------ battery
// One widget for both modes. USB: /api/battery (this computer's adapter),
// wireless: /status.battery (Pi service BatteryMonitor, which also halts
// the Pi itself before the hardware cutoff). Percent from the 3S LiPo
// open-circuit curve — under servo load the rail reads lower, so it is an
// estimate ("≈").
const LIPO_OCV = [[3.27, 0], [3.50, 5], [3.60, 12], [3.70, 25], [3.75, 35],
                  [3.80, 45], [3.85, 55], [3.90, 65], [3.97, 75], [4.05, 85],
                  [4.12, 93], [4.20, 100]];      // V per cell -> %
function lipoPercent(packV, cells = 3) {
  const v = packV / cells;
  if (v <= LIPO_OCV[0][0]) return 0;
  if (v >= LIPO_OCV[LIPO_OCV.length - 1][0]) return 100;
  for (let i = 1; i < LIPO_OCV.length; i++) {
    const [v0, p0] = LIPO_OCV[i - 1], [v1, p1] = LIPO_OCV[i];
    if (v <= v1) return Math.round(p0 + (p1 - p0) * (v - v0) / (v1 - v0));
  }
  return 100;
}
const USB_WARN_V = 11.1;          // same defaults as the Pi service
const USB_LOW_V = 10.8;
let batteryHaltSeen = false;
function renderBattery(b) {
  // b: null (unreachable) | {volts, servo_id, error, [enabled, level,
  //    low_for_s, hold_s, shutdown, age_s]}
  const box = $('battery'), fill = $('battFill');
  let cls = '', volts = '–', pct = '', note = '', frac = 0;
  if (!b) { note = wireless() ? 'Pi unreachable' : 'connect for the pack voltage'; cls = 'off'; }
  else if (b.enabled === false) { note = 'monitor off on the Pi'; cls = 'off'; }
  else if (b.volts === null || b.volts === undefined) { note = b.error ?? 'no reading'; cls = 'off'; }
  else {
    const v = b.volts, p = lipoPercent(v);
    volts = `${v.toFixed(1)} V`; pct = `≈ ${p} %`; frac = p / 100;
    const level = b.level ?? (v < USB_LOW_V ? 'low' : v < USB_WARN_V ? 'warn' : 'ok');
    if (b.servo_id !== null && b.servo_id !== undefined) note = `ID ${b.servo_id}`;
    if (b.age_s !== null && b.age_s !== undefined && b.age_s > 15)
      note += ` · stale ${b.age_s.toFixed(0)} s`;
    if (level === 'warn') { cls = 'warn'; note += ' · charge soon'; }
    if (level === 'low') {
      cls = 'low';
      note += b.low_for_s !== null && b.low_for_s !== undefined && b.hold_s
        ? ` · LOW — Pi halts in ${Math.max(0, b.hold_s - b.low_for_s).toFixed(0)} s`
        : ' · LOW — stop and charge';
    }
    if (b.shutdown === 'halting') { cls = 'low'; note = 'empty — Pi halting itself'; }
    if (b.shutdown === 'failed') { cls = 'low'; note = 'empty — HALT FAILED: sudo shutdown -h now, then cut power'; }
  }
  box.className = 'battery' + (cls ? ' ' + cls : '');
  fill.setAttribute('width', (26 * frac).toFixed(1));
  $('battVolts').textContent = volts;
  $('battPct').textContent = pct;
  $('battNote').textContent = note;
  if (b && (b.shutdown === 'halting' || b.shutdown === 'failed') && !batteryHaltSeen) {
    batteryHaltSeen = true;
    if (b.shutdown === 'halting' && !shutdownAt) shutdownAt = Date.now();
    showBatteryBanner(b.shutdown === 'failed'
      ? 'HALT FAILED (sudoers rule missing) — run "sudo shutdown -h now" on the Pi, then cut power'
      : 'Pi is halting …');
    clientMsg('⚠ BATTERY EMPTY — the Pi shut itself down; cut the main '
      + 'switch after the ACT LED stops, then charge');
  }
}

// the loud one: stays until acknowledged, replaces the ordinary "safe to cut
// power" banner for a battery-triggered halt
function showBatteryBanner(state) {
  $('batteryBannerState').textContent = state;
  $('batteryBanner').classList.remove('hidden');
  try { document.title = '⚠ BATTERY EMPTY — ' + document.title.replace(/^⚠ BATTERY EMPTY — /, ''); } catch (_) {}
}
$('batteryBannerOk').onclick = () => {
  $('batteryBanner').classList.add('hidden');
  batteryHaltSeen = false;                   // a later halt (after a recharge) warns again
  shutdownAt = null;
  try { document.title = document.title.replace(/^⚠ BATTERY EMPTY — /, ''); } catch (_) {}
};

// USB mode: poll the adapter every ~2 s (the server caches for 2 s anyway)
let usbBattN = 0;
async function usbBatteryPoll() {
  try {
    if (!wireless()) {
      if (!connected) renderBattery(null);
      else {
        usbBattN = (usbBattN + 1) % 8;
        if (usbBattN === 0) {
          const b = await api.get('/api/battery');
          if (!wireless()) renderBattery(b);
        }
      }
    }
  } catch (_) { /* soft: keep last shown value */ }
  finally { setTimeout(usbBatteryPoll, 250); }
}
usbBatteryPoll();

// ------------------------------------------------------------ head card
// Camera + IMU overlay (top-right of the viewport). Both feeds come straight
// from the Pi service: the IMU sample rides along in /status (piPoll), the
// camera is an <img> on the multipart MJPEG endpoint — opened only while the
// card is expanded, so nothing streams (and rpicam-vid does not run) when
// nobody is looking. Units are the sensor's: mg, °/s, °C, V.

const HEAD_OPEN_KEY = 'headCardOpen';
const ACC_FULL = 1500, GYRO_FULL = 250;      // bar scale: ±full = full width
let camRetry = null;

const headOpen = () => !$('headCard').classList.contains('collapsed');

function syncCamera() {
  const img = $('camImg');
  const want = wireless() && headOpen();
  clearTimeout(camRetry); camRetry = null;
  if (!want) {
    if (img.hasAttribute('src')) { img.src = ''; img.removeAttribute('src'); }
    $('camMsg').textContent = 'camera off';
    $('camMsg').classList.remove('hidden');
    return;
  }
  $('camMsg').textContent = 'connecting …';
  $('camMsg').classList.remove('hidden');
  img.src = `${conn.pi_url}/camera.mjpg?t=${Date.now()}`;
}
$('camImg').onload = () => $('camMsg').classList.add('hidden');
$('camImg').onerror = () => {
  if (!headOpen() || !wireless()) return;
  $('camMsg').textContent = 'camera unavailable — retrying …';
  $('camMsg').classList.remove('hidden');
  camRetry = setTimeout(syncCamera, 3000);
};

$('headToggle').onclick = () => {
  $('headCard').classList.toggle('collapsed');
  try { localStorage.setItem(HEAD_OPEN_KEY, headOpen() ? '1' : '0'); } catch (_) {}
  syncCamera();
};
try {
  if (localStorage.getItem(HEAD_OPEN_KEY) === '1')
    $('headCard').classList.remove('collapsed');
} catch (_) {}

for (const b of $('eyeChips').querySelectorAll('button'))
  b.onclick = guard(() => pi.post('/head/cmd', { line: b.dataset.cmd }));

const fmtNum = (v, d = 0) => v === null || v === undefined ? '–'
  : (v >= 0 ? '+' : '') + (+v).toFixed(d);

function setBar(el, v, full) {
  const pct = Math.max(-1, Math.min(1, (v ?? 0) / full)) * 50;
  el.style.left = (pct < 0 ? 50 + pct : 50) + '%';
  el.style.width = Math.abs(pct) + '%';
}

function drawTilt(roll, pitch) {
  const cv = $('tiltBubble'), ctx = cv.getContext('2d');
  const r = cv.width / 2, cx = r, cy = r;
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.strokeStyle = '#3a4352'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.arc(cx, cy, r - 1, 0, Math.PI * 2); ctx.stroke();
  ctx.beginPath(); ctx.arc(cx, cy, (r - 1) * (30 / 45), 0, Math.PI * 2); ctx.stroke();
  ctx.beginPath(); ctx.moveTo(cx - r, cy); ctx.lineTo(cx + r, cy);
  ctx.moveTo(cx, cy - r); ctx.lineTo(cx, cy + r); ctx.stroke();
  if (roll === null || roll === undefined || pitch === null) return;
  // dot = where the head leans: nose down -> up on the dial, right ear -> right
  const k = (r - 1) / 45;
  const x = cx + Math.max(-45, Math.min(45, roll)) * k;
  const y = cy - Math.max(-45, Math.min(45, pitch)) * k;
  ctx.fillStyle = '#ff8c1a';
  ctx.beginPath(); ctx.arc(x, y, 5, 0, Math.PI * 2); ctx.fill();
}

function renderHead(h) {
  const imu = h?.imu, s = imu?.sample, cam = h?.camera;
  const fresh = s && imu.age_s !== null && imu.age_s < 1.5;
  $('headDot').className = 'dot ' + (fresh ? 'live' : s ? 'stale' : '');
  for (const el of $('imuBars').querySelectorAll('.fill'))
    setBar(el, fresh ? s[el.dataset.k] : 0,
           el.dataset.k[0] === 'a' ? ACC_FULL : GYRO_FULL);
  for (const el of $('imuBars').querySelectorAll('.v'))
    el.textContent = s ? fmtNum(s[el.dataset.v], el.dataset.v[0] === 'a' ? 0 : 1) : '–';
  drawTilt(fresh ? s.roll_deg : null, fresh ? s.pitch_deg : null);
  $('imuTilt').textContent = fresh && s.tilt_deg !== null
    ? `tilt ${s.tilt_deg.toFixed(0)}°` : '–';
  let meta;
  if (!h) meta = 'Pi unreachable';
  else if (!imu.connected) meta = 'IMU: ' + (imu.error ?? 'no board');
  else if (!s) meta = `IMU: ${imu.port.split('/').pop()} — waiting for data`;
  else meta = (fresh ? 'IMU live' : `IMU stale (${imu.age_s.toFixed(0)} s)`)
    + (s.temp_c !== undefined ? ` · ${s.temp_c.toFixed(1)} °C` : '')
    + (s.vsys !== undefined ? ` · ${s.vsys.toFixed(2)} V` : '')
    + (s.source === 'demo' ? ' · stock firmware' : '')
    + (s.mood ? ` · ${s.mood}` : '');
  if (cam && headOpen() && cam.streaming && cam.fps)
    meta += ` · cam ${cam.fps.toFixed(0)} fps`;
  $('imuMeta').textContent = meta;
  for (const b of $('eyeChips').querySelectorAll('button'))
    b.disabled = !(s && s.source === 'json');
}
// After a confirmed /shutdown, the poll watches for the Pi going silent and
// then shows the "safe to cut power" banner. NOT immediately on unreachable:
// the HTTP service dies at the START of the halt sequence — flushing and
// unmounting happen after it, so we wait SHUTDOWN_GRACE_MS from the click.
const SHUTDOWN_GRACE_MS = 15000;
let shutdownAt = null;
$('piShutdown').onclick = guard(async () => {
  if (!confirm('Pi wirklich herunterfahren?\n\nDie Servos halten ihre Pose '
      + 'weiter (eigene Versorgung). Hauptschalter erst ausschalten, wenn '
      + 'die grüne ACT-LED aufgehört hat zu blinken (~15 s).')) return;
  await pi.post('/shutdown');
  shutdownAt = Date.now();
  clientMsg('Pi is shutting down — the banner appears once it is safe to '
    + 'cut the main switch.');
});
$('shutdownBannerOk').onclick = () => {
  $('shutdownBanner').classList.add('hidden');
  shutdownAt = null;
};
$('piCenter').onclick = guard(async () => {
  clientLog.length = 0;
  await pi.post('/center', { hold: true, speed: 300 });
});

$('refreshPorts').onclick = guard(refreshPorts);
$('connect').onclick = guard(async () => {
  await api.post('/api/connect', { port: $('port').value || null });
  await refreshStatus();
  await refreshPresence();               // gray out servos not on the bus
});
$('disconnect').onclick = guard(async () => {
  await api.post('/api/disconnect');
  await refreshStatus();
  await refreshPresence();               // -> all enabled again (simulation)
});
// Body regions fall out of the joint names, so there is no second list to keep
// in sync: the `left_`/`right_` prefix gives the side, shoulder/elbow vs.
// hip/knee/ankle gives upper vs. lower body.
const SECTION = j => /_(shoulder|elbow)_/.test(j) ? 'upper' : 'lower';
const SIDE = j => j.startsWith('left_') ? 'left'
  : j.startsWith('right_') ? 'right' : 'center';
const SECTIONS = [
  ['upper', 'upper body', 'shoulders · elbows'],
  ['lower', 'lower body', 'hips · knees · ankles'],
];

function renderGroup() {
  const wasChecked = new Set(selectedJoints());   // preserve selection across re-render
  const entries = Object.entries(servoIds).sort((a, b) => a[1] - b[1]);
  const check = ([j, id]) => {
    const lim = jointLimits[j];
    const range = lim ? ` [${lim.min_deg}, ${lim.max_deg}]°` : ' (no limits!)';
    const absent = availableIds && !availableIds.has(id);   // not on the bus
    return `<label class="check${absent ? ' absent' : ''}">`
      + `<input type="checkbox" class="gsel" value="${j}"`
      + `${absent ? ' disabled' : ''}> `
      + `${String(id).padStart(2)} · ${j}${range}`
      + `${absent ? ' — not found' : ''}</label>`;
  };
  // ID order already lays each section out left-limb-then-right (11..13 / 21..23,
  // 31..35 / 41..45), so the blocks read the way the robot is built.
  const block = ([key, label, hint]) => {
    const mine = entries.filter(([j]) => SECTION(j) === key);
    if (!mine.length) return '';
    return '<div class="grpblock"><div class="grphead">'
      + `<span>${label} <span class="hint">— ${hint}</span></span>`
      + '<span class="chips">'
      + `<button data-sel="${key}:left" title="Select/clear the left ${label}">L</button>`
      + `<button data-sel="${key}:right" title="Select/clear the right ${label}">R</button>`
      + `<button data-sel="${key}" title="Select/clear the whole ${label}">both</button>`
      + `</span></div>${mine.map(check).join('')}</div>`;
  };
  $('groupList').innerHTML = entries.length
    ? SECTIONS.map(block).join('')
    : '<span class="muted">no servo IDs configured (hardware/servo_ids.json)</span>';
  document.querySelectorAll('.gsel').forEach(c => {
    if (wasChecked.has(c.value) && !c.disabled) c.checked = true;
  });
  applyHighlights();
}
const selectedJoints = () =>
  [...document.querySelectorAll('.gsel:checked')].map(c => c.value);

// list -> 3D: ticking a box lights that motor up in the model right away
$('groupList').addEventListener('change', e => {
  if (e.target.classList.contains('gsel')) applyHighlights();
});

// gray out configured servos that don't answer on the bus (daisy chain not
// fully wired). null availableIds (disconnected / simulation) = all enabled.
async function refreshPresence() {
  if (!connected) { availableIds = null; renderGroup(); return; }
  try {
    const r = await api.get('/api/present');
    availableIds = new Set(r.present);
    const missing = r.configured.filter(i => !availableIds.has(i));
    clientMsg(missing.length
      ? `on bus: ${r.present.length}/${r.configured.length} — not found: `
        + `${missing.join(', ')} (grayed out)`
      : `all ${r.present.length} configured servos present`);
  } catch (e) { availableIds = null; clientMsg('presence check failed: ' + e.message); }
  renderGroup();
}

// One rule for every region chip ("all", "upper", "left", "upper:left", ...):
// a region that is already fully selected gets cleared, otherwise it gets
// selected whole. Servos missing from the bus (disabled) are never touched.
function selectRegion(spec) {
  if (spec === 'none') {                  // explicit deselect-all (the "all" chip only toggles)
    const boxes = [...document.querySelectorAll('.gsel:checked')];
    boxes.forEach(b => { b.checked = false; });
    applyHighlights();
    clientMsg(boxes.length ? `selection cleared (${boxes.length} servos)` : 'nothing was selected');
    return;
  }
  const parts = spec.split(':');
  const boxes = [...document.querySelectorAll('.gsel:not(:disabled)')]
    .filter(b => parts.every(p =>
      p === 'all' || p === SECTION(b.value) || p === SIDE(b.value)));
  if (!boxes.length) { clientMsg(`${spec}: no servos available`); return; }
  const on = boxes.every(b => b.checked);
  boxes.forEach(b => { b.checked = !on; });
  applyHighlights();
  clientMsg(`${spec.replace(':', ' ')} — `
    + (on ? 'cleared' : `${boxes.length} servo${boxes.length > 1 ? 's' : ''} selected`));
}
document.addEventListener('click', e => {
  const b = e.target.closest('button[data-sel]');
  if (b) selectRegion(b.dataset.sel);
});
$('groupCenter').onclick = guard(async () => {
  const js = selectedJoints();
  if (!js.length) { clientMsg('no servos selected'); return; }
  clientLog.length = 0;
  await api.post('/api/group/center', {
    joints: js,
    speed: Math.min(+$('speed').value, 500),
    acc: +$('acc').value,
    simulate: $('simulate').checked,
    hold_center: $('holdCenter').checked,
  });
});
// Torque targets, identical in both modes: checked servos in the list win;
// otherwise the joint clicked in the model; otherwise all configured servos.
const torqueTargets = () => {
  const js = selectedJoints();
  if (js.length) return js;
  if (currentJoint && servoIds[currentJoint.name] !== undefined)
    return [currentJoint.name];
  return [];                             // empty -> all configured
};
// One torque path for both modes — USB hits the local backend, wireless the
// Pi intent service (same zbot_core helper on either end).
const torqueCall = async (action) => {   // 'release' | 'lock'
  const js = torqueTargets();
  const body = { joints: js.length ? js : null };
  const r = wireless() ? await pi.post('/' + action, body)
                       : await api.post('/api/' + action, body);
  const ids = r.released ?? r.locked;
  clientMsg(`torque ${action === 'lock' ? 'locked at current position'
    : 'released'}: ${ids.length ? 'IDs ' + ids.join(', ') : 'nothing to do'}`);
};
$('groupRelease').onclick = guard(() => torqueCall('release'));
$('groupLock').onclick = guard(() => torqueCall('lock'));
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
    hold_center: $('holdCenter').checked,
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
  availableIds = new Set(r.found.map(f => f.id));   // refresh group availability
  renderGroup();
});
$('setId').onclick = guard(async () => {
  const oldId = +$('oldId').value, newId = +$('newId').value;
  const r = await api.post('/api/set_id', { old_id: oldId, new_id: newId });
  clientMsg(`ID ${oldId} -> ${newId} written (model ${r.model}, persistent)`);
  $('servoId').value = newId;
  // auto-select the body part that carries this ID, so you visually confirm
  // which servo you just configured (guards against re-flashing the wrong one)
  if (!selectJointForId(newId))
    clientMsg(`ID ${newId} is not in the joint table — select the part manually`);
  $('oldId').value = 1;                  // ready for the next factory servo
  $('newId').value = newId + 1;
});
// manual ID edits also move the 3D selection to the matching joint
$('servoId').addEventListener('change', () => selectJointForId(+$('servoId').value));
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
  const body = {
    joint: currentJoint.name,
    min_deg: +$('minDeg').value,
    max_deg: +$('maxDeg').value,
    symmetric: $('symmetric').checked,
  };
  // the repo copy is canonical in BOTH modes (git-tracked, deploys sync it)
  let r = await api.post('/api/limits', body);
  let where = 'the repo';
  if (wireless()) {
    // ...and the robot enforces its OWN copy, so the new range has to land
    // there too — otherwise it keeps clamping to the last deployed one
    try {
      r = await pi.post('/limits', body);
      where = 'the repo AND the robot';
    } catch (e) {
      where = 'the repo ONLY';
      clientMsg(`WARNING: limits saved to the repo but NOT to the robot `
        + `(${e.message}) — it still enforces its old range`);
    }
  }
  jointLimits = r.limits;
  renderGroup();
  clientMsg(`limits [${body.min_deg}, ${body.max_deg}]° saved to ${where} for `
    + `"${currentJoint.name}"`
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
$('modelZeroAll').onclick = guard(async () => {
  // fold EVERY joint's current pose angle into its display correction —
  // the visual pose stays identical, all sliders return to 0
  const offsets = {};
  let n = 0;
  for (const name of pivots.keys()) {
    const cur = jointAngles.get(name) ?? 0;
    if (cur) n++;
    offsets[name] = +(((modelZero[name] ?? 0) + cur).toFixed(1));
  }
  if (!n) { clientMsg('no joints posed — slide some joints first'); return; }
  const r = await api.post('/api/model_zero_bulk', { offsets });
  modelZero = r.offsets;
  for (const name of pivots.keys()) setJointAngle(name, 0);
  syncPoseUI(0);
  clientMsg(`model zero calibrated from posed model (${n} joints folded in)`);
});
$('centerPoseSet').onclick = guard(async () => {
  // the model's current pose (servo-space angles) becomes the center pose;
  // joints at 0 are simply left out of the override
  const angles = {};
  let n = 0;
  for (const name of Object.keys(servoIds)) {
    const cur = +((jointAngles.get(name) ?? 0).toFixed(1));
    angles[name] = Math.abs(cur) < 0.5 ? 0 : cur;   // idle-twin jitter (±0.1°) is not a pose
    if (angles[name]) n++;
  }
  if (!n) { clientMsg('model is at 0° everywhere — pose some joints first, or use reset center pose'); return; }
  const cur = Object.entries(centerPose);
  const summary = Object.entries(angles).filter(([, d]) => d).map(([j, d]) => `${j} ${d > 0 ? '+' : ''}${d}°`).join(', ');
  if (!confirm(`Set the center pose override to:\n${summary}\n\n`
      + (cur.length ? `This REPLACES the current override:\n${cur.map(([j, d]) => `${j} ${d > 0 ? '+' : ''}${d}°`).join(', ')}`
                    : 'Every ⌂ center action will move there from now on.'))) { clientMsg('center pose unchanged'); return; }
  const r = await api.post('/api/center_pose', { angles });
  centerPose = r.angles;
  renderCenterPose();
  clientMsg(`center pose override saved (${n} joints) — ⌂ center now moves there`
    + (wireless() ? '; deploy to apply on the Pi' : ''));
});
$('centerPoseReset').onclick = guard(async () => {
  const cur = Object.entries(centerPose);
  if (!cur.length) { clientMsg('no center pose override set — nothing to reset'); return; }
  if (!confirm(`Reset the center pose to the mount pose (all joints 0°)?\n\nThis DELETES the current override:\n`
      + cur.map(([j, d]) => `${j} ${d > 0 ? '+' : ''}${d}°`).join(', ')
      + '\n\nTip: note these values if you may want them back.')) { clientMsg('center pose unchanged'); return; }
  const r = await api.post('/api/center_pose', { angles: {} });
  centerPose = r.angles;
  renderCenterPose();
  clientMsg('center pose override cleared — ⌂ center = mount pose (all 0°)');
});
$('modelInvertBtn').onclick = guard(async () => {
  if (!currentJoint) return;
  const name = currentJoint.name;
  const r = await api.post('/api/model_invert',
    { joint: name, invert: !modelInvert[name] });
  modelInvert = r.invert;
  setJointAngle(name, jointAngles.get(name) ?? 0);   // re-render with new sign
  clientMsg(`model direction for ${name}: `
    + (modelInvert[name] ? 'INVERTED' : 'normal') + ' (display only)');
});
$('modelZeroBtn').onclick = guard(async () => {
  if (!currentJoint) return;
  const add = +$('poseSlider').value;      // fold slider into the correction
  const nz = +(((modelZero[currentJoint.name] ?? 0) + add).toFixed(1));
  const r = await api.post('/api/model_zero',
    { joint: currentJoint.name, deg: nz });
  modelZero = r.offsets;
  setJointAngle(currentJoint.name, 0);     // same visual, servo-space 0 again
  syncPoseUI(0);
  clientMsg(`model zero for ${currentJoint.name}: ${nz >= 0 ? '+' : ''}${nz}° `
    + `(display only)`);
});
$('center').onclick = guard(async () => {
  clientLog.length = 0;
  await api.post('/api/center', {
    servo_id: +$('servoId').value,
    speed: Math.min(+$('speed').value, 500),   // gentle move for assembly
    acc: +$('acc').value,
    simulate: $('simulate').checked,
    joint: currentJoint?.name ?? null,
    hold_center: $('holdCenter').checked,      // hold pose; ✋ release lets go
  });
});
$('saveOffset').onclick = guard(async () => {
  if (!currentJoint) return;
  const r = await api.post('/api/offsets', {
    joint: currentJoint.name,
    offset_deg: +$('offsetDeg').value,
  });
  jointOffsets = r.offsets;
  clientMsg(`mount offset saved: ${currentJoint.name} -> `
    + `${+$('offsetDeg').value >= 0 ? '+' : ''}${+$('offsetDeg').value}°`);
});
$('zeroHere').onclick = guard(async () => {
  if (!currentJoint) return;
  const r = await api.post('/api/zero', {
    servo_id: +$('servoId').value,
    joint: currentJoint.name,
  });
  jointOffsets = r.offsets;
  $('offsetDeg').value = r.offset;
  clientMsg(`zeroed "${currentJoint.name}" at current position (tick ${r.ticks})`
    + ` -> mount offset ${r.offset >= 0 ? '+' : ''}${r.offset}°`);
});
// ---------------------------------------------------------------- demos

let demos = [];        // saved demos from the repo (demos/*.json)
let editSteps = [];    // steps of the demo currently being edited

function renderDemoList() {
  const sel = $('demoList').value;
  $('demoList').innerHTML =
    '<option value="">— new demo —</option>'
    + demos.map(d =>
        `<option value="${d.name}">${d.name} (${d.steps.length} steps)</option>`
      ).join('');
  if (demos.some(d => d.name === sel)) $('demoList').value = sel;
}

const escAttr = v => String(v).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
const stepSummary = s => (s.title ? `${s.title}: ` : '') + stepPose(s);
// center step: flagged, or every angle exactly 0 (old "+ center" steps) — it
// follows the center pose override at playback (same rule as the engine)
const isCenterStep = s => !!s.center
  || (Object.keys(s.angles).length > 0 && Object.values(s.angles).every(d => d === 0));
const stepAngles = s => {                 // effective angles of a step for preview
  if (!isCenterStep(s)) return s.angles;
  const out = {};
  for (const j of Object.keys(s.angles)) out[j] = centerPose[j] ?? 0;
  return out;
};
const stepPose = s => {
  if (isCenterStep(s)) {
    const n = Object.keys(centerPose).filter(j => j in s.angles).length;
    return n ? `center pose (override on ${n} joint${n > 1 ? 's' : ''}, 0° elsewhere)` : 'center pose (all 0°)';
  }
  const nz = Object.entries(s.angles).filter(([, d]) => Math.abs(d) > 0.5);
  return nz.length
    ? `${nz.length}⌁ ` + nz.slice(0, 3).map(([j, d]) =>
        `${j.replace(/^(left|right)_/, m => m[0] === 'l' ? 'L·' : 'R·')} ${d > 0 ? '+' : ''}${d}°`
      ).join(', ') + (nz.length > 3 ? ', …' : '')
    : 'center pose (all 0°)';
};

// Numeric fields: an <input type=number> reports value === '' the moment the
// control considers the typed text invalid, and typing a comma as the decimal
// separator is the usual way in. Plain `+value` turns that into 0 — which is
// exactly why every typed pause silently became "no pause" while the
// integer-only speed/acc fields kept working. Parse leniently, take either
// separator, and never write 0 or NaN back into a step.
const parseNum = txt => {
  const v = parseFloat(String(txt).replace(',', '.'));
  return Number.isFinite(v) ? v : null;
};

// global speed/acc/pause row: shows the common value of all steps (empty =
// mixed); typing there stamps the value onto every step
function syncGlobalFields() {
  const live = document.activeElement;
  if (live === $('gSpeed') || live === $('gAcc') || live === $('gPause')) return;
  const one = pick => {
    const v = new Set(editSteps.map(pick));
    return v.size === 1 ? [...v][0] : '';
  };
  $('gSpeed').value = one(s => s.speed);
  $('gAcc').value = one(s => s.acc);
  $('gPause').value = one(s => s.pause_s);
}
// stamp one global field onto every step
const stampAll = (el, key, lo, hi) => el.addEventListener('input', () => {
  if (el.value.trim() === '') return;
  const v = parseNum(el.value);
  el.classList.toggle('bad', v === null);
  if (v === null) return;
  const c = Math.max(lo, Math.min(hi, v));
  editSteps.forEach(s => { s[key] = c; });
  renderDemoSteps();
});
stampAll($('gSpeed'), 'speed', 1, 3400);
stampAll($('gAcc'), 'acc', 0, 254);
stampAll($('gPause'), 'pause_s', 0, 10);

// --- waypoint preview: while a step is selected the model shows THAT pose and
// is deliberately detached from the live twin (live updates are suppressed);
// playing a demo / any run re-attaches automatically. previewI = step index.
let previewI = null;

function exitStepPreview(msg = true) {
  if (previewI === null) return;
  previewI = null;
  renderDemoSteps();
  if (lastRealPose)        // snap the rig back to the robot's last known pose
    for (const [j, d] of Object.entries(lastRealPose))
      if (pivots.has(j)) setJointAngle(j, d);
  if (msg) clientMsg('preview ended — model mirrors the robot again');
}

function applyStepPose(i) {
  for (const [j, d] of Object.entries(stepAngles(editSteps[i])))
    if (pivots.has(j)) setJointAngle(j, d);
  previewI = i;
  renderDemoSteps();
  clientMsg(`PREVIEW step #${i + 1} — model detached from live. Click joints `
    + '& use the pose slider to adjust, then "⟳ update"; "↩ live" returns');
}

function renderDemoSteps() {
  syncGlobalFields();
  if (previewI !== null && previewI >= editSteps.length) previewI = null;
  $('demoSteps').innerHTML = editSteps.map((s, i) => `
    <div class="step${i === previewI ? ' sel' : ''}" data-i="${i}" title="${escAttr(stepSummary(s))}">
      <span class="n drag" draggable="true" title="Drag to reorder (drop above or below another step)">⠿${i + 1}</span>
      <input type="number" data-k="speed" data-lo="1" data-hi="3400" value="${s.speed}" min="1" max="3400" title="Speed into this step [ticks/s] — 1…3400">
      <input type="number" data-k="acc" data-lo="0" data-hi="254" value="${s.acc}" min="0" max="254" title="Acceleration into this step — 0…254">
      <input type="text" inputmode="decimal" data-k="pause_s" data-lo="0" data-hi="10" value="${s.pause_s}" title="Pause AFTER this step [s] — 0…10; comma or dot both work">
      <input type="text" class="ttl" data-k="title" maxlength="60" value="${escAttr(s.title ?? '')}" placeholder="${escAttr(stepPose(s))}" title="Step title (optional, shown here and in the playback log)">
      <span class="acts">${i === previewI
        ? '<button data-a="upd" title="Replace this step\'s angles with the current model pose (only joints already in the step)">⟳ update</button>'
          + '<button data-a="pose" title="End the preview — the model follows the robot again">↩ live</button>'
        : '<button data-a="pose" title="Show this step\'s pose on the 3D model (detaches the model from the live robot while previewing)">▣ pose</button>'}
      <button data-a="robot" title="Overwrite this step's angles with the robot's CURRENT physical pose (release torque, hand-pose, then click) — title/speed/pause stay">⟲ robot</button>
      <button data-a="until" title="Play the SAVED demo from the start up to this step, then hold (save first if you edited)">▶ to here</button>
      <button data-a="up" title="Move this step one up"${i === 0 ? ' disabled' : ''}>▲</button>
      <button data-a="down" title="Move this step one down"${i === editSteps.length - 1 ? ' disabled' : ''}>▼</button>
      <button data-a="dup" title="Duplicate this step (copy inserted right after it)">⧉ dup</button>
      <button data-a="del" title="Remove this step">✕</button></span>
    </div>`).join('');
}
// Drag-and-drop reordering (HTML5 DnD; the "⠿n" handle is the drag source, the
// rows are drop targets — upper half = before, lower half = after). The
// previewed step is tracked by identity so its highlight moves with it.
let dragI = null;
const clearDropMarks = () => document.querySelectorAll('#demoSteps .step').forEach(r => r.classList.remove('drop-before', 'drop-after', 'dragging'));
$('demoSteps').addEventListener('dragstart', e => {
  const h = e.target.closest?.('.n.drag'); const row = h?.closest('.step');
  if (!h || !row) { e.preventDefault(); return; }
  dragI = +row.dataset.i; row.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
  try { e.dataTransfer.setData('text/plain', String(dragI)); } catch (_) {}
});
$('demoSteps').addEventListener('dragover', e => {
  const row = e.target.closest?.('.step');
  if (dragI === null || !row) return;
  e.preventDefault(); e.dataTransfer.dropEffect = 'move';
  const r = row.getBoundingClientRect(); const after = (e.clientY - r.top) > r.height / 2;
  document.querySelectorAll('#demoSteps .step').forEach(x => { if (x !== row) x.classList.remove('drop-before', 'drop-after'); });
  row.classList.toggle('drop-before', !after); row.classList.toggle('drop-after', after);
});
$('demoSteps').addEventListener('dragleave', e => {
  const row = e.target.closest?.('.step');
  if (row && !row.contains(e.relatedTarget)) row.classList.remove('drop-before', 'drop-after');
});
$('demoSteps').addEventListener('drop', e => {
  const row = e.target.closest?.('.step');
  if (dragI === null || !row) return;
  e.preventDefault();
  const r = row.getBoundingClientRect(); const after = (e.clientY - r.top) > r.height / 2;
  let to = +row.dataset.i + (after ? 1 : 0);
  const from = dragI; dragI = null; clearDropMarks();
  if (to > from) to--;                     // removing the source shifts later indices
  if (to === from) return;
  const previewObj = previewI !== null ? editSteps[previewI] : null;
  const [st] = editSteps.splice(from, 1);
  editSteps.splice(to, 0, st);
  if (previewObj) previewI = editSteps.indexOf(previewObj);
  renderDemoSteps();
  clientMsg(`step #${from + 1} moved -> #${to + 1}`);
});
$('demoSteps').addEventListener('dragend', () => { dragI = null; clearDropMarks(); });
$('demoSteps').addEventListener('input', e => {
  const row = e.target.closest('.step');
  if (!row || !e.target.dataset.k) return;
  if (e.target.dataset.k === 'title') {           // free text, no number parsing
    editSteps[+row.dataset.i].title = e.target.value;
    return;
  }
  const v = parseNum(e.target.value);
  e.target.classList.toggle('bad', v === null && e.target.value.trim() !== '');
  if (v === null) return;          // mid-edit or unparseable: keep the old value
  editSteps[+row.dataset.i][e.target.dataset.k] = v;
});
// clamp and normalise on blur, not while typing — otherwise "12" on the way to
// "120" gets fought by the lower bound
$('demoSteps').addEventListener('change', e => {
  const row = e.target.closest('.step');
  if (!row || !e.target.dataset.k) return;
  const step = editSteps[+row.dataset.i], k = e.target.dataset.k;
  if (k === 'title') {
    step.title = e.target.value.trim().slice(0, 60);
    e.target.value = step.title;
    row.title = stepSummary(step);
    return;
  }
  const v = parseNum(e.target.value);
  const out = Math.max(+e.target.dataset.lo,
                       Math.min(+e.target.dataset.hi, v === null ? +step[k] : v));
  step[k] = out;
  e.target.value = out;
  e.target.classList.remove('bad');
});
$('demoSteps').addEventListener('click', e => {
  const row = e.target.closest('.step');
  if (!row || !e.target.dataset.a) return;
  const i = +row.dataset.i;
  const a = e.target.dataset.a;
  if (a === 'del') {
    editSteps.splice(i, 1);
    if (previewI !== null) {
      if (i === previewI) previewI = null;
      else if (i < previewI) previewI--;
    }
    renderDemoSteps();
  } else if (a === 'until') {
    playDemo(i + 1).catch(err => clientMsg('ERROR: ' + err.message));
  } else if (a === 'robot') {
    overwriteStepFromRobot(i).catch(err => clientMsg('ERROR: ' + err.message));
  } else if (a === 'up' || a === 'down') {
    const j = a === 'up' ? i - 1 : i + 1;
    if (j < 0 || j >= editSteps.length) return;
    [editSteps[i], editSteps[j]] = [editSteps[j], editSteps[i]];
    if (previewI === i) previewI = j;           // the previewed step keeps its highlight
    else if (previewI === j) previewI = i;
    renderDemoSteps();
    clientMsg(`step #${i + 1} moved ${a} -> #${j + 1}`);
  } else if (a === 'dup') {
    const st = editSteps[i];
    editSteps.splice(i + 1, 0, { ...st, angles: { ...st.angles } });
    if (previewI !== null && previewI > i) previewI++;
    renderDemoSteps();
    clientMsg(`step #${i + 1} duplicated -> #${i + 2}` + (st.title ? ` (${st.title})` : ''));
  } else if (a === 'pose') {
    if (previewI === i) exitStepPreview();
    else applyStepPose(i);
  } else if (a === 'upd') {
    const st = editSteps[i];
    for (const j of Object.keys(st.angles))
      st.angles[j] = +((jointAngles.get(j) ?? 0).toFixed(1));
    delete st.center;                          // now a taught pose, no longer "center"
    renderDemoSteps();
    clientMsg(`step #${i + 1} updated from model pose — ${stepSummary(st)}`);
  }
});
$('demoList').addEventListener('change', () => {
  exitStepPreview(false);          // different demo -> stale preview index
  const val = $('demoList').value;
  if (!val) {                      // "— new demo —": fresh, empty editor
    editSteps = [];
    $('demoName').value = '';
    renderDemoSteps();
    clientMsg('new demo — pose and add steps, then name & save');
    return;
  }
  const d = demos.find(x => x.name === val);
  if (!d) return;
  $('demoName').value = d.name;
  editSteps = d.steps.map(s => ({ ...s, angles: { ...s.angles } }));
  renderDemoSteps();
});
$('demoAddStep').onclick = () => {
  // teach-in: freeze the current 3D pose (pose sliders / rig) as a step
  const angles = {};
  for (const j of Object.keys(servoIds))
    angles[j] = +((jointAngles.get(j) ?? 0).toFixed(1));
  editSteps.push({ angles, speed: +$('gSpeed').value || 300,
    acc: $('gAcc').value === '' ? 30 : +$('gAcc').value, pause_s: 0 });
  renderDemoSteps();
  clientMsg(`step #${editSteps.length} from model pose — ${stepSummary(editSteps.at(-1))}`);
};
// overwrite an existing step with the real robot's current pose (the same
// read as "+ robot pose"); the step keeps its title, speed, acc and pause
async function overwriteStepFromRobot(i) {
  const st = editSteps[i];
  if (!st) return;
  const r = wireless() ? await pi.get('/robot_pose')
                       : await api.get('/api/robot_pose');
  if (!r.pose) throw new Error(r.detail ?? 'no pose available');
  st.angles = { ...r.pose };
  delete st.center;                          // a measured pose, no longer "center"
  exitStepPreview(false);
  for (const [j, d] of Object.entries(r.pose))
    if (pivots.has(j)) setJointAngle(j, d);
  renderDemoSteps();
  clientMsg(`step #${i + 1} overwritten from ROBOT pose — ${stepSummary(st)}`
    + (r.missing?.length ? ` (missing: ${r.missing.join(', ')})` : ''));
}
$('demoAddRobot').onclick = guard(async () => {
  // physical teach-in: read the real robot's current pose (hand-posed,
  // torque released) and store it as a step; mirror it onto the 3D model.
  // In wireless mode the robot hangs off the Pi — ask the Pi service.
  const r = wireless() ? await pi.get('/robot_pose')
                       : await api.get('/api/robot_pose');
  if (!r.pose) throw new Error(r.detail ?? 'no pose available');
  editSteps.push({ angles: r.pose, speed: +$('gSpeed').value || 300,
    acc: $('gAcc').value === '' ? 30 : +$('gAcc').value, pause_s: 0 });
  exitStepPreview(false);      // mirroring the robot = the twin is back
  for (const [j, d] of Object.entries(r.pose))
    if (pivots.has(j)) setJointAngle(j, d);
  renderDemoSteps();
  clientMsg(`step #${editSteps.length} from ROBOT pose — `
    + stepSummary(editSteps.at(-1))
    + (r.missing.length ? ` (missing: ${r.missing.join(', ')})` : ''));
});
$('demoAddCenter').onclick = () => {
  // exact center step: the center pose override where one is set, 0° elsewhere
  const angles = {};
  for (const j of Object.keys(servoIds)) angles[j] = 0;     // resolved at playback (center: true)
  const nOv = Object.keys(centerPose).filter(j => j in angles).length;
  editSteps.push({ angles, center: true, title: 'center', speed: +$('gSpeed').value || 300,
    acc: $('gAcc').value === '' ? 30 : +$('gAcc').value, pause_s: 0 });
  renderDemoSteps();
  clientMsg(`step #${editSteps.length}: exact center — ` + (nOv
    ? `center pose override on ${nOv} joint${nOv > 1 ? 's' : ''}, 0.0° elsewhere`
    : 'all joints 0.0° (no center pose override set)'));
};
$('demoSave').onclick = guard(async () => {
  const name = $('demoName').value.trim();
  if (!name) { clientMsg('give the demo a name first'); return; }
  if (!editSteps.length) { clientMsg('no steps — pose the model and "+ add step"'); return; }
  // the repo copy is canonical in BOTH modes (git-tracked, deploys sync it)
  const r = await api.post('/api/demos', { name, steps: editSteps });
  if (wireless()) {
    // ...and the robot gets its own copy so ▶ play works without a deploy.
    // The picker keeps showing the ROBOT's list: on failure leave it alone —
    // swapping in the repo list would offer demos the Pi will 404 on.
    try {
      demos = (await pi.post('/demos', { name, steps: editSteps })).demos;
      clientMsg(`demo '${name}' saved to the repo AND the robot `
        + `(${editSteps.length} steps)`);
    } catch (e) {
      clientMsg(`WARNING: '${name}' saved to the repo but NOT to the robot `
        + `(${e.message}) — retry or deploy`);
    }
  } else {
    demos = r.demos;
    clientMsg(`demo '${name}' saved to the repo (${editSteps.length} steps)`);
  }
  renderDemoList();
  $('demoList').value = name;
});
$('demoDelete').onclick = guard(async () => {
  const name = $('demoList').value;
  if (!name) return;
  const r = await api.post('/api/demos/delete', { name });   // repo (canonical)
  if (wireless()) {
    // picker stays the robot's list; on failure keep it (see demoSave)
    try {
      demos = (await pi.post('/demos/delete', { name })).demos;
    } catch (e) {
      clientMsg(`WARNING: '${name}' deleted from the repo but NOT from the `
        + `robot (${e.message})`);
    }
  } else {
    demos = r.demos;
  }
  renderDemoList();
  editSteps = [];                 // clear the editor along with the demo
  $('demoName').value = '';
  renderDemoSteps();
  clientMsg(`demo '${name}' deleted`);
});
// play the SAVED demo selected in the list; until = 1-based last step (optional)
async function playDemo(until = null) {
  const name = $('demoList').value;
  if (!name) { clientMsg('no demo selected — save the demo first, then pick it in the list'); return; }
  const saved = demos.find(d => d.name === name);
  if (until !== null && saved && until > saved.steps.length) { clientMsg(`saved demo '${name}' has only ${saved.steps.length} steps — save first`); return; }
  if (saved && JSON.stringify(saved.steps) !== JSON.stringify(editSteps))
    clientMsg(`note: playing the SAVED '${name}' — the editor has unsaved changes`);
  clientLog.length = 0;
  if (wireless())
    await pi.post('/demo/' + encodeURIComponent(name), until ? { until } : {});
  else
    await api.post('/api/demo/play',
      { name, simulate: $('simulate').checked, until });
  if (until) clientMsg(`playing '${name}' up to step #${until}`);
}
$('demoPlay').onclick = guard(() => playDemo());

$('stop').onclick = guard(() => api.post('/api/stop'));
$('copyLog').onclick = guard(async () => {
  const txt = [...serverLog.map(l => l.msg), ...clientLog].join('\n');
  await navigator.clipboard.writeText(txt);
  clientMsg(`log copied to clipboard (${serverLog.length + clientLog.length} lines)`);
});

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

// re-check the backend version/connection every 10 s — a server restart with
// newer code clears the stale banner (and vice versa) without a page reload
setInterval(() => refreshStatus().catch(() => {}), 10000);

guard(async () => {
  await Promise.all([refreshPorts(), refreshStatus()]);
  mapping = await api.get('/api/mapping');
  await refreshLimits();
  jointOffsets = await api.get('/api/offsets');
  modelZero = await api.get('/api/model_zero');
  modelInvert = await api.get('/api/model_invert');
  servoIds = await api.get('/api/servo_ids');
  try { centerPose = await api.get('/api/center_pose'); } catch { centerPose = {}; }
  renderCenterPose();
  renderGroup();
  applyMode();                 // hide/show mode sections + load the demo list
  await refreshPresence();               // no-op if not connected
  const jr = await api.get('/api/joints');
  joints = jr.joints ?? [];
  fastened = jr.fastened ?? [];
  if (joints.length) clientMsg(`${joints.length} CAD joints loaded (pinned version)`);
  await loadModel();
})();
