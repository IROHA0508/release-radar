# 릴리스 레이더

**사이트: https://release-radar-ten.vercel.app**

ChatGPT(OpenAI), Claude(Anthropic), Gemini(Google)의 공식 발표를 뉴스별로 한국어로 요약하는 정적 웹사이트입니다. 소식마다 핵심 수치, 성능 그래프, 모델 사양, 활용 팁, 추천 프롬프트, 공식 출처를 정리하고, 세 회사의 프롬프트 가이드와 API 가격표를 함께 제공합니다.

## 구조

```
index.html              화면 전체(HTML·CSS·JS 한 파일, 빌드 없음)
data/manifest.json      사이트에 보여 줄 소식 id 목록과 마지막 확인 날짜
data/news/<id>.json     소식 한 건 = 파일 한 개
data/guides.json        프롬프트 가이드 탭 내용
docs/DATA_SCHEMA.md     데이터 형식 설명
scripts/validate_data.py  커밋 전 데이터 검증
vercel.json             Vercel 설정 (데이터 캐시 끄기, 깔끔한 URL)
backend/                새 소식 감지·요약·반영 Python 코드 (GitHub Actions에서 실행)
tests/                  backend 오프라인 테스트
.github/workflows/      매일 실행하는 GitHub Actions 워크플로
.vercelignore           배포에서 backend·tests 등 제외
```

## 로컬에서 보기

```bash
python3 -m http.server 8000
# 브라우저에서 http://localhost:8000
```

`index.html`을 파일로 바로 열면 브라우저 보안 정책 때문에 `data/`를 읽지 못하니 위처럼 로컬 서버로 여세요.

## Vercel 배포

1. https://vercel.com 에 GitHub 계정으로 로그인합니다(Hobby 플랜 무료).
2. **Add New → Project**에서 이 저장소(`release-radar`)를 **Import**합니다.
3. Framework Preset은 **Other**, Build Command와 Output Directory는 비워 둡니다.
4. **Deploy**를 누르면 공개 주소(Production 도메인)가 생깁니다. 이 저장소는 https://release-radar-ten.vercel.app 으로 배포되어 있습니다. 프로젝트 Settings → Domains에서 이름을 바꾸거나 개인 도메인을 연결할 수 있습니다.

> 배포마다 생기는 `release-radar-<해시>-<팀>.vercel.app` 주소는 Vercel 보호 설정 때문에 로그인한 본인만 볼 수 있습니다. 공유할 때는 위 Production 도메인을 쓰세요.

이후 `main` 브랜치에 커밋이 올라올 때마다 Vercel이 자동으로 다시 배포합니다.

## 자동 업데이트 (Python 백엔드)

`backend/`의 Python 코드가 GitHub Actions에서 매일 아침(한국 시간 8시 17분) 실행됩니다. 사이트는 정적 파일이라 서버가 따로 없고, 이 작업이 `data/`를 고쳐 커밋하면 Vercel이 자동으로 다시 배포합니다.

```
감지  OpenAI RSS, Google Gemini 블로그 RSS, Google DeepMind RSS, Anthropic 뉴스룸 페이지
  ↓   사이트에 이미 있는 출처 URL·이전 실행 기록과 비교, 최근 7일 이내 + 모델 관련 글만 후보
분류  Claude API(작은 모델)가 후보 중 '모델 소식'만 고름 (고객 사례·정책 글 등 제외)
읽기  원문 페이지 본문, 표(셀 그대로), 링크 추출. 막히면 r.jina.ai 리더로 재시도
작성  Claude API가 data/news/<id>.json 형식으로 한국어 요약·팁·프롬프트·그래프 작성
검사  그래프 값, 핵심 수치, 모델 ID, 가격을 원문과 프로그램으로 대조해 원문에 없는 값은 삭제
반영  manifest 갱신 → scripts/validate_data.py 통과 시에만 저장 → 커밋·푸시 → Vercel 배포
```

| 파일 | 역할 |
|---|---|
| `backend/feeds.py` | 소스 수집(RSS·뉴스룸 HTML) |
| `backend/detect.py` | 새 글 판정, 같은 글 중복 제거, 실행 기록(`backend/state/seen.json`) |
| `backend/extract.py` | 원문 본문·표·링크·발표일 추출 |
| `backend/summarize.py` | Claude API 호출(분류, 기사 작성) |
| `backend/guard.py` | 원문 대조로 지어낸 수치 제거 |
| `backend/store.py` | 파일·manifest 저장과 검증 |
| `backend/pipeline.py` | 전체 흐름, 실행 보고서(`backend/state/last-run.json`) |
| `.github/workflows/update-news.yml` | 매일 실행, 코드가 바뀌면 테스트와 소스 자가 시험 |

### 처음 한 번 설정

1. Anthropic Console(https://console.anthropic.com)에서 API 키를 만듭니다.
2. GitHub 저장소 **Settings → Secrets and variables → Actions → New repository secret**에서 이름 `ANTHROPIC_API_KEY`로 키를 저장합니다.
3. (선택) 같은 화면의 **Variables** 탭에서 `RR_MODEL`(기사 작성 모델, 기본 `claude-sonnet-5-5`), `RR_TRIAGE_MODEL`(분류 모델, 기본 `claude-haiku-4-5-20251001`)을 바꿀 수 있습니다.

키가 없으면 감지만 하고 후보 목록을 `backend/state/pending.json`에 남깁니다. 기사 작성 비용은 기본 모델 기준 소식 1건당 약 0.1달러(입력 2~3만, 출력 5천 토큰 안팎)이고, 실행당 최대 5건으로 제한합니다(`RR_MAX_ITEMS`).

### 직접 실행

```bash
pip install -r backend/requirements.txt
python -m backend detect     # 새 글 후보만 출력 (파일 변경 없음, API 키 불필요)
python -m backend selftest   # 회사마다 가장 최근 소식을 지웠다고 가정하고 다시 찾는지 확인
ANTHROPIC_API_KEY=... python -m backend update   # 실제 갱신
python -m pytest tests -q    # 오프라인 테스트
```

GitHub **Actions → 새 소식 자동 업데이트 → Run workflow**에서 `update`/`detect`/`selftest`를 골라 바로 실행할 수도 있습니다. 실행 결과는 run 페이지의 알림(annotation)과 `backend/state/last-run.json`에 남습니다.

## 소식 직접 추가하기

1. `data/news/<id>.json`을 [데이터 형식](docs/DATA_SCHEMA.md)대로 작성합니다.
2. `data/manifest.json`의 `news` 배열에 id를 추가합니다.
3. `python3 scripts/validate_data.py`로 검증한 뒤 커밋합니다.

## 참고

비공식 요약입니다. 수치와 가격은 각 사 공식 발표 시점 기준이며, 정확한 내용은 각 소식의 출처 링크를 확인하세요. 성능 그래프는 원문 이미지를 복제하지 않고, 공식 발표에 공개된 수치로 직접 그린 것입니다.
