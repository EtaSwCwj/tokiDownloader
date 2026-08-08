# tokiDownloader GUI 구현 인계 문서

## 0. 문서 목적

이 문서는 `C:\gitproject\tokiDownloader`의 현재 CLI 다운로더 위에 실제 Windows
데스크톱 GUI를 구현하기 위한 Claude Code용 요구사항과 인계 자료다.

목표는 Hitomi Downloader의 모든 기능을 복제하는 것이 아니다. Hitomi Downloader와
비슷한 조밀한 다운로드 관리자 형태만 참고하고, 세부 기능은 tokiDownloader에 맞게
새로 설계한다.

GUI는 브라우저에서 열리는 로컬 웹 페이지가 아니라 **PyQt6 기반 네이티브 Windows
창**이어야 한다.

시각 참고 문서:

```text
C:\Users\CWJ\Desktop\buffer\dfds\CLAUDE_GUI_REVERSE_ENGINEERING.md
```

위 문서는 레이아웃과 데스크톱 도구의 분위기를 참고하기 위한 자료다. 원본 Hitomi
Downloader의 실행 파일, 설정, 데이터, 아이콘 및 추출 리소스를 수정하거나 복사하지
않는다.

---

## 1. 작업 저장소와 현재 상태

```text
Repository: C:\gitproject\tokiDownloader
Primary CLI: C:\gitproject\tokiDownloader\down.js
Runtime: Node.js
Main dependency: puppeteer-real-browser
```

현재 작업 트리에는 사용자가 요청한 다운로더 수정 사항이 아직 커밋되지 않은 상태로
존재할 수 있다. GUI 작업을 시작하기 전에 반드시 다음을 확인하고 기존 변경을 보존한다.

```powershell
git -C C:\gitproject\tokiDownloader status --short --branch
git -C C:\gitproject\tokiDownloader diff -- down.js README.md tokiDownloader.js
```

`git reset --hard`, `git checkout --`, 원본 파일 덮어쓰기를 사용하지 않는다.

---

## 2. 현재 CLI 설치 및 사용법

### 설치

```powershell
git clone https://github.com/crossSiteKikyo/tokiDownloader.git
Set-Location .\tokiDownloader
npm install
```

현재 로컬 저장소에는 위 설치가 이미 완료되어 있고 `node_modules`도 존재한다.

### 전체 회차 다운로드

```powershell
node .\down.js -url "https://newtoki1.org/manhwa/34732"
```

### 일부 회차 다운로드

```powershell
node .\down.js `
  -url "https://newtoki1.org/manhwa/34732" `
  -start 1 `
  -last 10
```

### 저장 기준 폴더 지정

```powershell
node .\down.js `
  -url "https://newtoki1.org/manhwa/34732" `
  -start 1 `
  -last 10 `
  -output "D:\Manga"
```

옵션 의미:

| 옵션 | 필수 | 의미 |
|---|---:|---|
| `-url` | 예 | 작품의 회차 목록 페이지 URL |
| `-start` | 아니요 | 시작 회차 번호, 포함 범위 |
| `-last` | 아니요 | 마지막 회차 번호, 포함 범위 |
| `-output` | 아니요 | 저장 기준 폴더. 생략하면 현재 실행 폴더 |

README에 표시되는 대괄호(`[]`)는 선택 옵션 표기이며 실제 명령어에 입력하지 않는다.

---

## 3. 현재 지원 사이트와 이미 반영된 수정

현재 `down.js`는 다음 URL 계열을 판별한다.

```text
https://booktoki숫자.com/novel/작품ID
https://newtoki숫자.com/webtoon/작품ID
https://manatoki숫자.net/comic/작품ID
https://newtoki숫자.org/manhwa/작품ID
```

`newtoki숫자.org/manhwa/` 주소는 호스트 이름과 달리 실제 페이지가 마나토끼이므로
`마나토끼`로 분류한다.

현재 사이트 구조에 맞춰 다음 항목이 이미 수정되어 있다.

- `.org/manhwa/` URL 인식
- 현재 마나토끼 페이지 제목 대기 조건
- 신형 이미지 뷰어 선택자 `.theme-viewer-images img`
- 구형 선택자 `.view-padding div img` 동시 지원
- 외부 CDN 절대 이미지 URL 지원
- 브라우저 내부 `fetch` 대신 Node 측 이미지 다운로드
- 이미지 최대 5개 동시 다운로드
- 이미지 실패 시 최대 3회 재시도
- 기존 파일 건너뛰기 및 재실행 이어받기
- 범위를 벗어난 회차 선택 시 명확한 오류

자동화 Chrome은 사용자의 개인 Chrome 프로필이 아니라 별도 자동화 프로필로 열린다.
이는 정상 동작이며, GUI에서도 개인 Chrome 프로필을 강제로 연결하지 않는다.

---

## 4. 작품 폴더명과 메타데이터 규칙

### 필수 작품 폴더명

```text
[작가][그룹] 작품 제목
```

실제 예:

```text
[이요미네 츠쿠][N／A] 이세계에서 개인방송 활동을 했더니 대량의 얀데레 신자를 만들어 버린 건
```

그룹, 역자 또는 번역자 정보가 페이지에 없으면 반드시 `N／A`를 사용한다. ASCII
슬래시가 포함된 `N/A`는 Windows 폴더명으로 사용할 수 없으므로 사용하지 않는다.

현재 마나토끼 페이지에서 확인 가능한 메타데이터:

- 제목
- 작가
- 장르
- 발행구분/연재 상태
- 작품 설명
- 표지 URL
- 사이트 구분
- 작품 ID
- 원본 URL

### 저장 구조

`-output "D:\Manga"`를 지정한 경우:

```text
D:\Manga\
└─ 마나토끼\
   └─ [이요미네 츠쿠][N／A] 이세계에서 개인방송 활동을 했더니 대량의 얀데레 신자를 만들어 버린 건\
      ├─ metadata.json
      ├─ .toki-state.json
      ├─ 이세계에서 개인방송 활동을 했더니 대량의 얀데레 신자를 만들어 버린 건 1화\
      │  ├─ 0000.jpeg
      │  └─ ...
      └─ 이세계에서 개인방송 활동을 했더니 대량의 얀데레 신자를 만들어 버린 건 2화\
