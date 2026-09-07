# 2026-09-08 복수 선택·Delete 선택창·회차별 ZIP

## 요청과 기준

기준 커밋: `99c47f8`, 브랜치 `codex/toki-gui-foundation`.
사용자가 여러 작품 선택, Delete 키의 처리 선택지, 다운로드 후 압축을 요청했다.
추가로 압축 뷰어에서 순서대로 감상하고 원본은 계속 보관하지 않아도 된다고 결정했다.
기존 작품·회차 이름과 메타데이터, 콘솔 숨김, CLI 제어 원칙을 유지한다.

## 구현

- GUI 목록은 Ctrl+클릭/Shift+클릭 복수 선택과 Ctrl+A(로딩된 범위)를 지원한다.
  우클릭 시 기존 복수 선택을 보존하고, 새로고침 시 아직 표시되는 작품의 선택을 복원한다.
  선택 없이 Delete를 눌러도 예외로 종료되지 않는다. 더블클릭 폴더 열기는 유지한다.
- Delete 선택창: 다운로드 취소, 목록만 삭제, 다운로드 파일 삭제, 압축 파일만 삭제.
  대상 미리보기 후 최종 확인해야 실행된다. 취소/닫기는 어떤 삭제도 실행하지 않는다.
  삭제 대상은 지원 미디어 확장자 또는 ZIP/CBZ/7Z/RAR 계열로 구분하며 알 수 없는 파일과
  작품 메타데이터는 유지한다. 목록 삭제는 해당 작품과 실행 기록만 DB에서 제거한다.
- 파일 삭제는 작품 내부 `.toki-trash/<id>`로 이동한다. 이동 전 복구 manifest를 저장하고
  오류 시 되돌리기를 시도한다. `library restore`는 기존 파일을 덮어쓰지 않는다.
  오래된 완료 상태는 이후 다운로드 기록을 덮어쓰지 않도록 자동 복구하지 않는다.
- 회차별 ZIP은 `<작품 폴더>/_archives/<회차 전체 이름>.zip`으로 저장한다.
  `141.0`/`141.5`, `140-1`/`140-2` 등 기존 회차명 규칙을 변경하지 않는다.
  원본 페이지를 자연순으로 읽어 ZIP 내부에 `000001.jpg`, `000002.webp` 같은 고정폭
  이름을 부여한다. `.toki-episode.json`을 넣고 작품 폴더의 metadata/state는 보존한다.
- 원본 정리는 ZIP 임시 출력 → CRC 검사 → 원자적 배치 → 카탈로그 저장 이후에만 수행한다.
  쓰기 전후·삭제 직전 원본 크기/수정 시간을 확인한다. 원본 일부 정리 후 다시 실행해도
  완전한 ZIP을 부분 원본만 든 ZIP으로 대체하지 않는다. 변경된 ZIP과 앱 소유 기록이
  없는 ZIP은 덮어쓰지 않는다. 중지 요청은 스트리밍/회차 경계에서 처리한다.
- 완료 기록이 확인되는 회차만 압축한다. 미완료 또는 상태 확인 불가 회차를 압축 완료로
  승격하지 않는다. ZIP 전용 회차는 Python 파일 검사·메타데이터 재생성·미리보기와 Node
  다운로드의 신규/전체/범위 완료 판정에서 인식한다. GUI 미리보기는 외부 ZIP 뷰어 열기를
  제공하며 이미지를 몰래 전체 해제하지 않는다.
- 설정 → 고급: `archiveAfterDownload` 기본 false, `archiveRemoveOriginals` 기본 true.
  자동 압축은 다운로드 완료 후 PDF 등 기존 파일 작업이 끝나면 시작한다. 자동 압축 대기도
  완료 후 종료/절전 판단에 포함한다. 종료 시 진행 중인 파일 처리의 안전한 종료를 기다린다.

## 구조와 성능

- 공용 서비스: `toki_library.py`, Python 읽기 카탈로그: `toki_archive_catalog.py`.
- GUI/CLI 연결: `toki_library_gui.py`, `toki_library_cli.py`와 기존 앱 IPC.
- Node 완료 인식: `downloader_archives.js`와 `down.js`. 스캔당 ID/폴더 lookup을 한 번
  만들어 10,000회 조회에도 전체 목록을 반복 순회하지 않는다.
- GUI의 제한된 I/O thread pool에서 수행하고, 1 MiB 스트림으로 압축한다. 동시에 여러
  작품을 무제한 압축하지 않는다. public 계획에는 파일 상세 대신 개수/일부 대상만 남기고
  실행 시 한 작품씩 상세 파일 목록을 구성한다. 화면 출력은 최대 100개 대상 샘플로 제한한다.
- 진행 중 다운로드/변환/PDF/이동/회차 이름변경과 동일 작품 작업이 겹치지 않도록 기존
  mutation guard에 연결했다. 서비스도 전용 lock file과 경로·링크 검사로 중복 처리를 막는다.
  동일/상하위 저장 폴더를 한 번에 선택하면 파일 변경 전에 거부한다.
- ZIP은 Python 표준 라이브러리를 사용하므로 새 의존성 설치가 필요 없다.

