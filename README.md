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
메모리 전용 내장 브라우저를 사용하려면 `setup-gui.cmd -WithBrowserTools`를 사용합니다.
Windows 자격 증명 저장소 기반 쿠키 관리까지 사용하려면
`setup-gui.cmd -WithSecurityTools`를 사용합니다.

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
.\toki-cli.cmd archive-viewer status --json
.\toki-cli.cmd archive-viewer set --mode system --json
.\toki-cli.cmd archive-viewer set --mode custom --path "C:\Program Files\7-Zip\7zFM.exe" --json
.\toki-cli.cmd archive-viewer open --path "D:\Manga\work.cbz" --json
.\toki-cli.cmd archive-viewer open --path "D:\Manga\work.cbz" --execute --yes --json
.\toki-cli.cmd persistence status --json
.\toki-cli.cmd persistence set --autosave-seconds 3 --startup-recovery on --json
.\toki-cli.cmd persistence recover --json
.\toki-cli.cmd persistence recover --show-gui
.\toki-cli.cmd persistence recover --execute --yes --json
.\toki-cli.cmd persistence recover --close
.\toki-cli.cmd list-performance status --json
.\toki-cli.cmd list-performance set --page-size 200 --loaded-limit 2000 --scroll-lines 3 --lazy-loading on --low-spec off --json
.\toki-cli.cmd memory status --child-limit 200 --json
.\toki-cli.cmd memory set --display on --json
.\toki-cli.cmd local-api status --json
.\toki-cli.cmd local-api set --state off --port 8765 --json
.\toki-cli.cmd local-api request --path "/v1/health" --json
.\toki-cli.cmd local-api request --method POST --path "/v1/control" --body '{"action":"memory_status"}' --json
.\toki-cli.cmd local-api token --copy --yes --json
.\toki-cli.cmd local-api token --rotate --yes --json
.\toki-cli.cmd hitomi status --json
.\toki-cli.cmd hitomi inspect --input "https://hitomi.la/manga/sample-1234567.html" --json
.\toki-cli.cmd hitomi inspect --input "1234567" --provider hitomi --show-gui --json
.\toki-cli.cmd hitomi server status --json
.\toki-cli.cmd hitomi server set --mode auto --priority hitomi,exhentai,ehentai --json
.\toki-cli.cmd hitomi server set --mode manual --manual-server ehentai --json
.\toki-cli.cmd hitomi server plan --input "https://exhentai.org/g/987654/abcdef1234/" --json
.\toki-cli.cmd hitomi metadata status --json
.\toki-cli.cmd hitomi metadata set --mode auto --json
.\toki-cli.cmd hitomi metadata plan --input "https://hitomi.la/manga/sample-1234567.html" --json
.\toki-cli.cmd hitomi metadata parse --input "https://hitomi.la/manga/sample-1234567.html" --fixture ".\tests\fixtures\hitomi\galleryinfo_1234567.js" --json
.\toki-cli.cmd hitomi metadata show --input "https://hitomi.la/manga/sample-1234567.html" --json
.\toki-cli.cmd hitomi metadata fetch --input "https://hitomi.la/manga/sample-1234567.html" --yes --json
.\toki-cli.cmd hitomi metadata fetch --input "https://exhentai.org/g/987654/TOKEN/" --use-cookies --yes --json
.\toki-cli.cmd hitomi metadata close --json
.\toki-cli.cmd hitomi filenames status --json
.\toki-cli.cmd hitomi filenames set --mode number_original --json
.\toki-cli.cmd hitomi filenames plan --input "1234567" --fixture ".\tests\fixtures\hitomi\galleryinfo_1234567.js" --mode number_original --sample-limit 20 --json
.\toki-cli.cmd hitomi tags status --json
.\toki-cli.cmd hitomi tags set --tags "guro,female:full color" --json
.\toki-cli.cmd hitomi tags evaluate --input "1234567" --fixture ".\tests\fixtures\hitomi\galleryinfo_1234567.js" --json
.\toki-cli.cmd hitomi tags set --clear --json
.\toki-cli.cmd hitomi title status --json
.\toki-cli.cmd hitomi title set --prefer-japanese on --json
.\toki-cli.cmd hitomi title select --input "1234567" --fixture ".\tests\fixtures\hitomi\galleryinfo_1234567.js" --json
.\toki-cli.cmd hitomi metadata-files status --json
.\toki-cli.cmd hitomi metadata-files set --mode metadata_json --json
.\toki-cli.cmd hitomi metadata-files plan --input "1234567" --fixture ".\tests\fixtures\hitomi\galleryinfo_1234567.js" --output "C:\작품 폴더" --mode both --json
.\toki-cli.cmd hitomi metadata-files write --input "1234567" --fixture ".\tests\fixtures\hitomi\galleryinfo_1234567.js" --output "C:\작품 폴더" --mode both --yes --json
.\toki-cli.cmd hitomi images status --json
.\toki-cli.cmd hitomi images set --original on --json
.\toki-cli.cmd hitomi images plan --input "1234567" --fixture ".\tests\fixtures\hitomi\galleryinfo_1234567.js" --original off --json
.\toki-cli.cmd hitomi close --json
.\toki-cli.cmd sleep-prevention status --json
.\toki-cli.cmd sleep-prevention set --state on --json
.\toki-cli.cmd sleep-prevention plan --active-downloads 2 --json
.\toki-cli.cmd pdf status --json
.\toki-cli.cmd pdf set --automatic off --json
.\toki-cli.cmd pdf plan --job 작업ID --json
.\toki-cli.cmd pdf generate --job 작업ID --show-gui
.\toki-cli.cmd pdf generate --job 작업ID --execute --yes --progress-json
.\toki-cli.cmd pdf cancel --job 작업ID
.\toki-cli.cmd pdf close
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
.\toki-cli.cmd convert-images --close
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
.\toki-cli.cmd browser-mode status --json
.\toki-cli.cmd browser-mode set headless --json
.\toki-cli.cmd embedded-browser capabilities --json
.\toki-cli.cmd embedded-browser plan --url "https://newtoki1.org/manhwa/34360" --json
.\toki-cli.cmd embedded-browser manage --show-gui --url "https://newtoki1.org/manhwa/34360" --json
.\toki-cli.cmd embedded-browser manage --show-gui --url "https://newtoki1.org/manhwa/34360" --navigate --yes --json
.\toki-cli.cmd embedded-browser manage --close --json
.\toki-cli.cmd network-policy status --url "https://newtoki1.org/manhwa/34360" --json
.\toki-cli.cmd network-policy set --speed-limit-kib 2048 --provider manatoki --request-delay-ms 250 --backoff 4 --json
.\toki-cli.cmd proxy-auth capabilities --json
.\toki-cli.cmd proxy-auth status --yes --json
"비밀번호" | .\toki-cli.cmd proxy-auth set --username "proxy-user" --password-stdin --yes --json
.\toki-cli.cmd proxy-auth clear --yes --json
.\toki-cli.cmd proxy-auth manage --show-gui --json
.\toki-cli.cmd public-ip plan --json
.\toki-cli.cmd public-ip check --yes --json
.\toki-cli.cmd cookies capabilities --json
.\toki-cli.cmd cookies policy --provider exhentai --json
.\toki-cli.cmd cookies plan-import --provider exhentai --input "D:\cookies.json" --yes --json
.\toki-cli.cmd cookies status --provider manatoki --yes --json
.\toki-cli.cmd cookies import --provider manatoki --input "D:\cookies.json" --yes --json
.\toki-cli.cmd cookies export --provider manatoki --output "D:\cookies-backup.json" --yes --json
.\toki-cli.cmd cookies clear --provider manatoki --yes --json
.\toki-cli.cmd cookies manage --provider manatoki --show-gui --json
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