```

회차 폴더는 사이트 목록의 축약 표시문이나 게시물 순번을 노출하지 않는다. 전체 작품명과
실제 회차/부제를 사용하고, 사이트 회차 ID·URL·원문·폴더명 매핑은 state v2와
`metadata.json`의 `episodes` 배열에 따로 보존한다. 예전 `0001 + 축약 제목` 폴더는 계속
읽으며, 명시적인 `rename-episodes` 미리보기와 확인 실행으로만 새 형식으로 바꾼다.
같은 문맥의 소수 회차가 있을 때만 기본 정수 회차에 `.0`을 붙이고, `N-2화`만 있는
분할 회차에서는 기본 `N화`를 `N-1화`로 보정한다. 합본 범위와 다른 외전 문맥은 섞지
않으며, 두 규칙이 충돌하거나 `.0`·`-1`이 이미 있으면 자동 추론을 중단한다.
GUI 경유 미리보기는 현재 작품의 불변 snapshot으로 실행해 `jobs.db`를 변경하지 않는다.
실제 실행만 GUI 이력을 저장한 뒤 DB 기반 worker로 처리하며, CLI 응답 timeout 뒤에는
`status --json`으로 백그라운드 회차 이름변경 상태를 확인해야 한다.

현재 잘못 생성된 이전 경로가 있을 수 있다.

```text
C:\gitproject\tokiDownloader\마나토끼\일본만화\
```

이 폴더는 자동으로 삭제하거나 이동하지 않는다. 사용자가 별도로 요청하기 전까지
그대로 보존한다.

### metadata.json 예시

```json
{
  "schemaVersion": 1,
  "title": "이세계에서 개인방송 활동을 했더니 대량의 얀데레 신자를 만들어 버린 건",
  "author": "이요미네 츠쿠",
  "group": "N／A",
  "category": "일본만화",
  "genres": ["러브코미디", "이세계", "판타지", "라노벨"],
  "status": "연재중",
  "description": "작품 설명",
  "coverUrl": "https://...",
  "source": {
    "site": "manatoki",
    "siteTitle": "마나토끼",
    "workId": "34732",
    "url": "https://newtoki1.org/manhwa/34732"
  },
  "folderName": "[이요미네 츠쿠][N／A] 작품 제목",
  "episodeCount": 101,
  "selectedEpisodeCount": 1,
  "requestedRange": {
    "start": 1,
    "last": 1
  },
  "episodes": [
    {
      "number": 1,
      "sourceId": "/manhwa/34732/episode-1",
      "sourceUrl": "https://newtoki1.org/manhwa/34732/episode-1",
      "sourceTitle": "작품 제목 1화",
      "displayTitle": "작품 제목 1화",
      "folderName": "작품 제목 1화"
    }
  ],
  "generatedAt": "ISO-8601 timestamp"
}
```

메타데이터와 폴더명은 표시용 문자열과 Windows 안전 경로를 구분해서 처리한다.
Windows 금지 문자(`< > : " / \\ | ? *`)를 경로에서 제거하되 metadata.json의 원본
표시 값은 가능한 한 보존한다.

---

## 5. 실제 검증된 상태

다음 작품의 1화 다운로드가 실제로 검증되었다.

