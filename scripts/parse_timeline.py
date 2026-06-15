"""HY-TEK Session Report(타임라인) PDF 파서.

대회 세션별 이벤트 예상 시작 시각을 추출한다. 결과 형태:
  { "sessions": [ {"session": 1, "label": "THURSDAY PRELIMS", "round": "prelim",
                    "day": 1,
                    "events": [ {"number": 1, "description": "...", "round": "prelim",
                                 "entries": 117, "heats": 8,
                                 "start_time": "8:00 AM"} ] } ] }

입력 PDF 는 두 가지 줄 구조가 섞일 수 있다:
  1) 텍스트 추출형(일반 Session Report) — 한 이벤트의 항목이 여러 줄로 분리.
  2) OCR형(Prelims 가 벡터로 그려져 텍스트가 없는 페이지) — 한 줄에 모든 항목.
페이지별로 텍스트가 없으면 그 페이지만 OCR(pytesseract, 있을 때) 한다.
"""

from __future__ import annotations

import re
import sys
from typing import Optional

import fitz


# 시간: 8:00 AM / 12:45 PM (OCR 오인식 대비 '.' 구분자도 허용)
TIME_AT_RE = re.compile(r"\b(\d{1,2})[:.](\d{2})\s*([AP]M)\b", re.IGNORECASE)

ROUND_WORDS = r"Prelims|Finals|Timed Finals|Semifinals|Swim-?off"
# 이벤트 라인: (선택)라운드 + 이벤트번호 + 'Girls/Boys/...' 로 시작하는 설명
EVENT_LINE_RE = re.compile(
    rf"^(?:(?P<round>{ROUND_WORDS})\s+)?(?P<num>\d+)\s+"
    r"(?P<desc>(?:Girls|Boys|Women|Men|Mixed)\b.*)$",
    re.IGNORECASE,
)
SESSION_RE = re.compile(r"Session:?\s*(?P<num>\d+)\s*(?P<label>.*)", re.IGNORECASE)
DAY_RE = re.compile(r"Day of Meet:?\s*(?P<day>\d+)", re.IGNORECASE)
# 'FLIGHT A' / 'Flight B' 구분 헤더 (선수가 많아 한 이벤트를 두 플라이트로 나눠 진행)
FLIGHT_RE = re.compile(r"^FLIGHT\s+(?P<flight>[AB])\b", re.IGNORECASE)
# 설명 뒤에 붙는 'entries heats time' 꼬리 제거용
TAIL_RE = re.compile(r"(?:\s+\d+){0,2}\s+\d{1,2}[:.]\d{2}\s*[AP]M.*$", re.IGNORECASE)


def _time_minutes(t: Optional[str]) -> int:
    """'1:53 PM' -> 자정 기준 분. 정렬용. 파싱 실패 시 0."""
    if not t:
        return 0
    m = TIME_AT_RE.search(t)
    if not m:
        return 0
    h, mm, ap = int(m.group(1)), int(m.group(2)), m.group(3).upper()
    if ap == "PM" and h != 12:
        h += 12
    if ap == "AM" and h == 12:
        h = 0
    return h * 60 + mm


def _assign_flights(session: dict) -> None:
    """세션 내에서 같은 이벤트가 여러 번(다른 시간) 등장하면 플라이트로 본다.

    선수가 많은 이벤트는 'FLIGHT A'(이른 시간)/'FLIGHT B'(늦은 시간)로 나뉘는데,
    OCR 이 'FLIGHT B' 배너를 놓치는 경우가 많으므로, 헤더가 아니라 '같은 이벤트의
    중복 등장'으로 판정한다. 시작 시각이 빠른 쪽부터 A, B, C… 로 라벨링한다.
    한 번만 등장하면 분할이 없으므로 flight=None.
    """
    from collections import defaultdict

    label = (session.get("label") or "").upper()
    groups: dict[int, list] = defaultdict(list)
    for e in session.get("events", []):
        if e.get("start_time"):
            groups[e["number"]].append(e)

    # 플라이트/풀 포맷 세션만 플라이트를 부여한다(결승 등 일반 세션은 제외).
    flighted = ("FLIGHT" in label) or ("POOL" in label) or any(len(v) >= 2 for v in groups.values())

    for evs in groups.values():
        if flighted:
            # 문서 순서(= FLIGHT A 섹션이 먼저)대로 A, B, C… 라벨링.
            # 분할 안 된(단일) 이벤트도 첫(유일) 조는 Flight A 로 본다.
            for idx, e in enumerate(evs):
                e["flight"] = chr(ord("A") + idx)
        else:
            for e in evs:
                e["flight"] = None
    for e in session.get("events", []):
        if not e.get("start_time"):
            e["flight"] = None


