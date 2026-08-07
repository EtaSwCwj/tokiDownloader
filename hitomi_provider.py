from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit


HITOMI_PROVIDER_CONTRACT_VERSION = 1
HITOMI_HOSTS = frozenset({"hitomi.la", "www.hitomi.la"})
EXHENTAI_HOSTS = frozenset(
    {
        "exhentai.org",
        "www.exhentai.org",
        "e-hentai.org",
        "www.e-hentai.org",
    }
)
HITOMI_SUPPORTED_HOSTS = HITOMI_HOSTS | EXHENTAI_HOSTS
HITOMI_SERVER_CATALOG = (
    {
        "id": "hitomi",
        "label": "Hitomi.la",
        "providers": ("hitomi",),
        "requiresAuthentication": False,
    },
    {
        "id": "exhentai",
        "label": "ExHentai",
        "providers": ("exhentai",),
        "requiresAuthentication": True,
    },
    {
        "id": "ehentai",
        "label": "E-Hentai",
        "providers": ("exhentai",),
        "requiresAuthentication": False,
    },
)
HITOMI_SERVER_IDS = tuple(item["id"] for item in HITOMI_SERVER_CATALOG)
_GALLERY_ID = re.compile(r"^[0-9]{1,18}$")
_HITOMI_GALLERY_PATH = re.compile(r"^/galleries/([0-9]+)\.html/?$", re.IGNORECASE)
_HITOMI_READER_PATH = re.compile(r"^/reader/([0-9]+)\.html/?$", re.IGNORECASE)
_HITOMI_SLUG_PATH = re.compile(r"^/[^/]+/[^/]*-([0-9]+)\.html/?$", re.IGNORECASE)
_EXHENTAI_GALLERY_PATH = re.compile(
    r"^/g/([0-9]+)/([0-9a-f]{10})/?$", re.IGNORECASE
)
_EXHENTAI_MISSING_TOKEN_PATH = re.compile(r"^/g/([0-9]+)/?$", re.IGNORECASE)
_EXHENTAI_ANY_TOKEN_PATH = re.compile(r"^/g/([0-9]+)/([^/]+)/?$", re.IGNORECASE)