## CLI

모든 실행은 기본 미리보기이며 `--execute --yes`가 필요하다. GUI 실행 중이면 worker로
전달하고 `--wait`로 결과를 기다리거나 `operationId`를 `library status`로 조회한다.
`--show-gui --dry-run`은 해당 선택창과 대상 미리보기까지 연다.

```powershell
.\toki-cli.cmd library select --job ID1 --job ID2 --json
.\toki-cli.cmd library delete --job ID1 --job ID2 --kind records --show-gui --dry-run
.\toki-cli.cmd library delete --job ID1 --kind files --dry-run --wait --json
.\toki-cli.cmd library delete --job ID1 --kind archives --execute --yes --wait --json
.\toki-cli.cmd library archive --job ID1 --remove-originals --execute --yes --wait --json
.\toki-cli.cmd library cancel-downloads --job ID1 --execute --yes --wait --json
.\toki-cli.cmd library status --json
.\toki-cli.cmd library cancel --operation OPERATION_ID --json
.\toki-cli.cmd library restore --manifest "작품폴더\.toki-trash\삭제ID\manifest.json" --dry-run
.\toki-cli.cmd library close --json
.\toki-cli.cmd config set --key archiveAfterDownload --value true --json
.\toki-cli.cmd config set --key archiveRemoveOriginals --value true --json
```

## 검증

- Python 전체 **386건**, Node 전체 **58건**. 새 서비스/GUI/CLI 테스트 19건과 Node 3건 포함.
- 임시 한글 경로에서 ZIP 생성·페이지 순서·CRC 검사·원본 정리·ZIP 전용 완료 인식,
  부분 정리 후 재실행, CRC 실패/취소/기존 ZIP 보호, 파일 삭제/복구/덮어쓰기 거부,
  미완료 회차 보호, 상하위 경로 거부를 검증했다.
- PyQt QTest의 실제 Ctrl+클릭과 Delete 입력, 확인 대화상자를 통한 임시 기록 삭제,
  GUI worker 압축·잠금 해제·자동 압축과 설정 검색을 검증했다.
- 실제 GUI를 최신 코드로 다시 열고 CLI에서 복수 선택·선택창·설정창을 조작해 캡처했다.
  `logs/2026-09-08-library-selection.png`, `2026-09-08-library-delete.png`,
  `2026-09-08-library-archive.png`, `2026-09-08-library-settings.png`.
  캡처는 Git 제외 로그 폴더에 보관한다.
- 실제 작업 `54d3f0ed91`은 압축 dry-run **272 ZIP / 2,241 파일**.
  이후 파일 검사는 **272회차 / 2,241 이미지 / 문제 0 / 압축 회차 0**이었다.
  실제 사용자 파일의 압축·삭제·이름변경이나 라이브 사이트 다운로드는 실행하지 않았다.
- Python 컴파일, Node 구문 검사와 `git diff --check`를 실행한다.

재현:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p 'test_*.py'
$testFiles = @(rg --files tests -g 'downloader_*.test.js')
node --test @testFiles
.\toki-cli.cmd library archive --job 54d3f0ed91 --dry-run --wait --json
.\toki-cli.cmd verify-files --job 54d3f0ed91 --json
```

## 사용자 데이터와 남은 제한

- 자동 압축 설정을 임의로 켜거나 기존 만화에 실제 압축/삭제를 실행하지 않았다.
  설정 → 고급에서 켠 뒤 완료되는 다운로드부터 적용된다. 기존 작품은 우클릭 압축으로
  별도 실행한다. GUI를 거치지 않는 `download --direct`/Node 원본 명령에는 GUI 완료 후
  후처리 설정이 적용되지 않으므로 `library archive`를 이어서 실행해야 한다.
- 앱 휴지통은 Windows 휴지통이 아니며 디스크 용량을 확보하지 않는다. 압축 후 원본 정리는
  해당 ZIP으로 내용 복원이 가능하다. 휴지통 비우기나 원본 자동 재추출 기능은 추가하지 않았다.
- 회차 간 자연 숫자 정렬과 다음 압축파일 자동 열기는 연결한 외부 뷰어의 설정/기능에 따른다.
  특정 외부 뷰어를 실행해 끝까지 읽는 라이브 검증은 하지 않았다.
- ZIP 전용 회차의 GUI 내부 직접 이미지 해제/표시는 구현하지 않았다. 외부 뷰어로 연다.
- Node의 빠른 완료 판정은 크기/수정 시각·ZIP 중앙 디렉터리를 확인하며 매 다운로드마다
  전체 CRC를 반복하지 않는다. 전체 CRC는 생성 직후와 명시적 파일 검사에서 검증한다.
  4 GiB를 넘는 ZIP64 중앙 디렉터리 등 빠른 검사가 지원하지 않는 ZIP은 보수적으로 제외된다.
- 강제 전원 차단이나 GUI와 무관한 외부 프로그램의 동시 변경까지 트랜잭션으로 묶지는 않는다.
  복구 manifest/잠금/CRC/원본 변경 검사로 복구 가능성과 보수적 거부를 우선한다.
