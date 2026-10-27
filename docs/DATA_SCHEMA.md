# 데이터 형식

사이트는 빌드 없이 `index.html`이 `data/` 폴더의 JSON을 읽어 화면을 그립니다. 새 소식은 JSON 파일 하나를 추가하고 `manifest.json`에 id를 넣으면 나타납니다.

## data/manifest.json

```json
{
  "lastChecked": "2026-10-03 06:02",
  "news": ["gemini-4-argon", "gpt-6-1-sol"]
}
```

- `lastChecked`: 마지막으로 공식 소스를 확인한 시각 `YYYY-MM-DD HH:MM`(Asia/Seoul). 상단 "Update"에 표시되고 날짜 부분이 NEW 배지(7일 이내)의 기준입니다. 날짜만 있는 `YYYY-MM-DD`도 허용합니다.
- `news`: 사이트에 보여 줄 소식 id 목록. 순서와 관계없이 화면에서는 날짜 역순으로 정렬됩니다.

## data/news/&lt;id&gt;.json

| 필드 | 형식 | 설명 |
|---|---|---|
| `id` | 문자열 | 파일 이름과 같음. 소문자·숫자·하이픈만. `guide`, `prices`, `models`, `tech`, `lab`, `glossary`는 예약어 |
| `company` | `openai` \| `anthropic` \| `google` | 발표한 회사 |
| `date` | `YYYY-MM-DD` | 공식 발표일 |
| `kind` | `모델 출시` \| `모델 업데이트` \| `제품·기능 출시` \| `활용 팁` | 소식 종류. 화면의 종류 필터와 같음. 새 모델 출시·발표는 `모델 출시`, 기존 모델의 기능·가격·가용성 변경과 지원 종료는 `모델 업데이트`, ChatGPT·Codex·Claude·Claude Code·Gemini 앱·Gemini CLI 같은 공식 AI 제품과 개발자 도구의 새 앱·기능은 `제품·기능 출시`, 공식 사용 가이드·프롬프트 팁은 `활용 팁` |
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
- `appFeatures`: '공통 원칙' 탭의 앱 기능 대응표(지시 저장, 프로젝트·노트북, 메모리, 캔버스·아티팩트, 딥 리서치, 예약 작업). 줄마다 `cells`에 세 회사 칸이 모두 있어야 하고 칸마다 공식 도움말 `sources`가 필요합니다. `methodId`가 있으면 '방법 보기'로 그 회사 탭의 방법 카드로 이동합니다. 칸의 근거 페이지가 `watch`에 있고 본문이 바뀌면, Claude가 그 칸이 아직 맞는지 다시 확인해 고칩니다(고친 칸의 숫자는 모두 원문에 있어야 반영).
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

학습 경로(`group: "path"`)와 최신 활용 기술(`group: "radar"`)을 한 파일에 담고 화면에서는 두 탭으로 나눠 보여 줍니다.

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
- `news`: 이 기술을 다룬 사이트 소식 id(관련 소식 링크).
- `sources`: 공식 출처 1개 이상 필수(https).
- radar 항목 전용: `date`(공식적으로 처음 소개된 날, `YYYY-MM-DD`, 2025-01-01 이후 필수), `dateNote`(선택, 날짜에 대한 안내), `status`(`관찰`·`시도`·`랩`·`보관`), `companies`(이 기술을 다룬 회사), `status`가 `랩`이면 `lab`에 학습 경로 항목 id
- radar 목록은 `date` 최신순으로 보여 주고 화면의 기간 선택(연도·월)도 `date` 기준입니다.
- radar 항목 중 `관찰` 단계이면서 두 회사 이상이 다루거나 근거 소식이 3건 이상이면 화면에 '시도 추천'이 붙습니다(지침 9.1).
- `groups`에는 `path`와 `radar`가 하나씩 있어야 하고 각각 `title`과 `intro`가 필요합니다.
- `tech`, `lab`은 소식 id 예약어입니다.
- 자동 업데이트가 활용 팁·제품·기능 출시 소식을 추가하면 관련 기술의 `news`에 id를 넣습니다(radar 항목은 `companies`에 회사도 추가). 목록에 없는 새 기술 이름은 `backend/state/tech-candidates.json`에만 쌓이고 사람이 공식 출처를 확인한 뒤 항목으로 만듭니다.

## data/glossary.json (용어집 탭)

