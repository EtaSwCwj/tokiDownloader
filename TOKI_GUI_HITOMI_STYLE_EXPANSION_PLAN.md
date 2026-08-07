# tokiDownloader Hitomi 스타일 기능 확장 계획서

## 1. 목적과 기준 문서

이 문서는 사용자가 제공한 Hitomi Downloader 화면을 참고해
`C:\gitproject\tokiDownloader`에 추가할 수 있는 메뉴, 설정, 작업 관리 및 선택형 다운로드
공급자 기능을 분류하고 구현 순서를 정한다.

기존 문서를 대체하지 않는다. 적용 우선순위는 다음과 같다.

1. 사용자가 현재 대화에서 직접 지시한 내용
2. `TOKI_GUI_DEVELOPMENT_PLAN.md`
3. 이 확장 계획서
4. `CLAUDE_GUI_IMPLEMENTATION_BRIEF.md`
5. `README.md`

Hitomi Downloader를 그대로 복제하는 것이 목표가 아니다. tokiDownloader에 실제로 필요한
기능을 같은 수준의 사용성으로 구현하되, 현재 작품 단위 모델과 GUI/CLI 동등성, 사용자
파일 보존 원칙을 유지한다.

## 2. 검토한 참고 화면

- 작업 메뉴: 저장, 작업 내보내기·가져오기, 로컬 파일 작업, 그룹, 트레이, 종료
- 도구 메뉴: 검색, 스크립트, 중복 이미지 검색, 작품 번호 복사
- 옵션 메뉴: 목록/아이콘 보기, 완료 후 동작, 항상 위, 클립보드 자동 추가, 삭제 정책,
  썸네일 표시·크기, 투명도, 설정
- 빠른 실행 도구 사용자 지정
- 설정/일반: 언어, 저장 폴더, 폴더명 형식, 미리보기, 플레이리스트
- 설정/네트워크: 내장 브라우저, 쿠키, 동시 작업, 작업별 연결, 프록시, 속도 제한,
  DPI 우회, 공인 IP
- 설정/디스플레이: 테마, 다크/시스템 모드, UI 배율, 배경 이미지, 글꼴
- 설정/고급: 트레이, 단축키, 소리, 이미지 후처리, 기록, 자동 저장·복구, 페이지 제한,
  저사양 모드, 절전 방지, HTTP API, 메모리 표시 등
- Hitomi 전용: 서버, 갤러리 정보, 파일명, 제외 태그, 일본어 제목, info.txt, 원본 이미지
- YouTube 전용: 형식·해상도, 파일명, 언어·자막·오디오, 썸네일, 채널 역순,
  챕터, 날짜, 코덱

빨간색으로 가려진 메뉴 항목은 화면만으로 정확한 기능을 알 수 없으므로 추측해 구현하지
않는다. 이후 사용자가 이름이나 동작을 알려주면 가장 가까운 단계에 추가한다.

## 3. 구현 가능성 결론

### 3.1 현재 구조에서 직접 구현 가능

- 작업 저장·가져오기·내보내기
- 작품 그룹과 미분류 그룹
- 목록/아이콘 보기 전환
- 검색, 중복 작품 및 중복 이미지 검사
- 항상 위, 트레이 최소화, 완료 알림과 완료 후 동작
- 클립보드 URL 감지와 사용자 확인 후 작업 추가
- 썸네일 숨김·크기, 테마, UI 배율, 배경, 글꼴
- 빠른 실행 도구 모음 사용자 지정
- 설정 검색과 설정 가져오기·내보내기·초기화
- 프록시, 동시 작업 수, 연결 수, 속도 제한
- 단축키, 자동 저장, 비정상 종료 복구, 절전 방지
- 작업 기록, 메모리 사용량 표시, 로컬 HTTP API
- 이미지 형식 변환, 크기 조절, 파일 유형 제외, PDF 생성

### 3.2 별도 라이브러리 또는 외부 실행 파일로 구현 가능

| 기능 | 후보 의존성 | 비고 |
|---|---|---|
| 내장 브라우저 | `PyQt6-WebEngine` 또는 기존 Puppeteer | 패키지 크기가 큼 |
| 쿠키 보관 | `keyring`, 암호화 저장소 | 평문 저장 금지 |
| 휴지통 이동 | `Send2Trash` | 영구 삭제와 분리 |
| 이미지 변환·리사이즈·해시 | `Pillow`, `ImageHash` | CPU 프로세스 풀 사용 |
| 프로세스·메모리 정보 | `psutil` | 작업별 자식 프로세스 확인 |
| Windows 트레이·절전·연결 프로그램 | PyQt6, 선택적 `pywin32` | Windows 전용 계층 분리 |
| HTTP API | 표준 라이브러리 또는 `FastAPI`/`uvicorn` | 기본 비활성, 로컬 바인딩 |
| PDF | `Pillow` 또는 `pypdf` | 원본 파일 보존 |
| YouTube | `yt-dlp`, FFmpeg | 완전히 별도 공급자 |
| 압축 파일 | `py7zr`, 외부 7-Zip 등 | RAR는 외부 도구가 필요할 수 있음 |