자동화 브라우저는 기본 `headless`라 다운로드 중 별도 Chrome 창을 띄우지 않습니다.
`browser-mode set visible`은 사이트 인증이나 화면 선택자 문제를 직접 확인할 때만 사용하는
진단 모드이며 개인 Chrome 계정·프로필을 연결하지 않습니다. 확인 후
`browser-mode set headless`로 되돌리면 다음 실행부터 다시 백그라운드로 동작합니다.

선택형 내장 브라우저는 `PyQt6-WebEngine`을 설치한 경우에만 활성화됩니다. 기본 화면은
외부 요청이 없는 오프라인 안내 페이지이고, 주소를 입력해 실제 HTTPS 사이트로 이동할 때
GUI에서 매번 호스트를 확인합니다. 개인 Chrome·자동화 브라우저와 분리된 메모리 전용
프로필을 사용하며 영구 쿠키를 저장하지 않고 파일 다운로드와 새 팝업 창도 차단합니다.
`embedded-browser plan`은 네트워크 없이 URL과 전송 경계를 검사합니다. `manage --show-gui
--url URL`은 주소만 미리 채우고 이동하지 않으며, CLI에서 실제 이동하려면 `--navigate
--yes`가 함께 필요합니다.

`network-policy`는 HTTP/HTTPS/SOCKS4/SOCKS5 프록시, 전체 이미지 대역폭 제한과
마나토끼·뉴토끼·북토끼별 최소 요청 간격·지수 백오프를 관리합니다. 속도 0은 무제한이고
그 외에는 32~1048576 KiB/s입니다. 대역폭 제한기는 동시 이미지 스레드 전체가 하나의
스케줄을 공유하므로 연결 수만큼 제한이 배로 늘지 않습니다. 프록시는 브라우저 탐색과 별도
이미지 요청에 함께 적용됩니다. 사용자명·비밀번호가 든 URL은 평문 저장을 막기 위해
거부합니다. 선택적 인증은 `proxy-auth`로 관리하며 사용자명·비밀번호를 현재 프록시 주소에
묶어 Windows 자격 증명 저장소에만 보관합니다. 저장 정보는 주소가 정확히 일치할 때만
다운로드 자식 프로세스 환경으로 전달되고 명령행 인자·설정 파일·로그·상태 JSON에는
비밀번호를 넣지 않습니다. 브라우저도 인증 출처가 프록시인 요청에만 응답하며 사이트 자체의
HTTP 인증 요청에는 프록시 자격증명을 보내지 않습니다. 상태 읽기·저장·삭제에는 `--yes` 또는 GUI 재확인이 필요합니다.
자동화에서는 비밀번호가 프로세스 인자에 노출되지 않도록 `--password-stdin`을 사용합니다.