def _time_candidates(t: str) -> list[str]:
    """OCR 시각 문자열의 보정 후보. 원본 + '앞자리 1 누락' 복원형.

    OCR 은 '12:10 PM'→'2:10 PM', '10:36 AM'→'0:36 AM' 처럼 앞자리 1 을 자주
    떨어뜨린다. 한 자리 시(h)에 1 을 붙여 10/11/12 후보를 추가한다.
    """
    m = TIME_AT_RE.search(t)
    if not m:
        return [t]
    h, mm, ap = m.group(1), m.group(2), m.group(3).upper()
    cands = [f"{int(h)}:{mm} {ap}"]
    if len(h) == 1:
        ph = int("1" + h)  # 0->10, 1->11, 2->12, 3->13...
        if ph in (10, 11, 12):
            cands.append(f"{ph}:{mm} {ap}")
    return cands


def _repair_times(session: dict) -> None:
    """플라이트(세션 구간) 내 시각은 단조 증가해야 한다는 점을 이용해 OCR 오류 보정.

    각 플라이트 그룹을 등장 순서대로 보며, 직전 시각보다 빠르거나 다음 시각보다
    늦어 순서를 깨면 '앞자리 1 누락' 복원 후보 중 [직전, 다음] 사이에 맞는 값으로
    교정한다. 정상 시각(원본이 들어맞음)은 그대로 둔다.
    """
    from collections import defaultdict

    groups: dict = defaultdict(list)
    for e in session.get("events", []):
        if e.get("start_time"):
            groups[e.get("flight")].append(e)
    for evs in groups.values():
        prev = None
        for i, e in enumerate(evs):
            nxt = _time_minutes(evs[i + 1]["start_time"]) if i + 1 < len(evs) else None
            cands = _time_candidates(e["start_time"])
            chosen = None
            for c in cands:  # 원본 우선 — [직전, 다음] 범위에 맞으면 채택
                cm = _time_minutes(c)
                lo_ok = prev is None or cm >= prev
                hi_ok = nxt is None or cm <= nxt or (prev is not None and nxt < prev)
                if lo_ok and hi_ok:
                    chosen = c
                    break
            if chosen is None:  # 범위에 맞는 게 없으면 직전 이상인 최소 후보
                valid = [(c, _time_minutes(c)) for c in cands if prev is None or _time_minutes(c) >= prev]
                chosen = min(valid, key=lambda x: x[1])[0] if valid else cands[0]
            e["start_time"] = chosen
            prev = _time_minutes(chosen)


def round_category(s: Optional[str]) -> Optional[str]:
    """라벨/라운드 문자열을 'prelim' / 'final' 로 정규화."""
    if not s:
        return None
    s = s.lower()
    if "prelim" in s or "semi" in s:
        return "prelim"
    if "final" in s:  # 'timed finals' 포함
        return "final"
    return None


def _norm_time(h: str, m: str, ampm: str) -> str:
    return f"{int(h)}:{m} {ampm.upper()}"


def _ocr_page(page: "fitz.Page") -> str:
    try:
        import pytesseract
        from PIL import Image
        import io

        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img)
    except Exception as exc:  # pragma: no cover - 환경 의존
        print(f"[timeline] OCR 불가: {exc}", file=sys.stderr)
        return ""


def _rows_from_words(words: list, y_tol: float = 3.0) -> list[str]:
    """단어 좌표로 같은 줄(행)을 재구성해 정렬된 텍스트 줄 목록을 만든다.

    HY-TEK 의 'TWO POOL'(좌우 2열) 등 복잡한 레이아웃은 get_text() 의 줄 순서가
    뒤섞여 한 행의 항목들이 흩어진다. y 좌표로 묶고 x 로 정렬하면 한 행이
    'Prelims 68 Boys 11 & Over 200 Breaststroke 131 17 8:00 AM' 처럼 복원된다.
    """
    rows: list[dict] = []
    for w in sorted(words, key=lambda x: (x[1], x[0])):
        for r in rows:
            if abs(r["y"] - w[1]) <= y_tol:
                r["w"].append(w)
                break
        else:
            rows.append({"y": w[1], "w": [w]})
    out = []
    for r in sorted(rows, key=lambda r: r["y"]):
        toks = [t[4] for t in sorted(r["w"], key=lambda x: x[0])]
        out.append(" ".join(toks).strip())
    return out


