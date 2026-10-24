'use strict';
const $ = (id) => document.getElementById(id);
const names = { orange: 'Arancione', green: 'Verde', blue: 'Blu', red: 'Rosso', white: 'Bianco', black: 'Nero' };
const colors = { orange: '#efa25c', green: '#9acb76', blue: '#73a9d1', red: '#e28375', white: '#e3e9da', black: '#5e6b5c' };
let state = null, currentView = 'workspace', initialized = false, online = false, toastTimer, pairPaths = {};
let connection = {}, originEdited = false;
const previewUrls = {};
const busy = new Set();

function toast(message, error = false) {
  $('toast').textContent = message; $('toast').className = error ? 'error' : ''; $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('toast').hidden = true; }, error ? 9000 : 4000);
}
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers } });
  if (!response.ok) {
    let data; try { data = await response.json(); } catch { data = {}; }
    const detail = Array.isArray(data.detail) ? data.detail.map(x => x.msg).join(' · ') : data.detail;
    throw new Error(detail || `Richiesta non riuscita (${response.status})`);
  }
  return response.json();
}
async function action(button, operation) {
  if (busy.has(button)) return;
  busy.add(button); button.disabled = true;
  try { await operation(); await refresh(); } catch (e) { toast(e.message, true); }
  finally { busy.delete(button); button.disabled = false; }
}
function go(view) {
  currentView = view;
  document.querySelectorAll('.view').forEach(x => x.classList.toggle('active', x.id === `view-${view}`));
  document.querySelectorAll('.nav').forEach(x => x.classList.toggle('active', x.dataset.view === view));
  $('breadcrumb').textContent = { workspace: 'Workspace', sources: 'Sorgenti', calibration: 'Calibrazione', guide: 'Guida alla prova' }[view];
  if (view === 'sources') loadPairing();
  if (view === 'workspace') drawScene();
}
document.querySelectorAll('[data-view],[data-go]').forEach(button => button.addEventListener('click', event => {
  event.preventDefault(); go(button.dataset.view || button.dataset.go);
}));

