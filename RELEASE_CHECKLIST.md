# tokiDownloader 릴리스 체크리스트

## 버전 규칙

- `VERSION`은 SemVer를 사용한다: `MAJOR.MINOR.PATCH`.
- 개발 빌드는 `-dev.N`, 사전 배포는 `-alpha.N`, `-beta.N`, `-rc.N`을 붙인다.
- 호환되지 않는 설정/DB 변경은 MAJOR, 기능 추가는 MINOR, 호환 버그 수정은 PATCH를 올린다.
- 설정과 DB 스키마 버전은 앱 버전과 별도로 관리하며 마이그레이션 테스트를 반드시 추가한다.

## 릴리스 전

- [ ] 작업 트리가 의도한 변경만 포함한다.
- [ ] `setup-gui.cmd -CheckOnly`가 필수 5/5로 통과한다.
- [ ] `toki-cli.cmd doctor --json`의 필수 항목과 스키마가 정상이다.
- [ ] `toki-cli.cmd migrate status --json`이 최신 설정/DB 버전을 보고한다.
- [ ] `toki-cli.cmd self-test --json`이 Python, Node와 GUI IPC를 모두 통과한다.
- [ ] `toki-cli.cmd performance stability --records 10000 --cycles 100 --json`이 통과한다.
- [ ] `toki-cli.cmd diagnostics export --json` ZIP의 민감정보 제거를 확인한다.
- [ ] README 명령 집합과 argparse 명령 집합 일치 테스트가 통과한다.
- [ ] 콘솔 없는 `start-gui.vbs`, 창 복원과 주요 GUI 캡처를 확인한다.
- [ ] 실제 다운로드 스모크는 사용자가 허용한 URL·폴더에서만 수행한다.

## 배포와 롤백

- 현재 배포 형식은 소스 ZIP 또는 Git clone + `setup-gui.cmd`이다.
- `config.json`, `jobs.db`, 다운로드 폴더는 릴리스 파일에 포함하지 않는다.
- 업데이트 전 `*.pre-v*.bak`과 다운로드 폴더의 별도 백업을 안내한다.
- 마이그레이션 실패 시 앱을 종료하고 사전 백업을 원래 이름으로 복원한 뒤 이전 릴리스로
  돌아간다. 자동으로 사용자 파일을 삭제하지 않는다.
- 태그와 릴리스 노트에는 앱 버전, 설정/DB 버전, 주요 변경, 알려진 제한을 기록한다.
