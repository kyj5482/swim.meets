"""대회 폴더 1개를 처리하여 관심 선수 결과 JSON 을 생성한다.

입력:  input/<대회명>/  안의 PDF (Psych Sheet/Meet Program + Timeline)
출력:  data/<slug>.json  및  docs/data/<slug>.json (사이트용 복사본)

폴더 안의 PDF 는 파일명/내용으로 'psych'(프로그램)과 'timeline'(세션리포트)으로
자동 분류한다. 관심 선수는 swimmers.json 에서 읽어 성/이름 + 나이/팀으로 매칭한다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import fitz

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import parse_psych_sheet  # noqa: E402
import parse_timeline  # noqa: E402
import common  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# PDF 분류 & 메타데이터
# ---------------------------------------------------------------------------


def _first_page_text(path: Path) -> str:
    try:
        doc = fitz.open(path)
        text = ""
        for page in doc:
            text += page.get_text()
            if len(text) > 4000:
                break
        return text
    except Exception:
        return ""


def classify_pdf(path: Path) -> str:
    """'timeline' 또는 'psych' 으로 분류."""
    name = path.name.lower()
    if "timeline" in name or "session" in name:
        return "timeline"
    if any(k in name for k in ("program", "psych", "heat", "sheet")):
        return "psych"
    text = _first_page_text(path)
    if "Session Report" in text:
        return "timeline"
    if "Meet Program" in text or "Psych Sheet" in text or re.search(r"\bHeat\s+\d+\s+of\s+\d+", text):
        return "psych"
    # 마지막 휴리스틱: 이벤트/히트 구조가 많으면 psych
    if len(re.findall(r"\bEvent\s+\d+", text)) >= 2:
        return "psych"
    return "timeline"


def extract_meet_meta(psych_path: Path | None) -> dict:
    meta = {"club": None, "title": None, "dates": None, "sanction": None, "course": None}
    if psych_path is None:
        return meta
    text = _first_page_text(psych_path)
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    for i, l in enumerate(lines[:12]):
        if "Inc." in l or "Aquatics" in l or "Swim" in l and meta["club"] is None and "HY-TEK" not in l:
            if meta["club"] is None and "Program" not in l and "Session" not in l:
                meta["club"] = l
        dm = re.search(r"(.+?)\s*-\s*(\d{1,2}/\d{1,2}/\d{2,4})(?:\s*to\s*(\d{1,2}/\d{1,2}/\d{2,4}))?", l)
        if dm and meta["title"] is None and "HY-TEK" not in l and "Sanction" not in l:
            meta["title"] = dm.group(1).strip()
            meta["dates"] = dm.group(2) + (f" ~ {dm.group(3)}" if dm.group(3) else "")
        sm = re.search(r"Sanction\s*#:\s*(\S+)", l)
        if sm:
            meta["sanction"] = sm.group(1)
    cm = re.search(r"(LC Meter|SC Meter|SCY|Yard|Meter)", text)
    if cm:
        meta["course"] = cm.group(1)
    return meta


# ---------------------------------------------------------------------------
# 타임라인 라운드별 시작시각 조회
# ---------------------------------------------------------------------------


def lookup_start_time(timeline: dict | None, event_number: int, round_name: str | None) -> str | None:
    if not timeline:
        return None
    want_final = (round_name or "").lower().startswith("final")
    want_prelim = (round_name or "").lower().startswith(("prelim", "semi"))
    fallback = None
    for s in timeline.get("sessions", []):
        label = (s.get("label") or "").lower()
        for e in s.get("events", []):
            if e.get("number") != event_number or not e.get("start_time"):
                continue
            if want_final and "final" in label:
                return e["start_time"]
            if want_prelim and "prelim" in label:
                return e["start_time"]
            fallback = fallback or e["start_time"]
    return fallback


# ---------------------------------------------------------------------------
# 메인 처리
# ---------------------------------------------------------------------------


def load_swimmers() -> list[dict]:
    path = ROOT / "swimmers.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("swimmers", [])


def process_meet(meet_dir: Path, swimmers: list[dict]) -> dict:
    pdfs = sorted(p for p in meet_dir.iterdir() if p.suffix.lower() == ".pdf")
    psych_path = timeline_path = None
    for p in pdfs:
        kind = classify_pdf(p)
        if kind == "psych" and psych_path is None:
            psych_path = p
        elif kind == "timeline" and timeline_path is None:
            timeline_path = p
    # psych 미지정인데 PDF 가 하나뿐이면 그것을 psych 로
    if psych_path is None and pdfs:
        psych_path = next((p for p in pdfs if p != timeline_path), None)

    meet_name = meet_dir.name
    slug = common.slugify(meet_name)

    psych = parse_psych_sheet.parse_pdf(str(psych_path)) if psych_path else {"events": []}
    timeline = parse_timeline.parse_pdf(str(timeline_path)) if timeline_path else None
    meta = extract_meet_meta(psych_path)

    # 선수별 결과 누적
    results: dict[str, dict] = {}
    for sw in swimmers:
        results[sw["id"]] = {
            "id": sw["id"],
            "display_name": f"{sw.get('first','')} {sw.get('last','')}".strip(),
            "last": sw.get("last"),
            "first": sw.get("first"),
            "registered_age": sw.get("age"),
            "registered_teams": sw.get("teams"),
            "swimmerid": sw.get("swimmerid"),
            "entries": [],
        }

    for ev in psych.get("events", []):
        for heat in ev.get("heats", []):
            for entry in heat.get("entries", []):
                m = common.best_match(entry, swimmers)
                if not m:
                    continue
                sw, score = m
                std_eval = common.evaluate_standards(
                    entry.get("seed_time"), entry.get("age"), ev.get("standards", {})
                )
                start_time = lookup_start_time(timeline, ev.get("number"), heat.get("round"))
                results[sw["id"]]["entries"].append(
                    {
                        "event_number": ev.get("number"),
                        "event_title": ev.get("raw_title"),
                        "gender": ev.get("gender"),
                        "distance": ev.get("distance"),
                        "course": ev.get("course"),
                        "stroke": ev.get("stroke"),
                        "age_group": ev.get("age_group"),
                        "round": heat.get("round"),
                        "heat": heat.get("heat"),
                        "heat_of": heat.get("heat_of"),
                        "lane": entry.get("lane"),
                        "entry_age": entry.get("age"),
                        "entry_team": entry.get("team"),
                        "seed_time": entry.get("seed_time"),
                        "seed_seconds": common.time_to_seconds(entry.get("seed_time")),
                        "estimated_start": start_time,
                        "standards": std_eval,
                        "match_score": round(score, 2),
                    }
                )

    swimmer_results = [r for r in results.values() if r["entries"]]
    for r in swimmer_results:
        r["entries"].sort(key=lambda e: (e["event_number"] or 0, e.get("round") or ""))

    out = {
        "meet": {
            "name": meet_name,
            "slug": slug,
            "title": meta.get("title") or meet_name,
            "club": meta.get("club"),
            "dates": meta.get("dates"),
            "sanction": meta.get("sanction"),
            "course": meta.get("course"),
            "source_files": {
                "psych_sheet": psych_path.name if psych_path else None,
                "timeline": timeline_path.name if timeline_path else None,
            },
            "processed_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "event_count": len(psych.get("events", [])),
        },
        "swimmers": swimmer_results,
        "matched_swimmer_count": len(swimmer_results),
        "matched_entry_count": sum(len(r["entries"]) for r in swimmer_results),
    }
    return out


def write_outputs(result: dict) -> tuple[Path, Path]:
    slug = result["meet"]["slug"]
    data_path = ROOT / "data" / f"{slug}.json"
    site_path = ROOT / "docs" / "data" / f"{slug}.json"
    text = json.dumps(result, ensure_ascii=False, indent=2)
    data_path.parent.mkdir(parents=True, exist_ok=True)
    site_path.parent.mkdir(parents=True, exist_ok=True)
    data_path.write_text(text, encoding="utf-8")
    site_path.write_text(text, encoding="utf-8")
    return data_path, site_path


def prune_orphans(valid_slugs: set[str]) -> list[str]:
    """input/ 에 더 이상 없는 대회의 생성물(data/, docs/data/)을 삭제한다.

    index.json / swimmers.json 은 build_index.py 가 관리하므로 건드리지 않는다.
    """
    removed: list[str] = []
    keep = {"index", "swimmers"}
    for base in (ROOT / "data", ROOT / "docs" / "data"):
        if not base.exists():
            continue
        for p in base.glob("*.json"):
            if p.stem in keep:
                continue
            if p.stem not in valid_slugs:
                p.unlink()
                removed.append(str(p.relative_to(ROOT)))
    return removed


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="대회 폴더 처리")
    ap.add_argument("meet_dir", nargs="?", help="처리할 대회 폴더 (미지정 시 input/ 전체)")
    args = ap.parse_args(argv[1:])

    swimmers = load_swimmers()
    input_root = ROOT / "input"

    if args.meet_dir:
        dirs = [Path(args.meet_dir)]
        full_run = False
    else:
        dirs = [d for d in sorted(input_root.iterdir()) if d.is_dir()] if input_root.exists() else []
        full_run = True

    if not dirs and not full_run:
        print("처리할 대회 폴더가 없습니다 (input/<대회명>/).", file=sys.stderr)
        return 0

    valid_slugs: set[str] = set()
    for d in dirs:
        if not any(p.suffix.lower() == ".pdf" for p in d.iterdir()):
            print(f"건너뜀(PDF 없음): {d}", file=sys.stderr)
            continue
        result = process_meet(d, swimmers)
        dp, sp = write_outputs(result)
        valid_slugs.add(result["meet"]["slug"])
        print(
            f"[{d.name}] 선수 {result['matched_swimmer_count']}명 / "
            f"엔트리 {result['matched_entry_count']}건 -> {dp.relative_to(ROOT)}",
            file=sys.stderr,
        )

    # 전체 처리(=input/ 전체 스캔) 시에만, 삭제된 대회의 옛 산출물을 정리한다.
    if full_run:
        removed = prune_orphans(valid_slugs)
        for r in removed:
            print(f"정리(삭제된 대회): {r}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
