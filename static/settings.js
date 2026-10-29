const list = document.getElementById("list");
const tmpl = document.getElementById("row-tmpl");
let BRANDS = {};

function readRow(card) {
  const v = (sel) => card.querySelector(sel).value.trim();
  const st = card._onvif || {};
  return {
    id: card.dataset.id || "",
    name: v(".f-name"),
    brand: v(".f-brand"),
    ip: v(".f-ip"),
    port: parseInt(v(".f-port")) || 554,
    username: v(".f-username"),
    password: card.querySelector(".f-password").value,
    channel: parseInt(v(".f-channel")) || 1,
    stream: v(".f-stream"),
    transport: v(".f-transport"),
    transcode: v(".f-transcode"),
    path: v(".f-path"),
    onvif_port: parseInt(v(".f-onvif-port")) || 80,
    profile: st.token || "",
    rtsp: st.rtsp || "",
    ptz: !!st.ptz,
  };
}

function toggleBrandFields(card) {
  const brand = card.querySelector(".f-brand").value;
  card.querySelector(".f-path-wrap").style.display = brand === "custom" ? "" : "none";
  const onvif = brand === "onvif";
  card.querySelector(".f-onvif-wrap").style.display = onvif ? "" : "none";
  card.querySelector(".probe").style.display = onvif ? "" : "none";
  // โปรไฟล์จะโผล่หลังจาก probe สำเร็จเท่านั้น
  card.querySelector(".f-profile-wrap").style.display =
    onvif && card.querySelector(".f-profile").options.length ? "" : "none";
}

function applyProfile(card) {
  const sel = card.querySelector(".f-profile");
  const profiles = card._profiles || [];
  const p = profiles.find((x) => x.token === sel.value);
  if (!p) return;
  card._onvif = { token: p.token, rtsp: p.rtsp, ptz: p.ptz, snapshot: p.snapshot };
}

function setProfiles(card, profiles, info) {
  card._profiles = profiles;
  const sel = card.querySelector(".f-profile");
  sel.innerHTML = "";
  for (const p of profiles) {
    const o = document.createElement("option");
    o.value = p.token;
    o.textContent = `${p.name}${p.resolution ? " · " + p.resolution : ""}${p.ptz ? " · PTZ" : ""}`;
    sel.appendChild(o);
  }
  sel.value = profiles[0].token;
  applyProfile(card);
  toggleBrandFields(card);
  const out = card.querySelector(".test-result");
  const dev = [info.manufacturer, info.model].filter(Boolean).join(" ");
  out.textContent = "✓ ดึงสำเร็จ" + (dev ? " — " + dev : "");
  out.className = "test-result ok";
}

function addRow(data = {}) {
  const node = tmpl.content.cloneNode(true);
  const card = node.querySelector(".cam-card");
  card.dataset.id = data.id || "";
  card._onvif = data.rtsp ? { token: data.profile || "", rtsp: data.rtsp, ptz: !!data.ptz } : {};

  const brandSel = card.querySelector(".f-brand");
  for (const [key, b] of Object.entries(BRANDS)) {
    const o = document.createElement("option");
    o.value = key; o.textContent = b.label;
    brandSel.appendChild(o);
  }

  card.querySelector(".f-name").value = data.name || "";
  brandSel.value = data.brand || "hikvision";
  card.querySelector(".f-ip").value = data.ip || "";
  card.querySelector(".f-port").value = data.port || 554;
  card.querySelector(".f-username").value = data.username || "";
  card.querySelector(".f-password").value = data.password || "";
  card.querySelector(".f-channel").value = data.channel || 1;
  card.querySelector(".f-stream").value = data.stream || "main";
  card.querySelector(".f-transport").value = data.transport || "tcp";
  card.querySelector(".f-transcode").value = data.transcode ? "h264" : "";
  card.querySelector(".f-path").value = data.path || "";
  card.querySelector(".f-onvif-port").value = data.onvif_port || 80;

  // ถ้ามีโปรไฟล์ที่เคยบันทึกไว้ ให้แสดงตัวเลือกเดิม
  if (data.brand === "onvif" && data.rtsp) {
    setProfilesQuiet(card, [{
      token: data.profile || "default",
      name: "โปรไฟล์ที่บันทึกไว้",
      resolution: "", rtsp: data.rtsp, ptz: !!data.ptz, snapshot: "",
    }]);
  }

  brandSel.addEventListener("change", () => {
    toggleBrandFields(card);
    const dp = BRANDS[brandSel.value]?.default_port;
    if (dp) card.querySelector(".f-port").value = dp;
  });
  card.querySelector(".f-profile").addEventListener("change", () => applyProfile(card));
  toggleBrandFields(card);

  card.querySelector(".del").addEventListener("click", () => card.remove());
  card.querySelector(".probe").addEventListener("click", (e) => probeCard(card, e.target));
  card.querySelector(".test").addEventListener("click", (e) => testCard(card, e.target));

  list.appendChild(card);
  return card;
}

