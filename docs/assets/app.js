"use strict";

// ---- 다국어(i18n) --------------------------------------------------------
const I18N = {
  ko: {
    tab_meets: "대회별", tab_swimmers: "선수별 진척도",
    loading: "불러오는 중…", back: "← 대회 목록", print: "🖨 인쇄",
    col_event: "이벤트", col_round: "라운드", col_heatlane: "조·레인",
    col_seed: "시드", col_start: "예상시각", col_when: "일정(일자·시각)",
    col_meet: "대회", col_date: "일자", col_time: "기록",
    col_dprev: "직전대비", col_dfirst: "최초대비",
    swimmers_n: (n) => `선수 ${n}명`, entries_n: (n) => `엔트리 ${n}건`,
    events_n: (n) => `${n}종목`, meets_n: (n) => `${n}개 대회`,
    eventcnt_n: (n) => `이벤트 ${n}개`,
    flight: (f) => `${f}플라이트`,
    best: (t) => `최고 ${t}`, timeline_chip: "⏱ 타임라인",
    updated: "갱신", meet_count: (n) => `대회 ${n}개`,
    no_meets_title: "아직 처리된 대회가 없습니다.",
    no_meets_help: "input/<대회명>/ 에 Psych Sheet와 Timeline PDF를 올리세요.",
    no_matched: "이 대회에서 매칭된 관심 선수가 없습니다.",
    no_swimmers: "진척도 데이터가 없습니다.",
    no_record: "기록 없음",
    print_title: "관심 선수 출전 일정",
    seed_note: "시드기록", entries_word: "엔트리",
  },
  en: {
    tab_meets: "Meets", tab_swimmers: "Swimmer progress",
    loading: "Loading…", back: "← Meets", print: "🖨 Print",
    col_event: "Event", col_round: "Round", col_heatlane: "Heat·Lane",
    col_seed: "Seed", col_start: "Est. start", col_when: "When (date·time)",
    col_meet: "Meet", col_date: "Date", col_time: "Time",
    col_dprev: "vs prev", col_dfirst: "vs first",
    swimmers_n: (n) => `${n} swimmer${n === 1 ? "" : "s"}`,
    entries_n: (n) => `${n} entr${n === 1 ? "y" : "ies"}`,
    events_n: (n) => `${n} event${n === 1 ? "" : "s"}`,
    meets_n: (n) => `${n} meet${n === 1 ? "" : "s"}`,
    eventcnt_n: (n) => `${n} events`,
    flight: (f) => `Flight ${f}`,
    best: (t) => `Best ${t}`, timeline_chip: "⏱ timeline",
    updated: "Updated", meet_count: (n) => `${n} meet${n === 1 ? "" : "s"}`,
    no_meets_title: "No meets processed yet.",
    no_meets_help: "Upload a Psych Sheet & Timeline PDF into input/<MeetName>/.",
    no_matched: "No registered swimmers matched in this meet.",
    no_swimmers: "No progression data.",
    no_record: "No record",
    print_title: "Registered Swimmers — Meet Schedule",
    seed_note: "seed", entries_word: "events",
  },
};

const STROKE = {
  ko: { Freestyle: "자유형", Backstroke: "배영", Breaststroke: "평영", Butterfly: "접영",
        IM: "개인혼영", "Individual Medley": "개인혼영", "Medley Relay": "혼계영",
        "Free Relay": "계영", "Freestyle Relay": "계영" },
  en: {},
};
const ROUND = {
  ko: { Prelims: "예선", Finals: "결승", "Timed Finals": "타임결승", Semifinals: "준결승" },
  en: {},
};
const COURSE = {
  ko: { "LC Meter": "장수로(50m)", "SC Meter": "단수로(25m)", SCY: "단수로(야드)" },
  en: {},
};

let LANG = localStorage.getItem("lang") || "ko";
if (!["ko", "en"].includes(LANG)) LANG = "ko";

const t = (k, ...a) => {
  const v = I18N[LANG][k];
  return typeof v === "function" ? v(...a) : (v ?? k);
};
const tr = (map, v) => (v && (map[LANG][v] || map.en[v])) || v || "";
const trStroke = (s) => tr(STROKE, s);
const trRound = (r) => tr(ROUND, r);
const trCourse = (c) => tr(COURSE, c);

// ---- 유틸 ----------------------------------------------------------------
const $ = (sel, el = document) => el.querySelector(sel);
const main = $("#main");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function getJSON(path) {
  const r = await fetch(path, { cache: "no-cache" });
  if (!r.ok) throw new Error(path + " " + r.status);
  return r.json();
}

function fmtDelta(d) {
  if (d === null || d === undefined) return "";
  const cls = d < 0 ? "delta-neg" : d > 0 ? "delta-pos" : "muted";
  const sign = d > 0 ? "+" : "";
  return `<span class="${cls}">${sign}${d.toFixed(2)}s</span>`;
}

