# backend/state

GitHub Actions 실행이 남기는 상태 파일입니다. 사이트에는 배포되지 않습니다(`.vercelignore`).

| 파일 | 내용 |
|---|---|
| `seen.json` | 이미 처리한 글 URL과 결과(added, updated, skipped, old, failed). 같은 글을 다시 요약하지 않게 함 |
| `last-run.json` | 마지막 실행 보고서: 후보, 추가·보강·제외·실패 목록, 원문 대조로 지운 값 |
| `pending.json` | 인증 정보가 없어 요약하지 못한 후보 목록 |

특정 글을 다시 요약하게 하려면 `seen.json`에서 그 URL 항목을 지우고 커밋하세요.
