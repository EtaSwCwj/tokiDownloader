from __future__ import annotations

import json
import os
import re
import tempfile
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
HITOMI_FILENAME_MODES = ("original", "number", "number_original")
HITOMI_FILENAME_PLAN_MAX_FILES = 100_000
HITOMI_FILENAME_SAMPLE_LIMIT = 1_000
HITOMI_EXCLUDED_TAG_MAX_RULES = 500
HITOMI_EXCLUDED_TAG_MAX_LENGTH = 100
HITOMI_METADATA_FILE_MODES = ("metadata_json", "info_txt", "both", "disabled")
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
_WINDOWS_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_FILENAME = re.compile(
    r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.IGNORECASE
)


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
        "imageFilenamePolicy": True,
        "excludedTagPolicy": True,
        "japaneseTitlePolicy": True,
        "metadataFileGeneration": True,
        "originalImagePolicy": True,
        "userOwnedCookieAuthentication": True,
        "metadataExternalRequestRequiresConfirmation": True,
        "supportedProviders": ["hitomi", "exhentai"],
        "supportedHosts": sorted(HITOMI_SUPPORTED_HOSTS),
        "serverPolicy": True,
        "authenticationBypass": False,
        "notes": [
            "URL 및 갤러리 ID 분석은 외부 네트워크 없이 동작합니다.",
            "ExHentai 갤러리 토큰은 결과와 로그에 원문으로 표시하지 않습니다.",
            "메타데이터 요청은 명시적 확인 뒤에만 실행하며 다운로드는 아직 활성화되지 않았습니다.",
            "이미지 파일명 계획은 로컬 메타데이터만 사용하며 Windows 충돌을 방지합니다.",
            "제외 태그 판정은 정규화한 로컬 메타데이터에만 적용합니다.",
            "표시 제목은 일본어 우선 여부와 명시적 폴백 근거를 함께 반환합니다.",
            "metadata.json과 info.txt 저장은 기존 파일 교체 전 별도 확인을 요구합니다.",
            "원본/최적화 이미지 선택 계획은 파일 변형 플래그만 읽고 네트워크를 사용하지 않습니다.",
            "사용자 소유 쿠키는 기본 꺼짐이며 OS 보안 저장소와 명시적 요청 확인을 사용합니다.",
        ],
    }


def normalize_hitomi_metadata_mode(value: str | None) -> str:
    normalized = str(value or "auto").strip().lower()
    if normalized not in HITOMI_METADATA_MODES:
        raise ValueError("Hitomi 메타데이터 방식은 auto, required 또는 disabled여야 합니다.")
    return normalized


