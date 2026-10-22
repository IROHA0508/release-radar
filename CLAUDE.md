# 릴리스 레이더

GPT·Claude·Gemini 공식 발표를 한국어로 요약하는 정적 사이트(https://release-radar-ten.vercel.app)와, AI를 활용하는 기술을 정리하고 직접 실습해 보는 학습 공간. 1차 독자는 저장소 주인(학습용), 2차 독자는 링크를 받은 지인. 설명과 커밋 메시지는 한국어로 쓴다.

## 상황별로 볼 문서
- 목표·원칙·로드맵·결정 기록이 필요할 때: `docs/GUIDELINES.md` (지침 v1.3)
- `data/` 아래 JSON(소식, 가이드, 가격표, 기술)을 만들거나 고칠 때: `docs/DATA_SCHEMA.md`
- 자동 업데이트(GitHub Actions + `backend/`)를 고칠 때: `README.md`의 '자동 업데이트'
- 랩(실습)을 만들 때: `docs/GUIDELINES.md` 5장(랩)·6장(실습 환경)
- 한국어 글(`data/`의 소식·기술·용어집·가이드, 화면 문구, backend 프롬프트)을 쓰거나 고칠 때: `.claude/skills/humanize-korean-site/SKILL.md` (im-not-ai 문체 규칙)

## 반드시 지킬 것
- 사실·수치·가격·모델 ID는 공식 출처에서만. 확인 못 한 내용은 쓰지 말고 "확인 필요"로 남긴다.
- 글을 고친 뒤 `python3 scripts/style_check.py --spans`로 'AI 티' 신호를 확인하고 걸린 문장만 고친다. 특히 연결어미(-고/-며/-지만) 바로 뒤 쉼표와 제목의 "X: Y" 콜론 부제를 쓰지 않는다.
- `data/`를 고치면 `python3 scripts/validate_data.py`, 코드를 고치면 `python -m pytest tests -q`. 둘 다 통과해야 커밋한다.
- 큰 변경은 브랜치와 PR로. `main`에는 6시간마다 자동 커밋(`release-radar-bot`)이 올라오므로 직접 푸시하지 않는다.
- 커밋 작성자는 저장소 주인의 GitHub 계정 이메일(`siwonl0508@naver.com`)로 한다(예: `git -c user.name=IROHA0508 -c user.email=siwonl0508@naver.com commit ...`). 그래야 커밋이 GitHub 계정에 연결돼 기록이 한 사람으로 모인다. 푸시 전에 `git log -1 --format='%ae'`로 확인한다.
- Vercel 배포는 푸시 후 10~15분 늦게 시작될 때가 있다. 바로 안 보여도 GitHub 커밋의 Vercel 상태를 15분쯤 기다려 보고, 그래도 없을 때만 Vercel 대시보드에서 직접 배포한다.
- 토큰·API 키는 GitHub Secrets나 로컬 `.env`에만. 사이트 자동화는 구독 토큰(`CLAUDE_CODE_OAUTH_TOKEN`)을 쓰고 랩 실습용 API 키와 섞지 않는다.

## 함정
- 빌드 없는 정적 사이트다. 화면은 `index.html` 한 파일, 데이터는 `fetch`로 읽는다. 로컬 확인은 `python3 -m http.server 8000` (파일로 직접 열면 `data/`를 못 읽음).
- 소식 id 예약어: `guide`, `prices`, `tech`, `lab`, `glossary` (해시 라우팅과 겹침). 새 탭을 만들면 `scripts/validate_data.py`와 `backend/store.py`의 예약어에 함께 추가한다.
- 그래프·핵심 수치는 원문 텍스트에 있는 값만. `backend/guard.py`가 원문에 없는 값을 지운다.
- 소식 종류는 `모델 출시`·`모델 업데이트`·`제품·기능 출시`·`활용 팁` 넷. 바꾸면 `backend/summarize.py`, `scripts/validate_data.py`, `index.html`의 KINDS를 함께 고친다.
- 'AI 활용 기술' 탭(`#tech`, 최신 활용 기술)과 'AI 활용 LAB' 탭(`#lab`, 학습 경로)은 둘 다 `data/tech.json`을 `group`(`radar`/`path`)으로 나눠 쓴다. 기술 페이지는 필수 항목(정의, 왜 필요한가, 어떻게 활용하나, 기대 효과)과 공식 출처가 있어야 검증을 통과한다.
- 랩은 대화하며 함께 작성하고 저장소 주인이 직접 실행해 통과한 코드만 커밋한다. 오류를 도울 때는 고치기 전에 왜 났는지 먼저 설명한다.