의존성은 한꺼번에 설치하지 않는다. 기본 만화 다운로드에 필요 없는 패키지는 기능별
optional dependency로 분리하고, 설치 여부와 버전을 `doctor --json`에서 확인한다.

### 3.3 조건부 또는 별도 승인 필요

- 경고 없는 삭제, 영구 삭제, 시스템 종료
- 브라우저 쿠키 가져오기·내보내기
- 사용자 스크립트 실행
- 외부에서 접근 가능한 HTTP API
- 관리자 권한 실행과 파일 연결 프로그램 변경
- 사이트 접근 제한이나 인증 절차를 우회하는 기능

이 기능들은 기술적으로 가능해도 보안과 데이터 손실 위험이 있으므로 기본 비활성으로
두고, 실행 직전 대상과 영향을 보여준다.

### 3.4 별도 공급자로 다뤄야 하는 기능

Hitomi.la/ExHentai와 YouTube는 현재 newtoki/manatoki/booktoki 다운로드 옵션이 아니다.
각각 URL 분석, 메타데이터, 인증, 파일 목록, 재시도 규칙이 다른 별도 공급자다.

- Hitomi 공급자: 갤러리 ID, 서버 선택, 태그 제외, 일본어 제목, info.txt, 원본 이미지
- YouTube 공급자: `yt-dlp` 기반 형식·해상도·자막·오디오·챕터·코덱 및 FFmpeg 후처리

핵심 GUI가 안정된 뒤 플러그인형 공급자 인터페이스로 추가한다. 공급자가 없어도 기본
toki 기능이 정상 작동해야 한다.

## 4. 공통 아키텍처 원칙

### 4.1 서비스와 CLI 우선

모든 버튼, 메뉴, 토글과 설정은 다음 순서로 구현한다.

1. 공용 서비스와 설정 스키마
2. CLI 명령과 JSON 출력
3. 단위·통합 테스트
4. GUI 메뉴, 버튼, 대화상자
5. GUI 캡처와 상태 JSON 검증
6. 문서, 커밋, 푸시

GUI에서만 가능한 기능을 만들지 않는다. 파일 대화상자는 CLI의 `--path`, 토글은
`--on|--off`, 선택지는 `--mode` 또는 `--format`으로 대응한다.

### 4.2 설정 구조

현재 `config.json`을 버전이 있는 설정 스키마로 확장한다.

```json
{
  "schemaVersion": 2,
  "general": {},
  "network": {},
  "display": {},
  "advanced": {},
  "providers": {
    "toki": {},
    "hitomi": {},
    "youtube": {}
  }
}
```

- 설정 변경은 원자적으로 저장하고 이전 파일 백업을 한 개 유지한다.
- 알 수 없는 필드는 삭제하지 않아 향후 버전과 호환한다.
- 비밀번호와 쿠키는 config.json에 평문으로 넣지 않는다.
- 모든 설정은 `config get`, `config set`, `config export`, `config import`,
  `config reset --section`으로 제어한다.

### 4.3 공급자 인터페이스

```text
Provider
├─ can_handle(url)
├─ inspect(url, settings)
├─ build_work_identity(metadata)
├─ enumerate_items(metadata, range)
├─ download(item, output, cancellation)
└─ postprocess(result, settings)
```

GUI와 작업 큐는 공급자별 웹 구현을 알지 않고 공통 작업 이벤트만 받는다. 공급자별
설정과 오류 코드는 독립 네임스페이스를 사용한다.

### 4.4 성능

- 설정창과 메뉴가 늘어나도 앱 시작 시 모든 페이지와 플러그인을 로딩하지 않는다.
- 설정 페이지는 최초 접근 시 생성한다.
- 중복 이미지 해시, 변환, PDF는 CPU 프로세스 풀에서 실행한다.
- 네트워크 동시성은 공급자별 제한과 전역 제한을 모두 적용한다.
- 아이콘 보기에서도 화면에 보이는 썸네일만 디코딩한다.
- 10,000개 작품, 100,000개 실행 이력 기준의 페이지 조회를 유지한다.

## 5. 단계별 구현 계획

### 단계 A. 설정 기반과 설정창 골격

- [x] 버전 설정 스키마와 안전한 마이그레이션
- [x] `config get/set/export/import/reset --json`
- [x] 설정창: 일반, 네트워크, 디스플레이, 고급, 공급자 페이지
- [x] 설정 검색
- [x] 변경 적용·취소·기본값 복원
- [x] optional dependency 상태 표시와 `doctor --json`

완료 조건: GUI와 CLI에서 같은 설정을 읽고 쓰며 재시작 후 값이 보존된다.

구현 메모: 설정 내보내기는 원자 교체, 가져오기는 기본 미리보기와 실행 전 백업을 사용한다.
GUI가 실행 중이면 CLI 변경도 IPC를 통해 즉시 반영한다. `settings --show-gui --tab provider
--search yt-dlp`와 `status --json`으로 공급자 탭·검색 상태를 검증했고 프로그램 자체 캡처는
`logs/settings-provider-search.png`에 저장했다. Python 계약·CLI·GUI IPC 테스트 124건을
통과했다.

### 단계 B. 작업·도구 메뉴

