"""data/*.json 을 모아 사이트용 인덱스와 선수별 진척도(progression)를 생성한다.

산출물:
  docs/data/index.json    : 대회 목록 요약
  docs/data/swimmers.json : 선수별 종목 진척도(대회 시간순) + 최고기록 + 표준기록 비교

이로써 사이트에서 MeetMobile 처럼 대회별 조회는 물론,
myswimio Best Times 처럼 '과거 대비 향상도'와 '단계별 표준기록 비교'를 볼 수 있다.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _parse_meet_date(dates: str | None) -> str | None:
    """'6/11/2026 ~ 6/14/2026' -> 정렬용 ISO 'YYYY-MM-DD'(시작일)."""
    if not dates:
        return None
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", dates)
    if not m:
        return None
    mo, da, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if yr < 100:
        yr += 2000
    try:
        return dt.date(yr, mo, da).isoformat()
    except ValueError:
        return None


def _event_key(e: dict) -> str:
    return f"{e.get('distance')}|{(e.get('stroke') or '').lower()}|{(e.get('course') or '').lower()}"


def _event_label(e: dict) -> str:
    course = e.get("course") or ""
    return f"{e.get('distance')} {course} {e.get('stroke')}".replace("  ", " ").strip()


def load_standards_ref() -> dict:
    """선택적 외부 표준기록(standards/*.json) 로드. 없으면 빈 dict."""
    out = {}
    sdir = ROOT / "standards"
    if sdir.exists():
        for p in sorted(sdir.glob("*.json")):
            try:
                out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                pass
    return out


def build() -> None:
    data_dir = ROOT / "data"
    meets = []
    meet_files = sorted(data_dir.glob("*.json")) if data_dir.exists() else []

    # 선수별 진척도 누적: swimmer_id -> event_key -> [ {meet, date, seconds, time, ...} ]
    progression: dict[str, dict] = {}

    for mf in meet_files:
        try:
            data = json.loads(mf.read_text(encoding="utf-8"))
        except Exception:
            continue
        meet = data.get("meet", {})
        date_iso = _parse_meet_date(meet.get("dates"))
        meets.append(
            {
                "slug": meet.get("slug"),
                "name": meet.get("name"),
                "title": meet.get("title"),
                "dates": meet.get("dates"),
                "date_iso": date_iso,
                "course": meet.get("course"),
                "club": meet.get("club"),
                "matched_swimmer_count": data.get("matched_swimmer_count", 0),
                "matched_entry_count": data.get("matched_entry_count", 0),
                "has_timeline": bool(meet.get("source_files", {}).get("timeline")),
            }
        )

        for sw in data.get("swimmers", []):
            sid = sw["id"]
            sp = progression.setdefault(
                sid,
                {
                    "id": sid,
                    "display_name": sw.get("display_name"),
                    "last": sw.get("last"),
                    "first": sw.get("first"),
                    "swimmerid": sw.get("swimmerid"),
                    "teams": sw.get("registered_teams"),
                    "age": sw.get("registered_age"),
                    "meet_slugs": set(),
                    "events": {},
                },
            )
            sp["meet_slugs"].add(meet.get("slug"))
            # 종목별 best (round 무관, 가장 빠른 seed) 한 대회당 1건만 기록
            best_per_event: dict[str, dict] = {}
            for e in sw.get("entries", []):
                secs = e.get("seed_seconds")
                if secs is None:
                    continue
                key = _event_key(e)
                prev = best_per_event.get(key)
                if prev is None or secs < prev["seconds"]:
                    best_per_event[key] = {
                        "meet_slug": meet.get("slug"),
                        "meet_name": meet.get("title") or meet.get("name"),
                        "date_iso": date_iso,
                        "dates": meet.get("dates"),
                        "seconds": secs,
                        "time": e.get("seed_time"),
                        "label": _event_label(e),
                        "standards": e.get("standards", []),
                        "age": e.get("entry_age"),
                    }
            for key, rec in best_per_event.items():
                sp["events"].setdefault(key, {"label": rec["label"], "history": []})
                sp["events"][key]["history"].append(rec)

    # 진척도 정리: 시간순 정렬 + 향상도/PB/정체(tied) 계산
    swimmers_out = []
    for sid, sp in progression.items():
        events_list = []
        improved_cnt = 0
        for key, ev in sp["events"].items():
            hist = sorted(ev["history"], key=lambda r: (r["date_iso"] or "", r["meet_name"] or ""))
            best = min((h["seconds"] for h in hist), default=None)
            first_secs = hist[0]["seconds"] if hist else None
            running_best = None
            for i, h in enumerate(hist):
                secs = h["seconds"]
                # is_pb: 직전까지의 최고기록을 '실제로' 깬 경우(엄격히 더 빠름)만.
                # tied: 과거 최고와 같은 기록(= 최고기록을 못 깸).
                if running_best is None:
                    h["is_pb"], h["tied"] = False, False  # 첫 기록은 기준점
                elif secs < running_best - 1e-9:
                    h["is_pb"], h["tied"] = True, False
                elif abs(secs - running_best) <= 0.01:
                    h["is_pb"], h["tied"] = False, True
                else:
                    h["is_pb"], h["tied"] = False, False
                running_best = secs if running_best is None else min(running_best, secs)
                h["is_best"] = abs(secs - best) <= 1e-9
                h["delta_prev"] = round(secs - hist[i - 1]["seconds"], 2) if i > 0 else None
                h["delta_first"] = round(secs - first_secs, 2) if first_secs is not None else None
            improved = best is not None and first_secs is not None and best < first_secs - 1e-9
            if improved:
                improved_cnt += 1
            events_list.append(
                {
                    "key": key,
                    "label": ev["label"],
                    "best_seconds": best,
                    "best_time": common.seconds_to_time(best),
                    "first_seconds": first_secs,
                    "improved": improved,
                    "drop_seconds": round(first_secs - best, 2) if improved else 0.0,
                    "history": hist,
                    "meets": len(hist),
                }
            )
        # 향상된 종목 먼저, 그다음 라벨순
        events_list.sort(key=lambda e: (not e["improved"], e["label"]))
        swimmers_out.append(
            {
                "id": sid,
                "display_name": sp["display_name"],
                "last": sp["last"],
                "first": sp["first"],
                "swimmerid": sp["swimmerid"],
                "teams": sp.get("teams"),
                "age": sp.get("age"),
                "meet_count": len(sp.get("meet_slugs") or []),
                "event_count": len(events_list),
                "improved_count": improved_cnt,
                "events": events_list,
            }
        )

    swimmers_out.sort(key=lambda s: (s["last"] or "", s["first"] or ""))
    meets.sort(key=lambda m: (m["date_iso"] or "", m["name"] or ""), reverse=True)

    out_dir = ROOT / "docs" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.json").write_text(
        json.dumps(
            {
                "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "meet_count": len(meets),
                "meets": meets,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (out_dir / "swimmers.json").write_text(
        json.dumps(
            {
                "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                "swimmer_count": len(swimmers_out),
                "swimmers": swimmers_out,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"index: {len(meets)} meets, {len(swimmers_out)} swimmers -> docs/data/", file=sys.stderr)


if __name__ == "__main__":
    build()