def normalize_hitomi_filename_mode(value: str | None) -> str:
    normalized = str(value or "number_original").strip().lower().replace("+", "_")
    aliases = {
        "numbered": "number",
        "numeric": "number",
        "numbered_original": "number_original",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in HITOMI_FILENAME_MODES:
        raise ValueError(
            "Hitomi 파일명 방식은 original, number 또는 number_original이어야 합니다."
        )
    return normalized


def hitomi_filename_policy_snapshot(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = config if isinstance(config, dict) else {}
    mode = normalize_hitomi_filename_mode(source.get("hitomiFilenameMode"))
    examples = {
        "original": "원본 이름.jpg",
        "number": "0001.jpg",
        "number_original": "0001_원본 이름.jpg",
    }
    return {
        "ok": True,
        "mode": mode,
        "example": examples[mode],
        "supportedModes": list(HITOMI_FILENAME_MODES),
        "collisionPolicy": "append_counter",
        "windowsSafe": True,
        "networkRequested": False,
    }


def _safe_hitomi_original_name(value: Any, index: int) -> tuple[str, bool]:
    raw = Path(str(value or "").replace("\\", "/")).name.strip()
    if not raw:
        return "", False
    sanitized = _WINDOWS_INVALID_FILENAME.sub("", raw).rstrip(". ").strip()
    if not sanitized:
        sanitized = f"image-{index}"
    if _WINDOWS_RESERVED_FILENAME.fullmatch(sanitized):
        sanitized = f"_{sanitized}"
    suffix = Path(sanitized).suffix
    stem = sanitized[: -len(suffix)] if suffix else sanitized
    max_stem_length = max(1, 180 - len(suffix))
    if len(stem) > max_stem_length:
        stem = stem[:max_stem_length].rstrip(". ") or f"image-{index}"
        sanitized = f"{stem}{suffix}"
    return sanitized, sanitized != raw


def _hitomi_numbered_name(index: int, width: int, original: str, mode: str) -> str:
    suffix = Path(original).suffix.lower() if original else ".jpg"
    if not re.fullmatch(r"\.[a-zA-Z0-9]{1,10}", suffix):
        suffix = ".jpg"
    prefix = str(index).zfill(width)
    if mode == "number":
        return f"{prefix}{suffix}"
    stem = original[: -len(Path(original).suffix)] if Path(original).suffix else original
    return f"{prefix}_{stem}{suffix}"


def plan_hitomi_image_filenames(
    metadata: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    mode: str | None = None,
    sample_limit: int = 100,
) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise HitomiReferenceError(
            "hitomi.filename_metadata_invalid",
            "파일명 계획에는 공통 갤러리 메타데이터 객체가 필요합니다.",
        )
    policy = hitomi_filename_policy_snapshot(
        {"hitomiFilenameMode": mode} if mode is not None else config
    )
    files = metadata.get("files")
    rows = files if isinstance(files, list) else []
    total = max(_positive_int(metadata.get("pageCount")), len(rows))
    if total <= 0:
        raise HitomiReferenceError(
            "hitomi.filename_pages_missing",
            "파일명 계획을 만들 이미지 페이지가 없습니다.",
        )
    if total > HITOMI_FILENAME_PLAN_MAX_FILES:
        raise HitomiReferenceError(
            "hitomi.filename_too_many",
            f"파일명 계획은 {HITOMI_FILENAME_PLAN_MAX_FILES:,}장까지 지원합니다.",
        )
    requested_limit = max(0, min(HITOMI_FILENAME_SAMPLE_LIMIT, int(sample_limit)))
    width = max(4, len(str(total)))
    used: dict[str, int] | None = {} if policy["mode"] == "original" else None
    sample: list[dict[str, Any]] = []
    collision_count = 0
    sanitized_count = 0
    missing_original_count = 0
    for index in range(1, total + 1):
        row = rows[index - 1] if index <= len(rows) and isinstance(rows[index - 1], dict) else {}
        original, was_sanitized = _safe_hitomi_original_name(row.get("name"), index)
        if not original:
            missing_original_count += 1
            if policy["mode"] in {"original", "number_original"}:
                raise HitomiReferenceError(
                    "hitomi.filename_original_missing",
                    f"{index}번째 이미지의 원본 파일명이 없어 선택한 방식을 적용할 수 없습니다.",
                )
        if policy["mode"] == "original":
            candidate = original
        else:
            candidate = _hitomi_numbered_name(index, width, original, policy["mode"])
        base_candidate = candidate
        key = candidate.casefold()
        collision_index = (used.get(key, 0) + 1) if used is not None else 1
        if used is not None:
            used[key] = collision_index
        if used is not None and collision_index > 1:
            collision_count += 1
            suffix = Path(candidate).suffix
            stem = candidate[: -len(suffix)] if suffix else candidate
            candidate = f"{stem} ({collision_index}){suffix}"
            while candidate.casefold() in used:
                collision_index += 1
                candidate = f"{stem} ({collision_index}){suffix}"
            used[candidate.casefold()] = 1
        if was_sanitized:
            sanitized_count += 1
        if len(sample) < requested_limit:
            sample.append(
                {
                    "index": index,
                    "originalName": str(row.get("name") or ""),
                    "fileName": candidate,
                    "sanitized": was_sanitized,
                    "collisionResolved": candidate != base_candidate,
                }
            )
    return {
        **policy,
        "galleryId": str(metadata.get("galleryId") or ""),
        "workKey": str(metadata.get("workKey") or ""),
        "pageCount": total,
        "numberWidth": width,
        "sampleLimit": requested_limit,
        "sampleTruncated": total > len(sample),
        "sanitizedCount": sanitized_count,
        "collisionCount": collision_count,
        "missingOriginalCount": missing_original_count,
        "sample": sample,
    }


def _normalize_hitomi_tag_rule(value: Any) -> str:
    raw = str(value or "")
    if any(ord(character) < 32 for character in raw):
        raise ValueError("Hitomi 제외 태그에 제어 문자를 사용할 수 없습니다.")
    normalized = " ".join(raw.strip().lower().split())
    if not normalized:
        raise ValueError("빈 Hitomi 제외 태그는 사용할 수 없습니다.")
    if len(normalized) > HITOMI_EXCLUDED_TAG_MAX_LENGTH:
        raise ValueError(
            f"Hitomi 제외 태그는 {HITOMI_EXCLUDED_TAG_MAX_LENGTH}자 이하여야 합니다."
        )
    if normalized.startswith(":") or normalized.endswith(":"):
        raise ValueError("Hitomi 제외 태그의 네임스페이스 형식이 올바르지 않습니다.")
    return normalized


def normalize_hitomi_excluded_tags(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, str):
        candidates = re.split(r"[,;\n]", value)
    elif isinstance(value, set):
        candidates = sorted(value, key=lambda item: str(item).casefold())
    elif isinstance(value, (list, tuple)):
        candidates = list(value)
    else:
        raise ValueError("Hitomi 제외 태그는 문자열 또는 배열이어야 합니다.")
    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not str(candidate or "").strip():
            continue
        rule = _normalize_hitomi_tag_rule(candidate)
        if rule in seen:
            continue
        seen.add(rule)
        normalized.append(rule)
        if len(normalized) > HITOMI_EXCLUDED_TAG_MAX_RULES:
            raise ValueError(
                f"Hitomi 제외 태그는 {HITOMI_EXCLUDED_TAG_MAX_RULES}개까지 저장할 수 있습니다."
            )
    return normalized


def hitomi_excluded_tag_policy_snapshot(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = config if isinstance(config, dict) else {}
    rules = normalize_hitomi_excluded_tags(source.get("hitomiExcludedTags"))
    return {
        "ok": True,
        "enabled": bool(rules),
        "rules": rules,
        "ruleCount": len(rules),
        "maxRules": HITOMI_EXCLUDED_TAG_MAX_RULES,
        "matching": "exact_namespace_or_unqualified_name",
        "networkRequested": False,
    }


def evaluate_hitomi_excluded_tags(
    metadata: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    rules: Any = None,
) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise HitomiReferenceError(
            "hitomi.tags_metadata_invalid",
            "제외 태그 판정에는 공통 갤러리 메타데이터 객체가 필요합니다.",
        )
    policy = hitomi_excluded_tag_policy_snapshot(
        {"hitomiExcludedTags": rules} if rules is not None else config
    )
    source_tags = metadata.get("tags")
    tags = normalize_hitomi_excluded_tags(
        source_tags if isinstance(source_tags, list) else []
    )
    matches: list[dict[str, str]] = []
    for rule in policy["rules"]:
        matched_tag = next(
            (
                tag
                for tag in tags
                if tag == rule or (":" not in rule and tag.partition(":")[2] == rule)
            ),
            "",
        )
        if matched_tag:
            matches.append({"rule": rule, "tag": matched_tag})
    return {
        **policy,
        "galleryId": str(metadata.get("galleryId") or ""),
        "workKey": str(metadata.get("workKey") or ""),
        "tagCount": len(tags),
        "tags": tags,
        "excluded": bool(matches),
        "matchedCount": len(matches),
        "matches": matches,
        "decision": "exclude" if matches else "continue",
    }


def hitomi_title_policy_snapshot(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = config if isinstance(config, dict) else {}
    value = source.get("hitomiPreferJapaneseTitle", False)
    prefer_japanese = value if isinstance(value, bool) else False
    return {
        "ok": True,
        "preferJapanese": prefer_japanese,
        "primaryField": "japaneseTitle" if prefer_japanese else "title",
        "fallbackField": "title" if prefer_japanese else "japaneseTitle",
        "networkRequested": False,
    }


def select_hitomi_display_title(
    metadata: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    prefer_japanese: bool | None = None,
) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        raise HitomiReferenceError(
            "hitomi.title_metadata_invalid",
            "제목 선택에는 공통 갤러리 메타데이터 객체가 필요합니다.",
        )
    if prefer_japanese is not None and not isinstance(prefer_japanese, bool):
        raise ValueError("일본어 제목 우선 설정은 true 또는 false여야 합니다.")
    policy = hitomi_title_policy_snapshot(
        {"hitomiPreferJapaneseTitle": prefer_japanese}
        if prefer_japanese is not None
        else config
    )
    title = str(metadata.get("title") or "").strip()
    japanese_title = str(metadata.get("japaneseTitle") or "").strip()
    ordered = (
        (("japaneseTitle", japanese_title), ("title", title))
        if policy["preferJapanese"]
        else (("title", title), ("japaneseTitle", japanese_title))
    )
    selected = next(((field, value) for field, value in ordered if value), None)
    if not selected:
        raise HitomiReferenceError(
            "hitomi.title_missing",
            "갤러리 메타데이터에 선택할 제목이 없습니다.",
        )
    selected_field, selected_title = selected
    return {
        **policy,
        "galleryId": str(metadata.get("galleryId") or ""),
        "workKey": str(metadata.get("workKey") or ""),
        "title": title,
        "japaneseTitle": japanese_title,
        "selectedTitle": selected_title,
        "selectedField": selected_field,
        "usedFallback": selected_field != policy["primaryField"],
    }


def normalize_hitomi_metadata_file_mode(value: str | None) -> str:
    normalized = str(value or "metadata_json").strip().lower().replace("-", "_")
    aliases = {"json": "metadata_json", "info": "info_txt", "none": "disabled"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in HITOMI_METADATA_FILE_MODES:
        raise ValueError(
            "Hitomi 메타데이터 파일 방식은 metadata_json, info_txt, both 또는 disabled여야 합니다."
        )
    return normalized


def hitomi_metadata_file_policy_snapshot(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = config if isinstance(config, dict) else {}
    mode = normalize_hitomi_metadata_file_mode(source.get("hitomiMetadataFileMode"))
    names = {
        "metadata_json": ["metadata.json"],
        "info_txt": ["info.txt"],
        "both": ["metadata.json", "info.txt"],
        "disabled": [],
    }
    return {
        "ok": True,
        "mode": mode,
        "enabled": mode != "disabled",
        "fileNames": names[mode],
        "supportedModes": list(HITOMI_METADATA_FILE_MODES),
        "overwriteRequiresConfirmation": True,
        "networkRequested": False,
    }


def _common_hitomi_metadata(
    metadata: dict[str, Any], config: dict[str, Any] | None
) -> dict[str, Any]:
    selected = select_hitomi_display_title(metadata, config=config)
    artists = [str(value) for value in metadata.get("artists") or []]
    groups = [str(value) for value in metadata.get("groups") or []]
    tags = [str(value) for value in metadata.get("tags") or []]
    provider = str(metadata.get("provider") or "hitomi")
    gallery_id = str(metadata.get("galleryId") or "")
    return {
        "schemaVersion": 1,
        "title": selected["selectedTitle"],
        "originalTitle": str(metadata.get("title") or ""),
        "japaneseTitle": str(metadata.get("japaneseTitle") or ""),
        "titleSource": selected["selectedField"],
        "author": artists[0] if artists else "N／A",
        "group": groups[0] if groups else "N／A",
        "category": str(metadata.get("category") or ""),
        "genres": tags,
        "description": "",
        "coverUrl": str(metadata.get("thumbnailUrl") or ""),
        "source": {
            "site": provider,
            "siteTitle": "Hitomi.la" if provider == "hitomi" else "ExHentai / E-Hentai",
            "workId": gallery_id,
            "workKey": str(metadata.get("workKey") or f"{provider}:{gallery_id}"),
            "url": "",
        },
        "pageCount": int(metadata.get("pageCount") or 0),
        "files": list(metadata.get("files") or []),
        "providerMetadata": {
            "artists": artists,
            "groups": groups,
            "parodies": list(metadata.get("parodies") or []),
            "characters": list(metadata.get("characters") or []),
            "language": str(metadata.get("language") or ""),
            "postedAt": str(metadata.get("postedAt") or ""),
            "rating": str(metadata.get("rating") or ""),
            "uploader": str(metadata.get("uploader") or ""),
        },
        "generatedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
        "generatedBy": "tokiDownloader-hitomi-provider",
    }


def _hitomi_metadata_file_contents(
    metadata: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    mode: str | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    policy = hitomi_metadata_file_policy_snapshot(
        {"hitomiMetadataFileMode": mode} if mode is not None else config
    )
    if not isinstance(metadata, dict) or not metadata.get("ok"):
        raise HitomiReferenceError(
            "hitomi.metadata_file_input_invalid",
            "파일 생성에는 정상적으로 정규화된 갤러리 메타데이터가 필요합니다.",
        )
    common = _common_hitomi_metadata(metadata, config)
    contents: dict[str, str] = {}
    if "metadata.json" in policy["fileNames"]:
        contents["metadata.json"] = json.dumps(
            common, ensure_ascii=False, indent=2
        ) + "\n"
    if "info.txt" in policy["fileNames"]:
        provider = common["source"]
        contents["info.txt"] = "\n".join(
            [
                f"제목: {common['title']}",
                f"원제: {common['originalTitle'] or '-'}",
                f"일본어 제목: {common['japaneseTitle'] or '-'}",
                f"작가: {common['author']}",
                f"그룹: {common['group']}",
                f"분류: {common['category'] or '-'}",
                f"언어: {common['providerMetadata']['language'] or '-'}",
                f"페이지: {common['pageCount']}",
                f"태그: {', '.join(common['genres']) or '-'}",
                f"공급자: {provider['siteTitle']}",
                f"갤러리 ID: {provider['workId']}",
                f"작품 키: {provider['workKey']}",
            ]
        ) + "\n"
    return policy, contents


def plan_hitomi_metadata_files(
    metadata: dict[str, Any],
    output_dir: Path,
    *,
    config: dict[str, Any] | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    raw_output = str(output_dir or "").strip()
    if not raw_output:
        raise ValueError("메타데이터 파일을 저장할 작품 폴더를 지정해주세요.")
    output = Path(raw_output).expanduser().resolve()
    policy, contents = _hitomi_metadata_file_contents(
        metadata, config=config, mode=mode
    )
    files = [
        {
            "name": name,
            "path": str(output / name),
            "bytes": len(content.encode("utf-8")),
            "exists": (output / name).is_file(),
        }
        for name, content in contents.items()
    ]
    return {
        **policy,
        "galleryId": str(metadata.get("galleryId") or ""),
        "workKey": str(metadata.get("workKey") or ""),
        "outputPath": str(output),
        "outputExists": output.is_dir(),
        "files": files,
        "fileCount": len(files),
        "wouldOverwriteCount": sum(1 for item in files if item["exists"]),
        "executed": False,
    }


def write_hitomi_metadata_files(
    metadata: dict[str, Any],
    output_dir: Path,
    *,
    config: dict[str, Any] | None = None,
    mode: str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    plan = plan_hitomi_metadata_files(
        metadata, output_dir, config=config, mode=mode
    )
    output = Path(plan["outputPath"])
    if not output.is_dir():
        raise FileNotFoundError(f"작품 폴더를 찾을 수 없습니다: {output}")
    existing = [item for item in plan["files"] if item["exists"]]
    if existing and not overwrite:
        raise HitomiReferenceError(
            "hitomi.metadata_file_exists",
            "기존 메타데이터 파일이 있습니다. 명시적 덮어쓰기 확인이 필요합니다.",
        )
    _policy, contents = _hitomi_metadata_file_contents(
        metadata, config=config, mode=mode
    )
    temporary_paths: list[Path] = []
    written: list[dict[str, Any]] = []
    try:
        staged: list[tuple[Path, Path, str]] = []
        for name, content in contents.items():
            target = output / name
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                prefix=f".{name}.",
                suffix=".tmp",
                dir=output,
                delete=False,
            ) as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            temporary_paths.append(temporary)
            staged.append((temporary, target, content))
        for temporary, target, content in staged:
            os.replace(temporary, target)
            temporary_paths.remove(temporary)
            written.append(
                {
                    "name": target.name,
                    "path": str(target),
                    "bytes": len(content.encode("utf-8")),
                    "overwritten": any(item["name"] == target.name for item in existing),
                }
            )
    finally:
        for temporary in temporary_paths:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return {
        **plan,
        "executed": True,
        "overwriteConfirmed": bool(overwrite),
        "writtenCount": len(written),
        "written": written,
    }


def hitomi_original_image_policy_snapshot(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = config if isinstance(config, dict) else {}
    value = source.get("hitomiUseOriginalImages", True)
    use_original = value if isinstance(value, bool) else True
    return {
        "ok": True,
        "useOriginal": use_original,
        "preferredVariant": "original" if use_original else "optimized",
        "optimizedOrder": ["avif", "webp"],
        "fallbackVariant": "original",
        "networkRequested": False,
    }


def plan_hitomi_image_sources(
    metadata: dict[str, Any],
    *,
    config: dict[str, Any] | None = None,
    use_original: bool | None = None,
    sample_limit: int = 100,
) -> dict[str, Any]:
    if not isinstance(metadata, dict) or not metadata.get("ok"):
        raise HitomiReferenceError(
            "hitomi.image_source_metadata_invalid",
            "이미지 선택 계획에는 정상적으로 정규화된 갤러리 메타데이터가 필요합니다.",
        )
    if use_original is not None and not isinstance(use_original, bool):
        raise ValueError("원본 이미지 사용 설정은 true 또는 false여야 합니다.")
    policy = hitomi_original_image_policy_snapshot(
        {"hitomiUseOriginalImages": use_original}
        if use_original is not None
        else config
    )
    files = [item for item in metadata.get("files") or [] if isinstance(item, dict)]
    limit = max(0, min(HITOMI_FILENAME_SAMPLE_LIMIT, int(sample_limit)))
    sample: list[dict[str, Any]] = []
    optimized_count = 0
    fallback_count = 0
    for offset, item in enumerate(files, start=1):
        if policy["useOriginal"]:
            selected = "original"
            fallback = False
        elif _metadata_flag(item.get("hasAvif")):
            selected = "avif"
            fallback = False
            optimized_count += 1
        elif _metadata_flag(item.get("hasWebp")):
            selected = "webp"
            fallback = False
            optimized_count += 1
        else:
            selected = "original"
            fallback = True
            fallback_count += 1
        if len(sample) < limit:
            sample.append(
                {
                    "index": int(item.get("index") or offset),
                    "name": str(item.get("name") or ""),
                    "selectedVariant": selected,
                    "usedFallback": fallback,
                    "hasAvif": _metadata_flag(item.get("hasAvif")),
                    "hasWebp": _metadata_flag(item.get("hasWebp")),
                }
            )
    page_count = max(_positive_int(metadata.get("pageCount")), len(files))
    return {
        **policy,
        "galleryId": str(metadata.get("galleryId") or ""),
        "workKey": str(metadata.get("workKey") or ""),
        "pageCount": page_count,
        "knownFileCount": len(files),
        "unresolvedFileCount": max(0, page_count - len(files)),
        "optimizedCount": optimized_count,
        "fallbackCount": fallback_count,
        "sampleLimit": limit,
        "sampleTruncated": len(files) > len(sample),
        "sample": sample,
    }


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


def _metadata_flag(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


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
                    "hasWebp": _metadata_flag(item.get("haswebp")),
                    "hasAvif": _metadata_flag(item.get("hasavif")),
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
    cookie_header: str = "",
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
    normalized_cookie_header = str(cookie_header or "")
    if "\r" in normalized_cookie_header or "\n" in normalized_cookie_header:
        raise HitomiReferenceError(
            "hitomi.cookie_header_invalid",
            "쿠키 헤더에 안전하지 않은 줄바꿈이 있습니다.",
        )
    if normalized_cookie_header:
        headers["Cookie"] = normalized_cookie_header
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