- [x] 작업 저장 스냅샷과 JSON 내보내기·가져오기
- [x] 작품 그룹 생성·이름 변경·이동·해제
- [x] 로컬 작품 폴더 검사 작업
- [x] 로컬 압축 파일 검사 작업
- [x] 제목·작가·그룹·ID 통합 검색
- [x] 작품 중복 및 이미지 해시 중복 검사
- [x] 작품 ID/원본 URL/저장 폴더 경로 복사
- [x] 메뉴 단축키와 비활성 조건

CLI 예시:

```text
jobs export --output PATH --json
jobs import --input PATH --dry-run --json
group create --name NAME
group assign --job ID --group GROUP_ID
local inspect --path PATH --json
duplicates works --json
duplicates images --job ID --algorithm phash --json
```

구현 메모: 작품 단위 기록과 실행 이력을 버전 JSON으로 원자 내보내기한다. 가져오기는 기본
미리보기이며 기존 작품/실행은 덮어쓰지 않고 누락분만 추가한다. 미완료 상태는 `중지됨`으로
복원하고 다운로드 폴더·파일은 변경하지 않는다. 작업 메뉴와 `jobs export/import`,
`--show-gui`, `--via-gui`, `--close`가 같은 서비스를 사용한다. 실제 DB 2작품·3실행 기록을
내보낸 뒤 무변경 GUI 미리보기와 `logs/jobs-snapshot-import-gui.png` 캡처를 확인했으며
Python 127건과 Node 7건을 통과했다.

작품 정리 그룹은 DB v3의 별도 그룹·멤버십 테이블을 사용해 폴더명용 번역/출판 `group`
메타데이터와 분리했다. `group list/create/rename/assign/unassign/manage`와 작업 메뉴·작품
우클릭 메뉴가 같은 서비스를 사용한다. 실제 DB는 백업 후 v3으로 마이그레이션했으며 시험
그룹은 만들지 않았다. 빈 상태 관리창은 `logs/work-group-manager-gui.png`로 확인했다.
Python 130건과 Node 7건을 통과했다.

로컬 압축 작품 검사는 압축 해제 없이 중앙 목록만 읽어 이미지·빈 파일·암호화·경로 탈출
위험을 보고한다. ZIP/CBZ는 기본 지원하고 7Z/RAR 계열은 `requirements-archive-tools.txt`의
선택 모듈과 `setup-gui.cmd -WithArchiveTools`로 분리했다. `local inspect --path`,
`--show-gui`, `--close` 및 도구 메뉴가 같은 서비스를 사용한다. 정상 ZIP 1파일·이미지 1장을
읽기 전용으로 검사한 화면은 `logs/archive-inspection-gui.png`로 확인했다.
Python 133건과 Node 7건을 통과했으며 `doctor --json`에서 py7zr·rarfile 설치 여부를
선택 의존성으로 확인한다.

통합 검색은 DB v4의 작가·폴더명용 그룹 검색 열과 기존 제목·작업 ID·작품 키·URL, 별도
정리 그룹 이름을 한 쿼리로 묶었다. 기존 페이지 로딩·GUI 메모리 상한을 유지하고 10,000개
합성 작품에서 유일 작가 검색을 자동 검증한다. 실제 작가 `킷사` 검색은 CLI·GUI 모두 1건을
반환했고 `logs/integrated-search-author-gui.png`로 확인했다.
Python 134건과 Node 7건을 통과했고 실제 DB는 `jobs.db.pre-v4.bak` 보존 후 v4로
마이그레이션했다.

중복 검사 1차로 작품 키 강제 유일성 외에 제목+작가와 저장 경로 충돌을 진단하는
`duplicates works` 및 GUI 결과창을 추가했다. 실제 2작품은 중복 의심 0건이었고
`logs/duplicate-works-gui.png`로 빈 결과 상태를 확인했다. 자동 병합·삭제는 하지 않는다.
Python 137건과 Node 7건을 통과했다.

이미지 중복 검사는 작품별 파일을 변경하지 않고 `sha256` 완전 일치 또는 선택 기능인
ImageHash `phash`로 진단한다. SHA-256은 제한된 I/O 스레드 풀, pHash는 제한된 CPU
프로세스 풀을 사용하며 CLI·GUI·IPC가 같은 서비스를 호출한다. 실제 작품 169장을 스레드
8개로 검사해 중복 0건·실패 0건을 확인했고 화면은
`logs/duplicate-images-sha256-gui.png`로 보존했다. Python 140건과 Node 7건을 통과했다.

작품 우클릭 메뉴에서 작업 ID·원본 URL·저장 폴더 경로·작품명을 각각 복사할 수 있고
`copy-id/link/path/title --job ID`도 같은 값을 제공한다. GUI가 꺼진 경우 Windows 네이티브
클립보드를 직접 사용해 별도 셸 창을 띄우지 않는다. 실제 작품의 세 값을 CLI와
`Get-Clipboard`로 대조했고 메뉴 화면은 `logs/work-copy-context-menu.png`로 확인했다.
Python 143건과 Node 7건을 통과했다.

