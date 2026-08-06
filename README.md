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
## 준비물 
Node.js, Python 3

## Windows GUI

처음 한 번 `setup-gui.cmd`를 실행하면 저장소 전용 Python 가상환경과 PyQt6,
Node.js 의존성을 설치합니다. 이후에는 `start-gui.cmd`를 더블클릭하면 실제 Windows
창으로 실행됩니다.

GUI에서 URL, 시작/마지막 회차, 저장 기준 폴더를 지정할 수 있습니다. 작업은 한 번에
하나씩 실행되고 다음 작업은 대기열에 들어갑니다. 진행률, 현재 회차와 이미지 수,
오류를 화면 하단 로그에서 확인할 수 있으며 파일 로그는 `logs\gui.log`에 저장됩니다.

```powershell
.\setup-gui.cmd
.\start-gui.cmd
```

### GUI 제어 CLI

GUI의 주요 버튼은 모두 `toki-cli.cmd`에서도 실행할 수 있습니다. GUI가 꺼져 있을 때
`download`를 실행하면 GUI를 자동으로 시작하고 그 대기열에 작업을 추가합니다.

```powershell
# GUI 실행 또는 앞으로 가져오기
.\toki-cli.cmd gui
.\toki-cli.cmd show

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
.\toki-cli.cmd set-settings --works 2 --images 8 --retry-count 2 --retry-backoff 2
.\toki-cli.cmd set-settings --show-browser off --log-visible on --log-max-mib 2 --log-backups 1
.\toki-cli.cmd set-settings --row-density compact
.\toki-cli.cmd set-settings --theme dark
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
.\toki-cli.cmd copy-link --job 작업ID
.\toki-cli.cmd copy-title --job 작업ID
.\toki-cli.cmd job-menu --job 작업ID
.\toki-cli.cmd window
.\toki-cli.cmd logs --tail 200
.\toki-cli.cmd copy-log
.\toki-cli.cmd screenshot
.\toki-cli.cmd self-test --json
.\toki-cli.cmd self-test --via-gui --json
.\toki-cli.cmd clear-log
.\toki-cli.cmd quit --force
```

`list`는 제목, 폴더명에 포함된 작가·그룹, 작품 ID와 URL을 검색합니다. `--status`로
상태를 거르고 `--sort updated|title|progress`로 정렬할 수 있습니다. `--apply-gui`를
추가하면 같은 조건을 실행 중인 GUI 검색창과 목록에도 적용합니다. 빈 조건으로
`list --apply-gui`를 실행하면 GUI 필터가 초기화됩니다.

`pin --on|--off`는 작품을 모든 정렬의 상단에 고정하거나 해제합니다. `tag --color`는
`none`, `red`, `orange`, `yellow`, `green`, `blue`, `purple`, `gray` 중 하나를 지정하며
목록 행의 왼쪽에 색상 표시를 추가합니다. 같은 기능은 작품 우클릭 메뉴에서도 사용할 수
있습니다.

`도구 → 설정...` 또는 `settings --show-gui`는 일반·네트워크·고급 탭을 엽니다.
기본 저장 폴더, 자동화 브라우저 표시, 로그 패널, 작품/이미지 동시성, 재시도 정책과
로그 순환 크기·백업 수를 한 화면에서 바꿀 수 있습니다. 같은 값은 `settings --json`으로
조회하고 `set-settings`로 변경할 수 있으며 `status --json`의 `settings`에도 포함됩니다.
설정 파일의 잘못된 타입이나 범위 값은 시작할 때 안전한 기본값으로 정규화되고 저장은
임시 파일을 거친 원자 교체로 처리됩니다. GUI 로그는 설정한 최대 크기를 넘으면
`gui.log.1`, `gui.log.2` 순서로 지정 개수만큼 순환 보존합니다.
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
선택 기능이므로 다음 명령으로 Pillow를 설치합니다.

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-image-tools.txt
```

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
