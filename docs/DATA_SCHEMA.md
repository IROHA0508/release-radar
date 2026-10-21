# 데이터 형식

사이트는 빌드 없이 `index.html`이 `data/` 폴더의 JSON을 읽어 화면을 그립니다. 새 소식은 JSON 파일 하나를 추가하고 `manifest.json`에 id를 넣으면 나타납니다.

## data/manifest.json

```json
{
  "lastChecked": "2026-10-03 06:02",
  "news": ["gemini-4-argon", "gpt-6-1-sol"]
}
```

- `lastChecked`: 마지막으로 공식 소스를 확인한 시각 `YYYY-MM-DD HH:MM`(Asia/Seoul). 상단 "Update"에 표시되고, 날짜 부분이 NEW 배지(7일 이내)의 기준입니다. 날짜만 있는 `YYYY-MM-DD`도 허용합니다.
- `news`: 사이트에 보여 줄 소식 id 목록. 순서와 관계없이 화면에서는 날짜 역순으로 정렬됩니다.

## data/news/&lt;id&gt;.json

| 필드 | 형식 | 설명 |
|---|---|---|
| `id` | 문자열 | 파일 이름과 같음. 소문자·숫자·하이픈만. `guide`, `prices`는 예약어 |
| `company` | `openai` \| `anthropic` \| `google` | 발표한 회사 |
| `date` | `YYYY-MM-DD` | 공식 발표일 |
| `kind` | `모델 출시` \| `모델 업데이트` \| `활용 팁` | 소식 종류. 화면의 종류 필터와 같음. 새 모델 출시·발표는 `모델 출시`, 기존 모델의 기능·가격·가용성 변경과 지원 종료는 `모델 업데이트`, 공식 사용 가이드·프롬프트 팁은 `활용 팁` |
| `title`, `headline`, `tldr` | 문자열 | 제목, 한 줄 헤드라인, 2~3문장 요약 |
| `models` | 배열 | `{name, apiId, input, output, cached}` — 가격은 1M 토큰당 USD 문자열, 모르면 `null` |
| `numbers` | 배열 | `{label, value, note}` 핵심 수치 3~4개 |
| `chartSource` | 문자열(선택) | 그래프 수치의 출처 설명 |
| `charts` | 배열(선택) | 성능 그래프, 아래 참고 |
| `chartNote` | 문자열(선택) | 그래프를 만들 수 없을 때 보여 줄 안내 |
| `changes`, `availability`, `cautions` | 문자열 배열 | 바뀐 점, 사용처, 주의점 |
| `tips` | 배열 | `{title, body}` 활용 팁 |
| `prompts` | 배열 | `{title, when, type: "prompt" \| "code", text}` 추천 프롬프트 |
| `sources` | 배열 | `{title, url}` 공식 출처 |

### charts 항목

```json
{
  "title": "Terminal-Bench 4.0",
  "desc": "터미널 기반 에이전트 코딩",
  "type": "bar",
  "unit": "%",
  "lowerIsBetter": false,
  "source": "Google",
  "note": "선택: 그래프 아래 각주",
  "keepOrder": false,
  "rows": [
    { "label": "Gemini 4 Argon", "value": 57.4, "highlight": true },
    { "label": "Claude Opus 5.5", "value": 66.4 }
  ]
}
```

- `type`: `bar`(0에서 시작하는 막대) 또는 `dot`(Elo처럼 0이 의미 없는 점수)
- `unit`: `%`, `$`, `×`, `Elo`, 또는 빈 문자열
- `highlight`: 이 소식의 주인공 모델. 회사 색으로 칠해지고 나머지는 회색
- `display`: 값 대신 보여 줄 문자열(예: `"×8.9 이상"`)
- `keepOrder`: `true`면 입력 순서 유지, 아니면 성능 좋은 순으로 정렬
- 수치는 반드시 공식 발표의 텍스트·표·차트 대체 텍스트에 있는 값만 씁니다. 그래프가 이미지로만 공개된 경우 `charts`를 비우고 `chartNote`에 이유를 적습니다.

