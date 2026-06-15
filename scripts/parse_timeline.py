"""HY-TEK Session Report(타임라인) PDF 파서.

대회 세션별 이벤트 예상 시작 시각을 추출한다. 결과는 다음 형태:
  { "sessions": [ {"session": 1, "label": "Saturday", "day": 1,
                    "events": [ {"number": 1, "description": "...",
                                 "entries": 29, "heats": 4,
                                 "start_time": "12:45 PM"} ] } ] }

두 가지 입력 형태를 지원한다:
  1) 텍스트 추출이 되는 PDF (일반적인 HY-TEK Session Report) — 직접 파싱.
  2) 텍스트가 벡터로 그려져 추출이 안 되는 PDF — pytesseract 가 있으면 OCR,
     없으면 빈 결과를 반환하고 경고를 남긴다. (타임라인은 보조 정보)
"""

from __future__ import annotations

import re
import sys
from typing import Optional

import fitz


TIME_AT_RE = re.compile(r"\b(\d{1,2}:\d{2}\s*[AP]M)\b", re.IGNORECASE)
EVENT_LINE_RE = re.compile(
    r"^(?P<num>\d+)\s+(?P<desc>(?:Girls|Boys|Women|Men|Mixed)\s+.+)$"
)
SESSION_RE = re.compile(r"Session:\s*(?P<num>\d+)\s*(?P<label>.*)", re.IGNORECASE)
DAY_RE = re.compile(r"Day of Meet:\s*(?P<day>\d+)", re.IGNORECASE)


def _extract_text(doc: "fitz.Document") -> str:
    parts = [page.get_text() for page in doc]
    text = "\n".join(parts)
    if text.strip():
        return text
    # 텍스트가 없으면 OCR 시도 (CI 환경에서 tesseract 설치 시 동작)
    try:
        import pytesseract  # noqa: F401
        from PIL import Image
        import io

        ocr_parts = []
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            ocr_parts.append(pytesseract.image_to_string(img))
        return "\n".join(ocr_parts)
    except Exception as exc:  # pragma: no cover - 환경 의존
        print(f"[timeline] OCR 불가(텍스트 없음): {exc}", file=sys.stderr)
        return ""


def parse_pdf(path: str) -> dict:
    doc = fitz.open(path)
    text = _extract_text(doc)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    sessions: list[dict] = []
    current: Optional[dict] = None

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]

        sm = SESSION_RE.search(line)
        if sm:
            current = {
                "session": int(sm.group("num")),
                "label": sm.group("label").strip() or None,
                "day": None,
                "events": [],
            }
            sessions.append(current)
            i += 1
            continue

        dm = DAY_RE.search(line)
        if dm and current is not None:
            current["day"] = int(dm.group("day"))
            i += 1
            continue

        em = EVENT_LINE_RE.match(line)
        if em:
            if current is None:
                current = {"session": 1, "label": None, "day": None, "events": []}
                sessions.append(current)
            # 이벤트 라인 이후 몇 줄 안에서 entries/heats/시작시각을 수집
            window = lines[i : i + 8]
            nums = []
            start_time = None
            for w in window[1:]:
                tm = TIME_AT_RE.search(w)
                if tm:
                    start_time = re.sub(r"\s+", " ", tm.group(1)).upper()
                    break
                if w.isdigit():
                    nums.append(int(w))
            entries = nums[0] if len(nums) >= 1 else None
            heats = nums[1] if len(nums) >= 2 else None
            current["events"].append(
                {
                    "number": int(em.group("num")),
                    "description": em.group("desc").strip(),
                    "entries": entries,
                    "heats": heats,
                    "start_time": start_time,
                }
            )
        i += 1

    return {
        "source_file": path.split("/")[-1],
        "text_extracted": bool(text.strip()),
        "sessions": sessions,
    }


def event_start_map(timeline: dict) -> dict[int, str]:
    """이벤트 번호 -> 시작 시각 매핑 (여러 세션을 평탄화)."""
    out: dict[int, str] = {}
    for s in timeline.get("sessions", []):
        for e in s.get("events", []):
            if e.get("start_time"):
                out[e["number"]] = e["start_time"]
    return out


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
        print(f"parsed {len(result['sessions'])} sessions, {nev} events -> {argv[2]}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
