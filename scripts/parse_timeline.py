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

    groups: dict[int, list] = defaultdict(list)
    for e in session.get("events", []):
        if e.get("start_time"):
            groups[e["number"]].append(e)
    for evs in groups.values():
        if len(evs) >= 2:
            for idx, e in enumerate(sorted(evs, key=lambda x: _time_minutes(x["start_time"]))):
                e["flight"] = chr(ord("A") + idx)
        else:
            evs[0]["flight"] = None
    for e in session.get("events", []):
        if not e.get("start_time"):
            e["flight"] = None


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

        pix = page.get_pixmap(dpi=200)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return pytesseract.image_to_string(img)
    except Exception as exc:  # pragma: no cover - 환경 의존
        print(f"[timeline] OCR 불가: {exc}", file=sys.stderr)
        return ""


def _extract_text(doc: "fitz.Document") -> tuple[str, bool]:
    """페이지별로 텍스트를 얻되, 텍스트가 없는 페이지만 OCR 한다."""
    parts: list[str] = []
    ocr_used = False
    for page in doc:
        t = page.get_text()
        if t.strip():
            parts.append(t)
        else:
            ocr = _ocr_page(page)
            if ocr.strip():
                ocr_used = True
            parts.append(ocr)
    return "\n".join(parts), ocr_used


def parse_pdf(path: str) -> dict:
    doc = fitz.open(path)
    text, ocr_used = _extract_text(doc)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

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

    # 세션별로 중복 이벤트를 플라이트(A/B/…)로 라벨링 (헤더 누락에 강건)
    for s in sessions:
        _assign_flights(s)

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
