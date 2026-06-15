"""공통 유틸: 기록 시간 파싱/포맷, 선수 매칭, 표준기록 평가, 슬러그."""

from __future__ import annotations

import re
import unicodedata
from typing import Optional


# ---------------------------------------------------------------------------
# 시간(기록) 유틸
# ---------------------------------------------------------------------------

_TIME_NUM_RE = re.compile(r"^X?(?:(\d+):)?(\d{1,2})\.(\d{2})$")


def time_to_seconds(t: Optional[str]) -> Optional[float]:
    """수영 기록 문자열을 초(float)로 변환. 'NT','DQ' 등은 None.

    예: '2:10.44' -> 130.44, '58.12' -> 58.12, 'X1:00.00' -> 60.0
    """
    if not t:
        return None
    t = t.strip()
    if t.upper() in ("NT", "NS", "DQ", "SCR", "DFS", ""):
        return None
    m = _TIME_NUM_RE.match(t)
    if not m:
        return None
    minutes = int(m.group(1)) if m.group(1) else 0
    seconds = int(m.group(2))
    hundredths = int(m.group(3))
    return minutes * 60 + seconds + hundredths / 100.0


def seconds_to_time(s: Optional[float]) -> Optional[str]:
    """초(float)를 수영 기록 문자열로 변환. 130.44 -> '2:10.44'."""
    if s is None:
        return None
    s = round(s, 2)
    minutes = int(s // 60)
    rem = s - minutes * 60
    if minutes:
        return f"{minutes}:{rem:05.2f}"
    return f"{rem:.2f}"


# ---------------------------------------------------------------------------
# 슬러그 / 정규화
# ---------------------------------------------------------------------------


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text or "meet"


def _norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z]", "", s.lower())


def _norm_team(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r"[^a-z0-9]", "", s.lower())


def normalize_gender(s: Optional[str]) -> Optional[str]:
    """다양한 성별 표기를 'M' / 'F' 로 정규화. 알 수 없으면 None.

    허용: M/F, Boy(s)/Girl(s), Men/Women, Male/Female, B/G, W(여, HY-TEK).
    """
    if not s:
        return None
    c = str(s).strip().lower()
    if not c:
        return None
    if c[0] == "m" or c.startswith(("boy", "male")) or c[0] == "b":
        return "M"
    if c[0] in ("f", "g", "w") or c.startswith(("girl", "women", "female")):
        return "F"
    return None


# ---------------------------------------------------------------------------
# 선수 매칭
# ---------------------------------------------------------------------------


def match_score(swimmer: dict, entry: dict) -> Optional[float]:
    """등록 선수(swimmer)와 psych sheet 엔트리(entry)의 일치 점수.

    성(last)과 이름(first)은 반드시 일치해야 한다(동명이인 정확도 확보).
    나이/팀은 가산점 및 모순 시 감점. 매칭 불가면 None.

    swimmer: {"last","first","age"?,"birth_year"?,"teams"?:[...],
              "aliases"?:[{"last","first"}...], "first_prefix"?:bool}
    entry:   {"last_name","first_name","age","team"}
    """
    cand_names = [(swimmer.get("last", ""), swimmer.get("first", ""))]
    for a in swimmer.get("aliases", []) or []:
        cand_names.append((a.get("last", ""), a.get("first", "")))

    e_last = _norm_name(entry.get("last_name", ""))
    e_first = _norm_name(entry.get("first_name", ""))
    if not e_last or not e_first:
        return None

    best = None
    allow_prefix = swimmer.get("first_prefix", True)
    for s_last, s_first in cand_names:
        nl, nf = _norm_name(s_last), _norm_name(s_first)
        if not nl or not nf:
            continue
        if nl != e_last:
            continue
        # 이름(first): 정확히 일치하거나, 한쪽이 다른쪽의 접두(애칭/미들이니셜 포함)
        if nf == e_first:
            name_score = 1.0
        elif allow_prefix and (e_first.startswith(nf) or nf.startswith(e_first)):
            name_score = 0.8
        else:
            continue
        best = max(best or 0, name_score)

    if best is None:
        return None

    # 성별 평가: 둘 다 알려져 있고 다르면 동명이인이므로 제외(동성 종목 정확도 핵심).
    s_gender = normalize_gender(swimmer.get("gender"))
    e_gender = normalize_gender(entry.get("gender"))
    if s_gender and e_gender and s_gender != e_gender:
        return None

    score = 5.0 + best  # 성+이름 일치 기본 점수
    if s_gender and e_gender and s_gender == e_gender:
        score += 1.0

    # 나이 평가 (대회마다 ±1 변동 가능)
    s_age = swimmer.get("age")
    by = swimmer.get("birth_year")
    e_age = entry.get("age")
    if e_age is not None:
        if s_age is not None:
            diff = abs(int(s_age) - int(e_age))
            if diff == 0:
                score += 2.0
            elif diff == 1:
                score += 1.0
            else:
                score -= 2.0  # 나이 차 2 이상이면 동명이인 가능성 — 감점
        elif by is not None:
            # 출생연도 기반 추정 나이는 대회 시점에 따라 다를 수 있어 약하게 반영
            score += 0.5

    # 팀 평가
    teams = [_norm_team(t) for t in (swimmer.get("teams") or []) if t]
    e_team = _norm_team(entry.get("team"))
    if teams and e_team:
        if any(e_team == t or e_team.startswith(t) or t.startswith(e_team) for t in teams):
            score += 2.0
        else:
            score -= 1.0  # 팀 불일치는 약한 감점 (UN- 소속/전학 가능성)

    return score