단계 B 메뉴는 신규·범위 재검사, 스냅샷, 그룹, 압축 검사, 중복 검사까지 24개 고유 단축키와
대응 CLI를 공용 카탈로그로 관리한다. 선택 작품·활성·일시정지·대기 상태의 공용 판정으로
QAction과 상단 다운로드·중지·전체 재검사 버튼을 함께 활성화하며 `status --json`의
`actions`로도 조회한다. 유휴 실제 GUI에서 다운로드·중지·일시정지는 비활성, 작품 재검사와
폴더·상세는 활성임을 확인했고 단축키 표는 `logs/menu-shortcuts-gui.png`로 보존했다.
Python 144건과 Node 7건을 통과했다.

### 단계 C. 보기·빠른 실행·트레이

- [x] 목록/아이콘 보기와 가상화 유지
- [x] 항상 위, 썸네일 숨김·크기, 창 투명도
- [x] 빠른 실행 도구 항목 선택과 드래그 순서 변경
- [x] 트레이 최소화, 닫기 동작, 알림
- [x] 모든 작업 완료 후 아무 동작/프로그램 종료/시스템 종료
- [x] 클립보드 URL 감지와 중복 확인

시스템 종료는 카운트다운과 취소 버튼을 제공하고 기본값으로 선택하지 않는다.

구현 메모: 설정 스키마 v2에 목록/아이콘 보기, 썸네일 표시·크기, 항상 위와 불투명도를
추가했다. 기존 설정은 `config.json.pre-v2.bak`을 먼저 만든 뒤 자동 마이그레이션한다.
아이콘 모드는 한 번에 100개씩 배치 레이아웃하고 기존 SQLite 페이지 조회와 GUI 2,000개
메모리 상한을 그대로 사용한다. 목록 썸네일 숨김은 `logs/list-view-hidden-thumbnails.png`,
상태·제목 오버레이를 포함한 아이콘 보기는 `logs/icon-view-gui.png`로 확인했으며 검증 후
사용자 설정은 목록·썸네일 보통·불투명 100%·항상 위 끔으로 복원했다. Python 144건과
Node 7건을 통과했다.

빠른 실행 막대는 다운로드·중지·전체 재검사·폴더·작품 정보·중복 검사·설정·화면 캡처 중
원하는 항목만 표시한다. 디스플레이 설정의 체크 목록은 내부 드래그 이동으로 표시 순서를
바꾸고 `set-settings --quick-actions ID,...`도 같은 설정을 적용한다. 선택·실행 상태에 따른
버튼 비활성은 기존 공용 QAction 판정을 따른다. 실제 재정렬 막대는
`logs/quick-action-bar-gui.png`, 설정 목록은 `logs/quick-action-settings-gui.png`로 확인한
뒤 기본 빠른 실행 순서로 복원했다. Python 144건과 Node 7건을 통과했다.

모든 작업 완료 후 동작은 기본 `none`이며 프로그램 종료 또는 Windows 종료를 사용자가
명시 설정한 뒤 실제 대기열이 한 번 실행되고 완전히 비었을 때만 무장된다. 5~300초
카운트다운과 취소 버튼을 제공하고 `completion-action status|set|preview|cancel`로 정책과
GUI를 동일하게 검증한다. 시스템 종료 미리보기는 `executed: false`로 실행해
`logs/completion-shutdown-preview-gui.png`를 확인한 뒤 취소했으며 설정도 `none`으로
복원했다. 실제 시스템 종료 명령은 검증 중 호출하지 않았다. Python 147건과 Node 7건을
통과했다.

클립보드 감지는 기본 끔이며 Qt 이벤트로 새 텍스트만 검사한다. 지원 작품 URL은 회전 도메인과
무관한 작품 키로 변환해 전체 SQLite 기록과 중복을 확인하고, 중복이면 추가하지 않는다. 새
작품도 사용자 확인 전에는 대기열에 넣지 않는다. `clipboard inspect|monitor`와 GUI IPC가
같은 읽기 전용 판정을 사용한다. 실제 기존 URL은 `duplicate: true`, 미등록 ID는 `new`로
확인했고 설정 화면은 `logs/clipboard-monitor-settings-gui.png`로 캡처한 뒤 감지를 다시
껐다. Python 150건과 Node 7건을 통과했다.

### 단계 D. 일반·디스플레이 설정

- [x] 언어 구조와 한국어 리소스 분리
- [x] 기본 저장 폴더와 작품 폴더명 템플릿 편집기
- [x] 템플릿 미리보기와 Windows 경로 유효성 검사
- [x] 테마, 다크/시스템 모드
- [x] UI 배율, 배경 이미지, 글꼴
- [x] 고해상도 DPI와 다중 모니터 검증

폴더명 템플릿은 미리보기와 `--dry-run`을 먼저 제공하며 기존 폴더를 자동 변경하지 않는다.

2026-08-07 폴더명 템플릿 구현: 설정 스키마 v3에 `folderNameTemplate`을 추가하고 기본값을
요청된 `[{author}][{group}] {title}`로 유지했다. `{site}`, `{id}`도 선택적으로 지원하되
`{title}`은 필수이며 알 수 없는 변수, Windows 금지 문자·예약 이름·길이를 Python 공용
서비스와 Node 다운로더 양쪽에서 검사한다. `folder-template --output PATH --json`은 실제
파일 변경 없이 예상 경로와 충돌을 반환하고 설정창은 입력 즉시 같은 미리보기를 표시한다.
기존 작품은 모든 재검사·메타데이터 갱신에서 저장된 `output_path`를 `-content-path`로
우선 전달해 템플릿 변경으로 폴더가 바뀌지 않는다. 실제 CLI에서 요청된 한글·공백 예시와
기존 폴더 충돌을 확인했고 `logs/folder-template-settings-gui.png`의 다크 테마 대비를
검토했다. Python 152건과 Node 11건을 통과했다.