```text
URL: https://newtoki1.org/manhwa/34732
범위: 1화 ~ 1화
작가: 이요미네 츠쿠
그룹: N／A
감지 이미지: 31개
저장 이미지: 31개
0바이트 이미지: 0개
총 이미지 크기: 4,937,340 bytes
```

검증된 작품 폴더:

```text
C:\gitproject\tokiDownloader\마나토끼\[이요미네 츠쿠][N／A] 이세계에서 개인방송 활동을 했더니 대량의 얀데레 신자를 만들어 버린 건
```

GUI 통합 테스트에서도 전체 작품을 받지 말고 우선 `-start 1 -last 1`만 사용한다.

---

## 6. GUI의 필수 방향

### 기술 선택

- PyQt6 기반 실제 Windows 데스크톱 창
- 로컬 웹 서버/브라우저 GUI 금지
- 최초 개발은 Python + PyQt6 GUI가 Node `down.js`를 자식 프로세스로 실행하는 구조
- 최종적으로 Windows 실행 파일 또는 실행 가능한 배포 폴더 제공
- CLI는 계속 독립적으로 사용할 수 있어야 함

권장 구조:

```text
PyQt6 GUI / CLI
       │
       ├─ 공용 ApplicationService
       ├─ 작업 큐와 상태 저장
       ├─ 로그 관리자
       └─ QProcess/subprocess
              └─ node down.js
                     └─ puppeteer-real-browser
```

GUI 버튼과 CLI가 서로 다른 로직을 구현하면 안 된다. 두 인터페이스가 같은 공용 서비스
메서드를 호출하도록 설계한다.

### 메인 화면 구성

Hitomi Downloader의 조밀한 데스크톱 도구 구성을 참고하되 독자적으로 디자인한다.

```text
┌ 작업  도구  옵션  도움말 ─────────────────────────────┐
│ URL [____________________________________] [다운로드] │
│ 범위 [처음] ~ [마지막]  저장 [____________] [선택]   │
│ [중지] [재시도] [폴더 열기]                          │
├──────────────────────────────────────────────────────┤
│ [상태] [이요미네 츠쿠][N／A] 작품명                  │
│        1화 · 이미지 12/31                            │
│        ███████████░░░░ 38%                           │
│                                                      │
│ [대기] 다음 작품                                     │
├──────────────────────────────────────────────────────┤
│ 실행 로그                                      [지우기]│
│ 20:10:01 작업 시작                                   │
│ 20:10:10 이미지 31개 감지                            │
├──────────────────────────────────────────────────────┤
│ 전체 진행률 | 현재 상태 | 저장 폴더                 │
└──────────────────────────────────────────────────────┘
```

### 초기 필수 기능

- URL 입력
- 시작 회차와 마지막 회차 입력, 비워두면 전체 범위
- Windows 폴더 선택 대화상자
- 선택한 기본 저장 폴더 기억
- 다운로드 작업 추가 및 실행
- 한 작업 실행 중 다음 작업 대기열 추가
- 작품 제목/작가/그룹 표시
- 현재 회차와 이미지 진행률 표시
- 완료, 대기, 실행 중, 중지됨, 오류 상태 표시
- 현재 작업 중지
- 실패/중지 작업 재시도
- 선택 작업의 저장 폴더 열기
- 실시간 로그 표시
- 파일 로그 저장 및 로그 지우기
- GUI 종료 시 실행 중 작업에 대한 확인

### 초기 비필수 기능

다음은 첫 버전에서 구현하지 않아도 된다.

- Hitomi 검색기 복제
- 플러그인 관리자
- 토렌트
- 통계와 그래프
- 수십 개 사이트별 설정
- 원본 Hitomi 아이콘/리소스 복사
- 개인 Chrome 계정/쿠키 프로필 강제 연결
- 완전한 1:1 픽셀 복제

---

## 7. GUI 버튼과 CLI 기능 대응 요구사항

**GUI에 존재하는 모든 동작 버튼은 CLI에서도 실행할 수 있어야 한다.** CLI와 GUI가
실행 중인 동일 작업을 제어할 수 있도록 로컬 IPC를 사용한다. Windows에서는
`QLocalServer`/`QLocalSocket` 또는 동등한 로컬 전용 IPC를 권장한다.

권장 명령 인터페이스:

| GUI 동작 | CLI 대응 예시 |
|---|---|
| GUI 실행/앞으로 가져오기 | `toki-cli.cmd gui` / `toki-cli.cmd show` |
| 다운로드 추가 | `toki-cli.cmd download --url URL [--start N --last N --output PATH]` |
| 현재 작업 중지 | `toki-cli.cmd stop` |
| 선택/마지막 실패 작업 재시도 | `toki-cli.cmd retry [--job ID]` |
| 현재 상태 조회 | `toki-cli.cmd status [--json]` |
| 기본 저장 폴더 설정 | `toki-cli.cmd set-output "D:\Manga"` |
| 저장 폴더 열기 | `toki-cli.cmd open-folder [--job ID]` |
| 로그 출력/복사에 대응 | `toki-cli.cmd logs --tail 200` |
| 로그 지우기 | `toki-cli.cmd clear-log` |
| GUI 종료 | `toki-cli.cmd quit` |