MATCH_THRESHOLD = 5.5  # 성+이름 일치(최소 5.8)면 통과, 나이 큰 모순 시 탈락


def best_match(entry: dict, swimmers: list[dict]) -> Optional[tuple[dict, float]]:
    best = None
    for sw in swimmers:
        sc = match_score(sw, entry)
        if sc is None or sc < MATCH_THRESHOLD:
            continue
        if best is None or sc > best[1]:
            best = (sw, sc)
    return best


# ---------------------------------------------------------------------------
# 표준기록(급별 cut) 평가
# ---------------------------------------------------------------------------


def evaluate_standards(seed_time: Optional[str], age: Optional[int], standards: dict) -> list[dict]:
    """선수 기록을 이벤트의 급별 기준기록과 비교.

    standards: {"13-14 &JAG": "2:26.30", ...}
    반환: 각 기준에 대해 achieved 여부와 차이(초). 선수 나이에 해당하는
    기준만 우선 표시하되, 나이대 라벨 매칭이 애매하면 전부 포함한다.
    """
    seed_s = time_to_seconds(seed_time)
    out: list[dict] = []
    for label, t in (standards or {}).items():
        std_s = time_to_seconds(t)
        if std_s is None:
            continue
        applies = _age_label_applies(label, age)
        item = {
            "label": label,
            "time": t,
            "seconds": std_s,
            "applies_to_age": applies,
            "achieved": None,
            "delta_seconds": None,
        }
        if seed_s is not None:
            item["achieved"] = seed_s <= std_s
            item["delta_seconds"] = round(seed_s - std_s, 2)  # 음수면 기준 통과(빠름)
        out.append(item)
    # 나이에 해당하는 기준을 앞쪽으로
    out.sort(key=lambda x: (not x["applies_to_age"], x["seconds"]))
    return out


_AGE_RANGE_RE = re.compile(r"(\d+)\s*[-–]\s*(\d+)")
_AGE_OVER_RE = re.compile(r"(\d+)\s*&\s*(?:O|Over|Up)", re.IGNORECASE)
_AGE_UNDER_RE = re.compile(r"(\d+)\s*&\s*(?:U|Under)", re.IGNORECASE)


def _age_label_applies(label: str, age: Optional[int]) -> bool:
    if age is None:
        return True
    m = _AGE_RANGE_RE.search(label)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return lo <= age <= hi
    m = _AGE_OVER_RE.search(label)
    if m:
        return age >= int(m.group(1))
    m = _AGE_UNDER_RE.search(label)
    if m:
        return age <= int(m.group(1))
    # 나이 표기가 없는 라벨(예: 단일 연령부 이벤트의 'BB')은 항상 적용
    return True