def _page_lines(page: "fitz.Page") -> tuple[list[str], bool]:
    """한 페이지의 텍스트 줄 목록과 OCR 사용 여부.

    텍스트가 있으면 좌표로 행을 재구성(복잡한 2열 레이아웃 대응),
    없으면(벡터 페이지) OCR 한다.
    """
    words = page.get_text("words")
    if words:
        return _rows_from_words(words), False
    ocr = _ocr_page(page)
    return [l.strip() for l in ocr.splitlines() if l.strip()], bool(ocr.strip())


def parse_pdf(path: str) -> dict:
    doc = fitz.open(path)
    lines: list[str] = []
    ocr_used = False
    for page in doc:
        pls, used = _page_lines(page)
        ocr_used = ocr_used or used
        lines.extend(pls)
    text = "\n".join(lines)

    sessions: list[dict] = []
    current: Optional[dict] = None
    current_flight: Optional[str] = None

    def ensure_session() -> dict:
        nonlocal current
        if current is None:
            current = {"session": 1, "label": None, "round": None, "day": None, "events": []}
            sessions.append(current)
        return current

    i, n = 0, len(lines)
    while i < n:
        line = lines[i]

        sm = SESSION_RE.search(line)
        if sm:
            label = sm.group("label").strip() or None
            current = {
                "session": int(sm.group("num")),
                "label": label,
                "round": round_category(label),
                "day": None,
                "events": [],
            }
            sessions.append(current)
            current_flight = None
            i += 1
            continue

        fm = FLIGHT_RE.match(line)
        if fm:
            current_flight = fm.group("flight").upper()
            i += 1
            continue

        dm = DAY_RE.search(line)
        if dm and current is not None:
            current["day"] = int(dm.group("day"))
            i += 1
            continue

        em = EVENT_LINE_RE.match(line)
        if em:
            sess = ensure_session()
            round_tok = em.group("round")
            desc_raw = em.group("desc")

            entries = heats = start_time = None
            tm = TIME_AT_RE.search(line)
            if tm:
                # OCR형: 같은 줄에 entries/heats/시간이 모두 있음
                start_time = _norm_time(*tm.groups())
                trailing = re.search(
                    r"\s+(\d+)\s+(\d+)\s+\d{1,2}[:.]\d{2}\s*[AP]M\s*$", line, re.IGNORECASE
                )
                if trailing:
                    entries, heats = int(trailing.group(1)), int(trailing.group(2))
            else:
                # 텍스트형: 다음 줄들에서 entries/heats/시간 수집
                nums: list[int] = []
                for w in lines[i + 1 : i + 9]:
                    if EVENT_LINE_RE.match(w) or SESSION_RE.search(w):
                        break
                    t2 = TIME_AT_RE.search(w)
                    if t2:
                        start_time = _norm_time(*t2.groups())
                        break
                    if w.isdigit():
                        nums.append(int(w))
                if nums:
                    entries = nums[0]
                    heats = nums[1] if len(nums) > 1 else None

            desc = TAIL_RE.sub("", desc_raw).strip()
            ev_round = round_category(round_tok) or sess.get("round")
            sess["events"].append(
                {
                    "number": int(em.group("num")),
                    "description": desc,
                    "round": ev_round,
                    "flight": current_flight,
                    "entries": entries,
                    "heats": heats,
                    "start_time": start_time,
                }
            )
        i += 1

    # 세션별로 중복 이벤트를 플라이트(A/B/…)로 라벨링 후, OCR 시각 오류를 보정
    for s in sessions:
        _assign_flights(s)
        _repair_times(s)

    return {
        "source_file": path.split("/")[-1],
        "text_extracted": bool(text.strip()),
        "ocr_used": ocr_used,
        "sessions": sessions,
    }


def main(argv: list[str]) -> int:
    import json

    if len(argv) < 2:
        print("usage: parse_timeline.py <pdf> [out.json]", file=sys.stderr)
        return 2
    result = parse_pdf(argv[1])
    text = json.dumps(result, ensure_ascii=False, indent=2)
    if len(argv) > 2:
        with open(argv[2], "w", encoding="utf-8") as f:
            f.write(text)
        nev = sum(len(s["events"]) for s in result["sessions"])
        print(
            f"parsed {len(result['sessions'])} sessions, {nev} events "
            f"(ocr={result['ocr_used']}) -> {argv[2]}",
            file=sys.stderr,
        )
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