추가 요구사항:

- CLI는 경로와 URL을 문자열 연결로 셸에 전달하지 말고 안전한 인자 배열을 사용한다.
- `status --json`은 자동화에서 파싱할 수 있는 안정된 JSON을 반환한다.
- GUI가 실행 중이면 CLI `download`는 GUI 대기열에 작업을 추가한다.
- GUI가 실행 중이지 않을 때 사용할 `download --direct` 모드도 제공하면 좋다.
- 중지는 Node 프로세스뿐 아니라 그 프로세스가 실행한 자동화 Chrome 자식 프로세스까지
  정확한 PID 트리 범위에서 종료해야 한다.
- 광범위한 Chrome/Node 프로세스 전체 종료는 금지한다.

---

## 8. down.js 구조화 진행 이벤트 요구사항

현재 사람용 로그 문구만 파싱하지 말고 GUI용 JSON 이벤트 모드를 추가한다. 기존 일반
CLI 출력은 그대로 유지한다.

권장 옵션:

```text
-json-events
```

권장 출력 형식은 한 줄 JSON 또는 명확한 접두사가 붙은 JSON Lines다.

```text
@@TOKI@@{"event":"work_metadata","metadata":{...},"outputPath":"D:\\Manga\\..."}
@@TOKI@@{"event":"queue_ready","selectedEpisodes":10}
@@TOKI@@{"event":"episode_started","index":1,"total":10,"number":1,"title":"1화"}
@@TOKI@@{"event":"images_found","episodeNumber":1,"count":31}
@@TOKI@@{"event":"image_saved","current":12,"total":31,"skipped":false}
@@TOKI@@{"event":"episode_completed","index":1,"total":10,"number":1}
@@TOKI@@{"event":"completed","outputPath":"D:\\Manga\\..."}
@@TOKI@@{"event":"error","message":"오류 메시지"}
```

필수 이벤트:

- `work_metadata`
- `queue_ready`
- `episode_started`
- `images_found`
- `image_saved`
- `episode_completed`
- `completed`
- `error`

이미 존재해 건너뛴 이미지는 `image_saved`에 `skipped: true`로 표시한다. 이벤트 모드의
오류 종료 코드는 반드시 0이 아니어야 한다.

---

## 9. 로그 요구사항

사용자가 오류와 문제를 직접 확인할 수 있어야 한다.

### GUI 로그 화면

- 항상 접근 가능한 로그 패널
- 자동 스크롤
- 시각이 포함된 로그
- INFO/WARN/ERROR 구분
- Node stdout과 stderr를 모두 표시
- 구조화 이벤트 원문은 숨기고 사람이 이해할 수 있는 상태 문구로 표시 가능
- `로그 지우기`와 `로그 복사` 버튼

### 파일 로그

권장 위치:

```text
C:\gitproject\tokiDownloader\logs\gui.log
```

요구사항:

- UTF-8
- 날짜와 시각
- GUI 작업 ID
- 실행한 안전한 인자 목록
- 프로세스 PID
- Node stdout/stderr
- 종료 코드
- Python 예외 traceback
- 크기 기반 순환 로그 또는 날짜별 로그
- URL은 기록할 수 있지만 쿠키, 비밀번호, 개인 Chrome 데이터는 기록하지 않음

CLI `logs`와 `clear-log`는 GUI의 로그 파일과 동일한 로그 저장소를 사용해야 한다.

---

## 10. 설정과 작업 데이터

권장 로컬 설정 파일:

```text
config.json
```

최소 저장 항목:

```json
{
  "outputDir": "D:\\Manga",
  "window": {
    "x": 120,
    "y": 80,
    "width": 860,
    "height": 720,
    "maximized": false
  },
  "logVisible": true
}
```

설정, 로그, 가상환경, 빌드 출력은 Git에 포함하지 않는다.

창을 복원할 때 저장된 위치가 현재 연결된 어떤 모니터와도 겹치지 않으면 주 모니터
중앙으로 이동한다. 최대화 상태에서는 최대화 이전의 정상 위치와 크기를 저장한다.

```gitignore
.venv/
__pycache__/
config.json
logs/
build/
dist/
```

작업 큐를 디스크에 저장할 경우 완전한 원본 URL, 범위, 출력 경로, 상태만 저장하고
Puppeteer 세션이나 Chrome 쿠키를 저장하지 않는다.

---

## 11. Windows 실행과 배포

개발 중 권장 파일:

```text
toki_app.py              GUI와 CLI 엔트리포인트
toki_gui.py              PyQt6 화면
toki_core.py             공용 작업/설정/로그 서비스
requirements-gui.txt     PyQt6 버전 범위
start-gui.cmd             GUI 실행
toki-cli.cmd              CLI 실행
```

GUI 실행 목표:

```text
start-gui.cmd 더블클릭
        ↓
콘솔 입력 없이 PyQt6 Windows 창 표시
```

첫 실행에서 저장소 전용 `.venv`를 만들고 PyQt6를 설치할 수 있다. 전역 Python에는
설치하지 않는다.

장기적으로는 다음 두 배포 방식을 고려한다.

1. PyInstaller GUI 실행 파일 + Node/Puppeteer 런타임 폴더
2. 설치 스크립트가 Python 가상환경과 npm 의존성을 준비하는 개발자용 배포

Puppeteer와 Chrome 때문에 처음부터 단일 EXE에 집착하지 않는다. 먼저 재현 가능한
실행 폴더 형태를 완성한다.

---

## 12. 구현 순서

1. 현재 Git 변경 사항과 실제 `down.js`를 읽고 보존한다.
2. `down.js`에 `-json-events`를 추가하고 기존 CLI와 1화 테스트를 통과시킨다.
3. 공용 작업 서비스와 작업 모델을 구현한다.
4. CLI 명령을 먼저 구현하고 모든 명령을 단독 테스트한다.
5. PyQt6 메인 창을 구현하고 버튼이 공용 서비스를 호출하게 한다.
6. 로컬 IPC로 CLI가 실행 중 GUI를 제어하게 한다.
7. 로그 화면과 파일 로그를 연결한다.
8. 작업 큐, 중지, 재시도, 폴더 열기를 검증한다.
9. 오프스크린 렌더 또는 사용자 소유 스크린샷으로 시각 QA를 한다.
10. README에 GUI와 CLI 사용법을 추가한다.

GUI 외형을 먼저 완성하고 동작을 나중에 임시 연결하지 않는다. 최소 기능이라도 각 버튼은
처음부터 실제 공용 동작에 연결한다.

---

## 13. 완료 기준

### 기능

- `start-gui.cmd` 더블클릭으로 실제 PyQt6 창이 열린다.
- URL, 범위, 출력 폴더를 GUI에서 설정할 수 있다.
- 저장 폴더 선택 대화상자가 동작하고 다음 실행에도 기억된다.
- `[작가][N／A] 제목` 폴더와 metadata.json이 유지된다.
- 1화 테스트에서 이미지 31개가 정상 저장된다.
- 진행 중인 회차와 이미지 수가 GUI에서 갱신된다.
- 중지 후 자동화 Chrome 자식 프로세스가 남지 않는다.
- 재시도하면 기존 파일을 건너뛰고 누락 파일을 이어받는다.
- GUI 로그와 파일 로그에서 오류 원인을 확인할 수 있다.

### CLI

- 표 7의 모든 GUI 동작에 CLI 대응 명령이 존재한다.
- `status --json`이 유효한 JSON을 반환한다.
- GUI가 실행 중일 때 CLI로 작업 추가, 상태 조회, 중지, 재시도가 가능하다.
- 경로에 공백과 한글이 있어도 정상 동작한다.

### 안전과 호환성

- 기존 `node .\down.js ...` 명령이 계속 동작한다.
- 기존 사용자 다운로드 폴더를 삭제하거나 자동 이동하지 않는다.
- 원본 Hitomi Downloader 파일과 데이터에 쓰기 작업을 하지 않는다.
- 개인 Chrome 프로필과 쿠키를 읽거나 연결하지 않는다.
- 실행 실패 시 GUI가 성공으로 표시하지 않는다.

---

## 14. Claude Code가 사용자에게 확인할 항목

첫 동작 가능한 GUI가 나온 뒤 다음 세부 사항은 사용자와 함께 결정한다.

- 작업 행의 정확한 높이와 정보 밀도
- 밝은 테마/어두운 테마 우선순위
- 표지 이미지 표시 여부
- 완료 작업 자동 정리 여부
- 다중 작업 동시 실행 수
- 폴더명 템플릿을 사용자 설정으로 노출할지 여부
- 작업 기록 영구 저장 여부
- 최종 EXE/설치 방식

이 항목 때문에 기본 GUI 구현을 미루지는 않는다. 우선 기능이 연결된 간결한 1차 화면을
제공하고, 사용자 피드백으로 세부 UI를 조정한다.

---

## 15. 대규모 작업 목록 성능 원칙

GUI와 작업 엔진은 수십 개뿐 아니라 수백, 수천, 장기적으로 수만 개 작업 기록에서도
시작과 스크롤이 느려지지 않는 구조를 기본 전제로 한다. 멀티 코어와 멀티 스레드는
무조건 많이 만드는 방식이 아니라 작업 성격별로 분리된 제한형 워커 풀로 사용한다.