2026-08-07 언어·디스플레이 구현: 한국어 핵심 메뉴·설정·공급자 문구를
`locales/ko.json`으로 분리하고 `uiLanguage` 설정과 `language list|status|set` CLI를
연결했다. 현재 번들은 한국어만 제공하지만 동일 키 JSON을 추가할 수 있는 구조다. UI 배율
75~200%, 설치 글꼴, PNG/JPEG/BMP/WebP 배경 경로를 설정 스키마 v4와 GUI·CLI에서
동일하게 검증한다. 배율은 글꼴, 입력 여백, 버튼, 탭과 아이콘 격자에 반영하며 배경은 원본
파일을 수정하지 않고 화면에 맞춰 그린 뒤 테마별 보호 오버레이를 적용한다. 125%·Arial
설정 화면은 `logs/display-customization-125-gui.png`, 밝은 실제 배경의 대비 결과는
`logs/main-background-protected-gui.png`로 확인한 후 UI 배율 100%, Malgun Gothic,
배경 없음으로 복원했다. `window` CLI로 실제 3개 화면의 DPR 1.25·1.5·2.0, 음수 좌표,
저장 화면 복원과 `onScreen: true`를 확인하고 125% 실화면도 함께 검증했으며 Python
154건과 Node 11건을 통과했다.

2026-08-07 설정 기반 1차: 현재 toki 기능에 필요한 일반·네트워크·고급 탭을 먼저
구현했다. 저장 폴더, 브라우저 표시, 로그 패널, 동시성, 재시도와 로그 순환을 GUI·CLI에서
동일하게 조회·변경한다. 화면 예시의 전체 공급자 메뉴나 폴더명 템플릿, 테마·배율은 이
단위에 포함하지 않고 아래 후속 항목으로 유지한다.

### 단계 E. 네트워크·브라우저·쿠키

- [x] 기본 headless 브라우저와 진단용 표시 모드
- [x] 선택형 내장 브라우저
- [x] 쿠키 보기·가져오기·내보내기·초기화
- [x] 전역 작품 동시 수와 작업별 이미지 연결 수
- [x] HTTP/SOCKS 프록시와 선택적 인증
- [x] 전역 다운로드 속도 제한
- [ ] 공인 IP 확인
- [x] 공급자별 백오프, 속도 제한과 차단 감지

쿠키는 OS 자격 증명 저장소로 보호하고 내보낼 때 경고와 명시적 경로를 요구한다. 기본
동시성은 현재 보수적인 값을 유지하며 화면 예시의 16/24를 그대로 기본값으로 사용하지
않는다.

2026-08-07 브라우저 표시 정책 명시: 기본 설정은 `showBrowser: false`이고 Node 실행기는
`headless: new`로 별도 창 없이 동작한다. 진단 표시를 켠 경우에만 자동화 전용 임시
프로필의 창을 표시하며 개인 Chrome 프로필을 사용하지 않는다. 공용
`browser_launch_policy`와 `browser-mode status|set` CLI, 기존 일반 설정 체크박스가 같은
값을 사용하고 실제 설정을 다시 headless로 복원했다.

2026-08-07 선택형 내장 브라우저 구현: `PyQt6-WebEngine`을 별도
`requirements-browser-tools.txt`와 `setup-gui.cmd -WithBrowserTools`로 설치하는 선택 기능으로
추가했다. 도구 메뉴·공급자 설정 버튼과 `embedded-browser capabilities|plan|manage` CLI가 같은
창을 제어한다. 기본 페이지는 네트워크를 쓰지 않는 오프라인 HTML이며 URL을 주소창에 미리
채워도 자동 이동하지 않는다. 실제 HTTPS 이동은 GUI 호스트 확인 또는 CLI `--navigate --yes`가
필요하다. 이름 없는 off-the-record `QWebEngineProfile`, 메모리 캐시, 영구 쿠키 금지, 다운로드
취소와 새 창 차단을 적용해 개인 Chrome 및 자동화 쿠키와 분리했다. QApplication보다 먼저
`AA_ShareOpenGLContexts`를 설정해야 하는 Qt 초기화 오류도 실제 GUI 로그로 발견해 수정했다.
외부 이동 없이 `https://newtoki1.org/manhwa/34360`을 주소창에만 넣어
`logs/embedded-browser-offline-gui.png`를 자체 캡처했고 상태가 `url: ""`,
`networkApproved: false`, `offTheRecordProfile: true`, `persistentCookies: false`임을 확인했다.
Python 170건과 Node 16건을 통과했다.

