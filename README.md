# 릴리스 레이더

**사이트: https://release-radar-ten.vercel.app**

ChatGPT(OpenAI), Claude(Anthropic), Gemini(Google)의 공식 발표를 뉴스별로 한국어로 요약하는 정적 웹사이트입니다. 소식마다 핵심 수치, 성능 그래프, 모델 사양, 활용 팁, 추천 프롬프트, 공식 출처를 정리하고, 세 회사의 프롬프트 가이드와 API 가격표, AI를 활용하는 기술(학습 경로와 최신 활용 기술) 정리를 함께 제공합니다.

## 구조

```
index.html              화면 전체(HTML·CSS·JS 한 파일, 빌드 없음)
data/manifest.json      사이트에 보여 줄 소식 id 목록과 마지막 확인 날짜
data/news/<id>.json     소식 한 건 = 파일 한 개
data/guides.json        프롬프트 가이드 탭 내용
data/tech.json          AI 활용 기술 탭 내용 (학습 경로·최신 활용 기술)
docs/DATA_SCHEMA.md     데이터 형식 설명
docs/GUIDELINES.md      프로젝트 지침 (목표·원칙·로드맵)
CLAUDE.md               AI와 작업할 때 먼저 읽는 요약 지침
scripts/validate_data.py  커밋 전 데이터 검증
vercel.json             Vercel 설정 (데이터 캐시 끄기, 깔끔한 URL)
backend/                새 소식 감지·요약·반영 Python 코드 (GitHub Actions에서 실행)
tests/                  backend 오프라인 테스트
.github/workflows/      6시간마다 실행하는 GitHub Actions 워크플로
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

`backend/`의 Python 코드가 GitHub Actions에서 6시간마다(한국 시간 0시·6시·12시·18시) 실행됩니다. GitHub 사정으로 몇 분 늦게 시작할 수 있습니다. 사이트는 정적 파일이라 서버가 따로 없고, 이 작업이 `data/`를 고쳐 커밋하면 Vercel이 자동으로 다시 배포합니다.

```
감지  모델 발표: OpenAI 뉴스 RSS, Anthropic 뉴스룸·사이트맵, Google Gemini 모델 블로그·DeepMind RSS
      활용 팁:   OpenAI 개발자 블로그, Claude 블로그, Google Gemini 앱 블로그·Developers 블로그·Cloud AI 블로그
  ↓   사이트에 이미 있는 출처 URL·이전 실행 기록과 비교, 최근 7일 이내 + 모델·활용 관련 글만 후보
