# 고정 바로가기 복구와 종료 진단 실행기

## 요청과 확인한 원인

- 사용자가 프로그램이 다시 꺼졌고, 작업 표시줄 고정 아이콘으로도 실행되지 않는다고 보고했다.
- 기존 `Python.lnk`는 전역 Python 3.13 `pythonw.exe`만 가리키고 **Arguments가 비어 있었다**.
  Shell 속성의 AppUserModelID는 `EtaSwCwj.tokiDownloader.GUI.1`이므로 이 앱의 고정 항목임을
  확인했다. 이름만으로 다른 Python 프로그램의 바로가기를 수정하지 않았다.
- 이전 `gui.log`는 2026-09-09 02:10:06 작품 ZIP 생성 후 빈 회차 폴더 정리 과정의
  `WinError 5`에서 끝났다. 이 오류는 압축 서비스에서 잡혀 결과로 반환되는 오류이며,
  **GUI 프로세스 종료 원인이라고 입증되지 않았다**. 기존 로그로 과거의 갑작스러운 종료를
  소급 확정할 수 없으므로 이번 변경은 실행 복구와 다음 종료의 증거 확보에 한정했다.

## 구현

- `toki_launcher.py`: Qt 및 외부 모듈 없이 시작하는 표준 라이브러리 실행기. 별도의
  무창 프로세스가 GUI 자식 프로세스의 종료를 OS wait로 기다리고 실제 종료 코드를 남긴다.
  폴링 스레드나 다운로드 큐 변경은 추가하지 않았다. Windows 가상환경 redirector의 PID와
  실제 Python PID는 각각 `childPid`, `pythonPid`/`child.pid`로 구분할 수 있다.
- 실행별 `process.json`/`child.json`, 순환 `events.log`와 `fault.log`를 저장한다.
  시작 실패·Python 예외·Qt 메시지·백그라운드 스레드 예외·정상 종료·비정상 종료를 기록한다.
  `os._exit(0)`도 정상 반환 마커가 없으면 `unexpected_exit`로 처리한다.
- GUI 닫기 요청·트레이 숨기기·종료 취소·저장 완료·이벤트 루프 반환을 기록한다.
  사용자 닫기와 `cli_quit`, 프로그램 종료 액션을 구별한다.
- `start-gui.vbs`, `start-gui.cmd`, `start_gui_background`, 직접 `toki_app.py gui` 경로를
  같은 실행기로 연결했다. 이미 GUI가 있으면 기존 창을 보여주고 종료한다.
- `toki_windows_launch.py`: 네이티브 창에 AppUserModelID와 재실행 명령·이름·아이콘을 설정하고
  Windows에서 값을 다시 읽어 검증한다. 창 종료 시 VT_EMPTY로 정리한다.
  이는 [Windows 창 속성 저장소 규칙](https://learn.microsoft.com/en-us/windows/win32/api/shellapi/nf-shellapi-shgetpropertystoreforwindow)과
  [재실행 명령/표시 이름의 동시 설정 규칙](https://learn.microsoft.com/en-us/windows/win32/properties/props-system-appusermodel-relaunchcommand)을 따른다.
- `launcher taskbar`는 조회만 한다. `--repair`가 있을 때만 일치하는 앱 ID의 바로가기를
  백업 후 수정하고 검증하며, 실패 시 백업을 복원한다. PowerShell은 CREATE_NO_WINDOW로
  실행한다. 다른 앱의 고정 항목이나 작업 표시줄 레지스트리는 변경하지 않는다.
  수정 후 해당 `.lnk`에만 Shell 변경 알림을 보내며 Explorer를 재시작하지 않는다.

## CLI 및 검증

```powershell
.\toki-cli.cmd launcher taskbar --json
.\toki-cli.cmd launcher taskbar --repair --json
.\toki-cli.cmd launcher status --json
.\.venv\Scripts\python.exe -X utf8 toki_launcher.py status --json
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -p 'test_*.py'
node --test
git diff --check
```

- Python 전체 447개, Node 전체 72개 통과. 새 테스트는 정상 반환, 예외, 종료 코드 0/7의
  비정상 종료, 외부 종료, 시작 실패, 스레드 예외, stdout/stderr 기록, 로그 순환·보존,
  대체 로그 경로, 읽기 전용 조회/명시적 수정, Windows 실제 창 속성 읽기/쓰기/해제를 검증한다.
- 독립 임시 DB/설정/IPC와 offscreen Qt를 사용한 GUI를 실행기 아래에서 시작했다.
  CLI 상태 조회 → PNG 캡처 → CLI 정상 종료 → 저장 완료/종료 코드 확인까지 통과했다.
  실제 클립보드와 실제 다운로드는 테스트에 사용하지 않았다.
- 실제 고정 항목을 백업하고 수정한 후 다시 조회해 `needsRepair=false`를 확인했다.
  작업 표시줄 `.lnk` 12개를 수정 전후 SHA-256 비교하여 **이 앱의 Python.lnk 1개만 변경**,
  나머지 11개 불변/누락 없음 확인.
- 수정된 실제 `.lnk`를 Shell 실행하여 `existing_gui_show`와 종료 코드 0을 확인했다.
  기존 다운로드 프로세스는 그대로 진행 중이었다. 화면은
  `logs/2026-09-09-launcher-repair.png`로 캡처하고 확인했다.
- 기존 바로가기 백업:
  `logs/shortcut-backups/20260909-233049-0151583/Python.lnk`.

## 제한 / 사용자 데이터 보존

- 기존 GUI에는 실행 중 다운로드 1개, 대기 4개가 있어 종료하거나 재시작하지 않았다.
  **실제 기존 GUI의 강화된 종료 기록 및 새 창 속성은 다음 실행부터 적용**된다.
  이번 실제 실행 검증은 기존 창 표시 경로이며, 새 GUI 시작/정상 종료는 격리 환경에서 검증했다.
- 종료 코드는 종료 원인 조사에 필요한 증거지만, 강제 종료한 주체나 이유를 확정하지 않는다.
  관찰 프로세스까지 함께 종료되는 정전/재부팅에는 종료 코드가 없을 수 있다.
  이 경우 `exitObserved=false`이며 실행 중 상태와 미관찰 종료를 단정적으로 구별하지 않는다.
- faulthandler는 지원되는 네이티브 오류 스택 기록을 활성화한다. 실제 사용자 GUI에 네이티브
  충돌을 일으켜 검증하지 않았다. 강제 종료 재현은 별도 테스트 자식에만 수행했다.
- 새 실행 시 이전 완료 기록 20개를 보존하며, 활성/미완료 기록 및 모르는 파일은 삭제하지
  않는다. `events.log`는 실행당 2 MiB + 백업 1개로 순환한다. 로그 경로가 쓰기 불가능하면
  LocalAppData의 앱 전용 경로로 대체한다.
- 다운로드 파일·ZIP·작품 DB·클립보드 설정은 수정/이동/삭제하지 않았다.