2026-08-07 네트워크 정책 구현: 설정 스키마 v5에 인증 정보가 없는 HTTP/HTTPS/SOCKS
프록시, 전체 이미지 속도 제한과 마나토끼·뉴토끼·북토끼별 요청 간격·백오프를 추가했다.
Node 이미지 요청은 `proxy-agent`를 사용해 브라우저 탐색과 같은 프록시를 거치며, 동시
작업 전체가 하나의 토큰 일정을 공유해 설정 대역폭을 합산 기준으로 제한한다. 공급자별
간격은 페이지와 이미지 요청에, 백오프는 이미지 재시도에 적용된다. 429·Cloudflare·일반
네트워크·파일 시스템 오류의 기존 구조화 분류도 유지한다. `network-policy status|set`과
네트워크 설정 탭을 같은 서비스에 연결하고 `logs/network-policy-settings-gui.png`를
확인한 뒤 프록시 없음·속도 무제한·간격 0ms·백오프 2초로 복원했다. 인증이 포함된 프록시
URL은 평문 저장 방지를 위해 거부하므로 `HTTP/SOCKS 프록시와 선택적 인증` 항목은 OS 보안
저장소 구현 전까지 완료 처리하지 않는다. Python 159건과 Node 13건을 통과했다.

2026-08-07 쿠키 보안 관리 구현: 선택 의존성 `keyring`과 Windows WinVault 백엔드를
진단하고, JSON·Netscape 쿠키 파일의 5 MiB·10,000개 한도 미리보기, 공급자별 저장 상태,
가져오기, 민감 JSON 내보내기와 초기화를 구현했다. 실제 값은 `config.json`·DB·로그·화면에
남기지 않고 OS 자격 증명 저장소의 `tokiDownloader` 서비스에만 저장한다. 모든 민감
읽기·쓰기·평문 내보내기·삭제는 CLI `--yes`와 GUI 재확인을 요구한다. 단위 테스트는 메모리
가짜 저장소와 임시 쿠키만 사용했고 실제 Windows 저장소에서는 백엔드 가용성만 읽었다.
`cookies manage --show-gui`로 값 조회 전 상태를 `logs/cookie-manager-vault-gui.png`에
캡처했으며 실제 사용자 쿠키는 읽거나 쓰거나 삭제하지 않았다. Python 164건과 Node
13건을 통과했다.

2026-08-07 프록시 선택적 인증 구현: 프록시 주소는 기존처럼 인증 정보 없는 URL만
`config.json`에 저장하고 사용자명·비밀번호는 해당 정규화 주소와 함께 Windows 자격 증명
저장소의 `tokiDownloader` 서비스에만 보관한다. `proxy-auth capabilities|status|set|clear|manage`
CLI와 네트워크 설정의 인증 관리 창을 연결했으며 읽기·쓰기·삭제는 `--yes` 또는 GUI 재확인을
요구한다. 비밀번호는 표준 입력 또는 마스킹 입력으로만 받고 CLI 인자·설정·DB·로그·상태
JSON에는 넣지 않는다. 다운로드 실행 시 저장 주소가 현재 프록시와 정확히 일치할 때만 자식
프로세스 환경으로 전달하며 이미지 요청은 `proxy-agent`, 브라우저는 Chrome 인증 이벤트 중
출처가 `Proxy`인 도전에만 응답해 사이트 자체 인증에는 프록시 비밀번호를 보내지 않는다.
외부망 없이 임시 로컬 HTTP Basic 및 SOCKS5 사용자명·비밀번호 서버를 실제 통과하는 테스트를
완료했다. `logs/proxy-auth-vault-gui.png`는 값과 상태를 읽기 전 화면으로 자체 캡처했고
`passwordExposed: false`를 확인했으며 실제 Windows 저장소에는 테스트 자격증명을 쓰거나
삭제하지 않았다. 검증 후 프록시 없음으로 복원했고 Python 167건과 Node 16건을 통과했다.

공인 IP 확인은 `public-ip plan`과 주입 응답 단위 테스트, GUI 확인 절차까지 구현했다. 실제
`api.ipify.org` 요청은 외부 API 승인 전에는 실행하지 않으므로 해당 체크박스는 보류한다.

### 단계 F. 고급 동작과 파일 후처리

- [x] 단축키 편집·가져오기·내보내기
- [x] 작업 완료 알림음과 메시지
- [x] 이미지 형식 변환
- [x] 이미지 리사이즈와 파일 유형 제외
- [x] 압축 파일 연결 프로그램과 미리보기
- [x] 자동 저장 주기와 불완전 작업 복구
- [ ] 페이지 수 제한, 스크롤 속도, 지연 로딩, 저사양 모드
- [ ] 다운로드 중 절전 방지
- [ ] PDF 생성
- [ ] 메모리 사용량 표시
- [ ] 로컬 HTTP API

변환·리사이즈·PDF는 원본 보존이 기본이며, 원본 제거 옵션은 별도 승인 없이는 실행하지
않는다. HTTP API는 기본 `127.0.0.1` 바인딩, 임의 토큰 인증, 기본 비활성으로 한다.

2026-08-07 이미지 변환 보강: 별도 프로세스의 장별 JSON Lines 진행률을 GUI에 표시하고
GUI 중지 버튼과 `cancel-conversion --job ID`를 같은 IPC 동작으로 연결했다. 결과 파일은
임시 경로에 완전히 쓴 뒤 원자 교체하며, 중단 뒤 재실행 시 잔여 임시 파일을 정리하고
완성된 결과를 건너뛴다. 이 복구 범위는 이미지 변환에 한정되며 위의 전체 불완전 작업
복구 항목을 완료한 것으로 보지 않는다.