### 15.1 UI 메인 스레드 원칙

- Qt 메인 스레드는 입력, 레이아웃, 그리기만 담당한다.
- 네트워크, 디스크 탐색, 이미지 디코딩, JSON 대량 파싱, 프로세스 대기 작업을 메인
  스레드에서 실행하지 않는다.
- 작업별 QWidget을 수천 개 생성하는 구조는 사용하지 않는다. 작업 목록은
  `QListView`/`QTableView` + `QAbstractItemModel` + delegate 기반 가상화로 전환한다.
- 현재 화면에 보이는 행과 앞뒤 버퍼 행만 렌더링한다. 보이지 않는 작업의 썸네일과 상세
  위젯은 생성하지 않는다.
- 작업 상태 이벤트는 매 건마다 다시 그리지 않고 작업별 최신 상태를 합쳐 최대 초당
  10~20회만 UI에 반영한다.

### 15.2 저장소와 지연 로딩

- 작업 기록의 기준 저장소는 메모리 배열이 아니라 SQLite 같은 로컬 영속 저장소로 둔다.
- SQLite는 WAL 모드, 인덱스, 트랜잭션 배치 쓰기를 사용하고 쓰기는 단일 직렬화 워커가
  담당한다.
- 프로그램 시작 시 전체 작업과 로그를 읽지 않는다. 요약 통계와 첫 페이지 100~200개만
  불러오고 스크롤/검색 시 다음 페이지를 읽는다.
- 목록 정렬, 상태 필터, 제목 검색은 데이터베이스 쿼리와 인덱스로 처리한다.
- CLI `status`는 기본적으로 요약과 활성 작업만 반환한다. 전체 작업 조회는
  `--limit`, `--offset` 또는 cursor 기반 페이지 조회로 분리한다.
- 작업 삭제와 정리는 화면에서 즉시 숨긴 뒤 백그라운드에서 저장소에 반영한다.

### 15.3 멀티 코어·멀티 스레드 역할 분리

- I/O 작업은 제한된 스레드 풀 또는 비동기 I/O로 처리한다. 대상은 썸네일 다운로드,
  파일 존재 검사, 로그 기록, 데이터베이스 읽기다.
- CPU 사용량이 큰 이미지 리사이즈, 해시, 압축, 변환은 프로세스 풀로 분리한다. Python
  GIL의 영향을 받는 CPU 작업을 스레드 수만 늘려 처리하지 않는다.
- CPU 프로세스 풀 기본 크기는 `max(1, 논리 코어 수 - 1)`을 상한으로 삼아 GUI와 운영
  체제에 최소 한 코어를 남긴다.
- I/O 워커 수는 `min(32, 논리 코어 수 * 4)` 범위에서 시작하되 디스크와 서버 응답,
  오류율을 측정해 조정한다.
- 브라우저 인스턴스 수, 작품 동시 처리 수, 작품 내부 이미지 동시 다운로드 수는 서로
  독립된 제한값으로 관리한다. 작업 수만큼 Chrome이나 QProcess를 만들지 않는다.
- 기본 다운로드는 사이트 부하와 Cloudflare 차단을 고려해 보수적인 동시성으로 시작하고,
  설정 범위 안에서만 확장한다.

### 15.4 백프레셔와 취소

- 모든 큐는 무제한 생산을 허용하지 않는다. 워커 입력 큐에 상한을 두고 소비 속도보다
  빠르게 작업이 생기면 생산자를 대기시킨다.
- 중지 요청은 GUI → 작업 관리자 → Node → 해당 Chrome 자식 트리 순서로 전달한다.
- 완료, 오류, 중지 이벤트는 멱등적으로 처리해 같은 이벤트가 다시 와도 상태가 깨지지
  않게 한다.
- 프로그램 비정상 종료 후 `실행 중`이었던 작업은 다음 시작 시 `중단됨`으로 복구하고
  사용자가 이어받기 또는 재시도를 선택할 수 있게 한다.

### 15.5 썸네일과 로그

- 대표 이미지는 작품당 한 번만 원본을 저장하고 목록용 고정 크기 썸네일을 별도 캐시한다.
- 썸네일은 화면 진입 시 지연 로딩하며 디코딩과 리사이즈는 백그라운드에서 수행한다.
- 메모리 썸네일은 LRU 캐시로 제한하고 화면에서 멀어진 이미지는 해제한다.
- 로그 파일은 버퍼링·배치 기록하고 크기 기반 순환을 유지한다. GUI에는 최근 N줄만 보이며
  전체 로그를 메모리에 보관하지 않는다.
- 반복되는 이미지 진행 이벤트는 로그에도 묶어서 기록할 수 있게 해 디스크 쓰기와 화면
  갱신 폭주를 방지한다.

