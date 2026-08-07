# PyInstaller 배포 검토

## 결론

현재 릴리스는 Git 소스 + `setup-gui.cmd` 방식으로 유지한다. PyInstaller로 Python GUI만
묶는 것은 가능하지만, 지금 바로 단일 EXE를 배포하면 데이터 위치와 Node/Puppeteer 실행
계약이 깨질 수 있으므로 정식 배포물로 만들지 않는다.

## 확인된 차이

- 현재 `ROOT_DIR` 아래의 `config.json`, `jobs.db`, `logs`, `.cache`에 사용자 상태를 쓴다.
  frozen 앱에서는 코드 위치와 사용자 데이터 위치를 `%LOCALAPPDATA%\tokiDownloader`처럼
  분리해야 한다.
- GUI는 자체 점검, 이미지 변환과 성능 진단을 `sys.executable toki_app.py ...` 형태로 다시
  실행한다. frozen EXE에서는 `--worker` 재진입 계약으로 바꿔야 한다.
- 실제 다운로드에는 Node.js, `puppeteer-real-browser`, Chromium 프로필과 JavaScript 소스가
  필요하다. 시스템 Node를 요구할지, 검증된 portable Node와 브라우저를 함께 배포할지 먼저
  결정해야 한다.
- 300MB 이상이 될 수 있는 브라우저 런타임의 업데이트, 코드 서명, 바이러스 오진과 실패 시
  롤백 절차가 필요하다.

## 권장 구현 순서

1. 코드/리소스 경로와 사용자 데이터 경로를 분리한다.
2. Python 하위 작업을 frozen EXE 재진입 서브커맨드로 통합한다.
3. Node·Chromium 런타임 정책과 라이선스 파일 포함 범위를 확정한다.
4. `onedir` 빌드부터 doctor, 다운로드 스모크, 마이그레이션과 제거 테스트를 수행한다.
5. 코드 서명과 자동 업데이트가 준비된 뒤에만 일반 사용자 배포물로 승격한다.

Windows 빌드는 반드시 `--name tokiDownloader --icon assets\toki-downloader.ico`를 사용한다.
런타임은 `EtaSwCwj.tokiDownloader.GUI.1` AppUserModelID를 GUI 창보다 먼저 적용하므로 소스 실행과
배포 EXE가 같은 작업 표시줄 정체성을 유지한다. 다른 Python GUI 프로젝트는 서로 다른 EXE
이름·아이콘·AppUserModelID를 사용해야 한다.

`doctor --json`의 PyInstaller 항목은 빌드 개발 환경에만 필요한 선택 의존성으로 유지한다.
