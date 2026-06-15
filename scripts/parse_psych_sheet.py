"""HY-TEK Meet Manager 프로그램(Psych Sheet) PDF 파서.

좌표 기반(positional)으로 추출하여 대회마다 양식이 조금씩 달라도
Event / Heat / Lane / 선수(이름, 나이, 팀) / Seed Time 을 안정적으로 추출한다.

HY-TEK Meet Program 의 전형적인 레이아웃:
  - 페이지는 보통 2단(좌/우) 컬럼으로 구성된다.
  - 각 컬럼 내부는 [Lane] [Name(Last, First M)] [Age] [Team] [Seed Time] [Flag] 순서.
  - Event 헤더("Event 1  Girls 13 & Over 200 LC Meter Freestyle") 아래에
    급별 기준기록(Standard/Cut time)이 인쇄되어 있다. 예) "13-14 &JAG  2:26.30".
  - Heat 헤더("Heat 1 of 15  Prelims")로 조가 구분된다.

이 모듈은 PDF 를 구조화된 dict 로 변환한다. (선수 필터링은 별도 단계에서 수행)
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field, asdict
from typing import Optional

import fitz  # PyMuPDF


# ---------------------------------------------------------------------------
# 정규식 / 상수
# ---------------------------------------------------------------------------

EVENT_RE = re.compile(
    r"\bEvent\s+(?P<num>\d+)\s+(?P<gender>Girls|Boys|Women|Men|Mixed)\s+"
    r"(?P<agegroup>.*?)\s*(?P<distance>\d+)\s+(?P<course>LC Meter|SC Meter|SCY|LCM|SCM|Yard|Meter|Meters)?\s*"
    r"(?P<stroke>Freestyle|Backstroke|Breaststroke|Butterfly|IM|Individual Medley|Medley Relay|Free Relay|Freestyle Relay)\s*$",
    re.IGNORECASE,
)

# 좀 더 관대한 fallback: "Event N  <gender> <나머지>"
EVENT_LOOSE_RE = re.compile(
    r"\bEvent\s+(?P<num>\d+)\s+(?P<gender>Girls|Boys|Women|Men|Mixed)\s+(?P<rest>.+)$",
    re.IGNORECASE,
)

HEAT_RE = re.compile(
    r"\bHeat\s+(?P<heat>\d+)\s+of\s+(?P<of>\d+)\s*(?P<round>Prelims|Finals|Semifinals|Timed Finals|Swim-?off)?",
    re.IGNORECASE,
)
# 단순 "Heat 3" 또는 "Flight 2" 형태도 처리
HEAT_SIMPLE_RE = re.compile(r"\b(?:Heat|Flight)\s+(?P<heat>\d+)\b", re.IGNORECASE)

# 시드타임: 1:23.45 / 58.12 / 12:34.56 / NT / DQ / SCR / X1:23.45(번호표시)
TIME_RE = re.compile(r"^X?\d{0,2}:?\d{1,2}\.\d{2}$|^NT$|^NS$|^DQ$|^SCR$|^DFS$", re.IGNORECASE)

# 기준기록 라인: "13-14 &JAG  2:26.30" / "15&O BB 2:37.09" / "Open A 1:59.99"
STANDARD_RE = re.compile(
    r"^(?P<label>[A-Za-z0-9&+\-\s]+?)\s+(?P<time>X?\d{0,2}:?\d{1,2}\.\d{2})$"
)

# 이름: "Last, First M" — 콤마 필수
NAME_RE = re.compile(r"^[^,]+,\s+.+$")

# 나이: 5~99 사이 정수 (혹은 한 두자리)
AGE_RE = re.compile(r"^\d{1,2}$")

# 성별+나이 결합형 (일부 'Mixed' 대회 양식): M13, W11, F11, G14, B12
GENDER_AGE_RE = re.compile(r"^([MWFGB])(\d{1,2})$")

# 팀 코드: 보통 대문자/숫자/하이픈 (예: NOVA-CA, UN-01-SI, RAA-CA)
TEAM_RE = re.compile(r"^[A-Z0-9][A-Z0-9\-]{1,12}$")

# 페이지 머리글/꼬리글 등 사람 엔트리가 아닌 라인 식별용 키워드
NON_ENTRY_SUBSTR = (
    "HY-TEK",
    "MEET MANAGER",
    "Meet Program",
    "Session Report",
    "Sanction",
    "Inc.",
    ", LLC",
    "Page ",
    "Psych Sheet",
    "Performance",
    "Results",
)


# ---------------------------------------------------------------------------
# 데이터 구조
# ---------------------------------------------------------------------------


@dataclass
class Entry:
    lane: Optional[int]
    last_name: str
    first_name: str
    full_name: str
    age: Optional[int]
    team: Optional[str]
    seed_time: Optional[str]
    gender: Optional[str] = None
    flags: list = field(default_factory=list)


@dataclass
class Heat:
    heat: Optional[int]
    heat_of: Optional[int]
    round: Optional[str]
    entries: list = field(default_factory=list)


@dataclass
class Event:
    number: Optional[int]
    raw_title: str
    gender: Optional[str]
    age_group: Optional[str]
    distance: Optional[int]
    course: Optional[str]
    stroke: Optional[str]
    is_relay: bool
    standards: dict = field(default_factory=dict)  # label -> time
    heats: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# 컬럼 감지 & 행 재구성
# ---------------------------------------------------------------------------


def _detect_column_split(words: list[tuple], page_width: float) -> Optional[float]:
    """2단 컬럼 페이지에서 좌/우 컬럼을 가르는 x 경계를 추정.

    페이지 중앙 영역(40~60%)에서 어떤 단어도 가로지르지 않는 '빈 세로 띠'를
    찾아 그 중앙을 컬럼 경계로 삼는다. HY-TEK 2단 레이아웃은 좌/우 두 컬럼
    사이에 일정한 여백이 있으므로 이 방법이 글꼴/양식 변형에 강건하다.
    'Name'/'Lane' 머리글이 2개 이상일 때만 2단으로 간주한다.
    """
    name_xs = [w[0] for w in words if w[4] in ("Name", "Lane")]
    if len(name_xs) < 2:
        return None

    lo, hi = page_width * 0.40, page_width * 0.60
    # 중앙 영역에서 어떤 단어도 가로지르지 않는(빈) x 구간들을 찾고,
    # 그 중 '가장 넓은 빈 띠'의 중앙을 경계로 삼는다. (좌/우 컬럼 사이 여백)
    step = 1.0
    xs = []
    x = lo
    while x <= hi:
        crossings = sum(1 for w in words if w[0] < x < w[2])
        xs.append((x, crossings == 0))
        x += step
    # 연속된 빈 구간 중 최장 구간 탐색
    best_run = None  # (start_x, end_x)
    run_start = None
    for xv, empty in xs:
        if empty and run_start is None:
            run_start = xv
        elif not empty and run_start is not None:
            run = (run_start, xv - step)
            if best_run is None or (run[1] - run[0]) > (best_run[1] - best_run[0]):
                best_run = run
            run_start = None
    if run_start is not None:
        run = (run_start, xs[-1][0])
        if best_run is None or (run[1] - run[0]) > (best_run[1] - best_run[0]):
            best_run = run
    if best_run is not None:
        return (best_run[0] + best_run[1]) / 2
    return page_width / 2  # fallback: 정중앙


def _group_rows(words: list[tuple], y_tol: float = 3.0) -> list[list[tuple]]:
    """같은 y(행)에 속하는 단어들을 묶는다. 각 행은 x 정렬."""
    rows: list[list[tuple]] = []
    for w in sorted(words, key=lambda w: (w[1], w[0])):
        placed = False
        for row in rows:
            if abs(row[0][1] - w[1]) <= y_tol:
                row.append(w)
                placed = True
                break
        if not placed:
            rows.append([w])
    for row in rows:
        row.sort(key=lambda w: w[0])
    rows.sort(key=lambda r: r[0][1])
    return rows


# ---------------------------------------------------------------------------
# 행 파싱
# ---------------------------------------------------------------------------


def _parse_entry_row(tokens: list[str]) -> Optional[Entry]:
    """한 행의 토큰들을 선수 엔트리로 파싱.

    형태: [lane] Last, First [M] [age] [TEAM] [seed] [flags...]
    레이아웃 변형을 고려해 토큰 위치가 아니라 토큰 의미로 파싱한다.
    """
    if not tokens:
        return None

    toks = list(tokens)

    lane = None
    if toks and toks[0].isdigit() and len(toks[0]) <= 2 and int(toks[0]) <= 10:
        lane = int(toks[0])
        toks = toks[1:]

    # 이름 조립: 첫 토큰이 "Last," 형태(콤마 포함)여야 함
    if not toks or "," not in "".join(toks[:1]):
        # 콤마가 첫 토큰에 없으면, 콤마 포함 토큰을 찾는다
        comma_idx = next((i for i, t in enumerate(toks) if t.endswith(",")), None)
        if comma_idx is None:
            return None
    # last name 은 콤마로 끝나는 토큰까지
    name_tokens: list[str] = []
    i = 0
    # last (콤마 포함될 때까지)
    while i < len(toks):
        name_tokens.append(toks[i])
        if toks[i].endswith(","):
            i += 1
            break
        i += 1
    else:
        return None

    if not name_tokens or not name_tokens[-1].endswith(","):
        return None

    # 이후 토큰 중 나이가 나오기 전까지가 first name (+ middle initial).
    # 나이는 순수 숫자('14')이거나 성별+나이 결합형('M13','W11','F11','G14')일 수 있다.
    rest = toks[i:]
    age = None
    gender = None
    age_pos = None
    for j, t in enumerate(rest):
        if AGE_RE.match(t) and 4 <= int(t) <= 99:
            age = int(t)
            age_pos = j
            break
        gm = GENDER_AGE_RE.match(t)
        if gm and 4 <= int(gm.group(2)) <= 99:
            gender = gm.group(1).upper()
            age = int(gm.group(2))
            age_pos = j
            break
    if age_pos is None:
        # 나이를 못 찾으면 first name 만 채우고 종료
        first_tokens = rest
        after = []
    else:
        first_tokens = rest[:age_pos]
        after = rest[age_pos + 1 :]

    last = " ".join(name_tokens).rstrip(",").strip()
    first = " ".join(first_tokens).strip()
    if not last or not first:
        return None

    # after: [TEAM] [seed] [flags]
    team = None
    seed = None
    flags: list[str] = []
    for t in after:
        if seed is None and TIME_RE.match(t):
            seed = t
        elif team is None and TEAM_RE.match(t) and not TIME_RE.match(t):
            team = t
        else:
            flags.append(t)

    full = f"{last}, {first}"
    return Entry(
        lane=lane,
        last_name=last,
        first_name=first,
        full_name=full,
        age=age,
        team=team,
        seed_time=seed,
        gender=gender,
        flags=flags,
    )


def _parse_standard_row(tokens: list[str]) -> Optional[tuple[str, str]]:
    """기준기록(급별 cut time) 행을 (label, time) 으로 파싱.

    시간 토큰이 정확히 하나 있고 나머지가 라벨이면 인정한다.
    토큰 순서(시간이 앞이든 뒤든)에 무관하다.
    """
    times = [t for t in tokens if TIME_RE.match(t) and t.upper() not in ("NT", "NS")]
    if len(times) != 1:
        return None
    time = times[0]
    label_tokens = [t for t in tokens if t is not time and not (TIME_RE.match(t) and t == time)]
    # 위 비교는 동일 문자열이 두 번 나올 때 취약하므로 인덱스 기반으로 재구성
    label_tokens = []
    removed = False
    for t in tokens:
        if not removed and t == time:
            removed = True
            continue
        label_tokens.append(t)
    label = " ".join(label_tokens).strip()
    if not label:
        return None
    # 라벨은 보통 'AGE LEVEL' 형태 (예: 13-14 &JAG, 15&O BB, Open A). 너무 길면 제외.
    if len(label) > 24 or any(c.islower() for c in label.replace("Over", "").replace("Open", "")) and "," in label:
        return None
    return label, time


def _parse_event_header(line: str) -> Optional[Event]:
    m = EVENT_RE.search(line)
    if m:
        course = (m.group("course") or "").strip() or None
        stroke = m.group("stroke").strip()
        return Event(
            number=int(m.group("num")),
            raw_title=line[m.start():].strip(),
            gender=m.group("gender"),
            age_group=m.group("agegroup").strip(),
            distance=int(m.group("distance")),
            course=course,
            stroke=stroke,
            is_relay="relay" in stroke.lower(),
        )
    m = EVENT_LOOSE_RE.search(line)
    if m:
        rest = m.group("rest")
        dist_m = re.search(r"(\d+)", rest)
        stroke_m = re.search(
            r"(Freestyle|Backstroke|Breaststroke|Butterfly|IM|Individual Medley|Medley Relay|Free Relay|Freestyle Relay)",
            rest,
            re.IGNORECASE,
        )
        return Event(
            number=int(m.group("num")),
            raw_title=line[m.start():].strip(),
            gender=m.group("gender"),
            age_group=rest.split(str(dist_m.group(1)))[0].strip() if dist_m else None,
            distance=int(dist_m.group(1)) if dist_m else None,
            course=None,
            stroke=stroke_m.group(1) if stroke_m else None,
            is_relay="relay" in rest.lower(),
        )
    return None


# ---------------------------------------------------------------------------
# 메인 파서
# ---------------------------------------------------------------------------


def parse_pdf(path: str) -> dict:
    doc = fitz.open(path)
    events: list[Event] = []
    current_event: Optional[Event] = None
    current_heat: Optional[Heat] = None
    # event_num -> Event (중복 등장 시 heats 병합)
    by_num: dict[int, Event] = {}

    for page in doc:
        words = page.get_text("words")  # (x0,y0,x1,y1,word,block,line,wordno)
        if not words:
            continue
        split_x = _detect_column_split(words, page.rect.width)
        if split_x is not None:
            columns = [
                [w for w in words if w[0] < split_x],
                [w for w in words if w[0] >= split_x],
            ]
        else:
            columns = [words]

        for col_words in columns:
            rows = _group_rows(col_words)
            for row in rows:
                tokens = [w[4] for w in row]
                line = " ".join(tokens).strip()
                if not line:
                    continue

                # Event 헤더?
                ev = _parse_event_header(line)
                if ev is not None:
                    if ev.number in by_num:
                        current_event = by_num[ev.number]
                    else:
                        by_num[ev.number] = ev
                        events.append(ev)
                        current_event = ev
                    current_heat = None
                    continue

                # Heat 헤더?
                hm = HEAT_RE.search(line)
                if hm and current_event is not None:
                    current_heat = Heat(
                        heat=int(hm.group("heat")),
                        heat_of=int(hm.group("of")),
                        round=(hm.group("round") or "").strip() or None,
                    )
                    current_event.heats.append(current_heat)
                    continue
                hs = HEAT_SIMPLE_RE.search(line)
                if hs and current_event is not None and not hm:
                    current_heat = Heat(
                        heat=int(hs.group("heat")), heat_of=None, round=None
                    )
                    current_event.heats.append(current_heat)
                    continue

                # 컬럼 머리글(Lane/Name/Age/Team/Seed/Time) 스킵
                low = line.lower()
                if low.startswith(("lane name", "name age", "age team")) or line in (
                    "Lane Name Age Team Seed Time",
                ):
                    continue

                # 기준기록(Standard) 라인? — Event 헤더 직후, Heat 시작 전.
                # 시간 토큰이 라벨 앞/뒤 어디에 오든 처리한다. (예: "2:26.30 13-14 &JAG")
                if current_event is not None and current_heat is None and "," not in line:
                    std = _parse_standard_row(tokens)
                    if std is not None:
                        label, time = std
                        current_event.standards[label] = time
                        continue

                # 페이지 머리글/꼬리글 라인은 건너뛴다.
                if any(s in line for s in NON_ENTRY_SUBSTR):
                    continue

                # 선수 엔트리 행?
                if current_heat is not None and "," in line:
                    entry = _parse_entry_row(tokens)
                    if entry is not None:
                        current_heat.entries.append(entry)
                        continue

    meta = doc.metadata or {}
    result = {
        "source_file": path.split("/")[-1],
        "producer": meta.get("producer"),
        "title": meta.get("title"),
        "event_count": len(events),
        "events": [_event_to_dict(e) for e in events],
    }
    return result


def _event_to_dict(e: Event) -> dict:
    d = asdict(e)
    return d


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    import json

    if len(argv) < 2:
        print("usage: parse_psych_sheet.py <pdf> [out.json]", file=sys.stderr)
        return 2
    result = parse_pdf(argv[1])
    out = argv[2] if len(argv) > 2 else None
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
        n_entries = sum(len(h["entries"]) for e in result["events"] for h in e["heats"])
        print(
            f"parsed {result['event_count']} events, {n_entries} entries -> {out}",
            file=sys.stderr,
        )
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
