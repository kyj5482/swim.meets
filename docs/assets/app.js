"use strict";
/* FinSight — 관심 선수 대회 추적 & 기록 분석 (vanilla JS SPA) */

// ---------- i18n ----------
const I18N = {
  ko: {
    nav_meets: "대회", nav_swimmers: "선수",
    loading: "불러오는 중…", back_meets: "← 대회", back_swimmers: "← 선수",
    print: "🖨 인쇄", show_standards: "기준기록(JAG) 배지 표시",
    col_event: "이벤트", col_session: "라운드", col_heatlane: "조·레인", col_seed: "시드", col_when: "일정",
    swimmers_n: (n) => `선수 ${n}명`, entries_n: (n) => `엔트리 ${n}건`,
    events_n: (n) => `${n}종목`, meets_n: (n) => `대회 ${n}`,
    eventcnt: (n) => `이벤트 ${n}`, timeline_chip: "⏱ 타임라인",
    updated: "갱신", meet_count: (n) => `대회 ${n}개`,
    flight: (f) => `${f}조`,
    no_meets: "아직 처리된 대회가 없습니다.",
    no_meets_help: "input/<대회명>/ 에 Psych Sheet와 Timeline PDF를 올리세요.",
    no_matched: "이 대회에서 매칭된 관심 선수가 없습니다.",
    no_swimmers: "등록된 관심 선수가 없습니다.",
    no_record: "기록 없음",
    stat_meets: "대회", stat_events: "종목", stat_improved: "향상",
    best: "최고기록", improved_by: (s) => `−${s}s 단축`, no_improve: "기록 유지",
    one_meet: "대회 1회",
    h_meet: "대회", h_date: "일자", h_time: "기록", h_dprev: "직전대비",
    tag_pb: "PB", tag_tie: "동일",
    tie_help: "동일 기록 — 최고기록 미경신",
    legend_pb: "PB = 직전 최고기록을 실제로 경신",
    legend_tie: "동일 = 같은 기록(초) — 최고기록을 깨지 못함",
    improving: "향상 중인 종목", other_events: "그 외 종목",
    print_title: "관심 선수 출전 일정",
    sub_brand: "관심 선수 대회 추적",
  },
  en: {
    nav_meets: "Meets", nav_swimmers: "Swimmers",
    loading: "Loading…", back_meets: "← Meets", back_swimmers: "← Swimmers",
    print: "🖨 Print", show_standards: "Show standard (JAG) badges",
    col_event: "Event", col_session: "Round", col_heatlane: "Heat·Lane", col_seed: "Seed", col_when: "When",
    swimmers_n: (n) => `${n} swimmer${n === 1 ? "" : "s"}`, entries_n: (n) => `${n} entr${n === 1 ? "y" : "ies"}`,
    events_n: (n) => `${n} event${n === 1 ? "" : "s"}`, meets_n: (n) => `${n} meet${n === 1 ? "" : "s"}`,
    eventcnt: (n) => `${n} events`, timeline_chip: "⏱ timeline",
    updated: "Updated", meet_count: (n) => `${n} meet${n === 1 ? "" : "s"}`,
    flight: (f) => `Heat grp ${f}`,
    no_meets: "No meets processed yet.",
    no_meets_help: "Upload a Psych Sheet & Timeline PDF into input/<MeetName>/.",
    no_matched: "No registered swimmers matched in this meet.",
    no_swimmers: "No registered swimmers.",
    no_record: "No record",
    stat_meets: "meets", stat_events: "events", stat_improved: "improved",
    best: "Best time", improved_by: (s) => `−${s}s faster`, no_improve: "No drop yet",
    one_meet: "1 meet",
    h_meet: "Meet", h_date: "Date", h_time: "Time", h_dprev: "vs prev",
    tag_pb: "PB", tag_tie: "TIE",
    tie_help: "Same time — best not beaten",
    legend_pb: "PB = an actual new personal best",
    legend_tie: "TIE = identical time (s) — best not improved",
    improving: "Improving events", other_events: "Other events",
    print_title: "Registered Swimmers — Meet Schedule",
    sub_brand: "Track your swimmers, meet by meet",
  },
};
const STROKE = {
  ko: { Freestyle: "자유형", Backstroke: "배영", Breaststroke: "평영", Butterfly: "접영",
        IM: "개인혼영", "Individual Medley": "개인혼영", "Medley Relay": "혼계영",
        "Free Relay": "계영", "Freestyle Relay": "계영" }, en: {} };