검증: `python3 scripts/validate_data.py`

## data/guides.json (프롬프트 가이드 탭)

```json
{
  "updatedAt": "2026-10-21",
  "checkedAt": "2026-10-21 06:05",
  "common": [{ "title": "...", "body": "..." }],
  "vendors": [{
    "company": "openai", "name": "OpenAI · GPT", "summary": "...",
    "methods": [{
      "id": "openai-completion-criteria", "category": "기본 작성법",
      "title": "...", "body": "...", "before": "(선택)", "after": "(선택)", "code": "(선택)",
      "models": ["GPT-6 Astra"], "source": { "title": "...", "url": "https://..." },
      "newsId": "(선택) 이 방법이 나온 활용 팁 소식", "addedAt": "(자동) YYYY-MM-DD", "updatedAt": "(자동)"
    }],
    "templates": [{ "title": "...", "when": "...", "text": "...", "source": { "title": "...", "url": "https://..." } }],
    "watch": [{ "title": "...", "url": "https://...", "hash": "(자동)", "checkedAt": "(자동)", "changedAt": "(자동)" }]
  }],
  "structure": {
    "title": "태그·구분자는 웹 앱에서도 쓸 수 있나요?", "answer": "...",
    "rows": [{ "company": "openai", "recommended": "...", "inApp": "...", "saveIn": "...", "sources": [{ "title": "...", "url": "https://..." }] }],
    "notes": ["..."], "example": { "title": "...", "when": "...", "text": "..." }
  },
  "appFeatures": {
    "title": "태그 말고 앱에 있는 기능들: 세 앱 대응표", "intro": "...", "checkedAt": "(자동)", "updatedAt": "(자동)",
    "rows": [{
      "key": "memory", "label": "지난 대화 기억", "what": "...",
      "cells": {
        "openai": { "name": "메모리", "note": "...", "sources": [{ "title": "...", "url": "https://..." }],
                    "methodId": "openai-memory", "updatedAt": "(자동)" },
        "anthropic": { "...": "..." }, "google": { "...": "..." }
      }
    }],
    "notes": ["..."]
  }
}
```

- `category`: `기본 작성법`, `구조와 형식`, `앱 기능과 설정`, `예시 활용`, `추론과 effort`, `긴 문서와 자료`, `에이전트와 코딩`, `도구와 API 설정`, `이미지·영상·음성` 중 하나
- `watch`: 매일 내용을 확인하는 공식 프롬프트 가이드 페이지. 본문이 바뀌면 Claude가 새 권고만 골라 `methods`에 추가하거나 고칩니다.
- `structure`: '공통 원칙' 탭의 '태그·구분자는 웹 앱에서도 쓸 수 있나요?' 회사별 비교표.
- `appFeatures`: '공통 원칙' 탭의 앱 기능 대응표(지시 저장, 프로젝트·노트북, 메모리, 캔버스·아티팩트, 딥 리서치, 예약 작업). 줄마다 `cells`에 세 회사 칸이 모두 있어야 하고, 칸마다 공식 도움말 `sources`가 필요합니다. `methodId`가 있으면 '방법 보기'로 그 회사 탭의 방법 카드로 이동합니다. 칸의 근거 페이지가 `watch`에 있고 본문이 바뀌면, Claude가 그 칸이 아직 맞는지 다시 확인해 고칩니다(고친 칸의 숫자는 모두 원문에 있어야 반영).
- `addedAt`이 14일 이내인 방법은 화면에 NEW로 표시됩니다.
- `before`는 흔한 덜 좋은 요청(사이트가 쓴 예), `after`는 개선한 요청입니다. `exampleFromSource: true`는 `after`가 원문 예시를 옮긴 것이라는 뜻이며 화면에 '원문 예시'로 표시됩니다. `before`에는 적용되지 않습니다.

