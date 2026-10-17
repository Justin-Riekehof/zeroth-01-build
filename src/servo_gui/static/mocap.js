// Camera motion capture -> teleoperation of the arms.
//
// The webcam of THIS computer is read in the browser, MediaPipe Pose finds the
// body (33 landmarks, runs locally on the GPU/CPU — no image leaves the
// machine), the skeleton is drawn over the video, and the world landmarks are
// posted to /teleop/pose. The backend (zbot_core.mocap) turns them into arm
// joint angles, clamps them to the joint limits and — only while the
// Teleoperation switch is on — drives the servos. With the switch off the
// angles merely animate the 3D model, so signs/ranges can be checked safely.

const VENDOR = './vendor/mediapipe';
const SEND_MS = 50;                       // <= 20 Hz of poses to the backend
const ARMS = ['left_shoulder_pitch', 'left_shoulder_yaw', 'left_elbow_yaw',
              'right_shoulder_pitch', 'right_shoulder_yaw', 'right_elbow_yaw'];
const SHORT = j => j.replace('left_', 'L ').replace('right_', 'R ')
  .replace('shoulder_', 'shoulder ').replace('elbow_yaw', 'elbow');

// MediaPipe Pose skeleton (index pairs) and the arm bones that drive the robot
const BONES = [[0,1],[1,2],[2,3],[3,7],[0,4],[4,5],[5,6],[6,8],[9,10],
  [11,12],[11,13],[13,15],[15,17],[15,19],[15,21],[17,19],
  [12,14],[14,16],[16,18],[16,20],[16,22],[18,20],
  [11,23],[12,24],[23,24],[23,25],[25,27],[27,29],[29,31],[27,31],
  [24,26],[26,28],[28,30],[30,32],[28,32]];
const ARM_BONES = new Set(['11-13', '13-15', '12-14', '14-16']);