```json
{
  "updatedAt": "2026-10-22",
  "intro": "탭 맨 위 소개 문장",
  "groups": ["기본 개념", "프롬프트"],
  "terms": [{
    "id": "token", "term": "토큰", "en": "Token", "group": "기본 개념",
    "short": "한 줄 정의 (필수)", "body": "조금 더 설명 (선택)",
    "related": ["llm-api"],
    "sources": [{ "title": "...", "url": "https://..." }]
  }]
}
```

- `group`은 `groups` 중 하나. 화면은 `groups` 순서대로 묶어 보여 줍니다.
- `related`는 `data/tech.json`의 기술 id. 기술 페이지에 '관련 용어'로 거꾸로도 표시됩니다.
- 정의는 공식 문서(`sources`, 1개 이상 필수)를 바탕으로 씁니다. 화면 주소는 `#glossary`, 용어 하나는 `#glossary/<id>`.

## data/models.json (모델 추천 탭)

상황별로 어떤 모델을 어느 노력 단계(effort)로 쓰면 좋은지 세 회사 공식 문서를 근거로 정리합니다. 화면 주소는 `#models`.

```json
{
  "verifiedAt": "2026-10-27",
  "intro": "탭 맨 위 소개 문장",
  "params": { "openai": "reasoning.effort", "anthropic": "output_config.effort", "google": "thinking_level" },
  "models": [{
    "company": "openai", "name": "GPT-6.1 Sol", "apiId": "gpt-6.1-sol", "tier": "성능·비용 균형",
    "summary": "공식 설명", "efforts": ["low", "medium", "high", "xhigh", "max"], "default": "medium",
    "defaultNote": "(default가 null일 때 필수) 공식 문서에 명시 없음",
    "start": "시작 권장", "sources": [{ "title": "...", "url": "https://..." }]
  }],
  "situations": [{
    "id": "bulk", "title": "대량·반복 단순 작업", "examples": "분류, 필드 추출",
    "picks": {
      "openai": { "model": "gpt-6-luna", "effort": "low", "raise": ["medium"], "note": "...", "sources": [{ "title": "...", "url": "https://..." }] },
      "anthropic": { "name": "목록 밖 모델·에이전트 이름", "apiId": "(선택)", "note": "...", "sources": [] },
      "google": { "missing": "공식 안내를 찾지 못한 이유(확인 필요)" }
    }
  }],
  "levels": [{ "key": "none", "openai": "설명", "anthropic": null, "google": null }],
  "levelSources": [{ "title": "...", "url": "https://..." }],
  "principles": [{ "title": "...", "body": "...", "sources": [{ "title": "...", "url": "https://..." }] }],
  "notes": ["..."], "noteSources": [{ "title": "...", "url": "https://..." }]
}
```

- 노력 단계 값은 `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max` 중에서 씁니다. 화면도 이 순서로 그립니다. 값의 이름과 뜻은 회사마다 달라 `levels`에 회사별 설명을 둡니다(`null`은 그 회사에 없는 값).
- `models[].efforts`는 API가 받는 값만, `default`는 API 기본값입니다. 앱 기본값이 다르면 `notes`에 적습니다.
- `situations[].picks`에는 세 회사 칸이 모두 있어야 합니다. 칸은 셋 중 하나입니다.
  - `model`: `models`의 apiId. `effort`(시작 단계)와 `raise`(결과가 부족하면 올릴 단계)는 그 모델의 `efforts` 안에서 고릅니다.
  - `name`: 노력 단계로 고르지 않는 별도 모델·에이전트(예: Gemini Deep Research).
  - `missing`: 공식 안내를 찾지 못한 칸. 추측으로 채우지 않습니다.
- 가격은 넣지 않습니다. 화면이 `data/prices.json`에서 같은 apiId의 가격·상태·관련 소식을 가져오고 `deprecated`·`unlisted`면 배지를 붙입니다(가격표에 없는 apiId는 검증에서 경고만 냅니다).
- `verifiedAt`에서 30일이 지나거나 그 뒤 가격표에 새 텍스트 모델(`since`가 더 늦은 모델, 이미지·음성·임베딩 제외)이 올라오면 화면 위에 알림이 뜹니다.
- 자동 업데이트는 이 파일을 고치지 않습니다. 새 모델 소식이 오면 사람이 공식 문서를 확인해 고치고 `verifiedAt`을 바꿉니다.

## 문체

`data/` 아래 글은 im-not-ai의 'AI 티' 규칙을 따릅니다. 규칙과 적용 범위는 `.claude/skills/humanize-korean-site/SKILL.md`, 점검은 `python3 scripts/style_check.py --spans`.
