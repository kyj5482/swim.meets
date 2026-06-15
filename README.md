# 🏊 swim.meets

관심 선수를 등록해 두면, 대회마다 **Psych Sheet(Meet Program)** 와 **Timeline(Session Report)** PDF만 올려도
그 선수의 **Event · Heat · Lane · 시드기록 · 예상 출발시각 · 급별 표준기록 통과여부**를 추출하고,
**MeetMobile 처럼 HTML로 조회**할 수 있는 GitHub 기반 서비스입니다.
대회를 거듭할수록 종목별 **기록 진척도(과거 대비 향상폭)** 도 자동으로 쌓입니다.

---

## 무엇을 해주나요?

1. **관심 선수만 추출** — 수천 명이 출전한 psych sheet에서 등록한 선수만 골라냅니다.
   동명이인 정확도를 위해 **성(Last) + 이름(First)** 을 기본으로, **나이 · 팀**으로 가중 매칭합니다.
2. **대회별 JSON 기록** — 대회마다 `data/<대회슬러그>.json` 으로 결과를 남깁니다.
3. **HTML 조회** — `docs/` 의 정적 사이트(GitHub Pages)에서 대회별 / 선수별로 봅니다.
4. **표준기록 비교** — psych sheet 헤더에 인쇄된 급별 cut time(예: `&JAG`, `BB`)을 자동 추출해
   선수 기록이 어느 기준을 통과했는지, 못 미치면 몇 초 부족한지 보여줍니다.
5. **진척도 추적** — 여러 대회에 걸쳐 종목별 최고기록과 직전/최초 대비 향상폭을 계산합니다
   (myswimio Best Times 스타일). 선수에 `swimmerid` 를 넣으면 myswimio 링크도 연결됩니다.

---

## 빠른 시작

### 1) 관심 선수 등록 — `swimmers.json`

```json
{
  "swimmers": [
    {
      "id": "mu-maggie",
      "last": "Mu",
      "first": "Maggie",
      "age": 15,
      "teams": ["NOVA-CA"],
      "aliases": [{ "last": "Mu", "first": "Margaret" }],
      "swimmerid": 1045380
    }
  ]
}
```

- `last`/`first` 는 **반드시** 일치해야 매칭됩니다(애칭·미들이니셜은 접두 일치 허용; 전혀 다른 풀네임은 `aliases`로).
- `age` 는 ±1 까지 허용하고 2살 이상 차이는 감점하여 동명이인을 걸러냅니다.
- `teams` 가 일치하면 가점, 달라도 약한 감점(전학·`UN-` 무소속 출전 고려).

### 2) 대회 PDF 업로드 — `input/<대회명>/`

```
input/
└── 2026 SCS June AG Invite/
    ├── JAG26 Meet Program.pdf   ← Psych Sheet / Meet Program
    └── JAG26 Timeline.pdf       ← Timeline / Session Report
```

- 폴더 이름이 곧 대회명이 됩니다.
- 파일은 이름/내용으로 **psych sheet** 와 **timeline** 을 자동 구분합니다
  (파일명에 `program/psych/sheet` → psych, `timeline/session` → timeline; 못 찾으면 내용으로 판별).
- timeline 은 선택입니다. 있으면 이벤트별 **예상 출발시각**이 함께 채워집니다.

### 3) push → 자동 처리

`.github/workflows/process-meets.yml` 이 push를 감지해
`scripts/process_meet.py` → `scripts/build_index.py` 를 실행하고,
생성된 `data/*.json`, `docs/data/*.json` 을 커밋합니다. `main` 브랜치면 GitHub Pages로 배포합니다.

### 로컬에서 실행

```bash
pip install -r requirements.txt
python scripts/process_meet.py            # input/ 의 모든 대회 처리
python scripts/process_meet.py "input/2026 SCS June AG Invite"   # 특정 대회만
python scripts/build_index.py             # 사이트 인덱스/진척도 생성

# 사이트 미리보기
python -m http.server -d docs 8000        # http://localhost:8000
```

---

## 구조

```
swim.meets/
├── swimmers.json              # 관심 선수 등록
├── input/<대회명>/*.pdf        # 업로드한 psych sheet / timeline
├── data/<슬러그>.json          # 대회별 추출 결과(원본 기록)
├── standards/*.json           # (선택) 외부 표준기록표
├── scripts/
│   ├── parse_psych_sheet.py   # Meet Program PDF → 이벤트/조/레인/선수/표준기록 (좌표 기반)
│   ├── parse_timeline.py      # Session Report PDF → 이벤트별 시작시각 (텍스트, 안되면 OCR)
│   ├── common.py              # 시간 변환·선수 매칭·표준기록 평가
│   ├── process_meet.py        # 대회 폴더 처리 오케스트레이터
│   └── build_index.py         # 사이트 인덱스 + 선수 진척도 생성
└── docs/                      # GitHub Pages 정적 사이트
    ├── index.html, assets/    # MeetMobile 스타일 뷰어 (대회별 / 선수별)
    └── data/                  # 사이트가 읽는 JSON (자동 생성)
```

### PDF 파싱이 정확한 이유

HY-TEK Meet Manager 프로그램은 한 페이지가 **2단 컬럼**으로 흐릅니다.
단순 텍스트 추출은 컬럼이 섞여 부정확하므로, 이 파서는 **단어 좌표(x,y)** 를 이용해
빈 세로 여백으로 좌/우 컬럼을 가르고, 같은 행을 재구성한 뒤
`Lane / Name / Age / Team / Seed Time / Flag` 컬럼을 의미 기반으로 해석합니다.
이벤트 헤더 아래에 인쇄된 급별 기준기록(`13-14 &JAG 2:26.30` 등)도 함께 추출합니다.

> 검증: 실제 `2026 SCS June AG Invite` 프로그램(75p)에서 76개 이벤트 · 5,696 엔트리를
> 추출했으며 개별 종목 엔트리의 나이/시드기록 누락 0건을 확인했습니다.

### Timeline OCR

일부 타임라인 PDF는 글자가 **벡터 도형**으로 그려져 텍스트 추출이 안 됩니다.
이 경우 `pytesseract`(+ 시스템 `tesseract-ocr`)가 설치되어 있으면 OCR로 보완하고,
없으면 타임라인 없이 진행합니다(출발시각만 비게 됩니다). CI에서는 `tesseract-ocr` 를 자동 설치합니다.

---

## GitHub Pages 켜기

1. 저장소 **Settings → Pages → Build and deployment → Source: GitHub Actions** 선택.
2. `main` 브랜치에 push 하면 워크플로가 `docs/` 를 배포합니다.
3. 사이트 주소: `https://<사용자명>.github.io/swim.meets/`

---

## 진척도 / 표준기록 비교

- **종목별 최고기록**과 대회마다의 **직전 대비 / 최초 대비** 향상폭(초)을 자동 계산합니다.
- 각 기록 옆에 그 대회의 급별 기준(`&JAG`, `BB` 등) 통과여부를 칩으로 표시합니다.
- 더 일반적인 표준기록표(예: USA Swimming Motivational Times, Sectionals/Futures cut 등)를
  비교하려면 `standards/<이름>.json` 에 넣어 확장할 수 있습니다(향후 종목·연령·코스 매핑 추가 예정).
- `swimmers.json` 의 `swimmerid` 로 myswimio Best Times 페이지를 바로 링크합니다.