분류  Claude(작은 모델)가 후보 중 모델 출시·모델 업데이트·활용 팁만 고름 (고객 사례·정책·영업 공지 등 제외)
읽기  원문 페이지 본문, 표(셀 그대로), 링크 추출. 막히면 r.jina.ai 리더로 재시도
작성  Claude가 data/news/<id>.json 형식으로 한국어 요약·팁·프롬프트·그래프 작성
검사  그래프 값, 핵심 수치, 모델 ID, 가격을 원문과 프로그램으로 대조해 원문에 없는 값은 삭제
반영  manifest 갱신 → scripts/validate_data.py 통과 시에만 저장 → 커밋·푸시 → Vercel 배포
```

| 파일 | 역할 |
|---|---|
| `backend/config.py` | 감시할 소스 목록(`SOURCES`), 모델·실행 한도 설정 |
| `backend/feeds.py` | 소스 수집(RSS·뉴스룸 HTML) |
| `backend/detect.py` | 새 글 판정, 같은 글 중복 제거, 실행 기록(`backend/state/seen.json`) |
| `backend/extract.py` | 원문 본문·표·링크·발표일 추출 |
| `backend/summarize.py` | Claude 호출(분류, 기사 작성) — 구독 토큰이면 Claude Code CLI, API 키면 Claude API |
| `backend/guard.py` | 원문 대조로 지어낸 수치 제거 |
| `backend/store.py` | 파일·manifest 저장과 검증 |
| `backend/pipeline.py` | 전체 흐름, 실행 보고서(`backend/state/last-run.json`) |
| `.github/workflows/update-news.yml` | 6시간마다 실행, 코드가 바뀌면 테스트와 소스 자가 시험 |

### 처음 한 번 설정

요약을 쓰려면 Claude 인증 정보가 하나 필요합니다. 둘 중 하나만 넣으면 되고, 둘 다 있으면 구독 토큰을 먼저 씁니다.

**방법 A. Claude 구독(Pro·Max) 토큰 — 추가 결제 없음 (권장)**

1. 내 컴퓨터에 Claude Code를 설치합니다(설치 안내: https://code.claude.com/docs/en/setup).
2. 터미널에서 `claude setup-token`을 실행하고 브라우저에서 로그인하면 긴 토큰이 출력됩니다.
3. GitHub 저장소 **Settings → Secrets and variables → Actions → New repository secret**에서 이름 `CLAUDE_CODE_OAUTH_TOKEN`으로 그 토큰을 저장합니다.

이 방식은 워크플로가 Claude Code CLI를 설치해 구독 사용량으로 요약합니다. 사용량은 claude.ai·Claude Code와 같은 한도를 함께 씁니다. 한도를 넘었을 때 돈이 나가지 않게 하려면 claude.ai 설정의 사용량 크레딧(extra usage)을 꺼 두세요. 토큰은 비밀번호처럼 다루고 저장소 파일에는 절대 넣지 마세요.

**방법 B. Claude API 키 — 사용한 만큼 별도 과금**

1. Claude Console(https://platform.claude.com)에서 API 키를 만들고 크레딧을 충전합니다.
2. 같은 화면에서 이름 `ANTHROPIC_API_KEY`로 저장합니다.

기본 모델 기준 소식 1건당 약 0.1달러(입력 2~3만, 출력 5천 토큰 안팎)이며, 구독 요금과는 따로 청구됩니다.

**공통**

- (선택) **Variables** 탭에서 `RR_MODEL`(기사 작성 모델, 기본 `claude-sonnet-5-5`), `RR_TRIAGE_MODEL`(분류 모델, 기본 `claude-haiku-4-5-20251001`)을 바꿀 수 있습니다.
- 인증 정보가 없으면 감지만 하고 후보 목록을 `backend/state/pending.json`에 남깁니다.
- 실행당 최대 5건만 요약합니다(`RR_MAX_ITEMS`).

### 직접 실행

```bash
pip install -r backend/requirements.txt
python -m backend detect     # 새 글 후보만 출력 (파일 변경 없음, API 키 불필요)
python -m backend selftest   # 회사마다 가장 최근 소식을 지웠다고 가정하고 다시 찾는지 확인
python -m backend maintain --force   # API 가격표·프롬프트 가이드 지금 점검 (Claude 인증 필요)
CLAUDE_CODE_OAUTH_TOKEN=... python -m backend update   # 실제 갱신 (구독 사용, claude CLI 필요)
ANTHROPIC_API_KEY=... python -m backend update         # 실제 갱신 (API 과금)
python -m pytest tests -q    # 오프라인 테스트
```

GitHub **Actions → 새 소식 자동 업데이트 → Run workflow**에서 `update`/`detect`/`selftest`를 골라 바로 실행할 수도 있습니다. 실행 결과는 run 페이지의 알림(annotation)과 `backend/state/last-run.json`에 남습니다.

### 하루 한 번 정기 점검 (API 가격표·프롬프트 가이드)

6시간마다 실행할 때, 그날 처음 실행이면 `python -m backend maintain`이 이어서 돌아갑니다.

```
API 가격표    세 회사 공식 가격 페이지를 읽고, 사이트에서 다룬 모델이 실제로 API 가격표에 있는지와 현재 가격을 확인
              → 원문에 있는 값만 반영(data/prices.json), 두 번 연속 안 보이는 모델은 'API 가격표에 없는 모델'로 이동
              → 새 모델 소식이 추가되면 그 회사 가격 페이지는 그날 바로 다시 확인
프롬프트 가이드 회사별 공식 프롬프트 가이드 페이지(guides.json의 watch)를 읽어 본문이 바뀌었으면 새 권고만 추가·수정
              → 새 '활용 팁' 소식이 올라오면 그 글에서 프롬프트 방법을 최대 2개 골라 가이드에 추가
              → 앱 도움말 페이지(메모리·딥 리서치·예약 작업 등)가 바뀌면 '앱 기능 대응표'의 해당 칸도 다시 확인
```

결과는 `backend/state/maintenance-run.json`과 Actions 실행 페이지 알림에 남습니다. Actions에서 `maintain`을 골라 바로 점검할 수도 있습니다.

| 파일 | 역할 |
|---|---|
| `backend/prices.py` | 공식 가격 페이지 대조, `data/prices.json` 갱신 |
| `backend/guides.py` | 공식 가이드 페이지 변경 감지, 활용 팁에서 방법 추출, `data/guides.json` 갱신 |

### 화면 표시

- 상단 **Update**: 마지막으로 공식 소스를 확인한 한국 시간(`data/manifest.json`의 `lastChecked`, `YYYY-MM-DD HH:MM`). 새 소식이 없어도 실행할 때마다 갱신됩니다.
- 필터: 회사(OpenAI·Anthropic·Google)와 종류(모델 출시·모델 업데이트·활용 팁)를 함께 고를 수 있습니다.
- 소식 상세의 공식 출처는 한 줄 요약 바로 아래에 있습니다.

## 소식 직접 추가하기

1. `data/news/<id>.json`을 [데이터 형식](docs/DATA_SCHEMA.md)대로 작성합니다.
2. `data/manifest.json`의 `news` 배열에 id를 추가합니다.
3. `python3 scripts/validate_data.py`로 검증한 뒤 커밋합니다.

## 참고

비공식 요약입니다. 수치와 가격은 각 사 공식 발표 시점 기준이며, 정확한 내용은 각 소식의 출처 링크를 확인하세요. 성능 그래프는 원문 이미지를 복제하지 않고, 공식 발표에 공개된 수치로 직접 그린 것입니다.
