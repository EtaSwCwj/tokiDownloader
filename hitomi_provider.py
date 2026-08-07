from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


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
HITOMI_METADATA_MAX_BYTES = 8 * 1024 * 1024
HITOMI_METADATA_MODES = ("auto", "required", "disabled")
HITOMI_METADATA_ENDPOINT = "https://ltn.hitomi.la/galleries/{gallery_id}.js"
EHENTAI_METADATA_ENDPOINT = "https://api.e-hentai.org/api.php"
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
        "metadata": True,
        "metadataExternalRequestRequiresConfirmation": True,
        "supportedProviders": ["hitomi", "exhentai"],
        "supportedHosts": sorted(HITOMI_SUPPORTED_HOSTS),
        "serverPolicy": True,
        "authenticationBypass": False,
        "notes": [
            "URL 및 갤러리 ID 분석은 외부 네트워크 없이 동작합니다.",
            "ExHentai 갤러리 토큰은 결과와 로그에 원문으로 표시하지 않습니다.",
            "메타데이터 요청은 명시적 확인 뒤에만 실행하며 다운로드는 아직 활성화되지 않았습니다.",
        ],
    }


def normalize_hitomi_metadata_mode(value: str | None) -> str:
    normalized = str(value or "auto").strip().lower()
    if normalized not in HITOMI_METADATA_MODES:
        raise ValueError("Hitomi 메타데이터 방식은 auto, required 또는 disabled여야 합니다.")
    return normalized


def hitomi_metadata_policy_snapshot(config: dict[str, Any] | None = None) -> dict[str, Any]:
    source = config if isinstance(config, dict) else {}
    mode = normalize_hitomi_metadata_mode(source.get("hitomiMetadataMode"))
    return {
        "ok": True,
        "mode": mode,
        "enabled": mode != "disabled",
        "failurePolicy": "stop" if mode == "required" else "continue",
        "externalRequestRequiresConfirmation": True,
        "maxResponseBytes": HITOMI_METADATA_MAX_BYTES,
        "networkRequested": False,
    }


def _extract_exhentai_gallery_token(reference: str) -> str:
    raw = str(reference or "").strip()
    if "://" not in raw:
        raw = f"https://{raw}"
    try:
        parsed = urlsplit(raw)
    except ValueError as error:
        raise HitomiReferenceError("hitomi.invalid_url", "ExHentai URL이 올바르지 않습니다.") from error
    match = _EXHENTAI_GALLERY_PATH.fullmatch(parsed.path)
    if not match:
        raise HitomiReferenceError(
            "hitomi.exhentai_token_missing",
            "ExHentai 메타데이터 요청에는 토큰을 포함한 갤러리 URL이 필요합니다.",
        )
    return match.group(2).lower()