function standardChips(stds) {
  if (!stds || !stds.length) return "";
  const applied = stds.filter((s) => s.applies_to_age);
  const list = applied.length ? applied : stds;
  return list.map((s) => {
    if (s.achieved === true)
      return `<span class="chip good">${esc(s.label)} ✓ ${esc(s.time)}</span>`;
    if (s.achieved === false) {
      const d = s.delta_seconds;
      return `<span class="chip">${esc(s.label)} ${esc(s.time)} (${d > 0 ? "+" : ""}${d.toFixed(2)}s)</span>`;
    }
    return `<span class="chip">${esc(s.label)} ${esc(s.time)}</span>`;
  }).join("");
}

const eventName = (e) => `${e.distance} ${trStroke(e.stroke || "")}`.trim();

// ISO 날짜(2026-06-13) -> '6/13 (토)' / '6/13 (Sat)'
function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d)) return iso;
  const loc = LANG === "ko" ? "ko-KR" : "en-US";
  const wd = d.toLocaleDateString(loc, { weekday: "short" });
  return `${d.getMonth() + 1}/${d.getDate()} (${wd})`;
}

// ---- 상태 / 라우팅 -------------------------------------------------------
const state = { view: "meets", index: null, swimmers: null, meetCache: {} };

function applyStaticLabels() {
  document.querySelectorAll(".tab").forEach((tb) => {
    tb.textContent = tb.dataset.view === "meets" ? t("tab_meets") : t("tab_swimmers");
  });
  const lb = $("#lang-btn");
  if (lb) lb.textContent = LANG === "ko" ? "EN" : "한";
  document.documentElement.lang = LANG;
}

function setLang(l) {
  LANG = l;
  localStorage.setItem("lang", l);
  applyStaticLabels();
  routeFromHash();
}

function bindHeader() {
  document.querySelectorAll(".tab").forEach((tb) =>
    tb.addEventListener("click", () => { location.hash = tb.dataset.view === "meets" ? "" : "#swimmers"; }));
  const lb = $("#lang-btn");
  if (lb) lb.addEventListener("click", () => setLang(LANG === "ko" ? "en" : "ko"));
}

window.addEventListener("hashchange", routeFromHash);

