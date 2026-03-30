const API_BASE        = "http://localhost:8000";
const DEVICE_ID       = "ESP32_ENERGY_01";
const AUTO_REFRESH_MS = 5000;

let powerChart    = null;
let voltTempChart = null;
let currentHours  = 1;

const GRID_COLOR = () =>
  window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "rgba(255,255,255,0.07)"
    : "rgba(0,0,0,0.07)";

const TEXT_COLOR = () =>
  window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "#94a3b8"
    : "#64748b";

const BASE_OPTS = {
  responsive: true,
  maintainAspectRatio: true,
  interaction: { mode: "index", intersect: false },
  plugins: {
    legend: {
      labels: {
        color: TEXT_COLOR(),
        font: { family: "Space Mono", size: 10 },
        boxWidth: 12,
      },
    },
  },
  scales: {
    x: {
      type: "time",
      time: { tooltipFormat: "HH:mm:ss" },
      grid:  { color: GRID_COLOR() },
      ticks: { color: TEXT_COLOR(), font: { family: "Space Mono", size: 10 }, maxTicksLimit: 6 },
    },
  },
};

function makeYAxis(id, label, color, position = "left") {
  return {
    type: "linear",
    position,
    grid:  { color: id === "y" ? GRID_COLOR() : "transparent" },
    ticks: { color, font: { family: "Space Mono", size: 10 } },
    title: { display: true, text: label, color, font: { family: "Space Mono", size: 10 } },
  };
}

function initCharts() {
  const ctx1 = document.getElementById("powerChart").getContext("2d");
  powerChart = new Chart(ctx1, {
    type: "line",
    data: {
      datasets: [
        {
          label: "Power (W)", yAxisID: "y",
          borderColor: "#00d4aa", backgroundColor: "rgba(0,212,170,0.06)",
          borderWidth: 2, pointRadius: 0, tension: 0.3, data: [],
        },
        {
          label: "Current (A)", yAxisID: "y2",
          borderColor: "#0088ff", backgroundColor: "rgba(0,136,255,0.06)",
          borderWidth: 2, pointRadius: 0, tension: 0.3, data: [],
        },
      ],
    },
    options: {
      ...BASE_OPTS,
      scales: {
        ...BASE_OPTS.scales,
        y:  makeYAxis("y",  "Watts (W)",  "#00d4aa", "left"),
        y2: makeYAxis("y2", "Amps (A)",   "#0088ff", "right"),
      },
    },
  });

  const ctx2 = document.getElementById("voltTempChart").getContext("2d");
  voltTempChart = new Chart(ctx2, {
    type: "line",
    data: {
      datasets: [
        {
          label: "Voltage (V)", yAxisID: "y",
          borderColor: "#f59e0b", backgroundColor: "rgba(245,158,11,0.06)",
          borderWidth: 2, pointRadius: 0, tension: 0.3, data: [],
        },
        {
          label: "Temp (°C)", yAxisID: "y2",
          borderColor: "#ef4444", backgroundColor: "rgba(239,68,68,0.06)",
          borderWidth: 2, pointRadius: 0, tension: 0.3, data: [],
        },
      ],
    },
    options: {
      ...BASE_OPTS,
      scales: {
        ...BASE_OPTS.scales,
        y:  makeYAxis("y",  "Volts (V)", "#f59e0b", "left"),
        y2: makeYAxis("y2", "Temp (°C)", "#ef4444", "right"),
      },
    },
  });
}