function setProfilesQuiet(card, profiles) {
  card._profiles = profiles;
  const sel = card.querySelector(".f-profile");
  sel.innerHTML = "";
  for (const p of profiles) {
    const o = document.createElement("option");
    o.value = p.token; o.textContent = p.name;
    sel.appendChild(o);
  }
  sel.value = profiles[0].token;
  applyProfile(card);
}

async function probeCard(card, btn) {
  const out = card.querySelector(".test-result");
  out.textContent = "⏳ กำลังดึงข้อมูลจากกล้อง…"; out.className = "test-result load";
  btn.disabled = true;
  try {
    const res = await fetch("/api/onvif/probe", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readRow(card)),
    });
    const j = await res.json();
    if (res.ok && j.profiles?.length) {
      setProfiles(card, j.profiles, j.info || {});
    } else {
      out.textContent = "✗ " + (j.detail || "ดึงข้อมูลไม่สำเร็จ");
      out.className = "test-result err";
    }
  } catch {
    out.textContent = "✗ เชื่อมต่อ ONVIF ไม่สำเร็จ"; out.className = "test-result err";
  } finally {
    btn.disabled = false;
  }
}

async function testCard(card, btn) {
  const out = card.querySelector(".test-result");
  out.textContent = "⏳ กำลังทดสอบ…"; out.className = "test-result load";
  btn.disabled = true;
  try {
    const res = await fetch("/api/test", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(readRow(card)),
    });
    const j = await res.json();
    out.textContent = (j.ok ? "✓ " : "✗ ") + (j.message || j.detail || "");
    out.className = "test-result " + (j.ok ? "ok" : "err");
  } catch {
    out.textContent = "✗ ทดสอบไม่สำเร็จ"; out.className = "test-result err";
  } finally {
    btn.disabled = false;
  }
}

// ---------- ค้นหากล้อง ONVIF ในวงแลน ----------
const discoverBtn = document.getElementById("discover");
const discoverPanel = document.getElementById("discover-panel");

discoverBtn.addEventListener("click", async () => {
  discoverPanel.style.display = "";
  discoverPanel.innerHTML = "<p class='hint'>⏳ กำลังสแกนหากล้อง ONVIF ในวงแลน…</p>";
  discoverBtn.disabled = true;
  try {
    const res = await fetch("/api/onvif/discover");
    const j = await res.json();
    if (!res.ok) {
      discoverPanel.innerHTML = "<p class='savemsg err'>✗ " + (j.detail || "ค้นหาไม่สำเร็จ") + "</p>";
      return;
    }
    const devices = j.devices || [];
    if (!devices.length) {
      discoverPanel.innerHTML = "<p class='hint'>ไม่พบกล้อง ONVIF (กล้องบางรุ่นต้องเปิด ONVIF/WS-Discovery ก่อน)</p>";
      return;
    }
    discoverPanel.innerHTML = "<p class='hint'>พบ " + devices.length + " กล้อง — กด “เพิ่ม” แล้วกรอกรหัสผ่าน จากนั้นกด “ดึงจาก ONVIF”</p>";
    for (const d of devices) {
      const row = document.createElement("div");
      row.className = "disc-row";
      row.innerHTML = `<span><b>${d.ip}</b>:${d.port}${d.name ? " — " + d.name : ""}</span>`;
      const add = document.createElement("button");
      add.textContent = "+ เพิ่ม";
      add.addEventListener("click", () => {
        const card = addRow({ brand: "onvif", ip: d.ip, onvif_port: d.port, name: d.name || "" });
        card.scrollIntoView({ behavior: "smooth", block: "center" });
      });
      row.appendChild(add);
      discoverPanel.appendChild(row);
    }
  } catch {
    discoverPanel.innerHTML = "<p class='savemsg err'>✗ ค้นหาไม่สำเร็จ</p>";
  } finally {
    discoverBtn.disabled = false;
  }
});

document.getElementById("add").addEventListener("click", () => addRow());

document.getElementById("save").addEventListener("click", async () => {
  const cams = [...list.querySelectorAll(".cam-card")].map(readRow);
  const msg = document.getElementById("savemsg");
  msg.textContent = "กำลังบันทึก…"; msg.className = "savemsg";
  try {
    const res = await fetch("/api/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cameras: cams }),
    });
    const j = await res.json();
    if (res.ok) {
      msg.textContent = "✓ บันทึกแล้ว — ใช้งานได้ทันที"; msg.className = "savemsg ok";
    } else {
      msg.textContent = "✗ " + (j.detail || "บันทึกไม่สำเร็จ"); msg.className = "savemsg err";
    }
  } catch {
    msg.textContent = "✗ บันทึกไม่สำเร็จ"; msg.className = "savemsg err";
  }
});

async function init() {
  BRANDS = await (await fetch("/api/brands")).json();
  const cfg = await (await fetch("/api/config")).json();
  if (cfg.cameras?.length) cfg.cameras.forEach(addRow);
  else addRow();
  // ซ่อนปุ่มค้นหาถ้า backend ไม่มี onvif-zeep
  try {
    const a = await (await fetch("/api/onvif/available")).json();
    if (!a.available) discoverBtn.style.display = "none";
  } catch {}
}
init();
