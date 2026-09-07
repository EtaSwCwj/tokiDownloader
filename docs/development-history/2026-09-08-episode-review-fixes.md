# 2026-09-08 회차·WebP·미리보기 검수 후 수정

## 요청과 기준

기준 커밋: `1750237` (`codex/toki-gui-foundation`). 프로그램 검수에서 재현한 네 문제를
사용자가 모두 수정하도록 요청했다. 기존 사용자 폴더의 이름변경·삭제·재다운로드는 하지 않았다.

## 수정 내용

1. **잘못된 회차 ID 승계**: `discover_episode_folders`가 같은 순번의 다른 제목 폴더에도
   manifest ID를 붙이던 동작을 제거했다. 정규화한 제목이 유일한 identity에 일치할 때만
   연결한다. 서로 다른 ID가 같은 제목을 주장하면 ID 없이 남겨 누락 회차를 다시 드러낸다.
   이 공용 탐색을 쓰는 파일 검사와 메타데이터 재생성에도 적용된다. ID 없는 v1 완료
   숫자 호환성은 유지하되 엉뚱한 원본 제목·ID를 만들지 않는다.
2. **잘린 WebP 정상 판정**: Node의 다운로드 버퍼/기존 파일 검사와 Python의 파일 검사에
   RIFF 선언 크기, 청크 길이·패딩·경계, 이미지 청크 존재, ANMF 하위 청크 검사를 추가했다.
   기존 파일은 seek로 청크 헤더만 읽으며 전체 압축 데이터를 메모리에 적재하지 않는다.
   검증 실패한 새 버퍼는 기존 정상 파일을 덮어쓰지 않는다.
3. **부분 다운로드의 `.0`·`-1` 되돌림**: 이름변경 계획에 존재하는 폴더뿐 아니라 전체
   state·metadata 회차 목록을 포함했다. 실제 폴더와 매칭한 record는 두 번 세지 않으며,
   미다운로드 소수/분할 회차도 정렬 문맥과 충돌 판단에 반영한다.
4. **동일 순번 미리보기 혼합**: 미리보기 서비스는 항상 한 폴더의 페이지만 반환한다.
   `--episode-id`/`--episode-folder`를 CLI·GUI IPC에 연결하고 GUI에는 실제 폴더명으로
   선택 항목을 표시한다. 애매한 `--episode N`은 후보를 알려주며 선택을 요구한다.
   기본 조회는 첫 폴더를 선택한다. worker가 끝날 때까지 선택 표시는 현재 이미지와
   일치하게 유지하므로 실패/사용 중 응답에도 다른 회차의 내용으로 오인하지 않는다.

GUI 화면 검증 중 추가로 Pillow에서는 정상인 32×32 lossless WebP를 Qt가 읽지 못하는
사례를 발견했다. 기존 이미지 worker에서 Qt 실패 시 Pillow를 보조 디코더로 사용하고,
방향 보정·축소·RGBA 복사 후 표시한다. 이 경로도 회귀 테스트에 포함했다.

## 검증

- Node 전체 다운로더 테스트: **55건 통과**.
- Python 전체 테스트: **367건 통과**. CLI 선택·GUI IPC·동일 순번 선택·Pillow fallback 포함.
- 신규 `test_episode_review_regressions.py`: 네 문제의 실패 사례와 안전한 정상 사례를
  임시 폴더에서 검증했다. 손실/무손실/애니메이션 WebP 샘플을 JS/Python이 공유한다.
- GUI `ImagePreviewDialog`를 offscreen으로 렌더링하고, 같은 순번의 다른 회차로 선택을
  전환해 이미지 경로·선택 ID·한 폴더 페이지만 표시하는지 확인했다. 정상 lossless WebP의
  실제 디코딩과 한글 표시도 확인했다.
- 캡처: `logs/2026-09-08-review-fixes/preview-first.png`, `preview-second.png`.
  로그/캡처는 기존 방침대로 Git에서 제외된다. 실제 사용자 GUI는 실행하지 않았다.
- 실제 작업 `54d3f0ed91`: `verify-files`에서 **272개 회차, 2,241개 이미지, 문제 0**.
  `rename-episodes --dry-run`은 **변경 0, 유지 272, 충돌 0**.
  `preview --limit 1 --json`은 **272개 선택 항목, 한 회차의 페이지만 반환**.
- 실제 `config.json`, `.toki-state.json`, `metadata.json` SHA-256 유지.
  CLI 공통 DB 연결 코드의 `PRAGMA user_version` 때문에 `jobs.db` 파일 해시는 바뀔 수 있다.
  별도 조회 전후 논리 SQL dump를 비교해 DB 테이블 내용은 동일함을 확인했다.

재현 명령:

```powershell
$testFiles = @(rg --files tests -g 'downloader_*.test.js')
node --test @testFiles
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p 'test_*.py'
.\toki-cli.cmd verify-files --job 54d3f0ed91 --json
.\toki-cli.cmd rename-episodes --job 54d3f0ed91 --dry-run --json
.\toki-cli.cmd preview --job 54d3f0ed91 --limit 1 --json
```

## 범위와 제한

- 라이브 사이트 재다운로드·사용자 파일 이름변경은 실행하지 않았다.
- WebP 구조 검사는 모든 압축 픽셀 데이터의 정상 디코딩을 보증하지 않는다.
- 과거에 이미 잘못 확정되어 저장된 ID 매핑은 자동 추측해서 되돌리지 않는다.
- Pillow는 보조 디코더다. 미설치·미지원·손상 파일이면 Qt/Pillow 오류를 표시한다.
- GUI의 이미지 페이지 조회 상한 등 기존 기능 범위는 변경하지 않았다.