const ROUND = { ko: { Prelims: "예선", Finals: "결승", "Timed Finals": "타임결승", Semifinals: "준결승" }, en: {} };
const COURSE = { ko: { "LC Meter": "장수로", "SC Meter": "단수로(25m)", SCY: "단수로(yd)" }, en: {} };

let LANG = localStorage.getItem("lang") || (((navigator.language || "").startsWith("ko")) ? "ko" : "en");
if (!["ko", "en"].includes(LANG)) LANG = "ko";
let SHOW_STD = localStorage.getItem("showStandards") !== "0";

const t = (k, ...a) => { const v = I18N[LANG][k]; return typeof v === "function" ? v(...a) : (v ?? k); };
const tr = (m, v) => (v && (m[LANG][v] || m.en[v])) || v || "";
const trStroke = (s) => tr(STROKE, s), trRound = (r) => tr(ROUND, r), trCourse = (c) => tr(COURSE, c);

// ---------- utils ----------
const $ = (s, e = document) => e.querySelector(s);
const main = $("#main");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const initials = (s) => (s || "").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();

async function getJSON(path) {
  const r = await fetch(`${path}?t=${Date.now()}`, { cache: "no-store" });
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
}
function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00"); if (isNaN(d)) return iso;
  const loc = LANG === "ko" ? "ko-KR" : "en-US";
  return `${d.getMonth() + 1}/${d.getDate()} (${d.toLocaleDateString(loc, { weekday: "short" })})`;
}
function fmtDelta(d) {
  if (d === null || d === undefined) return "";
  if (Math.abs(d) < 0.005) return `<span class="muted">0.00s</span>`;
  const cls = d < 0 ? "delta-neg" : "delta-pos";
  return `<span class="${cls}">${d > 0 ? "+" : ""}${d.toFixed(2)}s</span>`;
}
const eventName = (e) => `${e.distance} ${trStroke(e.stroke || "")}`.trim();

function standardChips(stds) {
  if (!SHOW_STD || !stds || !stds.length) return "";
  const a = stds.filter((s) => s.applies_to_age);
  return (a.length ? a : stds).map((s) => {
    if (s.achieved === true) return `<span class="chip good">${esc(s.label)} ✓ ${esc(s.time)}</span>`;
    if (s.achieved === false) { const d = s.delta_seconds;
      return `<span class="chip">${esc(s.label)} ${esc(s.time)} (${d > 0 ? "+" : ""}${d.toFixed(2)}s)</span>`; }
    return `<span class="chip">${esc(s.label)} ${esc(s.time)}</span>`;
  }).join("");
}