class HitomiReferenceError(ValueError):
    """Stable, provider-scoped validation failure for URL/ID inspection."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"ok": False, "errorCode": self.code, "error": str(self)}


def hitomi_provider_capabilities() -> dict[str, Any]:
    return {
        "ok": True,
        "providerContractVersion": HITOMI_PROVIDER_CONTRACT_VERSION,
        "referenceInspection": True,
        "networkRequest": False,
        "download": False,
        "metadata": False,
        "supportedProviders": ["hitomi", "exhentai"],
        "supportedHosts": sorted(HITOMI_SUPPORTED_HOSTS),
        "serverPolicy": True,
        "authenticationBypass": False,
        "notes": [
            "URL 및 갤러리 ID 분석은 외부 네트워크 없이 동작합니다.",
            "ExHentai 갤러리 토큰은 결과와 로그에 원문으로 표시하지 않습니다.",
            "다운로드와 메타데이터 요청은 아직 활성화되지 않았습니다.",
        ],
    }


def normalize_hitomi_server_mode(value: str | None) -> str:
    normalized = str(value or "auto").strip().lower()
    if normalized not in {"auto", "manual"}:
        raise ValueError("Hitomi 서버 방식은 auto 또는 manual이어야 합니다.")
    return normalized


def normalize_hitomi_manual_server(value: str | None) -> str:
    normalized = str(value or "hitomi").strip().lower()
    if normalized not in HITOMI_SERVER_IDS:
        raise ValueError(
            "Hitomi 수동 서버는 hitomi, exhentai 또는 ehentai여야 합니다."
        )
    return normalized


def normalize_hitomi_server_priority(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates = [part.strip().lower() for part in value.split(",")]
    elif isinstance(value, (list, tuple)):
        candidates = [str(part).strip().lower() for part in value]
    else:
        raise ValueError("Hitomi 서버 우선순위는 서버 ID 목록이어야 합니다.")
    normalized = [candidate for candidate in candidates if candidate]
    if len(normalized) != len(HITOMI_SERVER_IDS):
        raise ValueError("Hitomi 서버 우선순위에는 서버 3개를 모두 한 번씩 넣어야 합니다.")
    if len(set(normalized)) != len(normalized) or set(normalized) != set(
        HITOMI_SERVER_IDS
    ):
        raise ValueError(
            "Hitomi 서버 우선순위는 hitomi, exhentai, ehentai의 중복 없는 순서여야 합니다."
        )
    return normalized


def hitomi_server_policy_snapshot(config: dict[str, Any] | None = None) -> dict[str, Any]:
    source = config if isinstance(config, dict) else {}
    mode = normalize_hitomi_server_mode(source.get("hitomiServerMode"))
    manual_server = normalize_hitomi_manual_server(source.get("hitomiManualServer"))
    priority = normalize_hitomi_server_priority(
        source.get("hitomiServerPriority", list(HITOMI_SERVER_IDS))
    )
    by_id = {item["id"]: item for item in HITOMI_SERVER_CATALOG}
    return {
        "ok": True,
        "mode": mode,
        "manualServer": manual_server,
        "priority": priority,
        "servers": [
            {
                "id": server_id,
                "label": str(by_id[server_id]["label"]),
                "providers": list(by_id[server_id]["providers"]),
                "requiresAuthentication": bool(
                    by_id[server_id]["requiresAuthentication"]
                ),
            }
            for server_id in priority
        ],
        "networkRequested": False,
    }


def plan_hitomi_server(
    reference: str | dict[str, Any],
    *,
    provider_hint: str = "auto",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inspected = (
        dict(reference)
        if isinstance(reference, dict)
        else inspect_hitomi_reference(reference, provider_hint=provider_hint)
    )
    if not inspected.get("ok") or inspected.get("provider") not in {
        "hitomi",
        "exhentai",
    }:
        raise HitomiReferenceError(
            "hitomi.invalid_reference_result",
            "서버 계획에 사용할 Hitomi 분석 결과가 올바르지 않습니다.",
        )
    policy = hitomi_server_policy_snapshot(config)
    by_id = {item["id"]: item for item in HITOMI_SERVER_CATALOG}
    provider = str(inspected["provider"])
    compatible = [
        server_id
        for server_id in policy["priority"]
        if provider in by_id[server_id]["providers"]
    ]
    if policy["mode"] == "manual":
        selected = str(policy["manualServer"])
        if selected not in compatible:
            raise HitomiReferenceError(
                "hitomi.server_incompatible",
                f"{selected} 서버는 {provider} 작품 URL과 호환되지 않습니다.",
            )
        candidates = [selected]
        reason = "manual"
    else:
        candidates = compatible
        reason = "priority"
    if not candidates:
        raise HitomiReferenceError(
            "hitomi.no_compatible_server",
            f"{provider} 작품에 사용할 수 있는 서버가 없습니다.",
        )
    return {
        "ok": True,
        "provider": provider,
        "galleryId": str(inspected["galleryId"]),
        "workKey": str(inspected["workKey"]),
        "mode": policy["mode"],
        "selectedServer": candidates[0],
        "fallbackServers": candidates[1:],
        "candidateServers": candidates,
        "selectionReason": reason,
        "requiresAuthentication": bool(
            by_id[candidates[0]]["requiresAuthentication"]
        ),
        "networkRequested": False,
    }


def _normalize_gallery_id(value: str) -> str:
    candidate = str(value or "").strip()
    if not _GALLERY_ID.fullmatch(candidate):
        raise HitomiReferenceError(
            "hitomi.invalid_gallery_id",
            "갤러리 ID는 1~18자리 양의 정수여야 합니다.",
        )
    normalized = str(int(candidate))
    if normalized == "0":
        raise HitomiReferenceError(
            "hitomi.invalid_gallery_id",
            "갤러리 ID는 0보다 커야 합니다.",
        )
    return normalized


def _provider_hint(value: str) -> str:
    hint = str(value or "auto").strip().lower()
    if hint not in {"auto", "hitomi", "exhentai"}:
        raise HitomiReferenceError(
            "hitomi.invalid_provider_hint",
            "공급자 힌트는 auto, hitomi 또는 exhentai여야 합니다.",
        )
    return hint


def _token_hint(token: str) -> str:
    return f"…{token[-4:]}" if token else ""


def _reference_result(
    *,
    provider: str,
    gallery_id: str,
    source_kind: str,
    host: str,
    gallery_token: str = "",
) -> dict[str, Any]:
    if provider == "hitomi":
        display_url = f"https://hitomi.la/galleries/{gallery_id}.html"
        requires_authentication = False
    else:
        display_url = (
            f"https://exhentai.org/g/{gallery_id}/<token>/"
            if gallery_token
            else ""
        )
        requires_authentication = True
    return {
        "ok": True,
        "provider": provider,
        "galleryId": gallery_id,
        "workKey": f"{provider}:{gallery_id}",
        "sourceKind": source_kind,
        "host": host,
        "displayUrl": display_url,
        "requiresAuthentication": requires_authentication,
        "galleryTokenPresent": bool(gallery_token),
        "galleryTokenHint": _token_hint(gallery_token),
        "networkRequested": False,
        "metadataRequested": False,
    }


def inspect_hitomi_reference(
    reference: str,
    *,
    provider_hint: str = "auto",
) -> dict[str, Any]:
    """Inspect a Hitomi/ExHentai URL or gallery ID without network access.

    ExHentai gallery tokens are validated only long enough to produce a hint and
    are never returned in full. The stable work identity intentionally excludes
    those tokens.
    """

    raw = str(reference or "").strip()
    hint = _provider_hint(provider_hint)
    if not raw:
        raise HitomiReferenceError(
            "hitomi.empty_reference",
            "Hitomi URL 또는 갤러리 ID를 입력해주세요.",
        )
    if len(raw) > 4096:
        raise HitomiReferenceError(
            "hitomi.reference_too_long",
            "URL 또는 갤러리 ID가 너무 깁니다.",
        )
    if _GALLERY_ID.fullmatch(raw):
        provider = "hitomi" if hint == "auto" else hint
        return _reference_result(
            provider=provider,
            gallery_id=_normalize_gallery_id(raw),
            source_kind="gallery_id",
            host="",
        )

    candidate = raw
    if "://" not in candidate:
        first_segment = candidate.split("/", 1)[0].lower().rstrip(".")
        if first_segment in HITOMI_SUPPORTED_HOSTS:
            candidate = f"https://{candidate}"
    try:
        parsed = urlsplit(candidate)
        parsed_host = parsed.hostname
    except ValueError as error:
        raise HitomiReferenceError(
            "hitomi.invalid_url",
            "Hitomi/ExHentai URL 구조가 올바르지 않습니다.",
        ) from error
    if parsed.scheme.lower() not in {"http", "https"} or not parsed_host:
        raise HitomiReferenceError(
            "hitomi.invalid_url",
            "http 또는 https 형식의 Hitomi/ExHentai URL이 아닙니다.",
        )
    if parsed.username or parsed.password:
        raise HitomiReferenceError(
            "hitomi.url_credentials_not_allowed",
            "URL 사용자 이름과 비밀번호는 허용하지 않습니다.",
        )
    host = parsed_host.lower().rstrip(".")
    if host not in HITOMI_SUPPORTED_HOSTS:
        raise HitomiReferenceError(
            "hitomi.unsupported_host",
            f"지원하지 않는 Hitomi 공급자 호스트입니다: {host}",
        )

    if host in HITOMI_HOSTS:
        if hint == "exhentai":
            raise HitomiReferenceError(
                "hitomi.provider_hint_mismatch",
                "Hitomi URL과 exhentai 공급자 힌트가 일치하지 않습니다.",
            )
        match = (
            _HITOMI_GALLERY_PATH.fullmatch(parsed.path)
            or _HITOMI_READER_PATH.fullmatch(parsed.path)
            or _HITOMI_SLUG_PATH.fullmatch(parsed.path)
        )
        if not match:
            raise HitomiReferenceError(
                "hitomi.gallery_id_missing",
                "Hitomi URL에서 갤러리 ID를 찾을 수 없습니다.",
            )
        return _reference_result(
            provider="hitomi",
            gallery_id=_normalize_gallery_id(match.group(1)),
            source_kind="url",
            host=host,
        )

    if hint == "hitomi":
        raise HitomiReferenceError(
            "hitomi.provider_hint_mismatch",
            "ExHentai URL과 hitomi 공급자 힌트가 일치하지 않습니다.",
        )
    if _EXHENTAI_MISSING_TOKEN_PATH.fullmatch(parsed.path):
        raise HitomiReferenceError(
            "hitomi.exhentai_token_missing",
            "ExHentai 갤러리 URL에는 10자리 갤러리 토큰이 필요합니다.",
        )
    match = _EXHENTAI_GALLERY_PATH.fullmatch(parsed.path)
    if not match and _EXHENTAI_ANY_TOKEN_PATH.fullmatch(parsed.path):
        raise HitomiReferenceError(
            "hitomi.exhentai_token_invalid",
            "ExHentai 갤러리 토큰은 10자리 16진수여야 합니다.",
        )
    if not match:
        raise HitomiReferenceError(
            "hitomi.gallery_id_missing",
            "ExHentai URL에서 갤러리 ID와 토큰을 찾을 수 없습니다.",
        )
    return _reference_result(
        provider="exhentai",
        gallery_id=_normalize_gallery_id(match.group(1)),
        source_kind="url",
        host=host,
        gallery_token=match.group(2).lower(),
    )