## data/prices.json (API 가격표 탭)

```json
{
  "checkedAt": "2026-10-21 06:05",
  "pages": { "openai": { "url": "https://...", "checkedAt": "2026-10-21 06:05", "result": "확인" } },
  "models": [{
    "company": "openai", "name": "GPT-6.1 Sol", "apiId": "gpt-6.1-sol",
    "input": "$2", "cached": "$0.10", "output": "$10", "note": "",
    "status": "available", "newsId": "gpt-6-1-sol", "verifiedAt": "2026-10-21", "missing": 0, "since": "2026-10-21"
  }]
}
```

- `status`: `available`(표에 표시), `deprecated`(표에 '지원 종료 예정'으로 표시), `unlisted`(공식 가격 페이지에 없음 → 아래 별도 목록)
- 가격은 기본 등급 텍스트 토큰, 100만 토큰당 USD. 공식 가격 페이지 문구 그대로 씁니다.
- 매일 한 번 공식 가격 페이지를 읽어 확인합니다. 가격 페이지에서 두 번 연속 보이지 않는 모델은 `unlisted`가 됩니다.

## data/tech.json (AI 활용 기술 탭 · AI 활용 LAB 탭)

학습 경로(`group: "path"`)와 최신 활용 기술(`group: "radar"`)을 한 파일에 담고, 화면에서는 두 탭으로 나눠 보여 줍니다.

| 탭 | group | 목록 | 상세 |
|---|---|---|---|
| AI 활용 기술 | `radar` | `#tech` | `#tech/<id>` |
| AI 활용 LAB | `path` | `#lab` | `#lab/<id>` |

```json
{
  "updatedAt": "2026-10-21",
  "groups": [{ "key": "path", "title": "학습 경로", "en": "learning path", "intro": "탭 맨 위 소개 문장", "desc": "목록 제목 아래 설명" }],
  "items": [{
    "id": "tool-use", "group": "path", "order": 3,
    "name": "도구 호출", "en": "Tool use · Function calling", "level": "기초",
    "definition": "정의 (필수)", "why": "왜 필요한가 (필수)",
    "how": ["어떻게 활용하나 (필수)"], "effects": ["기대 효과 (필수)"],
    "example": { "title": "...", "type": "code", "text": "..." },
    "limits": ["한계와 주의점"],
    "prerequisites": ["llm-api"], "related": ["agent-loop"],
    "sources": [{ "title": "...", "url": "https://..." }],
    "news": ["gemini-3-5-flash-developer-guide"],
    "verifiedAt": "2026-10-21"
  }]
}
```

- `group`: `path`(학습 경로, `order` 정수 필수·중복 금지) 또는 `radar`(최신 활용 기술)
- `level`: `기초`, `중급`, `심화`
- `example.type`: `code`(코드, 가로 스크롤), `prompt`(프롬프트), `scene`(구성 예시)
- `prerequisites`, `related`: 같은 파일의 다른 기술 id. 화면에서 링크로 표시됩니다.
- `news`: 이 기술을 다룬 사이트 소식 id. radar 항목은 이 소식 날짜로 '최근 언급'을 계산합니다.
- `sources`: 공식 출처 1개 이상 필수(https).
- radar 항목 전용: `status`(`관찰`·`시도`·`랩`·`보관`), `companies`(이 기술을 다룬 회사), `status`가 `랩`이면 `lab`에 학습 경로 항목 id
- radar 항목 중 `관찰` 단계이면서 두 회사 이상이 다루거나 근거 소식이 3건 이상이면 화면에 '시도 추천'이 붙습니다(지침 9.1).
- `groups`에는 `path`와 `radar`가 하나씩 있어야 하고, 각각 `title`과 `intro`가 필요합니다.
- `tech`, `lab`은 소식 id 예약어입니다.