2026-08-07 단축키 편집 구현: 설정 스키마 v6에 동작 ID별 키 배열을 저장하고 기본값과
사용자 지정·비활성 상태를 공용 카탈로그로 계산한다. PyQt6 PortableText 검증으로 동작 간
충돌, 알 수 없는 키, 수정 키 없는 단일 문자, `Alt+F4`를 차단하며 동작당 최대 4개를 허용한다.
`shortcuts --set|--disable|--reset|--reset-all|--export|--import` CLI와 GUI 편집창은 같은
검증·저장 서비스를 사용하고 실행 중 QAction에 즉시 반영한다. 가져오기는 1 MiB 제한과
형식 버전 검사를 거쳐 기본 미리보기, `--execute --yes` 확인 뒤에만 적용하며 내보내기에는
비밀값이 없다. 실제 GUI IPC로 임시 키를 적용·조회하고 원래 빈 덮어쓰기로 복원했으며
`logs/shortcut-editor-gui.png`에서 어두운 테마의 표·입력·버튼 대비를 확인했다. Python
173건과 Node 16건을 통과했다.

2026-08-07 작업 결과 알림음·메시지 구현: 설정 스키마 v7에 `notificationSound`와
`notificationMessageBox`를 추가했으며 기존 완료·오류 알림 선택과 분리해 둘 다 기본 꺼짐으로
두었다. 공용 서비스가 완료·오류 메시지, 대상 여부와 요청된 전달 방식을 먼저 계획하고 GUI는
상태 표시줄, 선택적 트레이 풍선, 비차단 메시지 상자와 Windows 시스템 알림음을 실행한다.
`notifications status|set|preview|close` CLI와 `status --json`으로 설정·미리보기 결과·열린
메시지 상자를 제어하고 검증한다. 실제 소리는 사용자에게 갑자기 재생하지 않고 모의 콜백으로
검증했으며, 메시지 상자만 임시 활성화해 실제 IPC 미리보기·캡처·CLI 닫기를 확인한 뒤
`sound=none`, 메시지 상자 꺼짐으로 복원했다. 화면은 `logs/notification-settings-gui.png`,
`logs/notification-message-preview.png`에 보존했고 Python 176건과 Node 16건을 통과했다.

2026-08-07 이미지 리사이즈·파일 유형 제외 구현: 설정 스키마 v8의 최대 너비·높이와 제외
확장자를 공용 정책으로 정규화하고 `image-processing status|set`, `convert-images` 실행별
옵션, 고급 설정과 이미지 변환 확인창에 연결했다. 최대 한 방향만 지정해도 되고 Pillow
LANCZOS가 원본 비율을 유지해 축소하며, 축소 결과는 무축소 결과와 분리된
`_converted/<형식>-<너비>x<높이>`에 임시 파일 후 원자 교체로 저장한다. JPG/JPEG/PNG/WebP/
GIF/BMP/AVIF 제외는 후처리 대상 선택에만 적용해 원본과 기존 결과를 지우지 않는다. 임시
한글·공백 작품 경로에서 128×96·120×80 원본을 실제 처리해 최대 64×64, 제외 1장, 원본
바이트 불변을 확인했고 사용자 작품에는 파일 생성 없이 dry-run만 실행했다. GUI는
`logs/image-processing-settings.png`, `logs/image-resize-conversion-plan.png`로 확인했고
Python 177건과 Node 16건을 통과했다.

2026-08-07 압축 파일 연결 프로그램·미리보기 구현: 설정 스키마 v9에 앱 내부
`system|custom` 뷰어 방식과 선택 실행 파일 경로를 추가했다. 기존 ZIP/CBZ/7Z/CB7/RAR/CBR
중앙 목록 검사는 그대로 읽기 전용이며 검사창에서 현재 뷰어와 `연결 프로그램으로 열기`
버튼을 제공한다. `archive-viewer status|set|open` CLI가 같은 정책을 사용하고 `open`은 기본
미리보기, 실제 외부 프로그램 실행은 `--execute --yes` 또는 GUI 확인 뒤에만 가능하다.
레지스트리와 Windows 시스템 파일 연결은 변경하지 않는다. 실제 GUI에서 Python 실행 파일을
임시 custom 뷰어로 저장·조회하고 기존 ZIP의 실행 계획만 확인한 뒤 system/빈 경로로 복원했으며
외부 프로그램은 실행하지 않았다. 화면은 `logs/archive-viewer-settings.png`,
`logs/archive-viewer-preview.png`에 보존했고 Python 180건과 Node 16건을 통과했다.