공급자 쿠키 관리는 선택 설치한 `keyring`을 통해 Windows 자격 증명 저장소를 사용합니다.
JSON 배열과 Netscape 쿠키 파일을 최대 5 MiB·10,000개 한도로 검사하며
`cookies policy`는 비밀값을 읽지 않고 공급자별 도메인·인증 정책만 보여줍니다.
`cookies plan-import`는 저장하지 않고 관련 쿠키 개수와 도메인만 보여주지만 민감 파일을
읽으므로 `--yes`가 필요합니다. 상태 읽기, 가져오기, 평문 JSON 내보내기와 초기화도 모두
`--yes`가 필요하고 GUI도 매번 확인합니다. 상태 화면과
로그에는 쿠키 값을 표시하지 않습니다. 내보낸 JSON은 민감한 평문 파일이므로 개인 보안
경로에서만 보관해야 합니다.

`public-ip plan`은 외부 요청 주소와 전송 범위만 보여주며 네트워크를 사용하지 않습니다.
실제 `public-ip check`는 `api.ipify.org`에 쿠키·다운로드 파일 없이 HTTPS 요청을 보내므로
명시적인 `--yes` 또는 GUI 확인이 필요합니다.

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
환경으로 검사합니다. npm은 설치 도구로, Pillow·ImageHash·py7zr·rarfile·PyQt6-WebEngine·FFmpeg·yt-dlp·PyInstaller는 선택 기능으로
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

`archive-viewer`는 압축 검사창의 `연결 프로그램으로 열기` 버튼과 같은 앱 내부 정책을
제어합니다. `system`은 Windows 기본 연결 프로그램을 사용하고, `custom`은 사용자가 고른
실행 파일에 압축 경로를 단일 인자로 전달합니다. `open`은 기본적으로 실행 계획만 보여주며
실제 외부 프로그램 실행에는 `--execute --yes`가 모두 필요합니다. 이 설정과 실행은 Windows
시스템 파일 연결이나 레지스트리를 변경하지 않으며 압축 원본도 수정하지 않습니다.

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

고급 설정의 `알림음`과 `메시지 상자`는 완료·오류 알림의 전달 방식을 보강합니다. 기본값은
둘 다 꺼짐이며, 알림 대상 작업은 트레이 사용 여부와 관계없이 메인 상태 표시줄에 5초 동안
메시지를 남깁니다. `시스템 알림음`을 켜면 Windows 기본 알림음을 재생하고 `메시지 상자`를
켜면 다운로드를 멈추지 않는 별도 완료·오류 창을 표시합니다. 최종 재시도까지 끝난 작업만
알리며 중지된 작업은 알리지 않습니다.

```powershell
.\toki-cli.cmd notifications status --json
.\toki-cli.cmd notifications set --complete on --error on --sound system --message-box on --json
.\toki-cli.cmd notifications preview --kind complete --title "알림 미리보기 작품" --json
.\toki-cli.cmd notifications close --json
```

`preview`는 현재 저장 설정으로 상태 표시줄·트레이·메시지 상자·알림음을 실제 시험하고 각
전달 성공 여부를 JSON으로 반환합니다. 열린 미리보기 창은 `close`로 정리할 수 있으며
`status --json`의 `notifications`와 `notifications status --json`에서 마지막 결과와 열린
메시지 상자 수를 확인할 수 있습니다.

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