function routeFromHash() {
  const h = location.hash.replace(/^#/, "");
  if (h.startsWith("meet/")) { state.view = "meet"; return renderMeet(decodeURIComponent(h.slice(5))); }
  state.view = h === "swimmers" ? "swimmers" : "meets";
  document.querySelectorAll(".tab").forEach((tb) =>
    tb.classList.toggle("active", tb.dataset.view === state.view));
  document.body.classList.remove("print-mode");
  render();
}

async function render() {
  if (state.view === "swimmers") return renderSwimmers();
  return renderMeetList();
}

// ---- 대회 목록 -----------------------------------------------------------
async function renderMeetList() {
  main.innerHTML = `<div class="muted">${t("loading")}</div>`;
  if (!state.index) state.index = await getJSON("data/index.json");
  const meets = state.index.meets || [];
  $("#footer-meta").textContent =
    `${t("meet_count", state.index.meet_count)} · ${t("updated")} ${state.index.generated_at?.slice(0, 16).replace("T", " ")} UTC`;
  if (!meets.length) {
    main.innerHTML = `<div class="empty">${t("no_meets_title")}<br><span class="muted">${t("no_meets_help")}</span></div>`;
    return;
  }
  main.innerHTML = meets.map((m) => `
    <div class="card click" onclick="location.hash='meet/${encodeURIComponent(m.slug)}'">
      <div class="row-between">
        <h2>${esc(m.title || m.name)}</h2>
        <span class="muted">${esc(m.dates || "")}</span>
      </div>
      <div class="muted">${esc(m.club || "")}</div>
      <div class="chips">
        <span class="chip">${esc(trCourse(m.course))}</span>
        <span class="chip">${t("swimmers_n", m.matched_swimmer_count)}</span>
        <span class="chip">${t("entries_n", m.matched_entry_count)}</span>
        ${m.has_timeline ? `<span class="chip">${t("timeline_chip")}</span>` : ""}
      </div>
    </div>`).join("");
}

// ---- 대회 상세 (인쇄용 Psych Sheet 포함) ---------------------------------
async function renderMeet(slug) {
  document.querySelectorAll(".tab").forEach((tb) => tb.classList.remove("active"));
  main.innerHTML = `<div class="muted">${t("loading")}</div>`;
  let data = state.meetCache[slug];
  if (!data) {
    try { data = await getJSON(`data/${slug}.json`); state.meetCache[slug] = data; }
    catch { main.innerHTML = `<div class="empty">${t("no_matched")}</div>`; return; }
  }
  const m = data.meet;
  const swimmers = data.swimmers || [];

  const head = `
    <div class="meet-toolbar no-print">
      <button class="back" onclick="location.hash=''">${t("back")}</button>
      ${swimmers.length ? `<button class="btn-print" onclick="window.print()">${t("print")}</button>` : ""}
    </div>
    <div class="card meet-head">
      <div class="print-title">${t("print_title")}</div>
      <div class="row-between"><h2>${esc(m.title || m.name)}</h2>
        <span class="muted">${esc(m.dates || "")}</span></div>
      <div class="muted">${esc(m.club || "")} ${m.sanction ? "· " + esc(m.sanction) : ""}</div>
      <div class="chips no-print">
        <span class="chip">${esc(trCourse(m.course))}</span>
        <span class="chip">${t("eventcnt_n", m.event_count ?? "?")}</span>
        ${m.source_files?.timeline ? `<span class="chip">${t("timeline_chip")}</span>` : ""}
      </div>
    </div>`;

  if (!swimmers.length) {
    main.innerHTML = head + `<div class="empty">${t("no_matched")}</div>`;
    return;
  }

  const blocks = swimmers.map((sw) => {
    const rows = sw.entries.map((e) => {
      const heat = e.heat != null ? `${e.heat}${e.heat_of ? "/" + e.heat_of : ""}` : "-";
      return `<tr>
        <td class="ev">#${e.event_number} <span class="muted">${esc(eventName(e))}</span></td>
        <td class="muted">${esc(trRound(e.round))}${e.flight ? ` · <span class="flight flight-${e.flight}">${t("flight", e.flight)}</span>` : ""}</td>
        <td class="hl">H${heat} · L${e.lane ?? "-"}</td>
        <td class="time">${esc(e.seed_time || "NT")}</td>
        <td class="start">${e.date ? `<span class="ev-date">${esc(fmtDate(e.date))}</span> ` : ""}${e.estimated_start ? esc(e.estimated_start) : ""}</td>
      </tr>
      <tr class="std-row no-print"><td colspan="5"><div class="chips">${standardChips(e.standards)}</div></td></tr>`;
    }).join("");
    return `<div class="swimmer-block">
      <div class="swimmer-head"><span class="name">${esc(sw.display_name)}</span>
        <span class="muted">${esc((sw.registered_teams || []).join(", "))} · ${t("events_n", sw.entries.length)}</span></div>
      <table class="entries">
        <thead><tr><th>${t("col_event")}</th><th>${t("col_round")}</th><th>${t("col_heatlane")}</th><th>${t("col_seed")}</th><th>${t("col_when")}</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  }).join("");

  main.innerHTML = head + `<div class="print-area">${blocks}</div>`;
}

// ---- 선수별 진척도 -------------------------------------------------------
async function renderSwimmers() {
  main.innerHTML = `<div class="muted">${t("loading")}</div>`;
  if (!state.swimmers) state.swimmers = await getJSON("data/swimmers.json");
  const swimmers = state.swimmers.swimmers || [];
  if (!swimmers.length) { main.innerHTML = `<div class="empty">${t("no_swimmers")}</div>`; return; }

  main.innerHTML = swimmers.map((s) => {
    const events = s.events.map((ev) => {
      const label = ev.label.replace(/(Freestyle|Backstroke|Breaststroke|Butterfly|Individual Medley|IM|Medley Relay|Freestyle Relay|Free Relay)/,
        (m) => trStroke(m));
      const hist = ev.history.map((h) => {
        const stds = standardChips(h.standards);
        return `<tr>
          <td>${esc(h.meet_name || "")}${h.is_pb ? '<span class="pb-badge">PB</span>' : ""}</td>
          <td class="muted">${esc(h.dates || "")}</td>
          <td class="time">${esc(h.time)}</td>
          <td>${fmtDelta(h.delta_prev)}</td>
          <td>${fmtDelta(h.delta_first)}</td>
        </tr>
        ${stds ? `<tr><td colspan="5"><div class="chips">${stds}</div></td></tr>` : ""}`;
      }).join("");
      return `<details>
        <summary><span class="lbl">${esc(label)}</span>
          <span class="best">${t("best", esc(ev.best_time))} · ${t("meets_n", ev.meets)}</span></summary>
        <table class="entries">
          <thead><tr><th>${t("col_meet")}</th><th>${t("col_date")}</th><th>${t("col_time")}</th><th>${t("col_dprev")}</th><th>${t("col_dfirst")}</th></tr></thead>
          <tbody>${hist}</tbody>
        </table>
      </details>`;
    }).join("");
    const swimioLink = s.swimmerid
      ? ` · <a href="https://www.myswimio.com/besttimes.php?swimmerid=${encodeURIComponent(s.swimmerid)}" target="_blank" rel="noopener">myswimio ↗</a>`
      : "";
    return `<div class="swimmer-block">
      <div class="swimmer-head"><span class="name">${esc(s.display_name)}</span>
        <span class="muted">${t("events_n", s.events.length)}${swimioLink}</span></div>
      ${events || `<div class="muted">${t("no_record")}</div>`}
    </div>`;
  }).join("");
}

// ---- 시작 ----------------------------------------------------------------
bindHeader();
applyStaticLabels();
routeFromHash();