### 15.6 측정과 완료 기준

- 성능 변경은 체감 추측이 아니라 100, 1,000, 10,000, 100,000개 합성 작업 데이터로
  시작 시간, 검색 시간, 스크롤 프레임, 메모리, 이벤트 처리량을 측정한다.
- 10,000개 기록이 있어도 첫 화면은 전체 자료 로딩을 기다리지 않고 2초 이내 표시하는
  것을 목표로 한다.
- 목록 스크롤은 보이는 행 수에 비례해야 하며 전체 작업 수 증가로 프레임 시간이 선형
  증가하면 안 된다.
- 유휴 상태에서는 작업 수가 늘어도 지속적인 CPU 사용이 발생하지 않아야 한다.
- 워커 수를 1, 2, 4, 8로 바꾼 벤치마크를 남기고 처리량이 더 이상 증가하지 않거나 오류가
  늘어나는 지점을 기본 상한으로 정한다.
- 성능 최적화가 다운로드 결과, 폴더명, metadata.json, 중지·재시도 의미를 바꾸지 않도록
  기능 회귀 테스트를 함께 실행한다.

### 15.7 구현 우선순위

1. `QListWidget + 작업별 QWidget`을 가상화된 model/view 목록으로 교체한다.
2. SQLite 작업 저장소와 페이지 조회를 추가한다.
3. 상태 이벤트 병합과 UI 갱신 주기 제한을 추가한다.
4. 썸네일 지연 로딩, 디스크 캐시, LRU 메모리 캐시를 추가한다.
5. I/O 스레드 풀과 CPU 프로세스 풀을 분리한다.
6. 작품/이미지/브라우저 동시성 제한과 백프레셔를 추가한다.
7. 합성 부하 테스트와 성능 회귀 기준을 CI 또는 로컬 검증 명령으로 고정한다.

---

## 16. CLI 우선 기능·테스트 원칙

**GUI에 보이는 모든 버튼과 사용자 기능은 반드시 CLI에서도 실행하고 검증할 수 있어야
한다. GUI에서만 가능한 기능은 만들지 않는다.**

### 16.1 단일 기능 구현

- GUI 버튼과 CLI 명령은 서로 별도 로직을 구현하지 않고 같은 application service
  메서드를 호출한다.
- 기능을 추가할 때는 서비스 메서드 → CLI 명령 → 자동 테스트 → GUI 버튼 순서로
  연결한다.
- 파일 선택 대화상자처럼 GUI에만 존재하는 입력 방식은 CLI에서 `--path`, `--output`
  같은 명시적 인자로 동일 결과를 만들 수 있어야 한다.
- GUI가 실행 중이면 CLI는 로컬 IPC를 통해 그 GUI의 실제 큐와 상태를 제어한다.
- GUI가 없어도 검증 가능한 기능은 `--direct` 또는 headless 실행 경로를 제공한다.

### 16.2 명령 결과 규격

- 모든 명령은 성공 시 종료 코드 0, 실패 시 0이 아닌 종료 코드를 반환한다.
- 자동 테스트 대상 명령은 `--json` 또는 이에 준하는 기계 판독 가능 출력을 제공한다.
- JSON 결과에는 최소한 `ok`, 작업 ID, 상태, 출력 경로, 오류 코드 또는 오류 메시지를
  포함한다.
- 성공 문구만 출력하고 실제 상태를 확인하지 않는 명령을 테스트 완료로 간주하지 않는다.
- 비동기 작업은 작업 ID를 반환하고 `status --job ID --json`으로 완료·오류·중지 상태를
  조회할 수 있어야 한다.
- 파일을 만드는 기능은 결과 JSON에 절대 경로를 반환하고 CLI 테스트가 파일 존재와 크기를
  확인할 수 있어야 한다.

### 16.3 현재 GUI 동작의 CLI 대응