`도움말 → 키보드 단축키...`는 24개 기본 키와 각 동작의 대응 CLI를 한 표에 표시하고,
선택 동작의 키를 즉시 편집·비활성화·기본값 복원할 수 있습니다. 키 여러 개는 세미콜론으로
구분해 최대 4개까지 지정합니다. 다른 동작과의 충돌, 수정 키 없는 단일 문자와 `Alt+F4`는
저장 전에 거부하며 빈 키 목록은 해당 동작을 비활성화합니다. JSON 파일 가져오기는 먼저
변경 개수를 보여주고 확인 뒤 적용하며, 내보내기 파일에는 단축키 덮어쓰기만 들어가고
쿠키·프록시 인증 같은 비밀값은 포함하지 않습니다.

`Ctrl+L`은 URL, `Ctrl+F`는 작품 검색, `F6`은 URL → 검색 → 목록 → 로그 순서로 포커스를
옮깁니다. 목록에서는 방향키로 이동하고 Enter로 상세 정보를 열며, `Ctrl+Shift+Up/Down`은
다른 입력에 포커스가 있어도 이전·다음 작품을 순환 선택합니다. 검색란의 Escape는 검색어를
지웁니다. 신규·범위 재검사, 작업 스냅샷, 그룹 관리, 압축 검사와 중복 작품 검사에도 메뉴에
표시되는 전용 단축키가 있습니다. 선택 작품·실행·일시정지·대기 여부에 따라 작업 메뉴와
상단 다운로드·중지·재검사 버튼을 함께 비활성화하고, 같은 판정은 `status --json`의
`actions`에서 검사할 수 있습니다. `shortcuts --json|--show-gui|--close`와
`focus --target url|search|list|log|next|previous|next-section [--clear]`로 같은 기능을
조회·실행할 수 있고 `status --json`의 `keyboard`에서 포커스와 선택 작업 ID를 확인합니다.

```powershell
.\toki-cli.cmd shortcuts --set focus.search --keys "Ctrl+Alt+F;F9" --json
.\toki-cli.cmd shortcuts --disable search.clear --json
.\toki-cli.cmd shortcuts --reset focus.search --json
.\toki-cli.cmd shortcuts --reset-all --json
.\toki-cli.cmd shortcuts --export ".\toki-shortcuts.json" --json
.\toki-cli.cmd shortcuts --import ".\toki-shortcuts.json" --json
.\toki-cli.cmd shortcuts --import ".\toki-shortcuts.json" --execute --yes --json
```

가져오기는 기본적으로 읽기 전용 미리보기이며 실제 적용은 `--execute --yes`를 함께 지정해야
합니다. GUI가 실행 중이면 같은 설정을 IPC로 적용해 QAction 키가 즉시 바뀝니다.

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

변경된 작품 상태는 기본 1초 주기로 묶어 SQLite에 자동 저장합니다. `persistence set
--autosave-seconds N`으로 1~300초 범위에서 바꿀 수 있고, 설정을 적용하면 실행 중 타이머에도
즉시 반영됩니다. 매번 전체 목록을 다시 쓰지 않고 변경된 작품 ID만 저장합니다.

GUI가 비정상 종료된 뒤 다시 시작하면 SQLite 전체의 `대기`, `실행 중`, `일시정지`,
`재시도 대기` 작품과 실행 이력을 `중지됨`으로 복구합니다. 목록의 첫 페이지에 보이지 않는
기록도 누락하지 않으며 진행률과 다운로드 파일은 그대로 보존합니다. `persistence status`와
`status --json`의 `startupRecovery`에서 복구 개수와 ID를 확인할 수 있습니다. 시작 복구는
고급 설정 또는 `persistence set --startup-recovery on|off`로 제어합니다. 수동
`persistence recover`는 기본 읽기 전용 미리보기이고 실제 DB 상태 변경에는 `--execute
--yes`가 모두 필요합니다. 현재 GUI에 실행·대기 작업이 있으면 수동 복구를 차단합니다.

작품 목록은 SQLite에서 페이지 단위로 조회하고 화면에 보이는 표지만 디코딩합니다. 고급
설정과 `list-performance set`에서 페이지 크기(25~1,000개), 메모리 내 작품 상한
(100~5,000개), 휠 스크롤 속도(1~20단계), 지연 로딩과 저사양 모드를 바꿀 수 있으며 실행
중인 GUI에도 즉시 반영됩니다. 지연 로딩을 끄면 설정한 메모리 상한까지 처음부터 읽는
명시적 eager 모드가 됩니다. 저사양 모드는 저장된 사용자 값을 덮어쓰지 않고 실행 중
유효값만 페이지 100개·메모리 500개·스크롤 3단계·지연 로딩 켜짐으로 제한하고 썸네일을
숨긴 뒤 메모리 썸네일 캐시도 32개로 줄입니다. 모드를 끄면 원래 설정으로 돌아갑니다.
`list-performance status --json`과 `status --json`의 `listPerformance`에서 설정값,
유효값, 현재 적재 수와 픽셀 스크롤 단계를 함께 확인할 수 있습니다.