function createSourceFields() {
  $('source-fields').innerHTML = ['left', 'right'].map((side, i) => `<section class="panel form-panel">
    <div class="source-heading"><b class="camera-letter">${i ? 'R' : 'L'}</b><div><h2>Camera ${i ? 'destra' : 'sinistra'}</h2><span class="help">${i ? 'Seconda vista stereo' : 'Origine del sistema di coordinate'}</span></div></div>
    <label>Tipo di sorgente<select id="${side}-kind"><option value="phone">Telefono · browser</option><option value="ip">Stream IP · MJPEG / RTSP</option><option value="usb">Camera USB</option></select></label>
    <label id="${side}-address-row" hidden>URL dello stream<input id="${side}-address" placeholder="http://192.168.1.20:8080/video" autocomplete="off"></label>
    <label id="${side}-device-row" hidden>Indice dispositivo USB<input id="${side}-device" type="number" min="0" max="20" value="${i}"></label>
    <div class="field-grid"><label>Larghezza richiesta<input id="${side}-width" type="number" min="320" max="1920" value="1280" required></label><label>Altezza richiesta<input id="${side}-height" type="number" min="240" max="1080" value="720" required></label></div>
    <p class="help">USB: dimensioni richieste al driver. Telefono: selezionare queste dimensioni anche nella pagina di acquisizione. IP: dipendono dall'app camera.</p>
    <label class="check"><input id="${side}-locked" type="checkbox"> Ho verificato il blocco di fuoco e zoom.</label><p class="help">Il controllo del driver può non essere supportato. Questa conferma richiede una verifica reale sulla camera.</p></section>`).join('');
  ['left', 'right'].forEach(side => $(`${side}-kind`).addEventListener('change', () => sourceVisibility(side)));
}
function sourceVisibility(side) {
  const kind = $(`${side}-kind`).value;
  $(`${side}-address-row`).hidden = kind !== 'ip'; $(`${side}-device-row`).hidden = kind !== 'usb';
}
createSourceFields();
$('rig-form').addEventListener('submit', event => {
  event.preventDefault(); action(event.submitter, async () => {
    const rig = { stationary_scene: $('stationary').checked };
    ['left', 'right'].forEach(side => { rig[side] = {
      kind: $(`${side}-kind`).value, address: $(`${side}-address`).value.trim(), device: +$(`${side}-device`).value,
      width: +$(`${side}-width`).value, height: +$(`${side}-height`).value, focus_locked: $(`${side}-locked`).checked,
    }; });
    await api('/api/rig', { method: 'PUT', body: JSON.stringify(rig) });
    await loadPairing(); toast('Sorgenti applicate. Apri i nuovi link sui telefoni.');
  });
});
async function loadPairing() {
  try {
    [pairPaths, connection] = await Promise.all([api('/api/pairing'), api('/api/connection')]);
    if (!originEdited && connection.public_origin) $('public-origin').value = connection.public_origin;
    renderPairing();
  } catch (e) { toast(e.message, true); }
}
function renderPairing() {
  let origin;
  try {
    const parsed = new URL($('public-origin').value);
    if (parsed.protocol !== 'https:' || ['localhost', '127.0.0.1', '[::1]', '0.0.0.0'].includes(parsed.hostname)) throw new Error();
    origin = parsed.origin;
  } catch { $('pair-links').textContent = 'Per i QR delle camere serve l’indirizzo HTTPS del PC sulla rete Wi-Fi, non 127.0.0.1.'; return; }
  $('pair-links').replaceChildren();
  ['left', 'right'].forEach(side => {
    if (!pairPaths[side]) return;
    const box = document.createElement('div'); box.className = 'pair-link';
    const title = document.createElement('strong'); title.textContent = side === 'left' ? 'L / Telefono sinistro' : 'R / Telefono destro';
    const qr = document.createElement('img'); qr.className = 'pair-qr'; qr.alt = `QR camera ${side === 'left' ? 'sinistra' : 'destra'}`;
    qr.src = `/api/pairing/qr/${side}.png?origin=${encodeURIComponent(origin)}&v=${Date.now()}`;
    qr.onerror = () => { qr.hidden = true; toast('QR non disponibile: verifica l’indirizzo HTTPS.', true); };
    const hint = document.createElement('p'); hint.className = 'help'; hint.textContent = 'Inquadra con il telefono, consenti la camera e premi Avvia fotocamera.';
    const code = document.createElement('code'); const url = origin + pairPaths[side]; code.textContent = url;
    const copy = document.createElement('button'); copy.type = 'button'; copy.className = 'text-button'; copy.textContent = 'Copia link ↗';
    copy.onclick = async () => { try { await navigator.clipboard.writeText(url); toast('Link copiato.'); } catch { toast('Copia il link mostrato nel riquadro.', true); } };
    box.append(title, qr, hint, code, copy); $('pair-links').append(box);
  });
  $('setup-qr-panel').hidden = !connection.setup_url;
  if (connection.setup_url) {
    $('setup-qr').src = `/api/pairing/qr/setup.png?v=${Date.now()}`;
    $('setup-link').href = connection.setup_url;
    $('setup-link').textContent = connection.setup_url;
  }
}
$('public-origin').value = location.origin;
$('public-origin').addEventListener('input', () => { originEdited = true; renderPairing(); });
$('demo-button').onclick = () => action($('demo-button'), async () => {
  await api('/api/demo', { method: 'POST', body: JSON.stringify({ enabled: state?.mode !== 'demo' }) });
});
$('pause-button').onclick = () => action($('pause-button'), async () => {
  await api('/api/pause', { method: 'POST', body: JSON.stringify({ enabled: !state?.paused }) });
});
$('settings-button').onclick = () => {
  if (!state) return;
  const config = state.detection;
  $('profile-checks').innerHTML = Object.entries(names).map(([key, name]) => `<label><input type="checkbox" name="profiles" value="${key}" ${config.profiles.includes(key) ? 'checked' : ''}>${name}</label>`).join('');
  Object.entries(config).forEach(([key, value]) => { const input = $('detection-form').elements.namedItem(key); if (key !== 'profiles' && input) input.value = value; });
  $('settings-dialog').showModal();
};
$('close-settings').onclick = () => $('settings-dialog').close();
$('detection-form').onsubmit = event => {
  event.preventDefault(); action(event.submitter, async () => {
    const form = new FormData(event.target), config = { profiles: form.getAll('profiles') };
    Object.keys(state.detection).filter(k => k !== 'profiles').forEach(k => { config[k] = +form.get(k); });
    await api('/api/detection', { method: 'PUT', body: JSON.stringify(config) });
    $('settings-dialog').close(); toast('Parametri di rilevamento aggiornati.');
  });
};
$('board-form').onsubmit = event => {
  event.preventDefault(); action(event.submitter, async () => {
    const config = { squares_x: +$('board-x').value, squares_y: +$('board-y').value, square_mm: +$('board-square').value, marker_mm: +$('board-marker').value };
    await api('/api/calibration/board', { method: 'PUT', body: JSON.stringify(config) }); toast('Tavola aggiornata. Nuova sessione pronta.');
  });
};
$('capture-button').onclick = () => action($('capture-button'), async () => {
  const result = await api('/api/calibration/capture', { method: 'POST' }); toast(`Coppia ${result.count} acquisita · ${result.common_corners} angoli comuni`);
});
$('solve-button').onclick = () => action($('solve-button'), async () => {
  toast('Calcolo intrinseci e stereo in corso…');
  const profile = await api('/api/calibration/solve', { method: 'POST' });
  toast(profile.accepted ? 'Calibrazione accettata. Ora verifica le distanze reali.' : 'Calibrazione da migliorare: consulta il report.', !profile.accepted);
});
$('export-button').onclick = () => action($('export-button'), async () => {
  const response = await fetch('/api/export.csv');
  if (!response.ok) { const body = await response.json(); throw new Error(body.detail); }
  const url = URL.createObjectURL(await response.blob()), a = document.createElement('a'); a.href = url; a.download = 'stereolab-measurements.csv'; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
});