export function initMocap(ctx) {
  const { $, api, pi, wireless, guard, clientMsg, setJointAngle, canPreview,
          getLimits, simulate } = ctx;
  const el = {
    cam: $('mocapCam'), sw: $('mocapTele'), video: $('mocapVideo'),
    canvas: $('mocapCanvas'), card: $('mocapCard'), badge: $('mocapBadge'),
    live: $('mocapLive'), status: $('mocapStatus'), rows: $('mocapRows'),
    mirror: $('mocapMirror'), flip: $('mocapFlip'), twist: $('mocapTwist'),
  };
  const g2 = el.canvas.getContext('2d');
  // teleop start/stop go to whoever owns the servo bus (Pi in wireless mode); the
  // pose solver is pure computation, so the PREVIEW always uses the local backend
  // (works with the Pi unreachable or still on an older version)
  const net = () => (wireless() ? pi : api);
  const path = p => (wireless() ? '/teleop/' : '/api/teleop/') + p;
  const solver = () => (teleOn ? { net: net(), path: path('pose') } : { net: api, path: '/api/teleop/pose' });

  let landmarker = null, stream = null, camOn = false, teleOn = false;
  let lastVideoT = -1, lastSend = 0, inflight = false, raf = 0;

  el.rows.innerHTML = ARMS.map(j => `<div class="mrow" data-j="${j}">
    <span class="k">${SHORT(j)}</span><span class="bar"><i></i></span><span class="v">–</span></div>`).join('');

  const say = t => { el.status.textContent = t; };

  async function loadModel() {
    if (landmarker) return;
    say('loading pose model …');
    const { FilesetResolver, PoseLandmarker } = await import(`${VENDOR}/vision_bundle.mjs`);
    const fileset = await FilesetResolver.forVisionTasks(`${VENDOR}/wasm`);
    const make = delegate => PoseLandmarker.createFromOptions(fileset, {
      baseOptions: { modelAssetPath: `${VENDOR}/pose_landmarker_full.task`, delegate },
      runningMode: 'VIDEO', numPoses: 1,
      minPoseDetectionConfidence: 0.5, minTrackingConfidence: 0.5,
    });
    try { landmarker = await make('GPU'); }
    catch { landmarker = await make('CPU'); clientMsg('mocap: GPU delegate unavailable, using CPU'); }
  }

  async function startCamera() {
    await loadModel();
    say('opening camera …');
    stream = await navigator.mediaDevices.getUserMedia(
      { video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }, audio: false });
    el.video.srcObject = stream;
    await el.video.play();
    el.canvas.width = el.video.videoWidth; el.canvas.height = el.video.videoHeight;
    camOn = true;
    el.card.classList.remove('hidden');
    el.cam.textContent = '■ Stop camera';
    el.sw.disabled = false;
    say('camera on — stand back so your arms and shoulders are in view');
    raf = requestAnimationFrame(frame);
  }

  async function stopCamera() {
    if (teleOn) await setTele(false);
    camOn = false;
    cancelAnimationFrame(raf);
    stream?.getTracks().forEach(t => t.stop());
    stream = null; el.video.srcObject = null;
    g2.clearRect(0, 0, el.canvas.width, el.canvas.height);
    el.card.classList.add('hidden');
    el.cam.textContent = '📷 Start camera';
    el.sw.disabled = true;
    say('camera off');
  }

  async function setTele(on) {
    if (on === teleOn) return;
    try {
      if (on) {
        const sim = !wireless() && simulate();
        await net().post(path('start'), { simulate: sim });
        clientMsg(`mocap teleoperation ON (${sim ? 'simulation' : 'robot'})`);
      } else {
        await net().post(path('stop'));
        clientMsg('mocap teleoperation OFF — arms hold their pose');
      }
      teleOn = on;
    } catch (e) {
      clientMsg('ERROR: ' + (wireless() && /not found/i.test(e.message)
        ? 'the Pi service is too old for teleoperation (needs API v10) — redeploy it: '
          + 'src/pi_service/deploy/deploy_pi.sh (or .ps1)'
        : e.message));
      teleOn = false;
    }
    el.sw.checked = teleOn;
    renderTeleState();
    say(teleOn ? 'LIVE — the arms follow you' : 'tracking — switch teleoperation on to move the robot');
  }

  function renderTeleState() {
    el.live.classList.toggle('hidden', !teleOn);
    el.card.classList.toggle('live', teleOn);
  }

  function draw(lm, tracked) {
    const W = el.canvas.width, H = el.canvas.height;
    g2.clearRect(0, 0, W, H);
    if (!lm) return;
    const accent = teleOn ? '#ff8c1a' : '#4cc3ff';
    g2.lineCap = 'round';
    for (const [a, b] of BONES) {
      const p = lm[a], q = lm[b];
      if (!p || !q) continue;
      const vis = Math.min(p.visibility ?? 1, q.visibility ?? 1);
      const arm = ARM_BONES.has(`${a}-${b}`);
      g2.globalAlpha = vis < 0.5 ? 0.25 : 1;
      g2.strokeStyle = arm ? accent : '#9fb0c8';
      g2.lineWidth = arm ? 5 : 2.5;
      g2.beginPath(); g2.moveTo(p.x * W, p.y * H); g2.lineTo(q.x * W, q.y * H); g2.stroke();
    }
    for (let i = 0; i < lm.length; i++) {
      const p = lm[i];
      g2.globalAlpha = (p.visibility ?? 1) < 0.5 ? 0.25 : 1;
      g2.fillStyle = [11, 12, 13, 14, 15, 16].includes(i) ? accent : '#e6edf7';
      g2.beginPath(); g2.arc(p.x * W, p.y * H, [11,12,13,14,15,16].includes(i) ? 5 : 3, 0, 7); g2.fill();
    }
    g2.globalAlpha = 1;
  }

  function renderAngles(res) {
    const lims = getLimits();
    const clamped = new Set(res?.clamped ?? []);
    for (const row of el.rows.children) {
      const j = row.dataset.j, v = res?.angles?.[j];
      const L = lims[j];
      row.querySelector('.v').textContent = v === undefined ? '–' : `${v >= 0 ? '+' : ''}${v.toFixed(0)}°`;
      row.classList.toggle('limit', clamped.has(j));
      const bar = row.querySelector('i');
      if (v === undefined || !L) { bar.style.width = '0'; continue; }
      const span = Math.max(1, L.max_deg - L.min_deg);
      bar.style.left = '0';
      bar.style.width = `${Math.max(0, Math.min(1, (v - L.min_deg) / span)) * 100}%`;
    }
    el.twist.textContent = res?.twist_deg != null ? `${res.twist_deg >= 0 ? '+' : ''}${res.twist_deg.toFixed(0)}°` : '–';
  }

  async function send(world) {
    inflight = true;
    try {
      const body = {
        landmarks: world.map(p => [p.x, p.y, p.z, p.visibility ?? 0]),
        mirror: el.mirror.checked, flip_forward: el.flip.checked,
      };
      const sv = solver();
      const res = await sv.net.post(sv.path, body, 1500);
      renderAngles(res);
      if (teleOn && !res.active) {            // ended on the robot: E-stop, timeout, ...
        teleOn = false; el.sw.checked = false; renderTeleState();
        clientMsg('mocap teleoperation ended on the robot');
      }
      if (!res.active && canPreview())        // switch off: animate the 3D model only
        for (const [j, d] of Object.entries(res.angles)) setJointAngle(j, d);
      say(res.tracked
        ? (teleOn ? 'LIVE — the arms follow you' : 'tracking — switch teleoperation on to move the robot')
        : 'no person — shoulders not visible');
    } catch (e) {
      console.error('mocap', e);
      say('backend: ' + e.message);
    } finally { inflight = false; }
  }

  function frame() {
    if (!camOn) return;
    raf = requestAnimationFrame(frame);
    const v = el.video;
    if (v.readyState < 2 || v.currentTime === lastVideoT) return;
    lastVideoT = v.currentTime;
    const now = performance.now();
    let res;
    try { res = landmarker.detectForVideo(v, now); } catch { return; }
    const lm = res.landmarks?.[0], world = res.worldLandmarks?.[0];
    draw(lm, !!lm);
    el.badge.textContent = lm ? 'TRACKING' : 'NO PERSON';
    el.badge.classList.toggle('lost', !lm);
    if (!lm) { renderAngles(null); if (!inflight) say('no person in view'); return; }
    if (world && !inflight && now - lastSend >= SEND_MS) { lastSend = now; send(world); }
  }

  el.cam.onclick = guard(async () => {
    el.cam.disabled = true;
    try { camOn ? await stopCamera() : await startCamera(); }
    catch (e) {
      camOn = false; say('camera: ' + (e.message || e.name));
      throw e;
    } finally { el.cam.disabled = false; }
  });
  el.sw.onchange = guard(() => setTele(el.sw.checked));
  el.sw.disabled = true;
  renderTeleState();
  // a stopped/aborted run elsewhere (E-stop button) is noticed on the next pose reply
  return { isTeleOn: () => teleOn };
}
