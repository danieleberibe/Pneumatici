'use strict';
const $ = id => document.getElementById(id);
const side = new URLSearchParams(location.search).get('side');
const token = new URLSearchParams(location.hash.slice(1)).get('token');
let stream, track, running = false, count = 0, started = 0, wakeLock, runId = 0;
const session = crypto.randomUUID ? crypto.randomUUID() : String(Date.now());
$('phone-title').textContent = `Camera ${side === 'left' ? 'sinistra / L' : 'destra / R'}`;
function status(message) { $('phone-status').textContent = message; }
if (!['left', 'right'].includes(side) || !token) { status('Apri il link completo dal pannello Sorgenti del computer.'); $('start').disabled = true; }
else if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) { status('Serve una connessione HTTPS attendibile sul telefono. Consulta la guida del progetto.'); $('start').disabled = true; }

function capabilities() { return track?.getCapabilities ? track.getCapabilities() : {}; }
function setFocusUi() {
  const caps = capabilities(), settings = track.getSettings(), manual = caps.focusMode?.includes('manual');
  $('lock-focus').disabled = !manual;
  $('focus-slider-label').hidden = !manual || !caps.focusDistance;
  if (manual && caps.focusDistance) {
    const slider = $('focus-distance'); slider.min = caps.focusDistance.min; slider.max = caps.focusDistance.max;
    slider.step = caps.focusDistance.step || .01; slider.value = settings.focusDistance ?? caps.focusDistance.min;
  }
  status(manual ? 'Camera attiva. Lascia mettere a fuoco, poi premi “Blocca fuoco”.' : 'Camera attiva. Questo browser non espone il fuoco manuale: il 3D rimane bloccato finché non verifichi un blocco reale. Preferisci una sorgente IP con fuoco manuale.');
}
$('start').onclick = async () => {
  $('start').disabled = true;
  try {
    const [width, height] = $('resolution').value.split('x').map(Number), deviceId = $('device').value;
    const video = { width: { exact: width }, height: { exact: height }, frameRate: { ideal: 15, max: 20 }, ...(deviceId ? { deviceId: { exact: deviceId } } : { facingMode: { ideal: 'environment' } }) };
    stream = await navigator.mediaDevices.getUserMedia({ video, audio: false });
    track = stream.getVideoTracks()[0]; $('video').srcObject = stream; await $('video').play();
    const current = track.getSettings().deviceId, devices = await navigator.mediaDevices.enumerateDevices();
    $('device').replaceChildren(); devices.filter(d => d.kind === 'videoinput').forEach((device, i) => {
      const option = document.createElement('option'); option.value = device.deviceId; option.textContent = device.label || `Camera ${i+1}`; option.selected = device.deviceId === current; $('device').append(option);
    });
    $('device').disabled = true; $('resolution').disabled = true; $('stop').disabled = false;
    setFocusUi(); running = true; count = 0; started = performance.now(); const id = ++runId;
    track.addEventListener('ended', () => stop('Camera interrotta dal sistema. Riapri il collegamento.'));
    try { wakeLock = await navigator.wakeLock?.request('screen'); } catch { /* Optional; iOS support varies. */ }
    transmit(id);
  } catch (e) {
    stop(e.name === 'OverconstrainedError' ? 'Risoluzione non supportata. Scegli 640 × 480 su entrambi i telefoni.' : `Accesso camera fallito: ${e.message}`);
  }
};
function stop(message = 'Camera arrestata. Le misure scadranno automaticamente sul computer.') {
  running = false; runId++; stream?.getTracks().forEach(t => t.stop()); stream = null; track = null;
  wakeLock?.release(); $('start').disabled = false; $('stop').disabled = true; $('lock-focus').disabled = true;
  $('device').disabled = false; $('resolution').disabled = false; $('focus-slider-label').hidden = true; status(message);
}
$('stop').onclick = () => stop();
$('lock-focus').onclick = async () => {
  try {
    const settings = track.getSettings(), caps = capabilities();
    if (!caps.focusMode?.includes('manual')) throw new Error('Fuoco manuale non disponibile.');
    const constraints = { focusMode: 'manual' };
    if (settings.focusDistance != null) constraints.focusDistance = settings.focusDistance;
    await track.applyConstraints({ advanced: [constraints] });
    if (track.getSettings().focusMode !== 'manual') throw new Error('Il browser non conferma il blocco.');
    status('Fuoco manuale confermato dal browser. Controlla la nitidezza, poi calibra dal computer.');
  } catch (e) { status(`Blocco fuoco non riuscito: ${e.message}`); }
};
$('focus-distance').onchange = async event => {
  try { await track.applyConstraints({ advanced: [{ focusMode: 'manual', focusDistance: +event.target.value }] }); status('Fuoco modificato. Ripeti la calibrazione stereo.'); }
  catch (e) { status(e.message); }
};
async function transmit(id) {
  if (!running || id !== runId) return;
  try {
    const settings = track.getSettings(), canvas = $('capture'), video = $('video');
    if (!video.videoWidth || !video.videoHeight || video.readyState < 2) { setTimeout(() => transmit(id), 100); return; }
    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
    canvas.getContext('2d', { alpha: false }).drawImage(video, 0, 0);
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .82));
    if (id !== runId) return;
    if (!blob || !blob.size) { setTimeout(() => transmit(id), 100); return; }
    const optics = { session, orientation: screen.orientation?.angle ?? window.orientation ?? 0 };
    ['deviceId', 'focusMode', 'focusDistance', 'zoom', 'width', 'height'].forEach(k => { if (settings[k] != null) optics[k] = settings[k]; });
    const response = await fetch(`/api/frames/${side}`, { method: 'POST', body: blob, headers: { 'Content-Type': 'image/jpeg', 'X-Pair-Token': token, 'X-Camera-Optics': JSON.stringify(optics) }, signal: AbortSignal.timeout(6000) });
    if (!response.ok) { const data = await response.json(); throw new Error(`${data.detail || `Errore ${response.status}`} (frame ${canvas.width} × ${canvas.height})`); }
    count++; $('phone-stats').textContent = `${canvas.width} × ${canvas.height} · ${count} frame · ${(count/((performance.now()-started)/1000)).toFixed(1)} FPS · fuoco: ${settings.focusMode || 'non esposto'}`;
    setTimeout(() => transmit(id), 90); // One upload in flight, no accumulating queue.
  } catch (e) { if (id === runId) stop(`Trasmissione interrotta: ${e.message}`); }
}
window.addEventListener('pagehide', () => stop());
document.addEventListener('visibilitychange', () => { if (document.hidden && running) stop('Pagina in background: acquisizione interrotta. Torna qui e riavvia.'); });