function render() {
  const result = state.result, demo = state.mode === 'demo', points = result.points || [], paused = state.paused;
  $('demo-button').textContent = demo ? 'Esci dalla demo' : 'Avvia demo';
  $('pause-button').textContent = paused ? '▷ Riprendi' : 'Ⅱ Pausa';
  $('mode-title').textContent = demo ? 'Demo sintetica · nessuna misura reale' : paused ? 'Acquisizione in pausa' : points.length ? 'Misura stereo · scena statica' : 'Preparazione della misura';
  $('mode-description').textContent = demo ? 'Immagini generate e processate dalla pipeline OpenCV. Le coordinate non provengono dalle tue camere.' : 'Per misurare: fuoco fisso, rig stabile e calibrazione verificata. Coordinate nel riferimento della camera sinistra.';
  $('metric-count').textContent = points.length || (result.blockers?.length ? '—' : '0');
  $('metric-count-foot').textContent = demo ? 'Rilevamenti su immagini sintetiche' : points.length ? 'Corrispondenze stereo accettate' : 'Nessuna misura disponibile';
  $('metric-epi').textContent = points.length ? (points.reduce((sum, p) => sum + p.epipolar_px, 0) / points.length).toFixed(2) : '—';
  $('metric-sigma').textContent = points.length ? Math.max(...points.map(p => p.sigma_z_mm)).toFixed(1) : '—';
  $('metric-skew').textContent = result.pair_skew_ms != null ? result.pair_skew_ms.toFixed(1) : '—';
  $('metric-skew-foot').textContent = demo ? 'Coppia sintetica simultanea' : 'Non misura la sincronia degli scatti';
  $('view-kind').textContent = result.rectified ? 'Viste rettificate · guide epipolari' : 'Immagini originali';
  $('object-count').textContent = points.length;
  $('objects-empty').hidden = points.length > 0;
  $('objects').innerHTML = points.map(p => `<tr><td><span class="object-dot" style="background:${colors[p.profile]}"></span>${p.id}<span class="object-profile">${names[p.profile]}</span></td><td>${p.x_m.toFixed(3)}</td><td>${p.y_m.toFixed(3)}</td><td>${p.z_m.toFixed(3)}</td><td>± ${p.sigma_z_mm.toFixed(1)}</td></tr>`).join('');
  $('scene-status').textContent = paused ? 'Pausa · misure sospese' : demo ? 'SCENA SINTETICA' : `${points.length} coordinate valide`;
  $('pipeline-time').textContent = result.processing_ms != null && !paused ? `${result.processing_ms.toFixed(0)} ms / coppia` : 'in attesa';
  $('blockers').replaceChildren();
  [...(result.blockers || []), ...(state.load_error ? [state.load_error] : [])].forEach(message => { const el = document.createElement('div'); el.textContent = message; $('blockers').append(el); });
  if (result.rejected?.ambiguous) { const el = document.createElement('div'); el.textContent = `${result.rejected.ambiguous} associazioni ambigue scartate. Separa le palline lungo l'asse verticale.`; $('blockers').append(el); }
  ['left', 'right'].forEach(side => {
    const cam = state.cameras[side], connected = demo || cam.connected;
    $(`${side}-badge`).textContent = paused ? 'PAUSA' : demo ? 'SINTETICA' : connected ? 'CONNESSA' : 'OFFLINE';
    $(`${side}-badge`).classList.toggle('on', connected && !paused);
    $(`${side}-size`).textContent = demo ? '960 × 540' : cam.size ? cam.size.join(' × ') : '— × —';
    $(`${side}-fps`).textContent = demo ? 'SIMULAZIONE' : `${cam.fps.toFixed(1)} FPS`;
    $(`${side}-focus`).textContent = demo ? '◎ Ottica ideale' : cam.focus_locked ? '◎ Fuoco verificato' : '○ Fuoco da verificare';
    $(`${side}-live`).hidden = !connected || paused; $(`${side}-live`).textContent = demo ? '● DEMO' : '● LIVE';
    if (!connected) { $(`${side}-image`).hidden = true; $(`${side}-empty`).hidden = false; }
  });
  $('sample-count').textContent = state.samples; $('sample-progress').value = state.samples;
  $('sample-state').textContent = state.solving ? 'Calcolo in corso…' : state.samples < 15 ? 'Minimo 15' : 'Pronta per il calcolo';
  if (!busy.has($('solve-button'))) $('solve-button').disabled = state.solving || state.samples < 15 || demo;
  if (!busy.has($('capture-button'))) $('capture-button').disabled = state.solving || demo || paused;
  renderCalibration(); drawScene();
}
function renderCalibration() {
  const profile = state.calibration; if (!profile) return;
  const rows = [['RMS stereo', profile.rms_stereo, 'px'], ['RMS camera L', profile.rms_left, 'px'], ['RMS camera R', profile.rms_right, 'px'], ['Errore epipolare · verifica', profile.epipolar_rms, 'px'], ['Riproiezione · verifica', profile.validation_rms, 'px'], ['Baseline stimata', profile.baseline_mm, 'mm']];
  $('calibration-report').innerHTML = `<div class="report-status ${profile.accepted ? '' : 'bad'}">${profile.accepted ? '✓ Controlli geometrici superati' : '○ Calibrazione da migliorare'}</div>` + rows.map(([label, value, unit]) => `<div class="report-row"><span>${label}</span><strong>${value.toFixed(3)} ${unit}</strong></div>`).join('') + `<div class="report-row"><span>Pose / verifica</span><strong>${profile.samples} / ${profile.validation_samples}</strong></div>`;
  profile.warnings.forEach(message => { const div = document.createElement('div'); div.className = 'report-warning'; div.textContent = message; $('calibration-report').append(div); });
}
async function refresh() {
  try {
    state = await api('/api/state'); online = true;
    $('server-dot').className = 'dot mint'; $('server-label').textContent = 'Backend connesso';
    if (!initialized) {
      ['left', 'right'].forEach(side => { const c = state.rig[side]; ['kind', 'address', 'device', 'width', 'height'].forEach(k => { $(`${side}-${k}`).value = c[k]; }); $(`${side}-locked`).checked = c.focus_locked; sourceVisibility(side); });
      $('stationary').checked = state.rig.stationary_scene;
      [['board-x','squares_x'],['board-y','squares_y'],['board-square','square_mm'],['board-marker','marker_mm']].forEach(([id,key]) => { $(id).value = state.board[key]; });
      initialized = true;
    }
    render();
  } catch {
    online = false; $('server-dot').className = 'dot bad'; $('server-label').textContent = 'Backend non raggiungibile';
    if (state) { state.result = { points: [], blockers: ['Connessione persa: misure non disponibili.'] }; render(); }
  }
}
async function updatePreview(side) {
  if (!online || state?.paused || !['workspace', 'calibration'].includes(currentView)) return;
  try {
    const response = await fetch(`/api/preview/${side}.jpg`);
    if (response.status === 204) return;
    if (!response.ok) return;
    const blob = await response.blob(); if (blob.type !== 'image/jpeg') return;
    const url = URL.createObjectURL(blob), previous = previewUrls[side]; previewUrls[side] = url;
    const image = $(`${side}-image`); image.src = url; image.hidden = false; $(`${side}-empty`).hidden = true;
    $(`cal-${side}`).src = url; if (previous) URL.revokeObjectURL(previous);
  } catch { /* Status polling reports connectivity once, without repeated toasts. */ }
}
async function poll() { await refresh(); setTimeout(poll, 700); }
async function previews() { await Promise.all(['left', 'right'].map(updatePreview)); setTimeout(previews, 200); }

