# 릴리스 레이더

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
4. **Deploy**를 누르면 `https://release-radar-<무작위>.vercel.app` 같은 주소가 생깁니다. 프로젝트 Settings → Domains에서 이름을 바꾸거나 개인 도메인을 연결할 수 있습니다.

이후 `main` 브랜치에 커밋이 올라올 때마다 Vercel이 자동으로 다시 배포합니다.

## 자동 업데이트

Claude 예약 작업이 매일 아침(한국 시간 8시 46분경) OpenAI·Anthropic·Google 공식 페이지를 확인합니다. 새 모델 소식이 있으면 `data/news/<id>.json`을 만들고 `data/manifest.json`을 갱신해 이 저장소에 커밋합니다. 커밋되면 Vercel이 자동 배포합니다.

## 소식 직접 추가하기

1. `data/news/<id>.json`을 [데이터 형식](docs/DATA_SCHEMA.md)대로 작성합니다.
2. `data/manifest.json`의 `news` 배열에 id를 추가합니다.
3. `python3 scripts/validate_data.py`로 검증한 뒤 커밋합니다.

## 참고

비공식 요약입니다. 수치와 가격은 각 사 공식 발표 시점 기준이며, 정확한 내용은 각 소식의 출처 링크를 확인하세요. 성능 그래프는 원문 이미지를 복제하지 않고, 공식 발표에 공개된 수치로 직접 그린 것입니다.
