"use strict";

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

// 적용 나이대 기준 중 통과(achieved) 여부 요약 칩
function standardChips(stds) {
  if (!stds || !stds.length) return "";
  const applied = stds.filter((s) => s.applies_to_age);
  const list = applied.length ? applied : stds;
  return list.map((s) => {
    if (s.achieved === true)
      return `<span class="chip good" title="기준 통과">${esc(s.label)} ✓ ${esc(s.time)}</span>`;
    if (s.achieved === false) {
      const d = s.delta_seconds;
      return `<span class="chip" title="기준까지">${esc(s.label)} ${esc(s.time)} (${d > 0 ? "+" : ""}${d.toFixed(2)}s)</span>`;
    }
    return `<span class="chip">${esc(s.label)} ${esc(s.time)}</span>`;
  }).join("");
}

// ---- 라우팅 --------------------------------------------------------------
const state = { view: "meets", index: null, swimmers: null, meetCache: {} };

function setView(v) {
  state.view = v;
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.view === v));
  location.hash = v === "meets" ? "" : "#" + v;
  render();
}

document.querySelectorAll(".tab").forEach((t) =>
  t.addEventListener("click", () => setView(t.dataset.view)));

window.addEventListener("hashchange", routeFromHash);

function routeFromHash() {
  const h = location.hash.replace(/^#/, "");
  if (h.startsWith("meet/")) return renderMeet(decodeURIComponent(h.slice(5)));
  if (h === "swimmers") { state.view = "swimmers"; }
  else { state.view = "meets"; }
  document.querySelectorAll(".tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.view === state.view));
  render();
}

// ---- 렌더: 대회 목록 ------------------------------------------------------
async function render() {
  if (state.view === "swimmers") return renderSwimmers();
  return renderMeetList();
}

async function renderMeetList() {
  if (!state.index) state.index = await getJSON("data/index.json");
  const meets = state.index.meets || [];
  $("#footer-meta").textContent =
    `대회 ${state.index.meet_count}개 · 갱신 ${state.index.generated_at?.slice(0, 16).replace("T", " ")} UTC`;
  if (!meets.length) {
    main.innerHTML = `<div class="empty">아직 처리된 대회가 없습니다.<br>
      <span class="muted">input/&lt;대회명&gt;/ 에 Psych Sheet와 Timeline PDF를 올리세요.</span></div>`;
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
        <span class="chip">${esc(m.course || "")}</span>
        <span class="chip">선수 ${m.matched_swimmer_count}명</span>
        <span class="chip">엔트리 ${m.matched_entry_count}건</span>
        ${m.has_timeline ? '<span class="chip">⏱ 타임라인</span>' : ""}
      </div>
    </div>`).join("");
}

// ---- 렌더: 대회 상세 ------------------------------------------------------
async function renderMeet(slug) {
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  main.innerHTML = `<div class="muted">불러오는 중…</div>`;
  let data = state.meetCache[slug];
  if (!data) {
    try { data = await getJSON(`data/${slug}.json`); state.meetCache[slug] = data; }
    catch (e) { main.innerHTML = `<div class="empty">대회 데이터를 찾을 수 없습니다.</div>`; return; }
  }
  const m = data.meet;
  const swimmers = data.swimmers || [];
  const head = `
    <button class="back" onclick="location.hash=''">← 대회 목록</button>
    <div class="card">
      <div class="row-between"><h2>${esc(m.title || m.name)}</h2>
        <span class="muted">${esc(m.dates || "")}</span></div>
      <div class="muted">${esc(m.club || "")} ${m.sanction ? "· " + esc(m.sanction) : ""}</div>
      <div class="chips">
        <span class="chip">${esc(m.course || "")}</span>
        <span class="chip">이벤트 ${m.event_count ?? "?"}개</span>
        ${m.source_files?.psych_sheet ? `<span class="chip">📄 ${esc(m.source_files.psych_sheet)}</span>` : ""}
        ${m.source_files?.timeline ? `<span class="chip">⏱ ${esc(m.source_files.timeline)}</span>` : ""}
      </div>
    </div>`;

  if (!swimmers.length) {
    main.innerHTML = head + `<div class="empty">이 대회에서 매칭된 관심 선수가 없습니다.</div>`;
    return;
  }

  const blocks = swimmers.map((sw) => {
    const rows = sw.entries.map((e) => {
      const evlabel = `${e.distance} ${esc(e.stroke || "")}`;
      const heat = e.heat != null ? `${e.heat}${e.heat_of ? "/" + e.heat_of : ""}` : "-";
      return `<tr>
        <td class="ev">#${e.event_number} <span class="muted">${evlabel}</span></td>
        <td class="muted">${esc(e.round || "")}</td>
        <td class="hl">H${heat} · L${e.lane ?? "-"}</td>
        <td class="time">${esc(e.seed_time || "NT")}</td>
        <td class="start">${e.estimated_start ? "⏱ " + esc(e.estimated_start) : ""}</td>
      </tr>
      <tr><td colspan="5"><div class="chips">${standardChips(e.standards)}</div></td></tr>`;
    }).join("");
    return `<div class="swimmer-block">
      <div class="swimmer-head"><span class="name">${esc(sw.display_name)}</span>
        <span class="muted">${esc(sw.registered_teams?.join(", ") || "")} · ${sw.entries.length}종목</span></div>
      <table class="entries">
        <thead><tr><th>이벤트</th><th>라운드</th><th>조·레인</th><th>시드</th><th>예상시각</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>`;
  }).join("");

  main.innerHTML = head + blocks;
}

// ---- 렌더: 선수별 진척도 --------------------------------------------------
async function renderSwimmers() {
  main.innerHTML = `<div class="muted">불러오는 중…</div>`;
  if (!state.swimmers) state.swimmers = await getJSON("data/swimmers.json");
  const swimmers = state.swimmers.swimmers || [];
  if (!swimmers.length) {
    main.innerHTML = `<div class="empty">진척도 데이터가 없습니다.</div>`;
    return;
  }
  main.innerHTML = swimmers.map((s) => {
    const events = s.events.map((ev) => {
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
        <summary><span class="lbl">${esc(ev.label)}</span>
          <span class="best">최고 ${esc(ev.best_time)} · ${ev.meets}개 대회</span></summary>
        <table class="entries">
          <thead><tr><th>대회</th><th>일자</th><th>기록</th><th>직전대비</th><th>최초대비</th></tr></thead>
          <tbody>${hist}</tbody>
        </table>
      </details>`;
    }).join("");
    const swimioLink = s.swimmerid
      ? ` · <a href="https://www.myswimio.com/besttimes.php?swimmerid=${encodeURIComponent(s.swimmerid)}" target="_blank" rel="noopener">myswimio ↗</a>`
      : "";
    return `<div class="swimmer-block">
      <div class="swimmer-head"><span class="name">${esc(s.display_name)}</span>
        <span class="muted">${s.events.length}종목${swimioLink}</span></div>
      ${events || '<div class="muted">기록 없음</div>'}
    </div>`;
  }).join("");
}

// ---- 시작 ----------------------------------------------------------------
routeFromHash();