// Small perspective renderer: no CDN or graphics dependency, values are always server measurements.
const canvas = $('scene'), ctx = canvas.getContext('2d');
let yaw = -.38, elevation = -.45, zoom = 1, dragging = false, lastPointer;
function drawScene() {
  const bounds = canvas.getBoundingClientRect(); if (!bounds.width) return;
  const dpr = window.devicePixelRatio || 1, w = bounds.width, h = bounds.height;
  if (canvas.width !== Math.round(w*dpr) || canvas.height !== Math.round(h*dpr)) { canvas.width = Math.round(w*dpr); canvas.height = Math.round(h*dpr); }
  ctx.setTransform(dpr,0,0,dpr,0,0); ctx.clearRect(0,0,w,h);
  const project = (x,y,z) => {
    const a = x*Math.cos(yaw)+(z-1.5)*Math.sin(yaw), b = -x*Math.sin(yaw)+(z-1.5)*Math.cos(yaw);
    const c = y*Math.cos(elevation)-b*Math.sin(elevation), depth = y*Math.sin(elevation)+b*Math.cos(elevation);
    const scale = Math.min(w*.22,h*.43)*zoom*4/(4+depth);
    return [w*.5+a*scale,h*.53+c*scale,scale];
  };
  function line(a,b,color,width=1) { const p=project(...a),q=project(...b);ctx.beginPath();ctx.moveTo(p[0],p[1]);ctx.lineTo(q[0],q[1]);ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke(); }
  for(let x=-1.5;x<=1.5;x+=.25)line([x,.45,0],[x,.45,3.5],'#38504466');
  for(let z=0;z<=3.5;z+=.25)line([-1.5,.45,z],[1.5,.45,z],'#38504466');
  line([0,0,0],[.5,0,0],'#d39e83',1.5);line([0,0,0],[0,.5,0],'#b5cc74',1.5);line([0,0,0],[0,0,.6],'#7ba9c6',1.5);
  ctx.font='8px Consolas, monospace';ctx.fillStyle='#8fa187';
  for(let z=1;z<=3;z++){const p=project(-1.55,.45,z);ctx.fillText(`${z}.0 m`,p[0]-15,p[1]);}
  const origin=project(0,0,0);ctx.fillStyle='#c6dfb4';ctx.fillRect(origin[0]-3,origin[1]-3,6,6);ctx.fillText('L',origin[0]-14,origin[1]+2);
  for(const point of state?.result?.points||[]){
    const {x_m:x,y_m:y,z_m:z}=point,p=project(x,y,z),ground=project(x,.45,z);
    ctx.setLineDash([3,4]);ctx.strokeStyle='#91b27588';ctx.beginPath();ctx.moveTo(...p.slice(0,2));ctx.lineTo(...ground.slice(0,2));ctx.stroke();ctx.setLineDash([]);
    const radius=Math.max(4,Math.min(10,p[2]*.045)),color=colors[point.profile];ctx.shadowBlur=14;ctx.shadowColor=color;ctx.fillStyle=color;ctx.beginPath();ctx.arc(p[0],p[1],radius,0,Math.PI*2);ctx.fill();ctx.shadowBlur=0;
    ctx.strokeStyle=color;ctx.globalAlpha=.25;ctx.beginPath();ctx.ellipse(ground[0],ground[1],10,3,0,0,Math.PI*2);ctx.stroke();ctx.globalAlpha=1;
    ctx.fillStyle='#d9e8ce';ctx.font='9px Consolas,monospace';ctx.fillText(point.id,p[0]+radius+6,p[1]-3);ctx.fillStyle='#809778';ctx.font='7px Consolas,monospace';ctx.fillText(`${z.toFixed(2)} m`,p[0]+radius+6,p[1]+9);
  }
}
canvas.addEventListener('pointerdown',e=>{dragging=true;lastPointer=[e.clientX,e.clientY];canvas.setPointerCapture(e.pointerId);});
canvas.addEventListener('pointermove',e=>{if(!dragging)return;yaw+=(e.clientX-lastPointer[0])*.007;elevation=Math.max(-1.2,Math.min(.3,elevation+(e.clientY-lastPointer[1])*.006));lastPointer=[e.clientX,e.clientY];drawScene();});
canvas.addEventListener('pointerup',()=>{dragging=false;});canvas.addEventListener('pointercancel',()=>{dragging=false;});
canvas.addEventListener('wheel',e=>{e.preventDefault();zoom=Math.max(.5,Math.min(2.5,zoom-e.deltaY*.001));drawScene();},{passive:false});
$('reset-view').onclick=()=>{yaw=-.38;elevation=-.45;zoom=1;drawScene();};
new ResizeObserver(drawScene).observe(canvas);
poll(); previews();
if (location.hash === '#sources') go('sources');