상태 표시줄의 메모리 막대는 기본적으로 켜져 있으며 시스템 RAM 사용률과 tokiDownloader
앱·자식 작업 프로세스의 RSS 합계를 `RAM 68% · 앱 149 MiB` 형식으로 구분해 표시합니다.
2초마다 읽기 전용으로 갱신하며 시스템 사용률 80% 이상은 `warning`, 90% 이상은
`critical`로 분류합니다. 메모리 제한이나 Windows 설정을 변경하지 않습니다. 고급 설정 또는
`memory set --display on|off`로 표시만 켜고 끌 수 있으며, `memory status --json`은 앱 자체,
모든 자식 프로세스, 시스템 전체·가용 메모리와 현재 GUI에서 추적하는 다운로드·이미지 변환·
PDF 작업별 프로세스 합계를 반환합니다. `--child-limit 0~1000`으로 상세 프로세스 배열 크기를
제한할 수 있지만 앱 합계에는 생략된 자식도 포함됩니다. `status --json`의 `memoryUsage`에서도
같은 현재 값을 확인할 수 있습니다.

로컬 HTTP API는 기본적으로 꺼져 있고 켜더라도 `127.0.0.1`에만 바인딩합니다. 기본 포트는
8765이며 고급 설정 또는 `local-api set --state on|off --port N`으로 바꿉니다. 서버를 시작할
때마다 32바이트 기반 임시 Bearer 토큰을 새로 만들고 설정 파일·DB·로그에는 원문을 저장하지
않습니다. 상태 조회에는 토큰 뒤 6자리만 표시하며 원문 표시·클립보드 복사·재발급에는 각각
`local-api token --show|--copy|--rotate --yes`처럼 명시적 확인이 필요합니다. CORS를 열지 않고
공개 주소 바인딩도 지원하지 않습니다.

인증된 `GET /v1/health`, `GET /v1/status`, `GET /v1/jobs?limit=200&offset=0`과
`POST /v1/control`을 제공합니다. 제어 경로는 GUI와 같은 서비스 계약을 사용하지만 다운로드
추가·중지·일시정지·재시도·안전한 조회/필터 설정 등 문서화된 허용 목록으로 제한합니다.
기록 삭제, 파일 이동·변환, 쿠키, 시스템 종료, 토큰 관리와 프로그램 종료는 HTTP API에서
거부합니다. 요청 본문은 최대 64 KiB이고 작품 목록은 최대 1,000개 페이지로 제한됩니다.
`local-api request`는 토큰을 화면에 출력하지 않고 현재 GUI의 임시 토큰을 로컬 IPC로 받아
루프백 API를 점검합니다. API를 켠 설정만 저장하고 GUI가 꺼져 있으면 서버는 실행되지
않습니다.

Hitomi/ExHentai 선택 공급자의 첫 단계로 URL·갤러리 ID 분석기를 제공합니다. `hitomi
inspect --input URL_OR_ID --provider auto|hitomi|exhentai --json`은 외부 네트워크를 전혀
사용하지 않고 공급자, 숫자 갤러리 ID, `hitomi:ID` 또는 `exhentai:ID` 작품 식별자를
반환합니다. Hitomi의 작품·리더·갤러리 URL과 ExHentai/E-Hentai의 `/g/ID/TOKEN/` 형식을
구분하며 잘못된 입력에는 `hitomi.*` 네임스페이스의 안정적인 오류 코드를 냅니다.
ExHentai 갤러리 토큰은 유효성만 확인하고 결과·로그·설정에 원문을 남기지 않으며 끝 4자리
힌트만 표시합니다. `--show-gui`로 같은 분석기를 GUI 대화상자에서 열고 `hitomi close`로
닫을 수 있습니다. 현재 이 명령은 식별자 분석 전용이며 `hitomi status`가 `networkRequest:
false`, `download: false`, `metadata: true`, `imageFilenamePolicy: true`,
`excludedTagPolicy: true`, `japaneseTitlePolicy: true`, `metadataFileGeneration: true`,
`originalImagePolicy: true`, `userOwnedCookieAuthentication: true`로 구현 범위를 명확히
표시합니다.
접근 제한 우회는 구현하지 않습니다. 프로그램 자체 캡처는
`logs\hitomi-reference-inspector.png`와 `logs\hitomi-provider-settings.png`에 저장됩니다.