async function apiFetch(path) {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function fetchRealtime() {
  const data = await apiFetch(`/api/realtime?device_id=${DEVICE_ID}`);
  updateMetrics(data);
  updateDeviceInfo(data);
  setOnline(true);
}

async function fetchHistory(hours = 1) {
  const data = await apiFetch(
    `/api/history?device_id=${DEVICE_ID}&hours=${hours}&limit=2000`
  );
  updateCharts(data.data || []);
}

async function fetchAlerts() {
  const data = await apiFetch(
    `/api/alerts?device_id=${DEVICE_ID}&limit=20&unacked_only=true`
  );
  updateAlerts(data.alerts || []);
}

async function fetchSummary() {
  const data = await apiFetch(
    `/api/history/summary?device_id=${DEVICE_ID}&hours=24`
  );
  updateSummary(data);
}

async function fetchAll() {
  try {
    await Promise.allSettled([
      fetchRealtime(),
      fetchHistory(currentHours),
      fetchAlerts(),
      fetchSummary(),
    ]);
    showToast("Data refreshed");
  } catch (e) {
    console.error("fetchAll error:", e);
    setOnline(false);
  }
}

function updateMetrics(data) {
  const faults = data.active_faults || [];

  setMetric("v",  data.voltage?.toFixed(1),
    faults.includes("OVERVOLTAGE") || faults.includes("UNDERVOLTAGE"));
  setMetric("i",  data.current?.toFixed(3),    faults.includes("OVERCURRENT"));
  setMetric("p",  data.power?.toFixed(1),      faults.includes("CURRENT_SPIKE"));
  setMetric("e",  data.energy_kwh?.toFixed(4));
  setMetric("pf", data.power_factor?.toFixed(3), faults.includes("LOW_POWER_FACTOR"));
  setMetric("f",  data.frequency?.toFixed(1) ?? "--");
  setMetric("t",  data.temperature?.toFixed(1),
    faults.includes("OVERHEATING") || faults.includes("THERMAL_TREND"));

  const card = document.getElementById("card-s");
  const val  = document.getElementById("val-s");
  const sub  = document.getElementById("sub-s");

  if (data.status === "FAULT") {
    card.className  = "metric-card fault";
    val.innerHTML   = "⚠ FAULT";
    val.style.color = "var(--danger)";
    sub.textContent = `${faults.length} fault(s) active`;
  } else {
    card.className  = "metric-card";
    val.innerHTML   = "✓ NORMAL";
    val.style.color = "var(--accent)";
    sub.textContent = "All systems nominal";
  }
}

function setMetric(id, value, fault = false) {
  const card = document.getElementById(`card-${id}`);
  const el   = document.getElementById(`val-${id}`);
  if (!el) return;
  const unit  = el.querySelector(".metric-unit")?.outerHTML || "";
  el.innerHTML = (value !== undefined && value !== null ? value : "--") + unit;
  if (card) card.className = "metric-card" + (fault ? " fault" : "");
}

function updateDeviceInfo(data) {
  const set = (id, val) => {
    const el = document.getElementById(id);
    if (el) el.textContent = val ?? "--";
  };
  set("devId",      DEVICE_ID);
  set("lastUpdate", new Date(data.ts).toLocaleTimeString());
  set("wifiRssi",   data.rssi ? `${data.rssi} dBm` : "--");
  set("uptime",     data.uptime_sec ? `${data.uptime_sec}s` : "--");
  set("faultCode",  data.fault_code ? `0x${data.fault_code.toString(16).padStart(2,"0").toUpperCase()}` : "0x00");
}

function updateCharts(records) {
  if (!records.length) return;

  powerChart.data.datasets[0].data = records.map(r => ({ x: new Date(r.ts), y: r.power }));
  powerChart.data.datasets[1].data = records.map(r => ({ x: new Date(r.ts), y: r.current }));
  powerChart.update("none");

  voltTempChart.data.datasets[0].data = records.map(r => ({ x: new Date(r.ts), y: r.voltage }));
  voltTempChart.data.datasets[1].data = records.map(r => ({ x: new Date(r.ts), y: r.temperature }));
  voltTempChart.update("none");
}

function updateAlerts(alerts) {
  const container = document.getElementById("alertsContainer");
  if (!alerts.length) {
    container.innerHTML = '<div class="no-alerts"><span>✅</span>No active alerts</div>';
    return;
  }
  const icons = { CRITICAL: "🔴", WARNING: "🟡", INFO: "🔵" };
  container.innerHTML = alerts
    .map(
      a => `
      <div class="alert-item ${a.severity.toLowerCase()}">
        <div class="alert-icon">${icons[a.severity] || "⚪"}</div>
        <div class="alert-body">
          <div class="alert-type ${a.severity.toLowerCase()}">${a.alert_type}</div>
          <div class="alert-msg">${a.message || ""}</div>
          <div class="alert-ts">${new Date(a.ts).toLocaleString()}</div>
        </div>
      </div>`
    )
    .join("");
}

function updateSummary(data) {
  const set = (id, val, unit = "") => {
    const el = document.getElementById(id);
    if (el) el.textContent = val !== null && val !== undefined ? `${val}${unit}` : "--";
  };
  set("sumAvgV",   data.avg_voltage,  " V");
  set("sumAvgP",   data.avg_power,    " W");
  set("sumMaxP",   data.max_power,    " W");
  set("sumEnergy", data.total_energy, " kWh");
  set("sumAvgPF",  data.avg_pf);
  set("sumFaults", data.fault_count);
}

function setOnline(online) {
  const dot  = document.getElementById("statusDot");
  const text = document.getElementById("statusText");
  if (dot)  dot.className    = "status-dot" + (online ? "" : " offline");
  if (text) text.textContent = online ? "Live" : "Offline";
}

function setRange(hours, btn) {
  currentHours = hours;
  document.querySelectorAll(".ctrl-btn").forEach(b => b.classList.remove("active"));
  btn.classList.add("active");
  fetchHistory(hours);
}

function showToast(msg) {
  const t = document.getElementById("toast");
  if (!t) return;
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2000);
}

window.addEventListener("DOMContentLoaded", async () => {
  initCharts();
  await fetchAll();
  const overlay = document.getElementById("loadingOverlay");
  if (overlay) overlay.style.display = "none";
  setInterval(fetchAll, AUTO_REFRESH_MS);
});
