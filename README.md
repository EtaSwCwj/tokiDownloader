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
.\toki-cli.cmd pin --job 작업ID --on
.\toki-cli.cmd tag --job 작업ID --color purple
.\toki-cli.cmd remove-record --job 작업ID --yes
.\toki-cli.cmd stop
.\toki-cli.cmd retry --job 작업ID

# 저장 폴더와 로그
.\toki-cli.cmd set-output "D:\Manga"
.\toki-cli.cmd open-folder --job 작업ID
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

`remove-record --yes`는 작품을 GUI 목록과 `jobs.db`에서만 제거합니다. 다운로드한 작품
폴더, 이미지, 표지와 `metadata.json`은 삭제하지 않습니다. 대기 또는 실행 중인 작품은
기록 제거가 거부되며, CLI에서는 실수 방지를 위해 `--yes`가 반드시 필요합니다.

`self-test --json`은 Python/Node 구문, 필수 파일, 단위 테스트와 GUI IPC 및 화면 캡처를
한 번에 검사합니다. GUI가 꺼져 있으면 점검용으로 시작했다가 자동 종료하며, 이미 실행
중이면 종료하지 않습니다. `self-test --via-gui --json`은 GUI의 `자체 점검` 버튼과 같은
비동기 경로를 CLI에서 실행해 검증합니다. 결과는 `logs/self-test.json`, 화면은
`logs/self-test-gui.png`에 저장됩니다. GUI를 전혀 시작하지 않으려면 `--core-only`를
사용합니다.

기본 자체 점검은 사이트에 접속하거나 만화를 받지 않습니다. 실제 사이트 통합 검증은
사용자가 지정한 폴더에 1화만 받도록 다음처럼 명시적으로 실행합니다.

```powershell
.\toki-cli.cmd download --direct --url "https://newtoki1.org/manhwa/34360" --start 1 --last 1 --output "D:\toki-self-test"
```

`retry`는 이전에 지정했던 일부 회차 범위를 반복하는 명령이 아닙니다. 작품의 전체 회차
목록을 다시 수집하고, 이미 저장된 파일은 건너뛰면서 새 회차와 누락 파일만 받습니다.

GUI 없이 기존 방식으로 바로 실행하려면 다음 명령을 사용할 수 있습니다.

```powershell
.\toki-cli.cmd download --direct --url "https://newtoki1.org/manhwa/34732" --start 1 --last 1 --output "D:\Manga"
```

자동화 브라우저는 개인 Chrome 계정과 분리된 전용 프로필을 사용합니다.
기본값은 창이 보이지 않는 백그라운드 실행입니다. Cloudflare 인증이나 사이트 오류를
직접 확인할 때만 GUI의 `브라우저 표시`를 켜거나 CLI에 `--show-browser`를 추가하세요.

## 설치 방법
```bash
git clone https://github.com/crossSiteKikyo/tokiDownloader.git
cd tokiDownloader
npm install
```
https://github.com/user-attachments/assets/b3879c59-3381-407b-a3a8-ad8bf8d84cbb
## 명령어
```bash
node down -url "URL" [-start STARTINDEX] [-last LASTINDEX] [-output "폴더 경로"]
```
- -url은 필수 입력입니다. 반드시 큰따옴표 안에 넣어주세요.
- -start는 옵션입니다. 받고싶은 회차 시작 번호를 입력하세요. 생략하면 처음부터 받습니다.
- -last는 옵션입니다. 받고싶은 마지막 회차 번호를 입력하세요. 생략하면 마지막까지 받습니다.
- -output은 옵션입니다. 저장할 기준 폴더를 지정하며, 생략하면 현재 실행 폴더에 저장합니다.
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
