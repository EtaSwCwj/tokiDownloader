# Windows 설치 및 실행

## 준비

1. Windows 10/11 64비트에 Git, Python 3.10 이상, Node.js/npm을 설치한다.
2. PowerShell에서 저장소를 clone하고 폴더로 이동한다.
3. 사용자 다운로드 폴더는 저장소 밖의 별도 위치를 권장한다.

```powershell
git clone https://github.com/crossSiteKikyo/tokiDownloader.git
cd tokiDownloader
.\setup-gui.cmd
.\setup-gui.cmd -CheckOnly
```

`setup-gui.cmd`는 `.venv`, PyQt6·psutil과 `package-lock.json` 기준 Node 의존성을 설치한 뒤
`doctor --json`을 실행한다. 이미지 변환도 사용할 경우 `setup-gui.cmd -WithImageTools`를
실행하고, 7Z/RAR 작품 검사도 사용할 경우 `setup-gui.cmd -WithArchiveTools`를 실행한다.
공급자 쿠키를 Windows 자격 증명 저장소에 보관하려면
`setup-gui.cmd -WithSecurityTools`를 실행한다.

## 실행

- 콘솔 없는 일반 실행: `start-gui.vbs` 더블클릭
- 콘솔에서 GUI 실행/앞으로 가져오기: `.\toki-cli.cmd gui`
- 환경 진단: `.\toki-cli.cmd doctor --show-gui --json`
- 전체 점검: `.\toki-cli.cmd self-test --json`

GUI가 켜지면 저장 폴더를 먼저 선택한다. 자동화 브라우저는 기본적으로 숨김 전용 프로필을
사용하며 개인 Chrome 프로필이나 쿠키를 자동으로 읽지 않는다.

## 업데이트

1. GUI와 다운로드 작업을 종료한다.
2. `config.json`, `jobs.db`, 다운로드 폴더를 별도 위치에 백업한다.
3. `git pull` 후 `setup-gui.cmd`, `toki-cli.cmd migrate apply --json`,
   `toki-cli.cmd self-test --core-only --json` 순서로 실행한다.
4. 문제가 있으면 앱을 종료하고 `*.pre-v*.bak`을 원래 파일명으로 복원한 뒤 이전 버전으로
   돌아간다.

## 깨끗한 설치 재현

개발자는 아래 명령으로 현재 Git `HEAD`만 임시 폴더에 풀어 완전한 재설치와 GUI IPC까지
검증할 수 있다. 기존 config, DB, `.venv`, `node_modules`와 다운로드 파일은 사용하지 않는다.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\clean-install-smoke.ps1
```

결과는 `logs\clean-install-smoke.json`에 남고 임시 작업공간은 성공·실패와 관계없이 제거된다.
디버깅 목적으로만 `-KeepWorkspace`를 지정할 수 있다.
