# 데이터 형식

사이트는 빌드 없이 `index.html`이 `data/` 폴더의 JSON을 읽어 화면을 그립니다. 새 소식은 JSON 파일 하나를 추가하고 `manifest.json`에 id를 넣으면 나타납니다.

## data/manifest.json

```json
{
  "lastChecked": "2026-10-02",
  "news": ["gemini-4-argon", "gpt-6-1-sol"]
}
```

- `lastChecked`: 마지막으로 공식 소스를 확인한 날짜(Asia/Seoul). 상단 "마지막 확인"과 NEW 배지(7일 이내)의 기준입니다.
- `news`: 사이트에 보여 줄 소식 id 목록. 순서와 관계없이 화면에서는 날짜 역순으로 정렬됩니다.

## data/news/&lt;id&gt;.json

| 필드 | 형식 | 설명 |
|---|---|---|
| `id` | 문자열 | 파일 이름과 같음. 소문자·숫자·하이픈만. `guide`, `prices`는 예약어 |
| `company` | `openai` \| `anthropic` \| `google` | 발표한 회사 |
| `date` | `YYYY-MM-DD` | 공식 발표일 |
| `kind` | `모델 출시` \| `모델 업데이트` \| `모델 발표` \| `활용 팁` | 소식 종류 |
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
