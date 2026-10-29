const grid = document.getElementById("grid");
const colsSel = document.getElementById("cols");
const players = [];

function setCols(n) {
  grid.style.gridTemplateColumns = `repeat(${n}, 1fr)`;
}
colsSel.addEventListener("change", () => setCols(colsSel.value));
setCols(colsSel.value);

function attach(video, src, setStatus) {
  // ทำลายตัวเล่นเดิมถ้ามี
  if (video._hls) { video._hls.destroy(); video._hls = null; }

  if (video.canPlayType("application/vnd.apple.mpegurl")) {
    // Safari เล่น HLS ได้เอง
    video.src = src;
    video.play().catch(() => {});
    setStatus("live");
    return;
  }
  if (!window.Hls || !Hls.isSupported()) {
    setStatus("error", "เบราว์เซอร์ไม่รองรับ HLS");
    return;
  }
  const hls = new Hls({ liveSyncDuration: 2, liveMaxLatencyDuration: 6, lowLatencyMode: true });
  video._hls = hls;
  hls.loadSource(src);
  hls.attachMedia(video);
  hls.on(Hls.Events.MANIFEST_PARSED, () => {
    video.play().catch(() => {});
    setStatus("live");
  });
  hls.on(Hls.Events.ERROR, (_e, data) => {
    if (!data.fatal) return;
    if (data.type === Hls.ErrorTypes.NETWORK_ERROR) {
      setStatus("error", "เชื่อมต่อกล้องไม่ได้");
      hls.startLoad();
    } else if (data.type === Hls.ErrorTypes.MEDIA_ERROR) {
      hls.recoverMediaError();
    } else {
      setStatus("error", "สตรีมขัดข้อง");
    }
  });
}

function makeTile(cam) {
  const tile = document.createElement("div");
  tile.className = "tile";

  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;

  const label = document.createElement("div");
  label.className = "label";
  label.textContent = cam.name;

  const status = document.createElement("div");
  status.className = "status load";
  status.textContent = "กำลังโหลด…";

  const setStatus = (state, text) => {
    status.className = "status " + (state === "live" ? "live" : state === "error" ? "error" : "load");
    status.textContent = text || (state === "live" ? "● LIVE" : "กำลังโหลด…");
  };

  tile.append(video, label, status);
  if (cam.ptz) tile.appendChild(makePtzPad(cam.id));
  grid.appendChild(tile);

  const src = `/hls/${cam.id}/index.m3u8`;
  attach(video, src, setStatus);
  players.push({ video, src, setStatus });
}

const PTZ_SPEED = 0.6;

async function sendPtz(camId, body) {
  try {
    await fetch("/api/onvif/ptz", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: camId, ...body }),
    });
  } catch {}
}

function makePtzPad(camId) {
  const pad = document.createElement("div");
  pad.className = "ptz";
  // [ทิศ, ป้าย, {pan,tilt,zoom}]
  const btns = [
    ["up", "▲", { tilt: PTZ_SPEED }],
    ["down", "▼", { tilt: -PTZ_SPEED }],
    ["left", "◀", { pan: -PTZ_SPEED }],
    ["right", "▶", { pan: PTZ_SPEED }],
    ["in", "＋", { zoom: PTZ_SPEED }],
    ["out", "－", { zoom: -PTZ_SPEED }],
  ];
  for (const [dir, glyph, vel] of btns) {
    const b = document.createElement("button");
    b.className = "ptz-btn ptz-" + dir;
    b.textContent = glyph;
    const start = (e) => { e.preventDefault(); sendPtz(camId, vel); };
    const stop = (e) => { e.preventDefault(); sendPtz(camId, { stop: true }); };
    b.addEventListener("pointerdown", start);
    b.addEventListener("pointerup", stop);
    b.addEventListener("pointerleave", stop);
    b.addEventListener("pointercancel", stop);
    pad.appendChild(b);
  }
  return pad;
}

async function init() {
  grid.innerHTML = "";
  players.length = 0;
  try {
    const res = await fetch("/api/cameras");
    const cams = await res.json();
    if (!cams.length) { grid.innerHTML = "<p style='padding:24px'>ยังไม่มีกล้อง — ไปที่ <a href='/settings.html' style='color:#60a5fa'>⚙️ ตั้งค่ากล้อง</a> เพื่อเพิ่มกล้องตัวแรก</p>"; return; }
    cams.forEach(makeTile);
  } catch (e) {
    grid.innerHTML = "<p style='padding:20px'>โหลดรายชื่อกล้องไม่สำเร็จ</p>";
  }
}

document.getElementById("reload").addEventListener("click", () => {
  players.forEach((p) => attach(p.video, p.src + "?t=" + Date.now(), p.setStatus));
});

init();
