from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from hitomi_provider import (
    HitomiReferenceError,
    evaluate_hitomi_excluded_tags,
    fetch_hitomi_metadata,
    hitomi_provider_capabilities,
    hitomi_filename_policy_snapshot,
    hitomi_excluded_tag_policy_snapshot,
    hitomi_metadata_policy_snapshot,
    hitomi_metadata_file_policy_snapshot,
    hitomi_original_image_policy_snapshot,
    hitomi_metadata_request_plan,
    hitomi_server_policy_snapshot,
    hitomi_title_policy_snapshot,
    inspect_hitomi_reference,
    load_hitomi_metadata_fixture,
    normalize_hitomi_server_priority,
    normalize_hitomi_excluded_tags,
    plan_hitomi_image_filenames,
    plan_hitomi_metadata_files,
    plan_hitomi_image_sources,
    parse_hitomi_metadata_payload,
    plan_hitomi_server,
    select_hitomi_display_title,
    write_hitomi_metadata_files,
)
from toki_core import default_config, normalize_config, validate_app_setting_updates


FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "hitomi"


class HitomiReferenceTests(unittest.TestCase):
    def test_hitomi_slug_gallery_and_reader_urls_share_stable_identity(self) -> None:
        references = (
            "https://hitomi.la/manga/sample-title-1234567.html#1",
            "http://www.hitomi.la/galleries/001234567.html?ignored=1",
            "hitomi.la/reader/1234567.html",
        )
        results = [inspect_hitomi_reference(reference) for reference in references]
        self.assertEqual({result["galleryId"] for result in results}, {"1234567"})
        self.assertEqual({result["workKey"] for result in results}, {"hitomi:1234567"})
        self.assertTrue(all(not result["networkRequested"] for result in results))
        self.assertEqual(
            results[0]["displayUrl"],
            "https://hitomi.la/galleries/1234567.html",
        )

    def test_exhentai_token_is_validated_but_never_returned_in_full(self) -> None:
        result = inspect_hitomi_reference(
            "https://exhentai.org/g/987654/abcdef1234/?p=0"
        )
        self.assertEqual(result["provider"], "exhentai")
        self.assertEqual(result["galleryId"], "987654")
        self.assertEqual(result["workKey"], "exhentai:987654")
        self.assertTrue(result["requiresAuthentication"])
        self.assertTrue(result["galleryTokenPresent"])
        self.assertEqual(result["galleryTokenHint"], "…1234")
        self.assertNotIn("abcdef1234", repr(result))
        self.assertIn("<token>", result["displayUrl"])

    def test_bare_gallery_id_uses_explicit_or_default_provider(self) -> None:
        hitomi = inspect_hitomi_reference("00042")
        exhentai = inspect_hitomi_reference("42", provider_hint="exhentai")
        self.assertEqual(hitomi["workKey"], "hitomi:42")
        self.assertEqual(exhentai["workKey"], "exhentai:42")
        self.assertFalse(exhentai["galleryTokenPresent"])
        self.assertEqual(exhentai["displayUrl"], "")

    def test_invalid_inputs_have_stable_provider_scoped_codes(self) -> None:
        cases = (
            ("", "auto", "hitomi.empty_reference"),
            ("https://example.com/galleries/123.html", "auto", "hitomi.unsupported_host"),
            ("https://hitomi.la/manga/no-id.html", "auto", "hitomi.gallery_id_missing"),
            ("https://exhentai.org/g/123/", "auto", "hitomi.exhentai_token_missing"),
            ("https://exhentai.org/g/123/not-a-token/", "auto", "hitomi.exhentai_token_invalid"),
            ("https://user:pass@hitomi.la/galleries/123.html", "auto", "hitomi.url_credentials_not_allowed"),
            ("https://[invalid/galleries/123.html", "auto", "hitomi.invalid_url"),
            ("https://hitomi.la/galleries/123.html", "exhentai", "hitomi.provider_hint_mismatch"),
            ("0", "auto", "hitomi.invalid_gallery_id"),
        )
        for reference, provider, expected_code in cases:
            with self.subTest(reference=reference), self.assertRaises(HitomiReferenceError) as caught:
                inspect_hitomi_reference(reference, provider_hint=provider)
            self.assertEqual(caught.exception.code, expected_code)
            self.assertEqual(caught.exception.to_dict()["errorCode"], expected_code)

    def test_capabilities_make_offline_partial_scope_explicit(self) -> None:
        result = hitomi_provider_capabilities()
        self.assertTrue(result["referenceInspection"])
        self.assertFalse(result["networkRequest"])
        self.assertFalse(result["download"])
        self.assertTrue(result["metadataFileGeneration"])
        self.assertTrue(result["originalImagePolicy"])
        self.assertFalse(result["authenticationBypass"])
        self.assertIn("exhentai.org", result["supportedHosts"])

    def test_server_policy_normalizes_complete_unique_priority(self) -> None:
        config = default_config()
        self.assertEqual(config["hitomiServerMode"], "auto")
        self.assertEqual(config["hitomiManualServer"], "hitomi")
        self.assertEqual(
            config["hitomiServerPriority"], ["hitomi", "exhentai", "ehentai"]
        )
        config["hitomiServerPriority"] = ["ehentai", "exhentai", "hitomi"]
        policy = hitomi_server_policy_snapshot(config)
        self.assertEqual(policy["priority"], ["ehentai", "exhentai", "hitomi"])
        self.assertFalse(policy["networkRequested"])
        with self.assertRaises(ValueError):
            normalize_hitomi_server_priority("hitomi,hitomi,exhentai")
        with self.assertRaises(ValueError):
            validate_app_setting_updates(
                {"hitomiServerPriority": ["hitomi", "exhentai"]}
            )
        migrated = normalize_config({"configVersion": 16})
        self.assertEqual(migrated["hitomiServerMode"], "auto")
        self.assertEqual(migrated["hitomiMetadataMode"], "auto")

    def test_server_plan_filters_priority_and_rejects_incompatible_manual_choice(self) -> None:
        auto = {
            **default_config(),
            "hitomiServerPriority": ["ehentai", "exhentai", "hitomi"],
        }
        exhentai = plan_hitomi_server(
            "https://exhentai.org/g/987654/abcdef1234/",
            config=auto,
        )
        self.assertEqual(exhentai["selectedServer"], "ehentai")
        self.assertEqual(exhentai["fallbackServers"], ["exhentai"])
        self.assertFalse(exhentai["requiresAuthentication"])
        self.assertFalse(exhentai["networkRequested"])

        hitomi = plan_hitomi_server("123", config=auto)
        self.assertEqual(hitomi["candidateServers"], ["hitomi"])

        manual = {
            **auto,
            "hitomiServerMode": "manual",
            "hitomiManualServer": "exhentai",
        }
        with self.assertRaises(HitomiReferenceError) as caught:
            plan_hitomi_server("123", config=manual)
        self.assertEqual(caught.exception.code, "hitomi.server_incompatible")

    def test_hitomi_galleryinfo_metadata_is_json_only_and_normalized(self) -> None:
        payload = (FIXTURE_DIR / "galleryinfo_1234567.js").read_text(encoding="utf-8")
        result = parse_hitomi_metadata_payload(
            "https://hitomi.la/manga/sample-1234567.html", payload
        )
        self.assertEqual(result["workKey"], "hitomi:1234567")
        self.assertEqual(result["japaneseTitle"], "日本語タイトル")
        self.assertEqual(result["artists"], ["artist one"])
        self.assertEqual(result["groups"], ["circle name"])
        self.assertEqual(result["tags"], ["female:full color", "uncensored"])
        self.assertEqual(result["pageCount"], 2)
        self.assertEqual(result["files"][1]["name"], "원본 02.png")
        self.assertFalse(result["networkRequested"])

    def test_ehentai_gdata_metadata_drops_token_and_parses_namespaced_tags(self) -> None:
        payload = (FIXTURE_DIR / "ehentai_gdata_987654.json").read_text(
            encoding="utf-8"
        )
        result = parse_hitomi_metadata_payload(
            "https://exhentai.org/g/987654/abcdef1234/", payload
        )
        self.assertEqual(result["provider"], "exhentai")
        self.assertEqual(result["pageCount"], 24)
        self.assertEqual(result["fileSizeBytes"], 123456)
        self.assertEqual(result["tags"], ["artist:sample", "language:korean"])
        self.assertNotIn("abcdef1234", repr(result))

    def test_metadata_plan_mode_and_fixture_support_stay_offline(self) -> None:
        self.assertEqual(default_config()["hitomiMetadataMode"], "auto")
        with self.assertRaises(ValueError):
            validate_app_setting_updates({"hitomiMetadataMode": "unknown"})
        config = {**default_config(), "hitomiMetadataMode": "disabled"}
        disabled = hitomi_metadata_request_plan("1234567", config=config)
        self.assertFalse(disabled["enabled"])
        self.assertIsNone(disabled["request"])
        self.assertFalse(disabled["networkRequested"])
        required = hitomi_metadata_policy_snapshot(
            {**config, "hitomiMetadataMode": "required"}
        )
        self.assertEqual(required["failurePolicy"], "stop")

        ex_plan = hitomi_metadata_request_plan(
            "https://exhentai.org/g/987654/abcdef1234/"
        )
        self.assertEqual(ex_plan["request"]["method"], "POST")
        self.assertEqual(
            ex_plan["request"]["body"]["gidlist"], [[987654, "<gallery-token>"]]
        )
        self.assertNotIn("abcdef1234", repr(ex_plan))

        with tempfile.TemporaryDirectory() as temporary:
            fixture = Path(temporary) / "한글 메타데이터 픽스처.js"
            fixture.write_text(
                'var galleryinfo = {"id":"42","title":"fixture","files":[]};',
                encoding="utf-8",
            )
            parsed = load_hitomi_metadata_fixture("42", fixture)
        self.assertEqual(parsed["title"], "fixture")
        self.assertTrue(parsed["fixturePath"].endswith("한글 메타데이터 픽스처.js"))
        self.assertFalse(parsed["networkRequested"])

    def test_metadata_fetch_uses_injected_transport_and_never_returns_token(self) -> None:
        payload = json.dumps(
            {
                "gmetadata": [
                    {
                        "gid": 987654,
                        "token": "abcdef1234",
                        "title": "Fetched title",
                        "filecount": "1",
                        "filesize": 100,
                        "tags": [],
                    }
                ]
            }
        ).encode()
        captured = {}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, limit):
                self.limit = limit
                return payload

        def opener(request, timeout):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["body"] = json.loads(request.data.decode())
            captured["timeout"] = timeout
            return Response()

        result = fetch_hitomi_metadata(
            "https://exhentai.org/g/987654/abcdef1234/",
            opener=opener,
            timeout=9,
        )
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(captured["body"]["gidlist"], [[987654, "abcdef1234"]])
        self.assertEqual(captured["timeout"], 9)
        self.assertTrue(result["networkRequested"])
        self.assertNotIn("abcdef1234", repr(result))

    def test_filename_modes_are_windows_safe_deterministic_and_bounded(self) -> None:
        metadata = load_hitomi_metadata_fixture(
            "1234567", FIXTURE_DIR / "galleryinfo_1234567.js"
        )
        self.assertEqual(default_config()["hitomiFilenameMode"], "number_original")
        policy = hitomi_filename_policy_snapshot(default_config())
        self.assertEqual(policy["example"], "0001_원본 이름.jpg")
        self.assertFalse(policy["networkRequested"])

        original = plan_hitomi_image_filenames(
            metadata, mode="original", sample_limit=1
        )
        self.assertEqual(original["sample"][0]["fileName"], "001.jpg")
        self.assertTrue(original["sampleTruncated"])
        numbered = plan_hitomi_image_filenames(metadata, mode="number")
        self.assertEqual(
            [item["fileName"] for item in numbered["sample"]],
            ["0001.jpg", "0002.png"],
        )
        combined = plan_hitomi_image_filenames(metadata)
        self.assertEqual(combined["sample"][1]["fileName"], "0002_원본 02.png")

        unsafe = {
            "galleryId": "9",
            "workKey": "hitomi:9",
            "pageCount": 3,
            "files": [
                {"name": "../CON.jpg"},
                {"name": "same?.jpg"},
                {"name": "same*.jpg"},
            ],
        }
        safe = plan_hitomi_image_filenames(unsafe, mode="original")
        self.assertEqual(safe["sample"][0]["fileName"], "_CON.jpg")
        self.assertEqual(safe["sample"][2]["fileName"], "same (2).jpg")
        self.assertEqual(safe["collisionCount"], 1)
        self.assertEqual(safe["sanitizedCount"], 3)

    def test_original_filename_modes_require_original_names(self) -> None:
        metadata = load_hitomi_metadata_fixture(
            "https://exhentai.org/g/987654/abcdef1234/",
            FIXTURE_DIR / "ehentai_gdata_987654.json",
        )
        numbered = plan_hitomi_image_filenames(
            metadata, mode="number", sample_limit=2
        )
        self.assertEqual(numbered["pageCount"], 24)
        self.assertEqual(numbered["sample"][0]["fileName"], "0001.jpg")
        self.assertEqual(numbered["missingOriginalCount"], 24)
        with self.assertRaises(HitomiReferenceError) as caught:
            plan_hitomi_image_filenames(metadata, mode="original")
        self.assertEqual(caught.exception.code, "hitomi.filename_original_missing")
        with self.assertRaises(ValueError):
            validate_app_setting_updates({"hitomiFilenameMode": "random"})
        migrated = normalize_config({"configVersion": 17})
        self.assertEqual(migrated["hitomiFilenameMode"], "number_original")

    def test_large_numbered_filename_plan_returns_only_bounded_sample(self) -> None:
        result = plan_hitomi_image_filenames(
            {
                "galleryId": "100000",
                "workKey": "hitomi:100000",
                "pageCount": 100_000,
                "files": [],
            },
            mode="number",
            sample_limit=3,
        )
        self.assertEqual(result["pageCount"], 100_000)
        self.assertEqual(result["numberWidth"], 6)
        self.assertEqual(len(result["sample"]), 3)
        self.assertEqual(result["sample"][-1]["fileName"], "000003.jpg")
        self.assertTrue(result["sampleTruncated"])

    def test_excluded_tags_match_exact_namespace_or_unqualified_name(self) -> None:
        metadata = load_hitomi_metadata_fixture(
            "1234567", FIXTURE_DIR / "galleryinfo_1234567.js"
        )
        self.assertEqual(default_config()["hitomiExcludedTags"], [])
        disabled = hitomi_excluded_tag_policy_snapshot(default_config())
        self.assertFalse(disabled["enabled"])
        self.assertFalse(disabled["networkRequested"])

        unqualified = evaluate_hitomi_excluded_tags(
            metadata, rules=" Full   Color ; unrelated ; full color "
        )
        self.assertTrue(unqualified["excluded"])
        self.assertEqual(unqualified["decision"], "exclude")
        self.assertEqual(
            unqualified["matches"],
            [{"rule": "full color", "tag": "female:full color"}],
        )
        exact = evaluate_hitomi_excluded_tags(
            metadata, rules=["male:full color", "uncensored"]
        )
        self.assertEqual(
            exact["matches"], [{"rule": "uncensored", "tag": "uncensored"}]
        )
        continued = evaluate_hitomi_excluded_tags(
            metadata, rules="male:full color"
        )
        self.assertFalse(continued["excluded"])
        self.assertEqual(continued["decision"], "continue")

    def test_excluded_tag_rules_are_bounded_validated_and_migrated(self) -> None:
        self.assertEqual(
            normalize_hitomi_excluded_tags("Artist:Sample, artist:sample;guro"),
            ["artist:sample", "guro"],
        )
        with self.assertRaises(ValueError):
            normalize_hitomi_excluded_tags(["bad\ttag"])
        with self.assertRaises(ValueError):
            normalize_hitomi_excluded_tags([f"tag-{index}" for index in range(501)])
        with self.assertRaises(ValueError):
            validate_app_setting_updates({"hitomiExcludedTags": [":broken"]})
        migrated = normalize_config({"configVersion": 18})
        self.assertEqual(migrated["hitomiExcludedTags"], [])

    def test_japanese_title_preference_selects_and_reports_fallback(self) -> None:
        metadata = load_hitomi_metadata_fixture(
            "1234567", FIXTURE_DIR / "galleryinfo_1234567.js"
        )
        self.assertFalse(default_config()["hitomiPreferJapaneseTitle"])
        default_policy = hitomi_title_policy_snapshot(default_config())
        self.assertEqual(default_policy["primaryField"], "title")
        default_title = select_hitomi_display_title(metadata)
        self.assertEqual(default_title["selectedTitle"], "Romanized Title")
        self.assertFalse(default_title["usedFallback"])

        japanese = select_hitomi_display_title(metadata, prefer_japanese=True)
        self.assertEqual(japanese["selectedTitle"], "日本語タイトル")
        self.assertEqual(japanese["selectedField"], "japaneseTitle")
        self.assertFalse(japanese["networkRequested"])

        fallback = select_hitomi_display_title(
            {**metadata, "japaneseTitle": ""}, prefer_japanese=True
        )
        self.assertEqual(fallback["selectedTitle"], "Romanized Title")
        self.assertTrue(fallback["usedFallback"])
        with self.assertRaises(HitomiReferenceError) as caught:
            select_hitomi_display_title({"title": "", "japaneseTitle": ""})
        self.assertEqual(caught.exception.code, "hitomi.title_missing")
        with self.assertRaises(ValueError):
            validate_app_setting_updates({"hitomiPreferJapaneseTitle": "yes"})
        migrated = normalize_config({"configVersion": 19})
        self.assertFalse(migrated["hitomiPreferJapaneseTitle"])

    def test_common_metadata_json_and_info_text_are_planned_and_written_safely(self) -> None:
        metadata = load_hitomi_metadata_fixture(
            "1234567", FIXTURE_DIR / "galleryinfo_1234567.js"
        )
        self.assertEqual(default_config()["hitomiMetadataFileMode"], "metadata_json")
        self.assertEqual(
            hitomi_metadata_file_policy_snapshot(default_config())["fileNames"],
            ["metadata.json"],
        )
        config = {
            **default_config(),
            "hitomiMetadataFileMode": "both",
            "hitomiPreferJapaneseTitle": True,
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "한글 작품 폴더"
            output.mkdir()
            plan = plan_hitomi_metadata_files(metadata, output, config=config)
            self.assertFalse(plan["executed"])
            self.assertEqual(plan["fileCount"], 2)
            self.assertEqual(plan["wouldOverwriteCount"], 0)
            self.assertTrue(all(not item["exists"] for item in plan["files"]))

            written = write_hitomi_metadata_files(metadata, output, config=config)
            self.assertTrue(written["executed"])
            self.assertEqual(written["writtenCount"], 2)
            common = json.loads((output / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(common["schemaVersion"], 1)
            self.assertEqual(common["title"], "日本語タイトル")
            self.assertEqual(common["titleSource"], "japaneseTitle")
            self.assertEqual(common["author"], "artist one")
            self.assertEqual(common["group"], "circle name")
            self.assertEqual(common["source"]["workKey"], "hitomi:1234567")
            info = (output / "info.txt").read_text(encoding="utf-8")
            self.assertIn("제목: 日本語タイトル", info)
            self.assertIn("갤러리 ID: 1234567", info)

            with self.assertRaises(HitomiReferenceError) as caught:
                write_hitomi_metadata_files(metadata, output, config=config)
            self.assertEqual(caught.exception.code, "hitomi.metadata_file_exists")
            replaced = write_hitomi_metadata_files(
                metadata, output, config=config, overwrite=True
            )
            self.assertEqual(replaced["wouldOverwriteCount"], 2)
            self.assertTrue(all(item["overwritten"] for item in replaced["written"]))
            self.assertEqual(list(output.glob("*.tmp")), [])

    def test_metadata_file_policy_validates_mode_directory_and_migration(self) -> None:
        metadata = load_hitomi_metadata_fixture(
            "1234567", FIXTURE_DIR / "galleryinfo_1234567.js"
        )
        with tempfile.TemporaryDirectory() as temporary:
            disabled = plan_hitomi_metadata_files(
                metadata, Path(temporary), mode="disabled"
            )
            self.assertEqual(disabled["fileCount"], 0)
            self.assertFalse(disabled["enabled"])
            missing = Path(temporary) / "missing"
            with self.assertRaises(FileNotFoundError):
                write_hitomi_metadata_files(metadata, missing)
            exhentai = load_hitomi_metadata_fixture(
                "https://exhentai.org/g/987654/abcdef1234/",
                FIXTURE_DIR / "ehentai_gdata_987654.json",
            )
            secret_output = Path(temporary) / "exhentai"
            secret_output.mkdir()
            write_hitomi_metadata_files(exhentai, secret_output)
            exported = (secret_output / "metadata.json").read_text(encoding="utf-8")
            self.assertNotIn("abcdef1234", exported)
            self.assertIn("exhentai:987654", exported)
        with self.assertRaises(ValueError):
            validate_app_setting_updates({"hitomiMetadataFileMode": "xml"})
        migrated = normalize_config({"configVersion": 20})
        self.assertEqual(migrated["hitomiMetadataFileMode"], "metadata_json")

    def test_original_image_policy_uses_known_optimized_variants_and_fallback(self) -> None:
        metadata = load_hitomi_metadata_fixture(
            "1234567", FIXTURE_DIR / "galleryinfo_1234567.js"
        )
        self.assertTrue(default_config()["hitomiUseOriginalImages"])
        policy = hitomi_original_image_policy_snapshot(default_config())
        self.assertEqual(policy["preferredVariant"], "original")
        original = plan_hitomi_image_sources(metadata)
        self.assertEqual(
            [item["selectedVariant"] for item in original["sample"]],
            ["original", "original"],
        )
        optimized = plan_hitomi_image_sources(metadata, use_original=False)
        self.assertEqual(
            [item["selectedVariant"] for item in optimized["sample"]],
            ["webp", "avif"],
        )
        self.assertEqual(optimized["optimizedCount"], 2)
        self.assertEqual(optimized["fallbackCount"], 0)
        self.assertFalse(optimized["networkRequested"])

        fallback = plan_hitomi_image_sources(
            {
                **metadata,
                "pageCount": 2,
                "files": [{"index": 1, "name": "only-original.jpg"}],
            },
            use_original=False,
        )
        self.assertEqual(fallback["sample"][0]["selectedVariant"], "original")
        self.assertTrue(fallback["sample"][0]["usedFallback"])
        self.assertEqual(fallback["fallbackCount"], 1)
        self.assertEqual(fallback["unresolvedFileCount"], 1)

    def test_original_image_policy_validates_boolean_and_migration(self) -> None:
        with self.assertRaises(ValueError):
            validate_app_setting_updates({"hitomiUseOriginalImages": "yes"})
        migrated = normalize_config({"configVersion": 21})
        self.assertTrue(migrated["hitomiUseOriginalImages"])
        exhentai = load_hitomi_metadata_fixture(
            "https://exhentai.org/g/987654/abcdef1234/",
            FIXTURE_DIR / "ehentai_gdata_987654.json",
        )
        unresolved = plan_hitomi_image_sources(exhentai, use_original=False)
        self.assertEqual(unresolved["knownFileCount"], 0)
        self.assertEqual(unresolved["unresolvedFileCount"], 24)
        self.assertEqual(unresolved["sample"], [])


if __name__ == "__main__":
    unittest.main()