2026-08-07 자동 저장 주기·불완전 작업 복구 구현: 설정 스키마 v10에 1~300초 자동 저장
주기와 시작 복구 선택을 추가하고 기존 변경 ID 전용 SQLite 묶음 저장 타이머에 즉시 반영한다.
복구 서비스는 `execute=False`에서 DB와 파일을 바꾸지 않고 대기·실행 중·일시정지·재시도
대기 후보를 보고하며, 명시적 실행 때만 상태와 실행 종료 시각을 중지됨으로 원자 갱신한다.
진행률과 다운로드 파일은 보존한다. `persistence status|set|recover`, GUI 고급 설정과 복구
미리보기 창이 같은 서비스를 사용하고, 실제 수동 복구는 `--execute --yes` 또는 GUI 확인을
요구하며 현재 실행·대기 작업이 있으면 차단한다. 실제 DB는 후보 0건이라 변경하지 않았고
기본 1초·시작 복구 켜짐을 유지했다. 저장 실패 시 dirty ID를 유지하고 타이머를 다시 예약해
성공으로 가장하지 않는다. 화면은
`logs/persistence-settings.png`, `logs/persistence-recovery-preview.png`에 보존했고 Python
184건과 Node 16건을 통과했다.

### 단계 G. Hitomi/ExHentai 선택형 공급자

- [ ] URL과 갤러리 ID 분석
- [ ] 서버 자동·수동 선택과 우선순위
- [ ] 갤러리 메타데이터 모드
- [ ] 원본/숫자/숫자+원본 파일명
- [ ] 제외 태그 관리
- [ ] 일본어 제목 우선
- [ ] info.txt 또는 공통 metadata.json 생성
- [ ] 원본 이미지 선택
- [ ] 인증이 필요한 사이트의 사용자 소유 쿠키 처리

접근 제한 우회는 구현 범위에 포함하지 않는다. 사이트 변경에 견딜 수 있도록 공급자
테스트 픽스처와 명확한 오류 코드를 둔다.

### 단계 H. YouTube 선택형 공급자

- [x] `yt-dlp`와 FFmpeg 설치 검사
- [ ] 형식, 해상도, 비디오·오디오 코덱
- [ ] 파일명 템플릿
- [ ] 선호 언어, 자막, 오디오 트랙
- [ ] 썸네일과 메타데이터
- [ ] 채널/재생목록 순서
- [ ] 챕터 마커
- [ ] 업로드 날짜를 파일 수정 날짜로 적용
- [ ] 진행률, 중지, 재시도와 실행 이력 통합

YouTube 공급자는 별도 optional dependency이며 기본 toki 설치와 테스트를 느리게 만들지
않는다. 사용자는 다운로드 권한이 있는 콘텐츠만 대상으로 해야 한다.

## 6. 기능별 안전 경계

다음 작업은 항상 실행 전에 확인한다.

- 실제 다운로드 파일 영구 삭제
- 기존 파일을 대체하는 변환·리사이즈·PDF 후 원본 제거
- 시스템 종료 또는 재부팅
- 쿠키·인증 정보 내보내기
- 사용자 스크립트 실행
- 관리자 권한 요청
- 외부 네트워크에 HTTP API 공개
- 대량 폴더명 변경과 이동

휴지통 이동, 기록만 제거, 설정 미리보기와 dry-run은 명확히 구분한다.

## 7. 공통 완료 정의

기능 하나는 다음 조건을 모두 충족해야 완료다.

- 공용 서비스와 설정 스키마 구현
- CLI 명령, 종료 코드와 `--json` 결과 구현
- 네트워크 없는 단위 테스트
- 필요한 경우 별도 실제 공급자 통합 테스트
- GUI 메뉴·버튼·설정 페이지 연결
- CLI로 GUI 동작 실행 또는 결과 확인
- GUI 직접 캡처와 텍스트 대비 확인
- 한글·공백 Windows 경로 검증
- 대량 데이터 성능 회귀 확인
- README, CLI 도움말과 계획서 갱신
- 논리적 단위 커밋과 추적 브랜치 푸시

## 8. 추진모드 규칙

추진모드에서는 기존 `TOKI_GUI_DEVELOPMENT_PLAN.md`의 아직 끝나지 않은 핵심 단계와 이
확장 계획의 단계 A부터 순서대로 진행한다. 공급자 G/H는 핵심 GUI와 설정 기반이 안정된
후 진행한다.

- 기존 다운로드 결과와 사용자 설정을 먼저 백업·마이그레이션 검증한다.
- 한 번에 하나의 수직 기능을 서비스 → CLI → 테스트 → GUI → 캡처 → 문서 순서로 끝낸다.
- 가짜 메뉴나 작동하지 않는 토글을 만들지 않는다.
- 새 GUI 동작은 반드시 CLI 대응 명령을 함께 추가한다.
- 선택 라이브러리는 필요한 단계에서만 설치하고 requirements를 분리한다.
- 검증된 단위마다 커밋·푸시한다.
- 안전 경계에 해당하는 실제 실행만 사용자에게 확인한다.

## 9. 권장 우선순위

1. 기존 계획의 단계 2: 실행 이력과 작품 상세 정보
2. 확장 단계 A: 설정 스키마와 설정창 골격
3. 단계 B: 작업 내보내기·가져오기와 그룹
4. 단계 C/D: 보기, 빠른 실행, 트레이, 테마
5. 단계 E: 네트워크와 쿠키
6. 단계 F: 파일 후처리와 HTTP API
7. 단계 G: Hitomi 공급자
8. 단계 H: YouTube 공급자

이 순서는 화면만 먼저 비슷하게 만드는 대신 각 설정이 실제 엔진 동작과 연결되도록 하기
위한 것이다.
