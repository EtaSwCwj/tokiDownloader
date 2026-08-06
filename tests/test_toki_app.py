from __future__ import annotations

import unittest

from toki_app import build_parser


class CliParserTests(unittest.TestCase):
    def test_self_test_core_only_json_arguments(self) -> None:
        args = build_parser().parse_args(["self-test", "--core-only", "--json"])
        self.assertEqual(args.command, "self-test")
        self.assertTrue(args.core_only)
        self.assertTrue(args.json)
        self.assertFalse(args.via_gui)

    def test_self_test_via_gui_arguments(self) -> None:
        args = build_parser().parse_args(["self-test", "--via-gui", "--json"])
        self.assertTrue(args.via_gui)
        self.assertFalse(args.core_only)

    def test_download_show_browser_is_explicit(self) -> None:
        args = build_parser().parse_args(
            ["download", "--url", "https://newtoki1.org/manhwa/34360"]
        )
        self.assertFalse(args.show_browser)

    def test_list_query_arguments(self) -> None:
        args = build_parser().parse_args(
            [
                "list", "--query", "작가", "--status", "완료", "--sort", "title",
                "--apply-gui", "--json",
            ]
        )
        self.assertEqual(args.query, "작가")
        self.assertEqual(args.status, "완료")
        self.assertEqual(args.sort, "title")
        self.assertTrue(args.apply_gui)
        self.assertTrue(args.json)

    def test_pin_and_tag_arguments(self) -> None:
        pin = build_parser().parse_args(["pin", "--job", "abc", "--on"])
        self.assertTrue(pin.on)
        tag = build_parser().parse_args(["tag", "--job", "abc", "--color", "blue"])
        self.assertEqual(tag.color, "blue")

    def test_remove_record_requires_explicit_confirmation_flag(self) -> None:
        args = build_parser().parse_args(["remove-record", "--job", "abc", "--yes"])
        self.assertTrue(args.yes)


if __name__ == "__main__":
    unittest.main()