// ---------- sparkline chart (lower time = higher point) ----------
function sparkline(history) {
  const pts = history.filter((h) => h.seconds != null);
  if (!pts.length) return "";
  const W = 320, H = 56, P = 8;
  const secs = pts.map((p) => p.seconds);
  const mn = Math.min(...secs), mx = Math.max(...secs), rng = (mx - mn) || 1;
  const n = pts.length;
  const X = (i) => (n === 1 ? W / 2 : P + (i * (W - 2 * P)) / (n - 1));
  const Y = (s) => P + ((s - mn) / rng) * (H - 2 * P); // faster(min) -> top
  if (n === 1) {
    return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <circle class="dot" cx="${W / 2}" cy="${H / 2}" r="4"/></svg>`;
  }
  const line = pts.map((p, i) => `${X(i).toFixed(1)},${Y(p.seconds).toFixed(1)}`).join(" ");
  const area = `${P},${H - P} ${line} ${W - P},${H - P}`;
  const dots = pts.map((p, i) => {
    const cls = p.is_pb ? "dot pb" : p.tied ? "dot tie" : "dot";
    return `<circle class="${cls}" cx="${X(i).toFixed(1)}" cy="${Y(p.seconds).toFixed(1)}" r="3.5"/>`;
  }).join("");
  return `<svg class="spark" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <polyline class="ar" points="${area}"/><polyline class="ln" points="${line}"/>${dots}</svg>`;
}

// ---------- state / routing ----------
const state = { index: null, swimmers: null, meetCache: {} };

function setActiveTab(view) {
  document.querySelectorAll(".seg-tab").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
}
function applyChrome() {
  document.querySelectorAll(".seg-tab").forEach((b) =>
    b.textContent = b.dataset.view === "meets" ? t("nav_meets") : t("nav_swimmers"));
  document.querySelectorAll(".lang-switch .seg").forEach((b) =>
    b.classList.toggle("active", b.dataset.lang === LANG));
  $("#lbl-show-standards").textContent = t("show_standards");
  $("#toggle-standards").checked = SHOW_STD;
  document.documentElement.lang = LANG;
}

function route() {
  const h = location.hash.replace(/^#/, "");
  if (h.startsWith("meet/")) { setActiveTab("meets"); return renderMeet(decodeURIComponent(h.slice(5))); }
  if (h.startsWith("swimmer/")) { setActiveTab("swimmers"); return renderSwimmer(decodeURIComponent(h.slice(8))); }
  if (h === "swimmers") { setActiveTab("swimmers"); return renderSwimmers(); }
  setActiveTab("meets"); return renderMeetList();
}

// ---------- meets list ----------
async function renderMeetList() {
  main.innerHTML = `<div class="muted pad">${t("loading")}</div>`;
  if (!state.index) state.index = await getJSON("data/index.json");
  const meets = state.index.meets || [];
  $("#footer-meta").textContent =
    `${t("meet_count", state.index.meet_count)} · ${t("updated")} ${(state.index.generated_at || "").slice(0, 16).replace("T", " ")} UTC`;
  if (!meets.length) {
    main.innerHTML = `<div class="empty">${t("no_meets")}<br><span class="muted">${t("no_meets_help")}</span></div>`; return;
  }
  main.innerHTML = meets.map((m) => `
    <div class="card click" data-go="meet/${encodeURIComponent(m.slug)}">
      <div class="row-between"><h2>${esc(m.title || m.name)}</h2><span class="muted">${esc(m.dates || "")}</span></div>
      <div class="muted">${esc(m.club || "")}</div>
      <div class="chips">
        ${m.course ? `<span class="chip accent">${esc(trCourse(m.course))}</span>` : ""}
        <span class="chip">${t("swimmers_n", m.matched_swimmer_count)}</span>
        <span class="chip">${t("entries_n", m.matched_entry_count)}</span>
        ${m.has_timeline ? `<span class="chip">${t("timeline_chip")}</span>` : ""}
      </div></div>`).join("");
}

// ---------- meet detail (schedule) ----------
async function renderMeet(slug) {
  main.innerHTML = `<div class="muted pad">${t("loading")}</div>`;
  let data = state.meetCache[slug];
  if (!data) { try { data = await getJSON(`data/${slug}.json`); state.meetCache[slug] = data; }
    catch { main.innerHTML = `<div class="empty">${t("no_matched")}</div>`; return; } }
  const m = data.meet, sw = data.swimmers || [];
  const head = `
    <div class="toolbar no-print">
      <button class="back" data-go="">${t("back_meets")}</button>
      ${sw.length ? `<button class="btn" id="print-btn">${t("print")}</button>` : ""}
    </div>
    <div class="print-title">${t("print_title")} — ${esc(m.title || m.name)}</div>
    <div class="card meet-head">
      <div class="row-between"><h2>${esc(m.title || m.name)}</h2><span class="muted">${esc(m.dates || "")}</span></div>
      <div class="muted">${esc(m.club || "")}${m.sanction ? " · " + esc(m.sanction) : ""}</div>
      <div class="chips no-print">
        ${m.course ? `<span class="chip accent">${esc(trCourse(m.course))}</span>` : ""}
        <span class="chip">${t("eventcnt", m.event_count ?? "?")}</span>
        ${m.source_files?.timeline ? `<span class="chip">${t("timeline_chip")}</span>` : ""}
      </div></div>`;
  if (!sw.length) { main.innerHTML = head + `<div class="empty">${t("no_matched")}</div>`; return; }

  const blocks = sw.map((s) => {
    const rows = s.entries.map((e) => {
      const heat = e.heat != null ? `${e.heat}${e.heat_of ? "/" + e.heat_of : ""}` : "-";
      const fl = e.flight ? `<span class="pill pill-${e.flight}" title="${esc(t("flight", e.flight))}">${e.flight}</span>` : "";
      const std = standardChips(e.standards);
      return `<tr>
        <td><span class="ev-no">#${e.event_number}</span> <span class="ev-name">${esc(eventName(e))}</span></td>
        <td class="hide-sm muted">${esc(trRound(e.round))}</td>
        <td class="hl">H${heat}·L${e.lane ?? "-"}</td>
        <td class="t-seed">${esc(e.seed_time || "NT")}</td>
        <td class="when">${e.date ? `<span class="d">${esc(fmtDate(e.date))}</span> ` : ""}${e.estimated_start ? `<span class="tm">${esc(e.estimated_start)}</span>` : ""}${fl ? " " + fl : ""}</td>
      </tr>${std ? `<tr class="std-row"><td colspan="5"><div class="chips">${std}</div></td></tr>` : ""}`;
    }).join("");
    return `<div class="swimmer-block">
      <div class="swimmer-head"><span class="avatar">${esc(initials(s.display_name))}</span>
        <span><span class="nm">${esc(s.display_name)}</span>
        <span class="muted"> · ${esc((s.registered_teams || []).join(", "))} · ${t("events_n", s.entries.length)}</span></span></div>
      <table class="sched"><thead><tr>
        <th>${t("col_event")}</th><th class="hide-sm">${t("col_session")}</th><th>${t("col_heatlane")}</th><th>${t("col_seed")}</th><th>${t("col_when")}</th>
      </tr></thead><tbody>${rows}</tbody></table></div>`;
  }).join("");
  main.innerHTML = head + blocks;
  const pb = $("#print-btn"); if (pb) pb.onclick = () => window.print();
}

// ---------- swimmers grid ----------
async function renderSwimmers() {
  main.innerHTML = `<div class="muted pad">${t("loading")}</div>`;
  if (!state.swimmers) state.swimmers = await getJSON("data/swimmers.json");
  const list = state.swimmers.swimmers || [];
  if (!list.length) { main.innerHTML = `<div class="empty">${t("no_swimmers")}</div>`; return; }
  main.innerHTML = `<div class="sw-grid">` + list.map((s) => `
    <div class="card click sw-card" data-go="swimmer/${encodeURIComponent(s.id)}">
      <div class="top"><span class="avatar lg">${esc(initials(s.display_name))}</span>
        <div><div class="nm">${esc(s.display_name)}</div>
          <div class="sub">${esc((s.teams || []).join(", "))}${s.age ? " · " + s.age : ""}</div></div></div>
      <div class="statline">
        <div class="stat"><b>${s.meet_count}</b><span>${t("stat_meets")}</span></div>
        <div class="stat"><b>${s.event_count}</b><span>${t("stat_events")}</span></div>
        <div class="stat"><b style="color:var(--good)">${s.improved_count}</b><span>${t("stat_improved")}</span></div>
      </div>
      ${s.improved_count ? `<div><span class="imp-badge">▲ ${t("improved_by", topDrop(s))}</span></div>` : ""}
    </div>`).join("") + `</div>`;
}
function topDrop(s) {
  let best = 0;
  (s.events || []).forEach((e) => { if (e.improved && e.drop_seconds > best) best = e.drop_seconds; });
  return best.toFixed(2);
}

// ---------- swimmer profile ----------
async function renderSwimmer(id) {
  main.innerHTML = `<div class="muted pad">${t("loading")}</div>`;
  if (!state.swimmers) state.swimmers = await getJSON("data/swimmers.json");
  const s = (state.swimmers.swimmers || []).find((x) => x.id === id);
  if (!s) { main.innerHTML = `<div class="empty">${t("no_swimmers")}</div>`; return; }

  const swimio = s.swimmerid
    ? `<a href="https://www.myswimio.com/besttimes.php?swimmerid=${encodeURIComponent(s.swimmerid)}" target="_blank" rel="noopener">myswimio ↗</a>` : "";
  const head = `
    <button class="back" data-go="swimmers">${t("back_swimmers")}</button>
    <div class="card">
      <div class="swimmer-head" style="margin:0">
        <span class="avatar lg">${esc(initials(s.display_name))}</span>
        <div><div class="nm" style="font-size:20px">${esc(s.display_name)}</div>
          <div class="muted">${esc((s.teams || []).join(", "))}${s.age ? " · " + s.age : ""} ${swimio ? "· " + swimio : ""}</div></div>
      </div>
      <div class="statline" style="margin-top:14px">
        <div class="stat"><b>${s.meet_count}</b><span>${t("stat_meets")}</span></div>
        <div class="stat"><b>${s.event_count}</b><span>${t("stat_events")}</span></div>
        <div class="stat"><b style="color:var(--good)">${s.improved_count}</b><span>${t("stat_improved")}</span></div>
      </div></div>
    <div class="legend"><span>● <b>${t("legend_pb")}</b></span><span>● ${t("legend_tie")}</span></div>`;

  const improving = s.events.filter((e) => e.improved);
  const others = s.events.filter((e) => !e.improved);
  const render = (e) => {
    const histRows = e.history.map((h) => `<tr>
      <td>${esc(h.meet_name || "")}</td>
      <td class="muted">${esc(fmtDate(h.date_iso) || h.dates || "")}</td>
      <td class="t-seed">${esc(h.time)}</td>
      <td>${fmtDelta(h.delta_prev)}</td>
      <td>${h.is_pb ? `<span class="tag tag-pb">${t("tag_pb")}</span>` : h.tied ? `<span class="tag tag-tie" title="${t("tie_help")}">${t("tag_tie")}</span>` : ""}</td>
    </tr>`).join("");
    const trend = e.improved
      ? `<span class="drop">${t("improved_by", e.drop_seconds.toFixed(2))}</span>`
      : (e.meets > 1 ? `<span class="flat">${t("no_improve")}</span>` : `<span class="muted">${t("one_meet")}</span>`);
    return `<div class="ev-prog">
      <div class="hd"><div><div class="lbl">${esc(eLabel(e.label))}</div>${trend}</div>
        <div class="best"><div class="t">${esc(e.best_time)}</div><div class="muted">${t("best")}</div></div></div>
      ${sparkline(e.history)}
      <details class="histwrap"><summary>${t("meets_n", e.meets)} · ${LANG === "ko" ? "기록 보기" : "history"}</summary>
        <table class="hist"><thead><tr><th>${t("h_meet")}</th><th>${t("h_date")}</th><th>${t("h_time")}</th><th>${t("h_dprev")}</th><th></th></tr></thead>
        <tbody>${histRows}</tbody></table></details>
    </div>`;
  };
  let body = "";
  if (improving.length) body += `<div class="section-title">▲ ${t("improving")}</div>` + improving.map(render).join("");
  if (others.length) body += `<div class="section-title">${t("other_events")}</div>` + others.map(render).join("");
  main.innerHTML = head + (body || `<div class="empty">${t("no_record")}</div>`);
}
const eLabel = (label) => label.replace(
  /(Freestyle|Backstroke|Breaststroke|Butterfly|Individual Medley|IM|Medley Relay|Freestyle Relay|Free Relay)/,
  (m) => trStroke(m));

// ---------- chrome events ----------
document.querySelectorAll(".seg-tab").forEach((b) =>
  b.addEventListener("click", () => { location.hash = b.dataset.view === "meets" ? "" : "#swimmers"; }));
document.querySelectorAll(".lang-switch .seg").forEach((b) =>
  b.addEventListener("click", () => {
    if (LANG === b.dataset.lang) return;
    LANG = b.dataset.lang; localStorage.setItem("lang", LANG);
    const y = window.scrollY; applyChrome(); route(); requestAnimationFrame(() => window.scrollTo(0, y));
  }));
$("#brand").addEventListener("click", (e) => { e.preventDefault(); location.hash = ""; });
$("#settings-btn").addEventListener("click", () => {
  const p = $("#settings-panel"); p.hidden = !p.hidden; $("#settings-btn").classList.toggle("on", !p.hidden);
});
$("#toggle-standards").addEventListener("change", (e) => {
  SHOW_STD = e.target.checked; localStorage.setItem("showStandards", SHOW_STD ? "1" : "0");
  const y = window.scrollY; route(); requestAnimationFrame(() => window.scrollTo(0, y));
});
// delegate card/button navigation
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-go]"); if (!el) return;
  location.hash = el.getAttribute("data-go");
});
window.addEventListener("hashchange", route);

// ---------- init ----------
applyChrome();
route();