def hitomi_metadata_request_plan(
    reference: str,
    *,
    provider_hint: str = "auto",
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inspected = inspect_hitomi_reference(reference, provider_hint=provider_hint)
    policy = hitomi_metadata_policy_snapshot(config)
    if not policy["enabled"]:
        return {
            **policy,
            "provider": inspected["provider"],
            "galleryId": inspected["galleryId"],
            "workKey": inspected["workKey"],
            "request": None,
            "reason": "disabled",
        }
    if inspected["provider"] == "hitomi":
        request = {
            "method": "GET",
            "url": HITOMI_METADATA_ENDPOINT.format(gallery_id=inspected["galleryId"]),
            "contentType": "application/javascript",
            "body": None,
            "containsSecret": False,
        }
    else:
        if not inspected["galleryTokenPresent"]:
            raise HitomiReferenceError(
                "hitomi.exhentai_token_missing",
                "ExHentai 메타데이터 요청에는 토큰을 포함한 갤러리 URL이 필요합니다.",
            )
        request = {
            "method": "POST",
            "url": EHENTAI_METADATA_ENDPOINT,
            "contentType": "application/json",
            "body": {
                "method": "gdata",
                "gidlist": [[int(inspected["galleryId"]), "<gallery-token>"]],
                "namespace": 1,
            },
            "containsSecret": True,
        }
    return {
        **policy,
        "provider": inspected["provider"],
        "galleryId": inspected["galleryId"],
        "workKey": inspected["workKey"],
        "request": request,
        "reason": "provider_metadata",
    }


def _metadata_names(value: Any, *keys: str) -> list[str]:
    source = value if isinstance(value, list) else []
    names: list[str] = []
    for item in source:
        if isinstance(item, str):
            candidate = item
        elif isinstance(item, dict):
            candidate = next(
                (str(item.get(key) or "") for key in keys if item.get(key)),
                "",
            )
        else:
            candidate = ""
        candidate = candidate.strip()
        if candidate and candidate not in names:
            names.append(candidate)
    return names


def _normalize_tag_strings(value: Any) -> list[str]:
    source = value if isinstance(value, list) else []
    tags: list[str] = []
    for item in source:
        if isinstance(item, str):
            candidate = item.strip().lower()
        elif isinstance(item, dict):
            name = str(item.get("tag") or item.get("name") or "").strip().lower()
            namespace = ""
            for key in ("female", "male"):
                marker = item.get(key)
                if marker not in (None, "", "0", 0, False):
                    namespace = key
                    break
            candidate = f"{namespace}:{name}" if namespace and name else name
        else:
            candidate = ""
        if candidate and candidate not in tags:
            tags.append(candidate)
    return tags


def _positive_int(value: Any, *, default: int = 0) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    return normalized if normalized >= 0 else default


def _posted_iso(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if raw.isdigit():
        try:
            return datetime.fromtimestamp(int(raw), timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    return raw


def _normalized_metadata(
    *,
    provider: str,
    gallery_id: str,
    title: str,
    japanese_title: str = "",
    category: str = "",
    language: str = "",
    artists: list[str] | None = None,
    groups: list[str] | None = None,
    parodies: list[str] | None = None,
    characters: list[str] | None = None,
    tags: list[str] | None = None,
    page_count: int = 0,
    file_size_bytes: int = 0,
    posted_at: str = "",
    rating: str = "",
    uploader: str = "",
    thumbnail_url: str = "",
    files: list[dict[str, Any]] | None = None,
    source_format: str,
    network_requested: bool,
) -> dict[str, Any]:
    clean_title = str(title or "").strip()
    if not clean_title:
        raise HitomiReferenceError(
            "hitomi.metadata_title_missing",
            "갤러리 메타데이터에 제목이 없습니다.",
        )
    clean_files = files or []
    return {
        "ok": True,
        "provider": provider,
        "galleryId": gallery_id,
        "workKey": f"{provider}:{gallery_id}",
        "title": clean_title,
        "japaneseTitle": str(japanese_title or "").strip(),
        "category": str(category or "").strip(),
        "language": str(language or "").strip(),
        "artists": artists or [],
        "groups": groups or [],
        "parodies": parodies or [],
        "characters": characters or [],
        "tags": tags or [],
        "pageCount": int(page_count or len(clean_files)),
        "fileSizeBytes": int(file_size_bytes or 0),
        "postedAt": str(posted_at or ""),
        "rating": str(rating or ""),
        "uploader": str(uploader or ""),
        "thumbnailUrl": str(thumbnail_url or ""),
        "files": clean_files,
        "sourceFormat": source_format,
        "metadataOnly": True,
        "networkRequested": bool(network_requested),
    }


def parse_hitomi_metadata_payload(
    reference: str,
    payload: str | bytes,
    *,
    provider_hint: str = "auto",
    network_requested: bool = False,
) -> dict[str, Any]:
    inspected = inspect_hitomi_reference(reference, provider_hint=provider_hint)
    raw_bytes = payload.encode("utf-8") if isinstance(payload, str) else bytes(payload)
    if len(raw_bytes) > HITOMI_METADATA_MAX_BYTES:
        raise HitomiReferenceError(
            "hitomi.metadata_too_large",
            "갤러리 메타데이터 응답이 8 MiB 상한을 넘었습니다.",
        )
    try:
        text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise HitomiReferenceError(
            "hitomi.metadata_encoding",
            "갤러리 메타데이터가 UTF-8이 아닙니다.",
        ) from error

    if inspected["provider"] == "hitomi":
        match = re.fullmatch(
            r"\s*var\s+galleryinfo\s*=\s*(\{.*\})\s*;?\s*",
            text,
            flags=re.DOTALL,
        )
        if not match:
            raise HitomiReferenceError(
                "hitomi.metadata_format",
                "Hitomi galleryinfo JSON 형식을 찾을 수 없습니다.",
            )
        try:
            source = json.loads(match.group(1))
        except json.JSONDecodeError as error:
            raise HitomiReferenceError(
                "hitomi.metadata_json",
                "Hitomi galleryinfo JSON을 해석할 수 없습니다.",
            ) from error
        if not isinstance(source, dict):
            raise HitomiReferenceError(
                "hitomi.metadata_format",
                "Hitomi galleryinfo 루트는 JSON 객체여야 합니다.",
            )
        payload_id = str(source.get("id") or inspected["galleryId"])
        try:
            normalized_payload_id = str(int(payload_id))
        except (TypeError, ValueError) as error:
            raise HitomiReferenceError(
                "hitomi.metadata_id_invalid",
                "Hitomi galleryinfo의 갤러리 ID가 올바르지 않습니다.",
            ) from error
        if normalized_payload_id != inspected["galleryId"]:
            raise HitomiReferenceError(
                "hitomi.metadata_id_mismatch",
                "요청한 갤러리 ID와 메타데이터 ID가 다릅니다.",
            )
        files = []
        for index, item in enumerate(source.get("files") or [], start=1):
            if not isinstance(item, dict):
                continue
            files.append(
                {
                    "index": index,
                    "name": str(item.get("name") or "").strip(),
                    "hash": str(item.get("hash") or "").strip(),
                    "width": _positive_int(item.get("width")),
                    "height": _positive_int(item.get("height")),
                }
            )
        return _normalized_metadata(
            provider="hitomi",
            gallery_id=inspected["galleryId"],
            title=str(source.get("title") or ""),
            japanese_title=str(source.get("japanese_title") or ""),
            category=str(source.get("type") or ""),
            language=str(source.get("language") or ""),
            artists=_metadata_names(source.get("artists"), "artist", "name"),
            groups=_metadata_names(source.get("groups"), "group", "name"),
            parodies=_metadata_names(source.get("parodys"), "parody", "name"),
            characters=_metadata_names(source.get("characters"), "character", "name"),
            tags=_normalize_tag_strings(source.get("tags")),
            page_count=len(files),
            posted_at=_posted_iso(source.get("date")),
            files=files,
            source_format="hitomi_galleryinfo_v1",
            network_requested=network_requested,
        )

    try:
        source = json.loads(text)
    except json.JSONDecodeError as error:
        raise HitomiReferenceError(
            "hitomi.metadata_json",
            "E-Hentai API JSON을 해석할 수 없습니다.",
        ) from error
    rows = source.get("gmetadata") if isinstance(source, dict) else None
    if not isinstance(rows, list) or not rows:
        raise HitomiReferenceError(
            "hitomi.metadata_format",
            "E-Hentai API gmetadata 배열이 없습니다.",
        )
    row = next(
        (
            item
            for item in rows
            if isinstance(item, dict)
            and str(item.get("gid") or "") == inspected["galleryId"]
        ),
        None,
    )
    if not row:
        raise HitomiReferenceError(
            "hitomi.metadata_id_mismatch",
            "요청한 갤러리 ID의 E-Hentai 메타데이터가 없습니다.",
        )
    if row.get("error"):
        raise HitomiReferenceError(
            "hitomi.metadata_provider_error",
            f"E-Hentai API 오류: {str(row['error']).strip()}",
        )
    return _normalized_metadata(
        provider="exhentai",
        gallery_id=inspected["galleryId"],
        title=str(row.get("title") or ""),
        japanese_title=str(row.get("title_jpn") or ""),
        category=str(row.get("category") or ""),
        tags=_normalize_tag_strings(row.get("tags")),
        page_count=_positive_int(row.get("filecount")),
        file_size_bytes=_positive_int(row.get("filesize")),
        posted_at=_posted_iso(row.get("posted")),
        rating=str(row.get("rating") or ""),
        uploader=str(row.get("uploader") or ""),
        thumbnail_url=str(row.get("thumb") or ""),
        source_format="ehentai_gdata_v1",
        network_requested=network_requested,
    )


def load_hitomi_metadata_fixture(
    reference: str,
    fixture_path: Path,
    *,
    provider_hint: str = "auto",
) -> dict[str, Any]:
    path = Path(fixture_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"메타데이터 픽스처를 찾을 수 없습니다: {path}")
    if path.stat().st_size > HITOMI_METADATA_MAX_BYTES:
        raise HitomiReferenceError(
            "hitomi.metadata_too_large",
            "갤러리 메타데이터 픽스처가 8 MiB 상한을 넘었습니다.",
        )
    result = parse_hitomi_metadata_payload(
        reference,
        path.read_bytes(),
        provider_hint=provider_hint,
        network_requested=False,
    )
    return {**result, "fixturePath": str(path)}


def fetch_hitomi_metadata(
    reference: str,
    *,
    provider_hint: str = "auto",
    config: dict[str, Any] | None = None,
    opener: Any = None,
    timeout: int = 30,
) -> dict[str, Any]:
    plan = hitomi_metadata_request_plan(
        reference,
        provider_hint=provider_hint,
        config=config,
    )
    if not plan["enabled"] or not plan["request"]:
        raise HitomiReferenceError(
            "hitomi.metadata_disabled",
            "Hitomi 메타데이터 요청이 설정에서 꺼져 있습니다.",
        )
    request_plan = plan["request"]
    headers = {
        "Accept": "application/json, application/javascript;q=0.9",
        "User-Agent": "tokiDownloader/0.1 metadata-only",
    }
    data = None
    if plan["provider"] == "exhentai":
        token = _extract_exhentai_gallery_token(reference)
        data = json.dumps(
            {
                "method": "gdata",
                "gidlist": [[int(plan["galleryId"]), token]],
                "namespace": 1,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(
        str(request_plan["url"]),
        data=data,
        headers=headers,
        method=str(request_plan["method"]),
    )
    open_request = opener or urlopen
    try:
        response = open_request(request, timeout=max(1, min(120, int(timeout))))
        with response:
            payload = response.read(HITOMI_METADATA_MAX_BYTES + 1)
    except HitomiReferenceError:
        raise
    except Exception as error:
        raise HitomiReferenceError(
            "hitomi.metadata_network",
            f"갤러리 메타데이터 요청 실패 ({type(error).__name__})",
        ) from error
    if len(payload) > HITOMI_METADATA_MAX_BYTES:
        raise HitomiReferenceError(
            "hitomi.metadata_too_large",
            "갤러리 메타데이터 응답이 8 MiB 상한을 넘었습니다.",
        )
    return parse_hitomi_metadata_payload(
        reference,
        payload,
        provider_hint=provider_hint,
        network_requested=True,
    )


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
