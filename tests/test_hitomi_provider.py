from __future__ import annotations

import unittest

from hitomi_provider import (
    HitomiReferenceError,
    hitomi_provider_capabilities,
    hitomi_server_policy_snapshot,
    inspect_hitomi_reference,
    normalize_hitomi_server_priority,
    plan_hitomi_server,
)
from toki_core import default_config, normalize_config, validate_app_setting_updates


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
        migrated = normalize_config({"configVersion": 15})
        self.assertEqual(migrated["hitomiServerMode"], "auto")

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


if __name__ == "__main__":
    unittest.main()