| GUI 동작 | CLI 검증 경로 |
|---|---|
| GUI 실행/앞으로 가져오기 | `toki-cli.cmd gui`, `toki-cli.cmd show` |
| 다운로드 | `toki-cli.cmd download --url URL --start N --last N --output PATH` |
| 현재 작업 중지 | `toki-cli.cmd stop` |
| 작업 재시도 | `toki-cli.cmd retry --job ID` |
| 폴더 선택/기본 경로 변경 | `toki-cli.cmd set-output PATH` |
| 선택 작업 폴더 열기 | `toki-cli.cmd open-folder --job ID` |
| 작품 링크 복사 | `toki-cli.cmd copy-link --job ID` |
| 작품명 복사 | `toki-cli.cmd copy-title --job ID` |
| 작품 우클릭 메뉴 표시 | `toki-cli.cmd job-menu --job ID` |
| 작업·진행 상태 확인 | `toki-cli.cmd status --json` |
| 작품 검색·상태 필터·정렬 | `toki-cli.cmd list --query TEXT --status STATE --sort title --apply-gui --json` |
| 작품 고정·색상 태그 | `toki-cli.cmd pin --job ID --on`, `toki-cli.cmd tag --job ID --color blue` |
| 작품 기록만 제거 | `toki-cli.cmd remove-record --job ID --yes` |
| 기록 일괄 정리·목록 새로고침 | `toki-cli.cmd cleanup-records --status completed --yes`, `toki-cli.cmd refresh-list` |
| GUI 화면 캡처 | `toki-cli.cmd screenshot --output PATH` |
| 자체 점검 실행 | `toki-cli.cmd self-test --via-gui --json` |
| 창 위치·크기 조회/설정 | `toki-cli.cmd window [--x N --y N --width N --height N]` |
| 로그 표시 | `toki-cli.cmd logs --tail N` |
| 로그 복사 | `toki-cli.cmd copy-log --tail N` |
| 로그 지우기 | `toki-cli.cmd clear-log` |
| GUI 종료 | `toki-cli.cmd quit --force` |

새 버튼이나 설정을 추가하면 이 표와 CLI 도움말을 같은 변경에서 갱신한다.

작품 단위 `retry`는 과거 실행의 `start`/`last` 범위를 그대로 반복하지 않는다. 항상 전체
회차 목록을 새로 수집하고, 기존 파일 건너뛰기 로직을 이용해 신규 회차와 누락 파일만
보충한다. 동일 범위만 다시 실행하는 기능이 필요하면 별도 명령으로 분리한다.

자동화 Chrome은 기본적으로 headless 백그라운드 모드로 실행한다. GUI의 `브라우저 표시`
체크박스와 CLI의 `download --show-browser`는 Cloudflare 인증 또는 사이트 오류를 사람이
직접 확인해야 할 때만 사용하는 진단용 예외 경로다.

### 16.4 자동화 테스트 원칙

- CLI 통합 테스트는 GUI 시작 → 기능 실행 → 상태 조회 → 결과 파일 검증 → GUI 종료를
  사람 클릭 없이 끝낼 수 있어야 한다.
- 버튼 활성화 여부, 상태 라벨, 진행률, 썸네일 등 화면 결과는 CLI 상태 조회와 GUI 직접
  캡처를 함께 사용해 검증한다.
- 다운로드 테스트는 기본적으로 1화 범위만 사용하며 전체 작품 다운로드를 자동 테스트로
  시작하지 않는다.
- 중지 테스트는 생성한 정확한 작업 ID와 PID 트리만 종료하고 다른 Node/Chrome 프로세스가
  살아 있는지에 영향을 주지 않는다.
- 네트워크가 필요 없는 단위 테스트와 실제 사이트를 사용하는 통합 테스트를 분리한다.
- 최종적으로 `toki-cli.cmd self-test --json` 한 명령으로 로컬 기능 점검을 실행할 수 있게
  하고, 새 기능은 해당 self-test 항목을 추가하지 않으면 완료로 간주하지 않는다.

---

## 17. 작품 단위 데이터 모델 원칙

GUI 작업 목록의 최상위 행은 다운로드 실행 1회가 아니라 **작품 1개**를 의미한다.

- 작품 식별자는 표시 제목이나 현재 도메인이 아니라 `사이트 종류 + 작품 ID`로 만든다.
  예: `manatoki:34360`.
- `newtoki1.org`가 `newtoki2.org`로 바뀌어도 `/manhwa/34360`이면 같은 작품이다.
- 같은 작품을 다시 다운로드하거나 다른 회차 범위로 이어받으면 새 행을 추가하지 않고 기존
  작품 행을 최신 상태로 갱신해 목록 맨 위로 이동한다.
- 같은 작품의 중복 동시 실행은 허용하지 않는다. 기존 작업이 대기 또는 실행 중이면 CLI와
  GUI 모두 명확한 오류를 반환한다.
- 작품 행에는 대표 이미지, 제목, 작가, 그룹, 저장 폴더, 전체/보유 회차, 최신 상태를
  집계해서 표시한다.
- 실행 ID, 요청 범위, 시작·종료 시각, 결과와 오류는 작품 아래의 실행 이력으로 분리한다.
  실행 이력이 늘어도 작품 목록 행은 하나만 유지한다.
- SQLite의 작품 레코드는 작품 식별자에 UNIQUE 제약을 두고 upsert한다.
- 기존 버전에서 같은 작품이 여러 행으로 저장된 경우 시작 시 최신 레코드 하나로 자동
  병합한다.
- 폴더명이나 작품 제목이 변경돼도 작품 ID가 같으면 같은 레코드를 갱신하며, 사용자의
  다운로드 파일을 자동 삭제하거나 중복 이동하지 않는다.
