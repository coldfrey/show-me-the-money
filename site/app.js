/* Show Me The Money — reads the frozen §8 export contract:
   ./data/summary.json and ./data/daily/YYYY-MM-DD.json.
   ./data/dates.json is an optional dev helper listing available days;
   without it the app probes daily files around today. */

const MONTHS = ["January","February","March","April","May","June",
                "July","August","September","October","November","December"];

const fmtGBP = (v, dp = 0) =>
  "£" + Number(v).toLocaleString("en-GB", { minimumFractionDigits: dp, maximumFractionDigits: dp });
const fmtMWh = v =>
  Number(v).toLocaleString("en-GB", { maximumFractionDigits: 0 }) + " MWh";
const byId = id => document.getElementById(id);

async function fetchJSON(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  return r.json();
}

/* ---------- headline ---------- */
function runCounter(el, target, ms = 1600) {
  const t0 = performance.now();
  const ease = x => 1 - Math.pow(1 - x, 4);
  const step = now => {
    const p = Math.min(1, (now - t0) / ms);
    el.textContent = Math.round(target * ease(p)).toLocaleString("en-GB");
    if (p < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function renderHeadline(summary) {
  byId("headline-year").textContent = summary.year;
  runCounter(byId("ytd-counter"), summary.totals.total_cost_gbp);
  byId("ytd-curtailment").textContent = fmtGBP(summary.totals.curtailment_cost_gbp);
  byId("ytd-volume").textContent = fmtMWh(summary.totals.curtailment_volume_mwh) + " curtailed";
  byId("ytd-replacement").textContent = fmtGBP(summary.totals.replacement_cost_gbp);
  byId("limitations").textContent = summary.limitations;
  byId("methodology-version").textContent = summary.methodology_version;
  byId("generated-at").textContent =
    summary.generated_at === "dev-preview" ? "dev preview build" : "generated " + summary.generated_at;
}

/* ---------- monthly chart ---------- */
const tip = document.createElement("div");
tip.className = "chart-tip";
document.body.appendChild(tip);

function renderChart(summary) {
  const months = summary.months;
  const W = 960, H = 380, PAD = { l: 64, r: 10, t: 20, b: 40 };
  const innerW = W - PAD.l - PAD.r, innerH = H - PAD.t - PAD.b;
  const max = Math.max(...months.map(m => m.total_cost_gbp), 1);
  const slot = innerW / 12;
  const barW = Math.min(52, slot * 0.62);

  const y = v => PAD.t + innerH * (1 - v / max);
  let s = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg">`;

  const gridSteps = 4;
  for (let i = 1; i <= gridSteps; i++) {
    const v = (max / gridSteps) * i;
    s += `<line class="gridline" x1="${PAD.l}" x2="${W - PAD.r}" y1="${y(v)}" y2="${y(v)}"/>`;
    s += `<text x="${PAD.l - 8}" y="${y(v) + 3}" font-size="11" text-anchor="end">£${(v / 1e6).toFixed(0)}m</text>`;
  }

  const byMonth = Object.fromEntries(months.map(m => [m.month, m]));
  for (let mo = 1; mo <= 12; mo++) {
    const cx = PAD.l + slot * (mo - 0.5);
    const m = byMonth[mo];
    s += `<text x="${cx}" y="${H - PAD.b + 18}" font-size="11" text-anchor="middle">${MONTHS[mo - 1].slice(0, 3)}${m && m.partial ? "*" : ""}</text>`;
    if (!m || m.total_cost_gbp <= 0) continue;
    const hWind = innerH * (m.curtailment_cost_gbp / max);
    const hGas = innerH * (m.replacement_cost_gbp / max);
    const yGas = PAD.t + innerH - hGas;
    const yWind = yGas - hWind;
    const delay = (mo * 0.05).toFixed(2);
    const meta = `data-m="${mo}"`;
    s += `<rect class="bar-seg bar-gas" ${meta} x="${cx - barW / 2}" y="${yGas}" width="${barW}" height="${hGas}" style="animation-delay:${delay}s"/>`;
    s += `<rect class="bar-seg bar-wind" ${meta} x="${cx - barW / 2}" y="${yWind}" width="${barW}" height="${hWind}" style="animation-delay:${delay}s"/>`;
    if (m.total_cost_gbp / max > 0.04)
      s += `<text class="bar-label" x="${cx}" y="${yWind - 7}" font-size="11" text-anchor="middle">£${(m.total_cost_gbp / 1e6).toFixed(1)}m</text>`;
  }
  s += `<line class="baseline" x1="${PAD.l}" x2="${W - PAD.r}" y1="${PAD.t + innerH}" y2="${PAD.t + innerH}"/>`;
  s += `</svg>`;

  const el = byId("monthly-chart");
  el.innerHTML = s;
  el.querySelectorAll(".bar-seg").forEach(rect => {
    rect.addEventListener("mousemove", e => {
      const m = byMonth[+rect.dataset.m];
      tip.style.display = "block";
      tip.style.left = e.clientX + "px";
      tip.style.top = e.clientY + "px";
      tip.textContent =
        `${MONTHS[m.month - 1]}${m.partial ? " (partial)" : ""}\n` +
        `wind stop  ${fmtGBP(m.curtailment_cost_gbp)}\n` +
        `gas start  ${fmtGBP(m.replacement_cost_gbp)}\n` +
        `total      ${fmtGBP(m.total_cost_gbp)}`;
    });
    rect.addEventListener("mouseleave", () => (tip.style.display = "none"));
  });
}

/* ---------- daily ledger ---------- */
let availableDates = [];
let currentDate = null;

function rowHTML(cells) {
  return `<tr>${cells.join("")}</tr>`;
}

function renderDaily(day) {
  byId("daily-body").hidden = false;
  byId("daily-empty").hidden = true;
  byId("d-total").textContent = fmtGBP(day.total_cost_gbp);
  byId("d-curt").textContent = fmtGBP(day.curtailment.cost_gbp);
  byId("d-repl").textContent = fmtGBP(day.turnup.replacement_cost_gbp);
  byId("d-vol").textContent = fmtMWh(day.curtailment.volume_mwh);

  byId("tbl-bmus").innerHTML = day.curtailment.top_bmus.length
    ? day.curtailment.top_bmus.map(b => rowHTML([
        `<td>${b.station_name}<span class="sub">${b.bmu_id} · ${b.lead_party_name}</span></td>`,
        `<td class="num">${fmtGBP(b.cost_gbp)}</td>`,
        `<td class="num">${Math.round(b.volume_mwh).toLocaleString("en-GB")}</td>`,
      ])).join("")
    : `<tr><td colspan="3"><em>No SO-flagged wind curtailment recorded.</em></td></tr>`;

  byId("tbl-companies").innerHTML = day.turnup.top_companies.length
    ? day.turnup.top_companies.map(c => rowHTML([
        `<td>${c.parent_company}<span class="sub">${c.fuel_types.join(" · ")}</span></td>`,
        `<td class="num">${fmtGBP(c.cost_gbp)}</td>`,
        `<td class="num">${Math.round(c.volume_mwh).toLocaleString("en-GB")}</td>`,
      ])).join("")
    : `<tr><td colspan="3"><em>No SO-flagged turn-up recorded.</em></td></tr>`;
}

function showEmpty() {
  byId("daily-body").hidden = true;
  byId("daily-empty").hidden = false;
}

async function loadDate(date) {
  currentDate = date;
  byId("date-input").value = date;
  const i = availableDates.indexOf(date);
  byId("prev-day").disabled = i <= 0 && availableDates.length > 0;
  byId("next-day").disabled = i >= 0 && i === availableDates.length - 1;
  try {
    renderDaily(await fetchJSON(`data/daily/${date}.json`));
  } catch {
    showEmpty();
  }
}

function wireNav() {
  byId("prev-day").addEventListener("click", () => {
    const i = availableDates.indexOf(currentDate);
    if (i > 0) loadDate(availableDates[i - 1]);
  });
  byId("next-day").addEventListener("click", () => {
    const i = availableDates.indexOf(currentDate);
    if (i >= 0 && i < availableDates.length - 1) loadDate(availableDates[i + 1]);
  });
  byId("date-input").addEventListener("change", e => loadDate(e.target.value));
}

/* ---------- boot ---------- */
function setMastheadDate() {
  byId("masthead-date").textContent = new Date().toLocaleDateString("en-GB", {
    day: "numeric", month: "long", year: "numeric",
  });
  const now = new Date();
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1);
  setTimeout(setMastheadDate, midnight - now + 1000);
}

(async function boot() {
  setMastheadDate();
  wireNav();
  try {
    const summary = await fetchJSON("data/summary.json");
    renderHeadline(summary);
    renderChart(summary);
  } catch (e) {
    console.error("summary load failed", e);
  }
  try {
    availableDates = await fetchJSON("data/dates.json");
  } catch {
    availableDates = [];
  }
  if (availableDates.length) {
    const input = byId("date-input");
    input.min = availableDates[0];
    input.max = availableDates[availableDates.length - 1];
    loadDate(availableDates[availableDates.length - 1]);
  } else {
    // No manifest (production): default to two days ago, navigate freely.
    const d = new Date(Date.now() - 2 * 864e5).toISOString().slice(0, 10);
    loadDate(d);
  }
})();
