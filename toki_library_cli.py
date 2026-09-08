import time
from toki_library import archive_library_items, delete_library_items, restore_library_trash


def configure_library_cli(subparsers):
    library = subparsers.add_parser("library", help="복수 선택·삭제 선택·작품 전체 ZIP 압축")
    commands = library.add_subparsers(dest="library_command", required=True)
    select = commands.add_parser("select", help="GUI 목록 복수 선택/조회")
    select.add_argument("--job", action="append")
    select.add_argument("--clear", action="store_true")
    select.add_argument("--json", action="store_true")
    status = commands.add_parser("status", help="압축/삭제 진행·결과 조회")
    status.add_argument("--operation")
    status.add_argument("--json", action="store_true")
    cancel = commands.add_parser("cancel", help="실행 중인 압축 중지")
    cancel.add_argument("--operation", required=True)
    cancel.add_argument("--json", action="store_true")
    close = commands.add_parser("close", help="선택 작품 처리 창 닫기")
    close.add_argument("--json", action="store_true")
    for name in ("delete", "archive", "restore", "cancel-downloads"):
        parser = commands.add_parser(name)
        if name != "restore":
            parser.add_argument("--job", action="append", required=True, help="작품 ID (반복 가능)")
        else:
            parser.add_argument("--manifest", required=True, help=".toki-trash의 manifest.json 경로")
        if name == "delete":
            parser.add_argument("--kind", choices=("records", "files", "archives"), default="records")
            parser.add_argument("--plan-token", help="미리보기의 planToken; 대상 변경 시 중단")
        if name == "archive":
            parser.add_argument("--remove-originals", action="store_true", help="작품당 ZIP 하나 생성·CRC 검증 후 회차 원본 정리 (메타데이터/표지 보존)")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--execute", action="store_true")
        mode.add_argument("--dry-run", action="store_true")
        parser.add_argument("--yes", action="store_true")
        parser.add_argument("--show-gui", action="store_true")
        parser.add_argument("--wait", action="store_true", help="GUI worker의 결과까지 대기")
        parser.add_argument("--json", action="store_true")


def run_library_cli(args, app):
    command = args.library_command
    if command in {"select", "cancel", "close"}:
        app.ensure_gui_running()
        request = {"action": "library_" + command}
        if command == "select":
            request.update({"jobIds": args.job, "clear": args.clear})
        elif command == "cancel":
            request["operationId"] = args.operation
        app.print_json(app.control_request(request))
        return 0
    if command == "status":
        result = app.control_request({"action": "library_status"}) if app.gui_is_running() else {"running": [], "results": {}, "guiRunning": False}
        if args.operation:
            result = result["results"].get(args.operation, {"done": False, "operationId": args.operation})
        app.print_json(result)
        return 0
    if args.execute and not args.yes:
        raise app.ControlError("실제 처리에는 --execute --yes가 필요합니다.")
    ids = getattr(args, "job", [])
    action = f"delete:{args.kind}" if command == "delete" else command
    remove = bool(getattr(args, "remove_originals", False))
    if args.show_gui:
        if command == "restore":
            raise app.ControlError("복구는 --dry-run 확인 후 --execute --yes로 실행하세요.")
        app.ensure_gui_running()
        app.print_json(app.control_request({"action": "library_dialog", "jobIds": ids,
            "archive": command == "archive", "operation": action, "preview": args.dry_run}))
        return 0
    if app.gui_is_running() or command == "cancel-downloads":
        app.ensure_gui_running()
        response = app.control_request({"action": "library_start", "jobIds": ids, "operation": action,
            "execute": args.execute, "removeOriginals": remove, "planToken": getattr(args, "plan_token", None),
            "manifest": getattr(args, "manifest", None)})
        if not args.wait:
            app.print_json(response)
            return 0
        deadline = time.monotonic() + 3600
        while time.monotonic() < deadline:
            snapshot = app.control_request({"action": "library_status"})
            completed = snapshot["results"].get(response["operationId"])
            if completed:
                app.print_json(completed)
                return 2 if completed.get("error") or completed.get("result", {}).get("success") is False else 0
            time.sleep(0.25)
        raise app.ControlError("결과 대기 시간이 지났습니다. library status로 확인하세요. 작업은 계속될 수 있습니다.")
    if command == "archive":
        result = archive_library_items(ids, execute=args.execute, remove_originals=remove)
    elif command == "delete":
        result = delete_library_items(ids, args.kind, execute=args.execute, plan_token=args.plan_token)
    else:
        result = restore_library_trash(args.manifest, execute=args.execute)
    app.print_json(result)
    return 2 if result.get("success") is False else 0