설정 스키마 v16은 Hitomi 서버 방식을 `auto` 또는 `manual`로 저장합니다. 자동 방식은
`hitomi`, `exhentai`, `ehentai` 세 서버의 중복 없는 전체 우선순위를 사용한 뒤 입력 URL의
공급자와 호환되는 후보만 남깁니다. 수동 방식은 지정 서버 하나만 사용하며 Hitomi 작품에
ExHentai 서버를 고르는 것처럼 호환되지 않는 조합은 `hitomi.server_incompatible`로
거부합니다. `hitomi server status|set|plan`과 공급자 설정 탭의 방식·서버·드래그 우선순위가
같은 정책을 사용하고, `plan`은 실제 접속 없이 선택 서버와 대체 후보를 계산합니다. 설정
마이그레이션 후 기본값은 자동, 수동 후보 Hitomi.la, 순서 Hitomi.la → ExHentai → E-Hentai로
복원됩니다. 화면은 `logs\hitomi-server-settings.png`에 저장됩니다.

설정 스키마 v17은 갤러리 정보 방식을 `auto`, `required`, `disabled`로 저장합니다. 자동은
메타데이터 실패 시 이후 다운로드를 계속할 정책이고, 필수는 중단, 사용 안 함은 요청 계획도
만들지 않습니다. Hitomi는 `galleryinfo` JS에서 JSON 객체만 추출하고 코드를 실행하지 않으며,
ExHentai/E-Hentai는 [공식 gdata API 형식](https://ehwiki.org/wiki/API)의 JSON을 공통 제목,
일본어 제목, 작가·그룹·태그, 페이지 수, 썸네일 정보로 정규화합니다. 응답과 픽스처는 8 MiB로
제한합니다.

`hitomi metadata plan`은 메서드·엔드포인트와 마스킹한 본문만 계산하고 외부 접속을 하지
않습니다. `parse --fixture PATH`는 사이트 변경 회귀 검사용 로컬 JS/JSON을 읽으며 한글·공백
Windows 경로를 지원합니다. `fetch --yes`만 실제 외부 요청을 실행하고 기본값은 저장 쿠키를
읽지 않습니다. 인증이 필요한 사용자 소유 세션을 명시적으로 쓰려면
`fetch --use-cookies --yes`를 사용하거나 GUI의 `OS 보안 저장소의 선택 공급자 쿠키 사용`을
체크한 뒤 목적지와 쿠키 읽기를 다시 확인합니다. ExHentai 관련 쿠키는 E-Hentai/ExHentai
도메인만 보관하며 요청 호스트·경로·Secure·만료 조건에 맞는 값만 해당 요청의 `Cookie`
헤더에 주입합니다. 쿠키 값은 결과 JSON·상태·설정·로그에 남기지 않고 접근 제한 우회는
지원하지 않습니다. GUI 조회는 제한형 I/O 풀에서 동작합니다. ExHentai
갤러리 토큰은 POST 요청 메모리에만 존재하고 계획·결과·설정·로그에는 원문을 남기지
않습니다. 로컬 검증 화면은 `logs\hitomi-metadata-plan.png`,
`logs\hitomi-metadata-fixture.png`, `logs\hitomi-metadata-settings.png`에 있습니다. 실제 공급자
요청 검증은 사용자 승인 전에는 실행하지 않습니다.

설정 스키마 v18은 Hitomi 이미지 파일명을 `original`, `number`, `number_original` 중 하나로
저장하며 기본값은 식별성과 자연 정렬을 함께 보존하는 `0001_원본.jpg` 방식입니다. 공용
파일명 계획은 Windows 금지 문자·예약 장치 이름·경로 구분자를 제거하고, 대소문자까지 같은
중복 이름에는 `(2)` 카운터를 붙여 덮어쓰기를 막습니다. 숫자 자릿수는 최소 4자리이고 최대
100,000장까지 계산하되 CLI 결과에는 요청한 최대 1,000개 샘플만 담아 대형 갤러리에서도
출력과 GUI를 막지 않습니다. E-Hentai `gdata`처럼 원본 이름이 없는 요약에서 `original` 또는
`number_original`을 요청하면 임의로 다른 정책으로 바꾸지 않고
`hitomi.filename_original_missing` 오류를 냅니다. `hitomi filenames status|set|plan`과 공급자
설정 탭이 같은 서비스를 사용하며, `plan --fixture`는 네트워크 없이 실제 저장 이름을
미리 확인합니다. 검증 화면은 `logs\hitomi-filename-settings.png`에 있습니다.

설정 스키마 v19는 최대 500개의 Hitomi 제외 태그를 저장합니다. 공급자 설정의 여러 줄
입력창 또는 `hitomi tags set --tags TAGS`에서 줄바꿈·쉼표·세미콜론으로 규칙을 구분하고,
대소문자·연속 공백·중복을 정규화합니다. `female:full color`처럼 네임스페이스를 지정한
규칙은 정확히 같은 태그만 일치하고, `full color`처럼 이름만 지정하면
`female:full color` 또는 `male:full color`도 일치합니다. 규칙 하나는 100자로 제한하고 제어
문자와 잘못된 `:tag` 형식은 거부합니다. `hitomi tags evaluate --fixture PATH`는 외부 접속
없이 공통 메타데이터의 `exclude` 또는 `continue` 결정과 일치 규칙을 반환합니다. 실제 GUI에
CLI 규칙을 적용하고 다시 빈 기본 목록으로 복원했으며 검증 화면은
`logs\hitomi-excluded-tags-settings.png`에 있습니다.

설정 스키마 v20은 `hitomiPreferJapaneseTitle`을 기본 꺼짐으로 저장합니다. 켜면
`japaneseTitle`을 먼저 사용하고 값이 없을 때만 기존 `title`로 폴백하며, 끄면 반대 순서를
사용합니다. 두 필드가 모두 비었으면 `hitomi.title_missing`으로 거부합니다. `hitomi title
status|set|select`, 공급자 설정의 체크박스, 메타데이터 대화상자의 `선택 제목`, `status
--json`이 같은 서비스를 사용하고 선택 필드와 폴백 여부를 함께 반환합니다. CLI로 실행 중
GUI 설정을 켜 로컬 픽스처의 `日本語タイトル` 선택을 확인한 뒤 기본 꺼짐으로 복원했습니다.
검증 화면은 `logs\hitomi-japanese-title-settings.png`와
`logs\hitomi-japanese-title-selection.png`에 있습니다.

설정 스키마 v21은 `metadata_json`, `info_txt`, `both`, `disabled` 생성 방식을 저장하며 기본은
기존 toki 작품 정보와 같은 스키마 v1 `metadata.json`입니다. 공통 JSON에는 선택 제목·원제·
일본어 제목, 작가·그룹·태그, 표지 주소, 페이지·파일 목록과 공급자 작품 키를 기록하고,
`info.txt`는 같은 핵심 정보를 사람이 읽는 UTF-8 텍스트로 만듭니다. ExHentai 갤러리 토큰은
어느 파일에도 기록하지 않습니다. `hitomi metadata-files plan`은 경로·크기·기존 파일 충돌만
계산하고, `write --yes`만 기존 작품 폴더에 임시 파일을 완성한 뒤 원자 교체합니다. 기존
파일이 있으면 `--overwrite`가 없을 때 `hitomi.metadata_file_exists`로 거부합니다. GUI의
`폴더에 정보 저장...` 버튼도 대상 파일과 교체 개수를 다시 확인합니다. 임시 한글 폴더에서
두 파일의 실제 생성·UTF-8·공통 필드·재실행 거부와 정리를 확인했고, 화면은
`logs\hitomi-metadata-file-settings.png`, `logs\hitomi-metadata-file-dialog.png`에 있습니다.

설정 스키마 v22는 `hitomiUseOriginalImages`를 기본 켜짐으로 저장합니다. 켜면 모든 알려진
파일에서 공급자 원본을 선택하고, 끄면 메타데이터의 변형 플래그에 따라 AVIF → WebP 순으로
최적화본을 고른 뒤 해당 변형이 없는 파일만 원본으로 폴백합니다. 파일 목록이 없는 E-Hentai
요약은 임의로 결정하지 않고 미확정 개수로 남깁니다. `hitomi images status|set|plan`, 공급자
설정 체크박스, 메타데이터 대화상자의 이미지 선택 요약과 `status --json`이 같은 서비스를
사용합니다. 로컬 픽스처에서 WebP·AVIF 두 장 선택을 확인하고 기본 원본 사용으로 복원했으며,
실제 이미지 URL 요청이나 다운로드는 수행하지 않았습니다. 화면은
`logs\hitomi-original-image-settings.png`, `logs\hitomi-optimized-image-plan.png`에 있습니다.

다운로드 중 절전 방지는 기본적으로 꺼져 있습니다. 고급 설정 또는 `sleep-prevention set
--state on`으로 켜면 실제 다운로드 프로세스가 실행되는 동안에만 Windows
`SetThreadExecutionState`의 시스템 절전 요청을 유지합니다. 모니터 화면을 계속 켜지는
않으며, 일시정지·재시도 대기·모든 작업 완료·GUI 종료에서는 즉시 요청을 해제합니다.
Windows 전원 관리 옵션이나 레지스트리는 변경하지 않습니다. `sleep-prevention status`와
`status --json`의 `sleepPrevention`에서 설정, 실행 다운로드 수, 요청·활성 상태와 오류를
확인할 수 있습니다. `sleep-prevention plan --active-downloads N`은 Windows API를 호출하지
않고 가정한 작업 수에 따른 정책만 계산하므로 자동화 검증에 사용할 수 있습니다.

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
`_converted\형식\기존 회차 폴더`에 생성합니다. 최대 너비나 높이를 지정하면 가로세로 비율을
유지해 축소하고 `_converted\형식-너비x높이`를 별도 출력 루트로 사용하므로 기존 무축소
결과와 섞이지 않습니다. `--exclude-ext`는 지정 확장자를 이번 변환 대상에서만 제외하며
원본이나 이미 만들어진 결과를 삭제하지 않습니다. 원본은 덮어쓰거나 삭제하지 않고, 같은
결과 파일이 있으면 건너뛰므로 중단 후 다시 실행할 수 있습니다. 기본 동작은 `dry-run`이고
실제 대량 파일 생성에는 `--execute --yes`가 모두 필요합니다. GUI도 먼저 대상 수·기존
결과·출력 경로를 보여준 뒤 `변환 실행...`에서 다시 확인합니다. 실행 중에는 처리 수와
완료·건너뜀·실패 수가 갱신되며 `변환 중지` 버튼 또는 `cancel-conversion` CLI로 중지할
수 있습니다. 각 이미지는 `.tmp` 파일을 완성한 뒤 원자적으로 교체하므로 중지해도 원본은
그대로이고, 다음 실행은 남은 임시 파일을 정리한 뒤 기존 완성 결과를 건너뜁니다.
`--progress-json`은 진행 이벤트와 최종 결과를 한 줄씩 JSON으로 출력하며 사용자 중지는
종료 코드 3을 사용합니다. 투명 이미지를 JPEG로 변환할 때는 흰 배경 RGB로 합성합니다.
고급 설정의 기본 최대 너비·높이와 제외 확장자는 `image-processing`으로 동일하게 조회·
변경할 수 있으며, `convert-images`에 직접 지정한 값이 해당 실행에서만 우선합니다.

`pdf`는 작품 폴더의 각 회차 폴더를 자연 숫자 순서로 읽어
`작품 폴더\_pdf\회차 폴더명.pdf` 하나씩 생성합니다. 원본 이미지는 덮어쓰거나 삭제하지
않고, PDF를 `.tmp`에 완성한 뒤 원자적으로 교체합니다. 원본이 바뀌지 않은 최신 PDF는
건너뛰며 원본 이미지의 수정 시각이나 크기가 달라진 회차만 기존 생성 PDF를 교체합니다.
자동 생성은 기본적으로 꺼져 있고 고급 설정 또는 `pdf set --automatic on`으로 켜면 성공한
다운로드 후 새롭거나 변경된 회차만 처리합니다. 이미지 변환과 같은 제한형 CPU 프로세스
예산을 사용하며 슬롯이 찼을 때는 완료 후 동작을 먼저 실행하지 않고 자리가 날 때까지
대기합니다. `pdf plan`과 GUI의 `회차별 PDF 생성...`은 파일을 만들지 않는 계획 조회이고,
실제 생성에는 `--execute --yes` 또는 GUI 재확인이 필요합니다. 실행 중지는 원본과 이미
완성된 PDF를 보존하며 다음 실행에서 남은 임시 파일을 복구합니다.

```powershell
.\toki-cli.cmd image-processing status --json
.\toki-cli.cmd image-processing set --max-width 1600 --max-height 2400 --exclude "gif,bmp,avif" --json
.\toki-cli.cmd convert-images --job 작업ID --format webp --max-width 1600 --max-height 2400 --exclude-ext gif --dry-run --json
.\toki-cli.cmd convert-images --job 작업ID --format webp --include-all-types --execute --yes --progress-json
.\toki-cli.cmd convert-images --close
.\toki-cli.cmd pdf status --json
.\toki-cli.cmd pdf plan --job 작업ID --json
.\toki-cli.cmd pdf generate --job 작업ID --show-gui
.\toki-cli.cmd pdf generate --job 작업ID --execute --yes --progress-json
.\toki-cli.cmd pdf cancel --job 작업ID
```

크기 `0`은 해당 방향 제한 없음이며, 실제 축소값은 64~16384px 범위입니다. 제외 가능한
유형은 JPG/JPEG/PNG/WebP/GIF/BMP/AVIF이고 `status --json`의 `imageProcessing`에서 현재
정책과 원본 보존 여부를 확인할 수 있습니다.
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
