# 1. 뉴토끼 마나토끼 북토끼 다운로드 스크립트
- 프로그램 설치 불필요
- 정보수집 없음
## 사용법
1. Tampermonkey 확장 프로그램 설치
2. [tokiDownloader](https://sleazyfork.org/ko/scripts/531932-tokidownloader) 접속해 스크립트 설치
3. 뉴토끼, 마나토끼, 북토끼 회차 목록 페이지 접속
4. 원하는 기능을 클릭해 다운로드

https://github.com/user-attachments/assets/fe974989-5ffb-4831-b2dc-7ea576712f62
## 폴더(디렉토리) 구조
뉴토끼, 마나토끼
```
뉴토끼 시작연재이름 ~ 마지막연재이름/
|
├─ 0001 어떤만화-1화/
|   ├─ 어떤만화-1화 image0000.jpg
|  ...
|   └─ 어떤만화-1화 image0015.jpg
├─ 0002 어떤만화-2화/
|   ├─ 어떤만화-2화 image0000.jpg
|  ...
|   └─ 어떤만화-2화 image0030.jpg
...
└─ 0123 어떤만화-123화/
    ├─ 어떤만화-123화 image0000.jpg
   ...
    └─ 어떤만화-123화 image0030.jpg
```
북토끼
```
북토끼 시작연재이름 ~ 마지막연재이름/
|
├─ 0001 어떤소설-1화.txt
├─ 0002 어떤소설-2화.txt
├─ 0003 어떤소설-3화.txt
...
└─ 1234 어떤소설-1234화.txt
```

# 2. 뉴토끼 마나토끼 북토끼 다운로더
현재 개발 버전은 `VERSION` 파일을 기준으로 하며 `toki-cli.cmd --version`으로 확인합니다.
배포 전 절차는 [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md), 독립 실행 파일 검토 결과는
[PYINSTALLER_REVIEW.md](PYINSTALLER_REVIEW.md)를 참고하세요.
처음 설치부터 업데이트·복구까지의 Windows 절차는 [WINDOWS_SETUP.md](WINDOWS_SETUP.md)를
기준 문서로 사용합니다.

## 준비물 
Node.js, Python 3

## Windows GUI

Python 3.10 이상과 Node.js/npm을 설치한 뒤 처음 한 번 `setup-gui.cmd`를 실행하면 저장소
전용 Python 가상환경과 PyQt6, 잠금파일 기준 Node.js 의존성을 설치합니다. 이후에는 콘솔이
보이지 않는 `start-gui.vbs`를 더블클릭해 실제 Windows 창으로 실행합니다.

GUI에서 URL, 시작/마지막 회차, 저장 기준 폴더를 지정할 수 있습니다. 작업은 한 번에
하나씩 실행되고 다음 작업은 대기열에 들어갑니다. 진행률, 현재 회차와 이미지 수,
오류를 화면 하단 로그에서 확인할 수 있으며 파일 로그는 `logs\gui.log`에 저장됩니다.

```powershell
.\setup-gui.cmd
.\setup-gui.cmd -CheckOnly
.\start-gui.vbs
```

`-CheckOnly`는 다운로드나 재설치 없이 `.venv`, Puppeteer와 공용 `doctor` 결과만 검증합니다.
이미지 변환·유사 이미지 해시용 Pillow와 ImageHash까지 함께 설치하려면
`setup-gui.cmd -WithImageTools`를 사용합니다.
7Z/RAR 작품 검사 모듈까지 설치하려면 `setup-gui.cmd -WithArchiveTools`를 사용합니다.

### GUI 제어 CLI

GUI의 주요 버튼은 모두 `toki-cli.cmd`에서도 실행할 수 있습니다. GUI가 꺼져 있을 때
`download`를 실행하면 GUI를 자동으로 시작하고 그 대기열에 작업을 추가합니다.

```powershell
# GUI 실행 또는 앞으로 가져오기
.\toki-cli.cmd gui
.\toki-cli.cmd show
.\toki-cli.cmd --version
.\toki-cli.cmd config get --json
.\toki-cli.cmd config get --key theme --json
.\toki-cli.cmd config set --key theme --value dark --json
.\toki-cli.cmd config export --output "D:\Backup\toki-settings.json" --json
.\toki-cli.cmd config import --input "D:\Backup\toki-settings.json" --json
.\toki-cli.cmd config import --input "D:\Backup\toki-settings.json" --execute --yes --json
.\toki-cli.cmd config reset --json
.\toki-cli.cmd config reset --execute --yes --json
.\toki-cli.cmd jobs export --output "D:\Backup\toki-jobs.json" --json
.\toki-cli.cmd jobs import --input "D:\Backup\toki-jobs.json" --dry-run --json
.\toki-cli.cmd jobs import --input "D:\Backup\toki-jobs.json" --show-gui
.\toki-cli.cmd jobs import --input "D:\Backup\toki-jobs.json" --execute --yes --json
.\toki-cli.cmd jobs import --close
.\toki-cli.cmd group list --json
.\toki-cli.cmd group create --name "나중에 읽기" --json
.\toki-cli.cmd group rename --group 그룹ID --name "즐겨찾기" --json
.\toki-cli.cmd group assign --job 작업ID --group 그룹ID --json
.\toki-cli.cmd group unassign --job 작업ID --json
.\toki-cli.cmd group manage --show-gui
.\toki-cli.cmd local inspect --path "D:\Manga\work.cbz" --json
.\toki-cli.cmd local inspect --path "D:\Manga\work.cbz" --show-gui
.\toki-cli.cmd local inspect --close
.\toki-cli.cmd duplicates works --json
.\toki-cli.cmd duplicates works --show-gui
.\toki-cli.cmd duplicates works --close
.\toki-cli.cmd duplicates images --job 작업ID --algorithm sha256 --json
.\toki-cli.cmd duplicates images --job 작업ID --algorithm phash --show-gui
.\toki-cli.cmd duplicates images --close

# 다운로드 추가
.\toki-cli.cmd download --url "https://newtoki1.org/manhwa/34732" --start 1 --last 10 --output "D:\Manga"

# 상태와 작업 제어
.\toki-cli.cmd status
.\toki-cli.cmd status --json
.\toki-cli.cmd list --query "오타쿠" --status "완료" --sort title --json
.\toki-cli.cmd list --query "오타쿠" --status "완료" --sort title --apply-gui --json
.\toki-cli.cmd list-state --json
.\toki-cli.cmd list-state --query "없는 작품" --json
.\toki-cli.cmd list-state --apply-gui --preview no-results --json
.\toki-cli.cmd list-state --apply-gui --preview error --message "진단 오류" --json
.\toki-cli.cmd shortcuts --json
.\toki-cli.cmd shortcuts --show-gui
.\toki-cli.cmd focus --target url --json
.\toki-cli.cmd focus --target search --clear --json
.\toki-cli.cmd focus --target next --json
.\toki-cli.cmd info --job 작업ID --json
.\toki-cli.cmd runs --job 작업ID --limit 100 --offset 0 --json
.\toki-cli.cmd run-info --run 실행ID --json
.\toki-cli.cmd run-logs --run 실행ID --tail 500 --json
.\toki-cli.cmd run-log --run 실행ID
.\toki-cli.cmd run-log --close
.\toki-cli.cmd details --job 작업ID
.\toki-cli.cmd details --close
.\toki-cli.cmd set-note --job 작업ID --text "확인할 내용"
.\toki-cli.cmd open-source --job 작업ID
.\toki-cli.cmd open-cover --job 작업ID
.\toki-cli.cmd refresh-metadata --job 작업ID
.\toki-cli.cmd pin --job 작업ID --on
.\toki-cli.cmd tag --job 작업ID --color purple
.\toki-cli.cmd remove-record --job 작업ID --yes
.\toki-cli.cmd cleanup-records --status completed --status error --yes
.\toki-cli.cmd refresh-list
.\toki-cli.cmd stop --job 실행중작업ID
.\toki-cli.cmd cancel --job 대기작업ID
.\toki-cli.cmd queue list --json
.\toki-cli.cmd queue move --job 대기작업ID --before 기준작업ID
.\toki-cli.cmd queue move --job 대기작업ID --first
.\toki-cli.cmd queue move --job 대기작업ID --last
.\toki-cli.cmd pause --job 실행중작업ID
.\toki-cli.cmd resume --job 일시정지작업ID
.\toki-cli.cmd concurrency --json
.\toki-cli.cmd set-concurrency --works 2 --images 5
.\toki-cli.cmd retry-policy --json
.\toki-cli.cmd set-retry-policy --count 2 --backoff 2
.\toki-cli.cmd settings --json
.\toki-cli.cmd settings --show-gui --tab network
.\toki-cli.cmd settings --show-gui --tab provider --search yt-dlp
.\toki-cli.cmd settings --close
.\toki-cli.cmd set-settings --works 2 --images 8 --retry-count 2 --retry-backoff 2
.\toki-cli.cmd set-settings --show-browser off --log-visible on --log-max-mib 2 --log-backups 1
.\toki-cli.cmd set-settings --row-density compact
.\toki-cli.cmd set-settings --theme dark
.\toki-cli.cmd set-settings --language ko --ui-scale 125 --font "Malgun Gothic"
.\toki-cli.cmd set-settings --background "D:\Pictures\background.png"
.\toki-cli.cmd set-settings --clear-background
.\toki-cli.cmd set-settings --tray on --close-to-tray on --notify-complete on --notify-error on
.\toki-cli.cmd tray status
.\toki-cli.cmd tray show
.\toki-cli.cmd tray hide
.\toki-cli.cmd rescan --job 작업ID --mode new
.\toki-cli.cmd rescan --job 작업ID --mode full
.\toki-cli.cmd rescan --job 작업ID --mode range --start 10 --last 25
.\toki-cli.cmd retry --job 작업ID

# 저장 폴더와 로그
.\toki-cli.cmd set-output "D:\Manga"
.\toki-cli.cmd open-folder --job 작업ID
.\toki-cli.cmd move-folder --job 작업ID --output "E:\Manga" --dry-run --json
.\toki-cli.cmd move-folder --job 작업ID --output "E:\Manga" --execute --yes --json
.\toki-cli.cmd rebuild-metadata --job 작업ID --dry-run --json
.\toki-cli.cmd rebuild-metadata --job 작업ID --execute --yes --json
.\toki-cli.cmd verify-files --job 작업ID --json
.\toki-cli.cmd verify-files --job 작업ID --show-gui
.\toki-cli.cmd preview --job 작업ID --episode 1 --json
.\toki-cli.cmd preview --job 작업ID --episode 1 --show-gui
.\toki-cli.cmd convert-images --job 작업ID --format webp --quality 85 --dry-run --json
.\toki-cli.cmd convert-images --job 작업ID --format webp --quality 85 --execute --yes --progress-json
.\toki-cli.cmd convert-images --job 작업ID --format webp --quality 85 --show-gui
.\toki-cli.cmd cancel-conversion --job 작업ID
.\toki-cli.cmd copy-id --job 작업ID
.\toki-cli.cmd copy-link --job 작업ID
.\toki-cli.cmd copy-path --job 작업ID
.\toki-cli.cmd copy-title --job 작업ID
.\toki-cli.cmd completion-action status --json
.\toki-cli.cmd completion-action set --action exit --countdown 15 --json
.\toki-cli.cmd completion-action preview --action shutdown --countdown 15 --show-gui
.\toki-cli.cmd completion-action cancel
.\toki-cli.cmd clipboard inspect --text "https://newtoki1.org/manhwa/34360" --json
.\toki-cli.cmd clipboard monitor --state on --json
.\toki-cli.cmd folder-template --template "[{author}][{group}] {title}" --output "D:\Manga" --json
.\toki-cli.cmd language list --json
.\toki-cli.cmd language set ko --json
.\toki-cli.cmd job-menu --job 작업ID
.\toki-cli.cmd window
.\toki-cli.cmd window --screen "모니터 이름" --center --normal
.\toki-cli.cmd window --safe
.\toki-cli.cmd performance audit --json
.\toki-cli.cmd performance audit --show-gui
.\toki-cli.cmd performance benchmark --json
.\toki-cli.cmd performance benchmark --sizes 100 1000 10000 100000 --via-gui --json
.\toki-cli.cmd performance event-policy --event image_saved --json
.\toki-cli.cmd thumbnail-cache status --json
.\toki-cli.cmd thumbnail-cache cleanup --execute --json
.\toki-cli.cmd retention status --json
.\toki-cli.cmd retention cleanup-runs --max-per-work 500 --max-age-days 365 --json
.\toki-cli.cmd retention cleanup-runs --max-per-work 500 --max-age-days 365 --execute --json
.\toki-cli.cmd performance resources --json
.\toki-cli.cmd performance stability --records 10000 --cycles 100 --json
.\toki-cli.cmd performance stability --records 1000 --cycles 10 --via-gui --json
.\toki-cli.cmd doctor --json
.\toki-cli.cmd doctor --show-gui --json
.\toki-cli.cmd migrate status --json
.\toki-cli.cmd migrate apply --json
.\toki-cli.cmd diagnostics export --json
.\toki-cli.cmd diagnostics export --output "D:\Reports\toki-diagnostics.zip" --via-gui --json
.\toki-cli.cmd logs --tail 200
.\toki-cli.cmd copy-log
.\toki-cli.cmd screenshot
.\toki-cli.cmd self-test --json
.\toki-cli.cmd self-test --via-gui --json
.\toki-cli.cmd clear-log
.\toki-cli.cmd quit --force
```

`copy-id`, `copy-link`, `copy-path`, `copy-title`은 GUI가 실행 중이면 선택 작품과 같은
클립보드 경로를 사용하고, GUI가 꺼져 있어도 `--job`을 지정하면 Windows 네이티브
클립보드에 직접 복사합니다. 별도 PowerShell·명령 프롬프트 창은 시작하지 않습니다.

`list`는 제목, 폴더명에 포함된 작가·그룹, 작품 ID와 URL을 검색합니다. `--status`로
상태를 거르고 `--sort updated|title|progress`로 정렬할 수 있습니다. `--apply-gui`를
추가하면 같은 조건을 실행 중인 GUI 검색창과 목록에도 적용합니다. 빈 조건으로
`list --apply-gui`를 실행하면 GUI 필터가 초기화됩니다.

`window`는 `--screen`으로 지정한 모니터로 창을 옮기고 `--center`로 가운데에 배치합니다.
`--safe`는 모니터 분리나 해상도 변경으로 창이 화면 밖에 있을 때 현재 사용 가능한 화면으로
복구합니다. 다중 모니터의 정상적인 음수 좌표는 그대로 유지합니다. `status --json`의
`window`에서 현재 모니터 이름, 배율, 화면 안 배치 여부와 전체 모니터 목록을 확인할 수 있습니다.

설정의 디스플레이 페이지에서 목록/아이콘 보기, 썸네일 표시와 크기, 항상 위, 창 불투명도를
바꿀 수 있습니다. 같은 값은 `set-settings --view-mode list|icon --thumbnails on|off
--thumbnail-size small|medium|large --always-on-top on|off --opacity 50~100`으로 적용하고
`status --json`의 `view`로 확인합니다. 아이콘 보기도 SQLite 페이지 조회, GUI 최대 2,000개
보유, 100개 배치 레이아웃을 유지해 기록 전체를 한 번에 메모리에 올리지 않습니다.

한국어 UI 문구는 `locales\ko.json`에 분리되어 있고 `language list|status|set`으로 설치된
언어와 현재 값을 조회·변경합니다. 현재 배포 언어는 한국어이며 새 언어는 같은 키 구조의
JSON 리소스를 추가하는 방식입니다. 디스플레이 설정의 UI 배율(75~200%), 글꼴, 배경
이미지는 `set-settings --ui-scale N --font NAME --background PATH`와 동일한 설정을
사용합니다. 배경은 밝은 이미지에서도 글자가 묻히지 않도록 현재 테마의 보호 오버레이를
함께 그리며 `--clear-background`로 원본 파일을 건드리지 않고 연결만 해제합니다.

메인 입력 영역 아래의 빠른 실행 막대는 디스플레이 설정에서 항목을 체크하고 드래그해
순서를 바꿀 수 있습니다. CLI에서는 `set-settings --quick-actions
download.start,job.stop,job.rescan_full,folder.open,settings.open`처럼 동작 ID 순서를
지정합니다. 빠른 실행 버튼도 메뉴와 동일한 활성/비활성 판정과 대응 CLI를 사용합니다.

일반 설정의 `모든 작업 완료 후`는 기본적으로 아무 동작도 하지 않습니다. 프로그램 종료나
Windows 종료를 선택한 경우 실제로 실행한 대기열이 완전히 끝난 뒤 5~300초 카운트다운을
표시하며 사용자가 취소할 수 있습니다. `completion-action status|set`으로 정책을 관리하고
`preview --action shutdown --countdown 15 --show-gui`로 실제 종료 없이 화면과 취소 동작을
점검합니다. 미리보기 명령은 시스템 종료를 실행하지 않습니다.

클립보드 URL 감지는 기본적으로 꺼져 있습니다. 켜면 지원 작품 URL이 새로 복사될 때 작품
키를 전체 DB와 비교하고, 이미 등록된 작품은 건너뛰며 새 작품은 확인 질문 뒤에만 대기열에
추가합니다. `clipboard inspect --text URL --json`은 추가 없이 판정만 수행하고,
`clipboard monitor --state on|off`로 감지 설정을 바꿉니다.

일반 설정의 작품 폴더명은 기본적으로 `[작가][그룹] 제목` 규칙을 사용합니다.
`{author}`, `{group}`, `{title}`, `{site}`, `{id}`를 조합할 수 있고 `{title}`은 필수입니다.
`folder-template` 명령은 예상 폴더명과 저장 경로 충돌을 dry-run으로 확인하며 파일이나 기존
폴더를 바꾸지 않습니다. 저장된 작품의 실제 경로가 항상 우선되므로 템플릿 변경은 기존
다운로드 결과를 자동으로 이름 변경하거나 다른 폴더에 중복 생성하지 않습니다.

`performance audit`은 작품 목록의 갱신일·제목·진행률 정렬과 상태 필터 조합 6가지를
`EXPLAIN QUERY PLAN`으로 검사합니다. 각 조회가 전용 SQLite 복합 인덱스를 사용하는지,
전체 임시 정렬이 발생하는지를 JSON으로 반환합니다. `--show-gui`는 같은 결과를 도구 메뉴의
`목록 성능 진단...` 창으로 표시하며 `--close`로 닫을 수 있습니다.

`performance benchmark`는 사용자 DB와 분리된 임시 SQLite 파일에 합성 작품을 누적해
첫 200개 로딩과 정렬·상태 필터 시간을 측정하고 `logs/performance-benchmark.json`에
원자적으로 저장합니다. 기본 크기는 100, 1,000, 10,000, 100,000개이며 임시 DB는 실행 후
자동 제거됩니다. `--via-gui`는 진단창을 열고 숨겨진 백그라운드 프로세스로 같은 벤치마크를
실행합니다. 진행·완료 상태는 `status --json`의 `performanceBenchmark`에서도 확인합니다.

이미지 한 장 저장 이벤트는 100ms 동안 작품별 최신 상태로 병합해 카드 렌더와 DB 저장 예약을
제한합니다. 회차 시작·완료, 작품 메타데이터, 오류와 최종 완료는 즉시 반영됩니다.
`performance event-policy --event EVENT --json`으로 공용 정책을 확인하고, 실행 중 누적된
수신·병합·렌더 횟수는 `status --json`의 `eventUpdates`에서 확인할 수 있습니다.

작품 카드는 원본 표지의 경로·크기·수정 시각으로 키를 만든 50×66 PNG를
`.cache\thumbnails`에 저장해 다음 실행의 원본 이미지 디코딩을 줄입니다. 앱 전용 캐시는
최대 2,000개, 256 MiB, 최근 90일로 제한되며 GUI 시작 시 자동 정리됩니다.
`thumbnail-cache status`는 정리 예정량만 조회하고 `cleanup --execute`가 실제 캐시만
제거합니다. 다운로드 폴더의 원본 표지와 작품 파일은 건드리지 않습니다. 실행 중 GUI가 있으면
같은 도구 메뉴 동작을 호출해 메모리 캐시도 함께 비웁니다.

`retention status`는 현재 설정의 로그 파일 크기·백업 수와 오래된 실행 이력 정리 예정량을
함께 보여줍니다. 로그는 설정의 크기와 백업 개수에 따라 자동 순환합니다. 실행 이력은 기본
작품별 500건·365일 정책을 사용하되 작품별 최신 1건과 대기·실행·일시정지·재시도 중인 기록은
항상 보존합니다. `cleanup-runs`는 기본 미리보기이고 `--execute`를 붙여야 DB의 오래된 실행
이력만 제거합니다. 작품 목록 레코드와 다운로드 폴더·이미지 파일은 삭제하지 않습니다.

`performance resources`는 현재 PC와 실행 중인 GUI의 자원 상한·사용량을 반환합니다. 파일
검사, 회차 이미지 목록과 미리보기 디코딩은 최대 2~8개의 공용 I/O 스레드 풀에서 실행되고
대기 포함 I/O 작업은 스레드 수의 4배로 제한됩니다. 이미지 변환은 CPU 수와 가용 메모리에
따라 1~4개의 숨김 프로세스로 제한되어 GUI와 다운로드 스케줄러를 막지 않습니다. 다운로드
대기열은 최대 1,000개이며 상한 도달 시 새 작업을 명확히 거부합니다.
GUI가 한 번에 보유하는 작품 카드는 최대 2,000개이고, 전체 건수와 SQLite 검색·정렬 및
`list --offset` 조회는 전체 기록을 계속 대상으로 합니다. 프로세스별 stdout/stderr 버퍼는
각 2MiB로 제한되며 생략된 출력량은 `performance resources --json`의 `memory` 진단에
누적됩니다.

`performance stability`는 사용자 `jobs.db`와 분리된 임시 WAL 데이터베이스를 만들고 반복
읽기·쓰기 후 테스트용 숨김 자식 프로세스를 실제로 강제 종료합니다. 이어 새 연결에서 실행
중이던 작품과 실행 이력이 `중지됨`으로 복구되는지, SQLite 무결성과 임시 DB 제거까지
검사해 `logs/stability-recovery.json`에 기록합니다. `--via-gui`는 성능 진단창의
`장시간·강제 종료 복구 검증` 버튼과 같은 경로를 실행합니다.

`doctor`는 Python 3.10+, PyQt6, psutil, Node.js와 `puppeteer-real-browser`를 필수 실행
환경으로 검사합니다. npm은 설치 도구로, Pillow·ImageHash·py7zr·rarfile·FFmpeg·yt-dlp·PyInstaller는 선택 기능으로
분리해 설치 여부·버전·실제 경로를 표시합니다. `--show-gui`와 도구 메뉴의
`설치 및 선택 기능 진단...`은 같은 보고서를 표로 보여주며 `--close`로 닫을 수 있습니다.

설정은 `configVersion`, 작업 DB는 SQLite `PRAGMA user_version`과 `schema_migrations`로
버전을 관리합니다. `migrate status`는 변경 없이 현재/지원 버전을 확인하고 `migrate apply`는
최신 스키마를 적용합니다. 기존 파일을 변경하기 전 `config.json.pre-vN.bak`와
`jobs.db.pre-vN.bak`을 한 번 생성하며, 평상시 앱 시작에서 자동 마이그레이션되더라도 같은
DB 백업 절차를 거칩니다. 업데이트 전에는 GUI를 종료하고 두 백업 파일과 다운로드 폴더를
별도 위치에 보관한 뒤 `setup-gui.cmd`, `migrate apply`, `self-test --core-only` 순서로
검증하세요.

`diagnostics export`는 오류 보고에 필요한 의존성, 스키마, DB 쿼리 계획, 자원·보존 정책,
안전한 설정 요약과 최근 로그를 ZIP으로 만듭니다. `config.json`, `jobs.db`, 쿠키와 다운로드
파일은 포함하지 않으며 앱 경로·사용자 홈·저장 폴더·URL·작업 ID·작품 키를 치환합니다.
도구 메뉴의 `오류 보고용 진단 묶음 내보내기`와 `--via-gui`도 같은 서비스를 사용합니다.

`pin --on|--off`는 작품을 모든 정렬의 상단에 고정하거나 해제합니다. `tag --color`는
`none`, `red`, `orange`, `yellow`, `green`, `blue`, `purple`, `gray` 중 하나를 지정하며
목록 행의 왼쪽에 색상 표시를 추가합니다. 같은 기능은 작품 우클릭 메뉴에서도 사용할 수
있습니다.

`도구 → 설정...` 또는 `settings --show-gui`는 일반·네트워크·디스플레이·고급·공급자 탭을 엽니다.
기본 저장 폴더, 자동화 브라우저 표시, 로그 패널, 작품/이미지 동시성, 재시도 정책과
로그 순환 크기·백업 수를 한 화면에서 바꿀 수 있습니다. 검색란은 관련 설정 페이지만 남기며
`--search`로 같은 검색을 CLI에서 재현할 수 있습니다. `적용`은 창을 유지하고 값을 저장하고,
`저장 후 닫기`, `취소`, `기본값`은 각각 CLI의 설정 변경, `settings --close`, `config reset`
계약에 대응합니다. 같은 값은 `settings --json`으로
조회하고 `set-settings`로 변경할 수 있으며 `status --json`의 `settings`에도 포함됩니다.
설정 파일의 잘못된 타입이나 범위 값은 시작할 때 안전한 기본값으로 정규화되고 저장은
임시 파일을 거친 원자 교체로 처리됩니다. GUI 로그는 설정한 최대 크기를 넘으면
`gui.log.1`, `gui.log.2` 순서로 지정 개수만큼 순환 보존합니다.
`config import`와 `config reset`은 기본적으로 변경 예정만 보여줍니다. 실제 반영에는
`--execute --yes`가 모두 필요하며, 가져오기 전 기존 설정은 타임스탬프 백업으로 보존됩니다.
GUI 실행 중 CLI로 설정을 바꾸거나 가져오면 현재 창에도 즉시 반영됩니다.

`jobs export`는 작품 단위 기록과 실행 이력을 한 JSON에 저장합니다. 이 파일에는 원본 URL과
로컬 저장 경로가 포함되므로 개인 백업으로 취급해야 합니다. `jobs import`는 기본적으로
미리보기이며 실제 추가에는 `--execute --yes`가 필요합니다. 가져오기는 현재 기록을 덮어쓰지
않고 누락된 작품·실행만 추가하며, 미완료 상태는 실행 프로세스 없이 `중지됨`으로 복원합니다.
다운로드 폴더와 파일은 읽거나 변경하지 않습니다. 작업 메뉴의 내보내기·가져오기와
`--show-gui`, `--via-gui`도 같은 서비스를 사용합니다.

`group` 명령과 `작업 → 작품 그룹 관리...`는 많은 작품을 목록 정리용 그룹으로 묶습니다.
작품 우클릭 메뉴의 `작품 정리 그룹`에서 바로 배정하거나 `미분류`로 되돌릴 수 있습니다.
이 그룹은 작품 폴더명의 `[작가][번역/출판 그룹]` 및 `metadata.json`의 `group`과 별개이며,
배정·이름 변경으로 다운로드 파일이나 메타데이터가 바뀌지 않습니다. 그룹 관리창의 모든
동작은 `group list/create/rename/assign/unassign/manage` CLI로 동일하게 실행할 수 있습니다.

`local inspect --path ARCHIVE`는 ZIP/CBZ/7Z/CB7/RAR/CBR의 파일 목록과 이미지 수, 빈 파일,
암호화 여부, `../` 같은 위험 경로를 검사합니다. ZIP/CBZ는 Python 기본 기능만 사용하며,
7Z와 RAR 계열은 `-WithArchiveTools`로 설치하는 선택 모듈을 사용합니다. 검사는 압축을 풀지
않고 원본이나 주변 파일을 변경하지 않습니다. `도구 → 로컬 압축 작품 검사...`와
`--show-gui`, `--close`도 같은 읽기 전용 서비스를 사용합니다.

메인 작품 검색과 `list --query TEXT`는 제목뿐 아니라 작가, 폴더명용 번역/출판 그룹,
작업 ID, 작품 키, 원본 URL, 별도 작품 정리 그룹 이름을 함께 찾습니다. 결과는 기존 SQLite
페이지 로딩과 GUI 메모리 상한을 그대로 사용하며, 10,000개 합성 기록에서도 한 페이지 검색
응답이 성능 기준 안에 들어오는지 자동 검증합니다.

`duplicates works`는 작품 키 유일성 검사에 더해 제목+작가가 같은 서로 다른 작품 키와
동일 저장 경로를 공유하는 기록을 찾습니다. 결과는 진단만 제공하며 자동 병합·기록 삭제·
폴더 변경을 하지 않습니다. `도구 → 중복 의심 작품 검사...`, `--show-gui`, `--close`가
같은 읽기 전용 서비스를 사용합니다.

디스플레이 탭의 `편안하게`는 표지·상세·진행률 막대를 유지하고, `간략하게`는 66px
높이에서 표지를 생략하고 핵심 정보와 진행률을 표시합니다. `set-settings --row-density
compact|comfortable`로 같은 선택을 즉시 적용할 수 있습니다.
테마는 `system`, `light`, `dark`를 지원합니다. 시스템 모드는 Windows 애플리케이션
팔레트의 밝기를 따라 시작 시 결정하고 실행 중 팔레트 변경도 다시 적용합니다. 메인 입력,
메뉴, 목록 카드, 진행률, 로그, 설정과 상세 대화상자는 같은 색상 토큰을 사용하므로 일부
창만 흰 배경이나 흰 글씨로 남지 않습니다. `set-settings --theme system|light|dark`로
실행 중에도 즉시 바꿀 수 있습니다.
일반 설정의 트레이 옵션을 켜면 트레이 메뉴에서 창 표시·숨기기·실행/대기 수 확인·종료를
할 수 있습니다. 닫기 또는 최소화 시 트레이로 숨기는 동작은 각각 따로 선택하며 기본값은
꺼짐입니다. 완료와 오류 알림도 별도로 끌 수 있습니다. `tray status|show|hide|notify`와
`set-settings --tray ...`가 같은 기능을 CLI에서 제공하고 `status --json`은 현재 트레이
사용 가능 여부와 표시 상태를 반환합니다. 트레이 메뉴의 종료는 실행 중 작업이 있으면
기존 중지 확인 창을 그대로 거칩니다.

작품 목록은 작품당 한 줄만 유지하고, 다운로드·전체 재검사·범위 다운로드를 실행할
때마다 별도의 실행 ID를 `runs` 이력에 누적합니다. `info`는 작품 메타데이터와 전체 실행
수를, `runs`는 최대 1000건 범위에서 페이지 단위 이력을, `run-info`는 실행 1건의 요청
범위·발견/선택/처리 회차·PID·시작/종료·오류를 보여줍니다. `run-logs`는 회전된 이전 로그와
현재 로그에서 실행 ID가 붙은 줄만 찾아 마지막 N줄을 반환하고, `run-log --run`은 같은 내용을
GUI 로그창으로 엽니다. `details --job`은 작품 정보를 대표 이미지와 사용자 메모를 포함한
GUI 상세창으로 엽니다. 실행 이력 행을 더블클릭하거나 `선택 실행 로그 보기`를 눌러도 해당
실행 로그창이 열립니다. GUI의 상세창과 우클릭 메뉴
버튼은 각각 `open-folder`, `open-source`, `open-cover`, `set-note`, `runs`, `run-logs`, `run-log`,
`details` 명령으로도 제어하거나 검증할 수 있습니다.

`refresh-metadata --job`은 작품의 기존 저장 폴더를 대상으로 메타데이터와 대표 이미지만
다시 받습니다. 전체 회차 목록은 최신 `episodeCount` 계산을 위해 확인하지만 각 회차
페이지에는 들어가지 않고, 이미지·본문·회차 폴더는 생성하거나 변경하지 않습니다.
새로고침 실행도 `runs`에 `metadata_refresh` 종류로 별도 기록되며 기본적으로 자동화
브라우저 창을 표시하지 않습니다. 제목이나 작가가 사이트에서 바뀌어도 기존 작품 폴더를
자동 이동하거나 이름 변경하지 않아 다운로드 결과 경로를 보존합니다.

`remove-record --yes`는 작품을 GUI 목록과 `jobs.db`에서만 제거합니다. 다운로드한 작품
폴더, 이미지, 표지와 `metadata.json`은 삭제하지 않습니다. 대기 또는 실행 중인 작품은
기록 제거가 거부되며, CLI에서는 실수 방지를 위해 `--yes`가 반드시 필요합니다.
`cleanup-records`도 같은 파일 보존 규칙을 사용하며 `completed`, `error`,
`authentication`, `stopped` 상태를 여러 번 지정할 수 있습니다. `refresh-list`는
SQLite에서 현재 페이지를 다시 읽고 목록용
썸네일 메모리 캐시를 비웁니다. DB 조회가 실패하면 `ok: false`, `refreshed: false`와
종료 코드 2를 반환하고 GUI의 오류 상태를 유지합니다.

작품 목록은 로딩 중, 첫 사용 빈 목록, 검색 결과 없음, 읽기 오류와 정상 목록을 서로 다른
상태로 표시합니다. 빈 목록에서는 URL 입력으로 이동하고, 검색 결과가 없으면 필터를
초기화하며, 오류 상태에서는 목록을 다시 읽을 수 있습니다. `list-state --json`은 GUI 없이
같은 공용 판정 결과를 반환하고, `--apply-gui --preview loading|error|empty|no-results`는
화면 배치와 복구 버튼을 CLI에서 점검할 때만 사용하는 일시적 미리보기입니다.
`--preview auto` 또는 `refresh-list`를 실행하면 실제 목록 상태로 돌아갑니다.
현재 상태는 `status --json`의 `listViewState`에도 포함됩니다.

`도움말 → 키보드 단축키...`는 24개 기본 키와 각 동작의 대응 CLI를 한 표에 표시합니다.
`Ctrl+L`은 URL, `Ctrl+F`는 작품 검색, `F6`은 URL → 검색 → 목록 → 로그 순서로 포커스를
옮깁니다. 목록에서는 방향키로 이동하고 Enter로 상세 정보를 열며, `Ctrl+Shift+Up/Down`은
다른 입력에 포커스가 있어도 이전·다음 작품을 순환 선택합니다. 검색란의 Escape는 검색어를
지웁니다. 신규·범위 재검사, 작업 스냅샷, 그룹 관리, 압축 검사와 중복 작품 검사에도 메뉴에
표시되는 전용 단축키가 있습니다. 선택 작품·실행·일시정지·대기 여부에 따라 작업 메뉴와
상단 다운로드·중지·재검사 버튼을 함께 비활성화하고, 같은 판정은 `status --json`의
`actions`에서 검사할 수 있습니다. `shortcuts --json|--show-gui|--close`와
`focus --target url|search|list|log|next|previous|next-section [--clear]`로 같은 기능을
조회·실행할 수 있고 `status --json`의 `keyboard`에서 포커스와 선택 작업 ID를 확인합니다.

`self-test --json`은 Python/Node 구문, 필수 파일, 단위 테스트와 GUI IPC 및 화면 캡처를
한 번에 검사합니다. GUI가 꺼져 있으면 점검용으로 시작했다가 자동 종료하며, 이미 실행
중이면 종료하지 않습니다. `self-test --via-gui --json`은 GUI의 `자체 점검` 버튼과 같은
비동기 경로를 CLI에서 실행해 검증합니다. 결과는 `logs/self-test.json`, 화면은
`logs/self-test-gui.png`에 저장됩니다. 저장된 작품이 있으면 작품 상세 IPC, 페이지 실행
이력, 실행별 로그와 상세창 캡처도 검사하고 `logs/self-test-work-details.png` 및
`logs/self-test-run-log.png`를 만듭니다. GUI를 전혀 시작하지 않으려면 `--core-only`를
사용합니다.

기본 자체 점검은 사이트에 접속하거나 만화를 받지 않습니다. 실제 사이트 통합 검증은
사용자가 지정한 폴더에 1화만 받도록 다음처럼 명시적으로 실행합니다.

```powershell
.\toki-cli.cmd download --direct --url "https://newtoki1.org/manhwa/34360" --start 1 --last 1 --output "D:\toki-self-test"
```

`retry`는 이전에 지정했던 일부 회차 범위를 반복하는 명령이 아닙니다. 작품의 전체 회차
목록을 다시 수집하고, 이미 저장된 파일은 건너뛰면서 새 회차와 누락 파일만 받습니다.

`stop --job`은 지정한 ID가 실제 현재 실행 작업과 일치할 때만 프로세스를 중지합니다.
`cancel --job`은 아직 시작하지 않은 대기 작업만 큐에서 제거하고 작품·실행 상태를
`취소됨`으로 기록합니다. 둘 다 다운로드 폴더나 이미 저장된 파일은 삭제하지 않으며,
작품 우클릭 메뉴의 `현재 작업 중지`와 `대기 작업 취소`도 같은 서비스 경로를 사용합니다.

`queue list`는 실제 실행 대기 순서를 번호와 함께 반환합니다. `queue move`는 작업 ID를
다른 대기 작업 바로 앞, 맨 앞 또는 맨 뒤로 옮깁니다. GUI 우클릭 메뉴의 `대기열 우선순위`
에서도 맨 앞·맨 뒤 이동을 실행할 수 있고, 대기 상태인 작품 행에는 현재 대기열 번호가
표시됩니다. 순서 변경은 대기 작업에만 허용되며 실행 중이거나 완료된 작업에는 적용되지
않습니다.

`pause --job`은 지정한 현재 작업의 Node 프로세스와 자식 Chrome 프로세스 트리를 Windows
수준에서 함께 일시정지하고, `resume --job`은 같은 PID 트리를 계속 실행합니다. 새
프로세스로 재시작하거나 진행률을 되돌리는 기능이 아니며, 긴 시간 멈추면 사이트 연결이
만료되어 재개 후 해당 작업이 오류로 끝날 수 있습니다. 이 경우 실행 이력과 로그를 확인한
뒤 전체 재검사를 사용합니다. 프로세스 트리 제어에는 `psutil`을 사용하며 `setup-gui.cmd`가
자동으로 설치합니다.

`set-concurrency --works N`은 동시에 실행할 작품 수를 1~4 범위로 설정합니다.
기본값은 1이며 각 작품은 독립된 Node/Chrome 프로세스, 로그 버퍼, 실행 이력과 중지·
일시정지 상태를 갖습니다. `stop`, `pause`, `resume`은 여러 작품이 실행 중일 때도
`--job ID`로 지정한 작품만 제어합니다.

`set-concurrency --images N`은 한 회차 안에서 동시에 내려받을 이미지 수를 1~16 범위로
설정합니다. 기본·권장값은 5입니다. 두 값은 한 명령에 같이 지정하거나 하나만 변경할 수
있으며 `config.json`에 저장됩니다. GUI의 `작품 병렬`, `이미지 병렬`과 `concurrency`
CLI 조회는 같은 값을 사용합니다.

`rescan --mode new`는 작품 목록을 확인한 뒤 로컬 완료 상태에 없는 회차만 받습니다.
받을 회차가 0개면 오류가 아니라 정상 완료로 기록됩니다. `full`은 모든 회차
페이지를 다시 확인하지만 이미 있는 정상 이미지·본문 파일은 건너뛰므로 누락 복구에
사용합니다. `range`는 `--start`, `--last` 중 하나 이상이 필요하며 해당 구간만 검사합니다.
GUI의 `검사 방식` 선택, 작업 메뉴, 작품 우클릭 `작품 재검사`가 같은 서비스를
사용합니다. 기존 `retry`는 `full`의 호환 별칭입니다.

완료 회차는 작품 폴더의 `.toki-state.json`에 기록됩니다. 이전 버전에서 받은 폴더는
파일·폴더명 앞의 회차 번호를 최초 1회 완료 상태로 가져옵니다. 이전 폴더가 불완전하면
`전체 재검사`를 사용해 누락 파일을 복구하세요.

GUI가 비정상 종료된 뒤 다시 시작하면 SQLite 전체의 `대기`, `실행 중`, `일시정지`
작품과 실행 이력을 `중지됨`으로 복구합니다. 목록의 첫 페이지에 보이지 않는 기록도
누락하지 않으며 `status --json`의 `startupRecovery`에서 복구 개수와 ID를 확인할 수
있습니다.

`set-retry-policy --count N --backoff S`는 프로세스 실패 후 자동 재시도 횟수와
기본 대기 초를 설정합니다. 기본값은 2회·2초이고, 대기는 2초→4초→8초처럼 2배씩
늘어나며 최대 300초로 제한됩니다. 횟수는 0~5, 기본 대기는 1~60초 범위입니다.
사용자가 `stop --job ID`로 중지한 작업과 정상 완료는 재시도하지 않으며, `재시도 대기`
상태에서도 같은 작품 ID로 중지할 수 있습니다. 실행 이력에는 실제 시도 횟수와
정책 상한이 함께 남습니다. 설정 변경은 새로 추가하는 작업부터 적용됩니다.

다운로더 오류는 `인증 필요`, `요청 제한`, `네트워크`, `사이트 구조 변경`,
`파일 시스템`, `기타`로 분류되어 작품 행과 실행 이력에 저장됩니다. Cloudflare 확인,
CAPTCHA와 HTTP 403은 `인증 필요`로 끝내고 무의미한 자동 재시도를 하지 않습니다.
`run-info --run 실행ID`로 분류와 자동 재시도 가능 여부를 확인할 수 있습니다.

`move-folder`는 새 저장 루트 아래에 기존 사이트 폴더와 작품 폴더명을 유지한 목적지를
계산합니다. 기본 동작과 `--dry-run`은 파일을 건드리지 않고 원본·목적지·충돌 여부만
보여줍니다. 실제 이동은 `--execute --yes`가 모두 있어야 하며, GUI에서는 작품 우클릭
`작품 폴더 이동...`에서 목적지를 미리 보여준 뒤 한 번 더 확인합니다. 목적지 폴더가 이미
있거나 작품이 실행 중이면 이동하지 않습니다. 파일 이동이 끝난 뒤에만 작품 기록의
저장 루트·표지·메타데이터 경로를 갱신하고, 기록 저장이 실패하면 원위치 복구를 시도합니다.

`rebuild-metadata`는 사이트에 접속하지 않고 작품 DB, 현재 폴더명과 읽을 수 있는 기존
`metadata.json`을 합쳐 로컬 메타데이터를 다시 만듭니다. 기본 동작은 미리보기이며 실제
쓰기는 `--execute --yes`가 모두 필요합니다. 기존 파일은 `metadata.json.bak`으로 먼저
백업하고 임시 파일을 완성한 뒤 원자적으로 교체합니다. 설명·장르·연재 상태처럼 기존에만
있는 값은 보존하며, 손상된 파일은 DB와 `[작가][그룹] 제목` 폴더명에서 핵심 필드를
복구합니다. GUI에서는 작품 우클릭 `로컬 메타데이터 재생성...`에서 같은 기능을 확인 후
실행할 수 있습니다.

`verify-files`는 작품 폴더를 변경하지 않는 읽기 전용 검사입니다. 완료 상태 대비 누락
회차, 같은 번호의 중복 폴더, 이미지가 없는 회차, 0바이트 파일, JPG·PNG·WebP·GIF·BMP·
AVIF 이미지 서명 불일치, 손상된 `metadata.json`과 `.toki-state.json`을 구분해 반환합니다.
문제가 없으면 종료 코드 0, 문제가 발견되면 결과 JSON을 출력한 뒤 종료 코드 2를 사용합니다.
`--issue-limit`으로 상세 문제 배열 크기를 제한할 수 있어 수천 파일에서도 출력이 무한히
커지지 않습니다. GUI 우클릭 `보유 회차·파일 검사`와 `--show-gui`는 같은 CLI 검사를 별도
프로세스로 실행하므로 검사 중에도 작품 목록과 창 조작이 멈추지 않습니다.

`preview`는 보유 회차 번호와 이미지 파일을 자연 숫자 순서로 조회합니다. 기본 200장,
최대 1,000장 범위에서 `--limit`·`--offset` 페이지 조회를 지원하며 `--episode`를 생략하면
첫 보유 회차를 선택합니다. `--show-gui` 또는 작품 우클릭 `회차 이미지 미리보기`는 회차
선택과 이미지 목록, 원본 열기 버튼을 제공하며 선택한 한 장만 최대 1400×1000 크기로 Qt
스레드 풀에서 축소 디코딩합니다. 따라서 작품 전체 이미지나 한 회차의 모든 이미지를 GUI
메인 스레드에서 한꺼번에 읽지 않습니다.

`convert-images`는 JPG·PNG·WebP 변환을 지원하며 결과를 작품 폴더 아래
`_converted\형식\기존 회차 폴더`에 생성합니다. 원본은 덮어쓰거나 삭제하지 않고, 같은
결과 파일이 있으면 건너뛰므로 중단 후 다시 실행할 수 있습니다. 기본 동작은 `dry-run`이고
실제 대량 파일 생성에는 `--execute --yes`가 모두 필요합니다. GUI도 먼저 대상 수·기존
결과·출력 경로를 보여준 뒤 `변환 실행...`에서 다시 확인합니다. 실행 중에는 처리 수와
완료·건너뜀·실패 수가 갱신되며 `변환 중지` 버튼 또는 `cancel-conversion` CLI로 중지할
수 있습니다. 각 이미지는 `.tmp` 파일을 완성한 뒤 원자적으로 교체하므로 중지해도 원본은
그대로이고, 다음 실행은 남은 임시 파일을 정리한 뒤 기존 완성 결과를 건너뜁니다.
`--progress-json`은 진행 이벤트와 최종 결과를 한 줄씩 JSON으로 출력하며 사용자 중지는
종료 코드 3을 사용합니다. 투명 이미지를 JPEG로 변환할 때는 흰 배경 RGB로 합성합니다.
선택 기능이므로 다음 명령으로 Pillow와 ImageHash를 설치합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-image-tools.txt
```

`duplicates images`는 지정 작품의 이미지 파일을 삭제하거나 수정하지 않는 읽기 전용
검사입니다. `sha256`은 파일 내용이 완전히 같은 이미지를 제한된 I/O 스레드 풀로 찾고,
선택 기능인 `phash`는 Pillow·ImageHash와 제한된 CPU 프로세스 풀을 사용해 시각적으로
유사한 이미지를 찾습니다. 결과에는 검사 파일 수, 중복 그룹, 관련 이미지, 사용한 풀과
작업자 수가 포함됩니다.

GUI 없이 기존 방식으로 바로 실행하려면 다음 명령을 사용할 수 있습니다.

```powershell
.\toki-cli.cmd download --direct --url "https://newtoki1.org/manhwa/34732" --start 1 --last 1 --output "D:\Manga"
```

자동화 브라우저는 개인 Chrome 계정과 분리된 전용 프로필을 사용합니다.
기본값은 창이 보이지 않는 백그라운드 실행입니다. Cloudflare 인증이나 사이트 오류를
직접 확인할 때만 GUI의 `브라우저 표시`를 켜거나 CLI에 `--show-browser`를 추가하세요.
개인 Chrome 프로필이나 쿠키를 자동으로 가져오거나 접근 제한을 우회하지 않습니다.

Windows에서 콘솔 창 없이 프로그램을 열려면 `start-gui.vbs`를 더블클릭하세요.
기존 `start-gui.cmd`도 지원하지만 시작할 때 명령 프롬프트가 한 번 보일 수 있습니다.
GUI가 실행하는 Node·Python 작업은 출력과 진행률을 유지하면서 Windows
`CREATE_NO_WINDOW`로 실행하므로 다운로드·점검·미리보기·변환 중 콘솔 창을 만들지
않습니다.

## 설치 방법
```bash
git clone https://github.com/crossSiteKikyo/tokiDownloader.git
cd tokiDownloader
npm install
```
https://github.com/user-attachments/assets/b3879c59-3381-407b-a3a8-ad8bf8d84cbb
## 명령어
```bash
node down -url "URL" [-scan-mode new|full|range] [-start STARTINDEX] [-last LASTINDEX] [-output "폴더 경로"] [-image-concurrency 1~16] [-metadata-only] [-content-path "기존 작품 폴더"]
```
- -url은 필수 입력입니다. 반드시 큰따옴표 안에 넣어주세요.
- -start는 옵션입니다. 받고싶은 회차 시작 번호를 입력하세요. 생략하면 처음부터 받습니다.
- -last는 옵션입니다. 받고싶은 마지막 회차 번호를 입력하세요. 생략하면 마지막까지 받습니다.
- -output은 옵션입니다. 저장할 기준 폴더를 지정하며, 생략하면 현재 실행 폴더에 저장합니다.
- -image-concurrency는 한 회차에서 동시에 받을 이미지 수이며 기본값은 5입니다.
- -scan-mode는 신규·전체·범위 검사를 분리합니다. 옵션을 생략한 기존 CLI는 하위 호환을 위해 전체 검사로 동작합니다.
- -metadata-only는 회차를 받지 않고 메타데이터와 대표 이미지만 다시 받습니다.
- -content-path는 메타데이터 전용 실행이 사용할 기존 작품 폴더를 직접 지정합니다.
- 대괄호(`[]`)는 옵션이라는 뜻이므로 명령어에 직접 입력하지 마세요.

예시
```bash
node down -url "https://newtoki1.org/manhwa/34732"
node down -url "https://newtoki1.org/manhwa/34732" -start 1 -last 10
node down -url "https://newtoki1.org/manhwa/34732" -start 1 -last 10 -output "D:\Manga"
```

`newtoki숫자.org/manhwa/` 주소는 실제 페이지 종류에 맞춰 마나토끼 폴더에 저장됩니다.

https://github.com/user-attachments/assets/86c17334-c96c-48d2-bfdb-31072766030c

## 폴더(디렉토리) 구조
```
뉴토끼/
├─ [작가][그룹] 웹툰이름1/
│   ├─ metadata.json
│   ├─ 0001 어떤웹툰-1화/
│   │   ├─ 0001 어떤웹툰-1화 image0000.jpg
│   │   ├─ 0001 어떤웹툰-1화 image0001.jpg
│   │   ...
│   │   └─ 0001 어떤웹툰-1화 image0024.jpg
│   └─ 0002 어떤웹툰-2화/
│       ├─ 0002 어떤웹툰-2화 image0000.jpg
│       ├─ 0002 어떤웹툰-2화 image0001.jpg
│       ...
│       └─ 0002 어떤웹툰-2화 image0020.jpg
└─ 웹툰이름2/

마나토끼/
├─ [작가][N／A] 만화이름1/
│   ├─ metadata.json
│   ├─ 0001 어떤만화-1화/
│   │   ├─ 0001 어떤만화-1화 image0000.jpg
│   │   ├─ 0001 어떤만화-1화 image0001.jpg
│   │   ...
│   │   └─ 0001 어떤만화-1화 image0015.jpg
│   └─ 0002 어떤만화-2화/
│       ├─ 0002 어떤만화-2화 image0000.jpg
│       ├─ 0002 어떤만화-2화 image0001.jpg
│       ...
│       └─ 0002 어떤만화-2화 image0032.jpg
└─ 만화이름2/

북토끼/
├─ [작가][그룹] 소설이름1/
│   ├─ metadata.json
│   ├─ 0001 어떤소설-1화.txt
│   ├─ 0001 어떤소설-2화.txt
│   ...
│   └─ 0002 어떤소설-20화.txt
└─ 소설이름2/
```
## 질문
### 오류 또는 개선사항 문의 
[issue](https://github.com/crossSiteKikyo/tokiDownloader/issues) 에 제보해주세요. 스크립트방식인지 다운로더인지, 어떤 링크를 시도한건지 어떤 오류가 난건지 상세히 적어주셔야 해결 가능합니다.
### cloudflare captcha 자동으로 체크해주실 수 없나요?
전에는 라이브러리에 오류가 있었는데 지금은 자동 체크 합니다.
