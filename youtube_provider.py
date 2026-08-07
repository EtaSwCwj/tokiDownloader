from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit


YOUTUBE_FORMAT_MODES = ("video_audio", "video_only", "audio_only")
YOUTUBE_MAX_HEIGHTS = (0, 2160, 1440, 1080, 720, 480, 360, 240, 144)
YOUTUBE_CONTAINERS = ("auto", "mp4", "mkv", "webm")
YOUTUBE_VIDEO_CODECS = ("auto", "h264", "h265", "vp9", "av1")
YOUTUBE_AUDIO_CODECS = ("auto", "aac", "opus")
YOUTUBE_SUBTITLE_MODES = ("none", "manual", "manual_auto")
YOUTUBE_SUBTITLE_FORMATS = ("best", "srt", "vtt", "ass")
YOUTUBE_AUDIO_TRACK_MODES = ("preferred_single", "all")
YOUTUBE_COLLECTION_ORDERS = ("site", "reverse")
YOUTUBE_PROGRESS_PREFIX = "@@TOKI_YTDLP_PROGRESS@@"
YOUTUBE_ITEM_PREFIX = "@@TOKI_YTDLP_ITEM@@"
YOUTUBE_COMPLETE_PREFIX = "@@TOKI_YTDLP_COMPLETE@@"
YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
    }
)
_VIDEO_CODEC_SORT = {
    "h264": "vcodec:h264",
    "h265": "vcodec:h265",
    "vp9": "vcodec:vp9",
    "av1": "vcodec:av01",
}
_AUDIO_CODEC_SORT = {"aac": "acodec:aac", "opus": "acodec:opus"}
YOUTUBE_FILENAME_FIELDS = frozenset(
    {"title", "id", "uploader", "channel", "upload_date", "playlist", "playlist_index", "ext"}
)
DEFAULT_YOUTUBE_FILENAME_TEMPLATE = "%(title)s [%(id)s].%(ext)s"
_YOUTUBE_TEMPLATE_FIELD = re.compile(r"%\(([a-z_]+)\)s")
_WINDOWS_FILENAME_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


class YouTubePolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"ok": False, "errorCode": self.code, "error": str(self)}


def _normalize_choice(value: Any, choices: tuple[str, ...], label: str) -> str:
    normalized = str(value or choices[0]).strip().lower()
    if normalized not in choices:
        raise ValueError(f"{label}은(는) {', '.join(choices)} 중 하나여야 합니다.")
    return normalized


def normalize_youtube_format_mode(value: Any) -> str:
    return _normalize_choice(value, YOUTUBE_FORMAT_MODES, "YouTube 형식")


def normalize_youtube_max_height(value: Any) -> int:
    try:
        normalized = int(value or 0)
    except (TypeError, ValueError) as error:
        raise ValueError("YouTube 최대 해상도는 숫자여야 합니다.") from error
    if normalized not in YOUTUBE_MAX_HEIGHTS:
        raise ValueError(
            "YouTube 최대 해상도는 best(0), 2160, 1440, 1080, 720, 480, 360, 240, 144 중 하나여야 합니다."
        )
    return normalized


def normalize_youtube_container(value: Any) -> str:
    return _normalize_choice(value, YOUTUBE_CONTAINERS, "YouTube 컨테이너")


def normalize_youtube_video_codec(value: Any) -> str:
    return _normalize_choice(value, YOUTUBE_VIDEO_CODECS, "YouTube 비디오 코덱")


def normalize_youtube_audio_codec(value: Any) -> str:
    return _normalize_choice(value, YOUTUBE_AUDIO_CODECS, "YouTube 오디오 코덱")


def normalize_youtube_filename_template(value: Any) -> str:
    template = str(value or "").strip()
    if not template:
        raise ValueError("YouTube 파일명 템플릿을 입력해주세요.")
    if len(template) > 240:
        raise ValueError("YouTube 파일명 템플릿은 240자 이하여야 합니다.")
    fields = _YOUTUBE_TEMPLATE_FIELD.findall(template)
    unknown = sorted(set(fields) - YOUTUBE_FILENAME_FIELDS)
    if unknown:
        raise ValueError(f"지원하지 않는 YouTube 파일명 변수입니다: {', '.join(unknown)}")
    literal = _YOUTUBE_TEMPLATE_FIELD.sub("", template)
    if "%" in literal:
        raise ValueError("지원하지 않는 yt-dlp 파일명 표현식이 있습니다.")
    if _WINDOWS_FILENAME_INVALID.search(literal):
        raise ValueError("YouTube 파일명 템플릿에 Windows 금지 문자를 사용할 수 없습니다.")
    if "ext" not in fields or not ({"title", "id"} & set(fields)):
        raise ValueError("YouTube 파일명에는 %(ext)s와 %(title)s 또는 %(id)s가 필요합니다.")
    return template


def normalize_youtube_languages(value: Any) -> list[str]:
    candidates = re.split(r"[,;\s]+", value) if isinstance(value, str) else list(value or [])
    result: list[str] = []
    for candidate in candidates:
        language = str(candidate or "").strip().lower()
        if not language:
            continue
        if not re.fullmatch(r"[a-z]{2,3}(?:-[a-z0-9]{2,8})?", language):
            raise ValueError(f"잘못된 YouTube 언어 코드입니다: {language}")
        if language not in result:
            result.append(language)
    if not result:
        raise ValueError("YouTube 선호 언어를 하나 이상 입력해주세요.")
    if len(result) > 20:
        raise ValueError("YouTube 선호 언어는 최대 20개입니다.")
    return result


def normalize_youtube_subtitle_mode(value: Any) -> str:
    return _normalize_choice(value, YOUTUBE_SUBTITLE_MODES, "YouTube 자막 방식")


def normalize_youtube_subtitle_format(value: Any) -> str:
    return _normalize_choice(value, YOUTUBE_SUBTITLE_FORMATS, "YouTube 자막 형식")


def normalize_youtube_audio_track_mode(value: Any) -> str:
    return _normalize_choice(value, YOUTUBE_AUDIO_TRACK_MODES, "YouTube 오디오 트랙 방식")


def normalize_youtube_collection_order(value: Any) -> str:
    return _normalize_choice(value, YOUTUBE_COLLECTION_ORDERS, "YouTube 채널·재생목록 순서")


def youtube_collection_policy_snapshot(config: dict[str, Any] | None = None) -> dict[str, Any]:
    source = config if isinstance(config, dict) else {}
    return {
        "ok": True,
        "order": normalize_youtube_collection_order(
            source.get("youtubeCollectionOrder", "site")
        ),
        "supportedOrders": list(YOUTUBE_COLLECTION_ORDERS),
        "videoWithPlaylistPolicy": "single_video",
        "channelBaseScope": "all_uploads",
        "channelTabScopePreserved": True,
        "reverseRequiresFullCollectionScan": True,
        "networkRequested": False,
        "downloadExecuted": False,
    }


def _normalize_youtube_boolean(value: Any, label: str, default: bool = False) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ValueError(f"{label}은(는) true 또는 false여야 합니다.")
    return value


def youtube_chapter_policy_snapshot(config: dict[str, Any] | None = None) -> dict[str, Any]:
    source = config if isinstance(config, dict) else {}
    embed_chapters = _normalize_youtube_boolean(
        source.get("youtubeEmbedChapters"), "YouTube 챕터 마커 포함"
    )
    return {
        "ok": True,
        "embedChapters": embed_chapters,
        "sourceChaptersRequired": True,
        "postProcessingRequired": embed_chapters,
        "requiresFfmpeg": embed_chapters,
        "networkRequested": False,
        "downloadExecuted": False,
    }


def youtube_mtime_policy_snapshot(config: dict[str, Any] | None = None) -> dict[str, Any]:
    source = config if isinstance(config, dict) else {}
    apply_upload_date = _normalize_youtube_boolean(
        source.get("youtubeApplyUploadDateMtime"), "YouTube 업로드 날짜 파일 시간 적용"
    )
    return {
        "ok": True,
        "applyUploadDateMtime": apply_upload_date,
        "sourceField": "upload_date",
        "sourceTimezone": "UTC",
        "ytDlpMtimeOptionUsed": False,
        "preserveAccessTime": True,
        "rejectSymlinks": True,
        "networkRequested": False,
        "downloadExecuted": False,
    }


def normalize_youtube_upload_date(value: Any) -> str:
    normalized = str(value or "").strip()
    if not re.fullmatch(r"\d{8}", normalized):
        raise ValueError("YouTube 업로드 날짜는 YYYYMMDD 8자리여야 합니다.")
    try:
        datetime.strptime(normalized, "%Y%m%d")
    except ValueError as error:
        raise ValueError("유효하지 않은 YouTube 업로드 날짜입니다.") from error
    return normalized


def plan_youtube_upload_date_mtime(
    file_path: str | Path,
    upload_date: Any,
    *,
    config: dict[str, Any] | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    policy_source = dict(config) if isinstance(config, dict) else {}
    if enabled is not None:
        policy_source["youtubeApplyUploadDateMtime"] = enabled
    policy = youtube_mtime_policy_snapshot(policy_source)
    normalized_date = normalize_youtube_upload_date(upload_date)
    target = Path(os.path.abspath(os.fspath(Path(file_path).expanduser())))
    moment = datetime.strptime(normalized_date, "%Y%m%d").replace(tzinfo=timezone.utc)
    timestamp = int(moment.timestamp())
    timestamp_ns = timestamp * 1_000_000_000
    return {
        **policy,
        "filePath": str(target),
        "uploadDate": normalized_date,
        "targetTimestamp": timestamp,
        "targetTimestampNs": timestamp_ns,
        "targetUtc": moment.isoformat(),
        "targetLocal": moment.astimezone().isoformat(),
        "wouldModifyFileTimestamp": policy["applyUploadDateMtime"],
        "requiresConfirmation": policy["applyUploadDateMtime"],
        "executed": False,
    }


def apply_youtube_upload_date_mtime(
    file_path: str | Path,
    upload_date: Any,
    *,
    config: dict[str, Any] | None = None,
    enabled: bool | None = None,
    confirmed: bool = False,
) -> dict[str, Any]:
    plan = plan_youtube_upload_date_mtime(
        file_path, upload_date, config=config, enabled=enabled
    )
    if not plan["applyUploadDateMtime"]:
        raise ValueError("YouTube 업로드 날짜 파일 시간 적용을 먼저 켜주세요.")
    if not confirmed:
        raise ValueError("파일 수정 시각을 바꾸려면 --yes 확인이 필요합니다.")
    target = Path(plan["filePath"])
    if target.is_symlink():
        raise ValueError("심볼릭 링크의 파일 시간은 변경하지 않습니다.")
    if not target.is_file():
        raise ValueError(f"파일을 찾을 수 없습니다: {target}")
    before = target.stat()
    target_ns = int(plan["targetTimestampNs"])
    os.utime(target, ns=(before.st_atime_ns, target_ns))
    after = target.stat()
    return {
        **plan,
        "executed": True,
        "requiresConfirmation": False,
        "beforeMtimeNs": before.st_mtime_ns,
        "afterMtimeNs": after.st_mtime_ns,
        "accessTimePreserved": after.st_atime_ns == before.st_atime_ns,
    }


def youtube_metadata_policy_snapshot(config: dict[str, Any] | None = None) -> dict[str, Any]:
    source = config if isinstance(config, dict) else {}
    write_thumbnail = _normalize_youtube_boolean(
        source.get("youtubeWriteThumbnail"), "YouTube 썸네일 파일 저장"
    )
    embed_thumbnail = _normalize_youtube_boolean(
        source.get("youtubeEmbedThumbnail"), "YouTube 썸네일 포함"
    )
    write_info_json = _normalize_youtube_boolean(
        source.get("youtubeWriteInfoJson"), "YouTube 정보 JSON 저장"
    )
    write_description = _normalize_youtube_boolean(
        source.get("youtubeWriteDescription"), "YouTube 설명 파일 저장"
    )
    embed_metadata = _normalize_youtube_boolean(
        source.get("youtubeEmbedMetadata"), "YouTube 미디어 메타데이터 포함"
    )
    return {
        "ok": True,
        "writeThumbnail": write_thumbnail,
        "embedThumbnail": embed_thumbnail,
        "writeInfoJson": write_info_json,
        "writeDescription": write_description,
        "embedMetadata": embed_metadata,
        "cleanInfoJson": True,
        "requestComments": False,
        "commentsMayBePresent": write_info_json,
        "writePlaylistMetafiles": False,
        "infoJsonMayContainPersonalInformation": write_info_json,
        "networkRequested": False,
        "downloadExecuted": False,
    }


def preview_youtube_filename(
    template: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = normalize_youtube_filename_template(template)
    source = {
        "title": "영상 제목",
        "id": "dQw4w9WgXcQ",
        "uploader": "업로더",
        "channel": "채널",
        "upload_date": "20260807",
        "playlist": "재생목록",
        "playlist_index": "001",
        "ext": "mp4",
        **(metadata if isinstance(metadata, dict) else {}),
    }
    rendered = _YOUTUBE_TEMPLATE_FIELD.sub(
        lambda match: str(source.get(match.group(1)) or "미상"), normalized
    ).strip().rstrip(". ")
    rendered = _WINDOWS_FILENAME_INVALID.sub("_", rendered)
    if not rendered:
        raise ValueError("YouTube 파일명 미리보기 결과가 비어 있습니다.")
    return {
        "ok": True,
        "template": normalized,
        "preview": rendered,
        "fields": _YOUTUBE_TEMPLATE_FIELD.findall(normalized),
        "windowsSafe": True,
        "networkRequested": False,
        "downloadExecuted": False,
    }


def inspect_youtube_url(url: str) -> dict[str, Any]:
    raw = str(url or "").strip()
    try:
        parsed = urlsplit(raw)
    except ValueError as error:
        raise YouTubePolicyError("youtube.invalid_url", "YouTube 주소 형식이 잘못되었습니다.") from error
    host = str(parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in YOUTUBE_HOSTS:
        raise YouTubePolicyError(
            "youtube.unsupported_url", "지원하는 HTTPS YouTube 주소를 입력해주세요."
        )
    if parsed.username or parsed.password:
        raise YouTubePolicyError(
            "youtube.url_credentials_not_allowed", "YouTube 주소에 인증 정보를 넣을 수 없습니다."
        )
    video_id = ""
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/", 1)[0]
    elif parsed.path == "/watch":
        video_id = str(parse_qs(parsed.query).get("v", [""])[0]).strip()
    elif parsed.path.startswith(("/shorts/", "/live/", "/embed/")):
        parts = [part for part in parsed.path.split("/") if part]
        video_id = parts[1] if len(parts) > 1 else ""
    playlist_id = str(parse_qs(parsed.query).get("list", [""])[0]).strip()
    if video_id and not re.fullmatch(r"[A-Za-z0-9_-]{3,128}", video_id):
        raise YouTubePolicyError(
            "youtube.video_id_invalid", "YouTube 동영상 식별자 형식이 잘못되었습니다."
        )
    if playlist_id and not re.fullmatch(r"[A-Za-z0-9_-]{3,256}", playlist_id):
        raise YouTubePolicyError(
            "youtube.playlist_id_invalid", "YouTube 재생목록 식별자 형식이 잘못되었습니다."
        )
    path_parts = [part for part in parsed.path.split("/") if part]
    channel_scope = ""
    channel_path = ""
    if host != "youtu.be" and not video_id and path_parts:
        first = path_parts[0]
        channel_prefix = first.startswith("@") or first in {"channel", "c", "user"}
        required_parts = 1 if first.startswith("@") else 2
        allowed_tabs = {"featured", "videos", "shorts", "streams", "playlists"}
        if channel_prefix and len(path_parts) in {required_parts, required_parts + 1}:
            channel_id = path_parts[0] if first.startswith("@") else path_parts[1]
            tab = path_parts[-1].lower() if len(path_parts) == required_parts + 1 else ""
            if (
                channel_id
                and not re.search(r"[\s\\?#]", channel_id)
                and (not tab or tab in allowed_tabs)
            ):
                channel_path = "/" + "/".join(path_parts)
                channel_scope = tab or "all_uploads"
    is_playlist = bool(playlist_id and parsed.path.rstrip("/") == "/playlist")
    if not video_id and not is_playlist and not channel_path:
        raise YouTubePolicyError(
            "youtube.reference_missing", "동영상, 재생목록 또는 채널 식별자를 찾을 수 없습니다."
        )
    reference_type = "video" if video_id else ("playlist" if is_playlist else "channel")
    return {
        "ok": True,
        "host": host,
        "videoId": video_id,
        "playlistId": playlist_id if is_playlist or video_id else "",
        "channelPath": channel_path,
        "channelScope": channel_scope,
        "referenceType": reference_type,
        "collection": reference_type in {"playlist", "channel"},
        "networkRequested": False,
    }


def youtube_format_policy_snapshot(config: dict[str, Any] | None = None) -> dict[str, Any]:
    source = config if isinstance(config, dict) else {}
    metadata_policy = youtube_metadata_policy_snapshot(source)
    collection_policy = youtube_collection_policy_snapshot(source)
    chapter_policy = youtube_chapter_policy_snapshot(source)
    mtime_policy = youtube_mtime_policy_snapshot(source)
    return {
        "ok": True,
        "mode": normalize_youtube_format_mode(source.get("youtubeFormatMode")),
        "maxHeight": normalize_youtube_max_height(source.get("youtubeMaxHeight")),
        "container": normalize_youtube_container(source.get("youtubeContainer")),
        "videoCodec": normalize_youtube_video_codec(source.get("youtubeVideoCodec")),
        "audioCodec": normalize_youtube_audio_codec(source.get("youtubeAudioCodec")),
        "filenameTemplate": normalize_youtube_filename_template(
            source.get("youtubeFilenameTemplate", DEFAULT_YOUTUBE_FILENAME_TEMPLATE)
        ),
        "preferredLanguages": normalize_youtube_languages(
            source.get("youtubePreferredLanguages", ["ko", "en", "ja"])
        ),
        "subtitleMode": normalize_youtube_subtitle_mode(
            source.get("youtubeSubtitleMode", "none")
        ),
        "subtitleFormat": normalize_youtube_subtitle_format(
            source.get("youtubeSubtitleFormat", "best")
        ),
        "embedSubtitles": _normalize_youtube_boolean(
            source.get("youtubeEmbedSubtitles"), "YouTube 자막 포함"
        ),
        "audioTrackMode": normalize_youtube_audio_track_mode(
            source.get("youtubeAudioTrackMode", "preferred_single")
        ),
        "collectionOrder": collection_policy["order"],
        "embedChapters": chapter_policy["embedChapters"],
        "applyUploadDateMtime": mtime_policy["applyUploadDateMtime"],
        "writeThumbnail": metadata_policy["writeThumbnail"],
        "embedThumbnail": metadata_policy["embedThumbnail"],
        "writeInfoJson": metadata_policy["writeInfoJson"],
        "writeDescription": metadata_policy["writeDescription"],
        "embedMetadata": metadata_policy["embedMetadata"],
        "cleanInfoJson": metadata_policy["cleanInfoJson"],
        "requestComments": metadata_policy["requestComments"],
        "commentsMayBePresent": metadata_policy["commentsMayBePresent"],
        "writePlaylistMetafiles": metadata_policy["writePlaylistMetafiles"],
        "infoJsonMayContainPersonalInformation": metadata_policy[
            "infoJsonMayContainPersonalInformation"
        ],
        "codecSelection": "preference_with_fallback",
        "networkRequested": False,
        "downloadExecuted": False,
    }


def plan_youtube_format(url: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    reference = inspect_youtube_url(url)
    policy = youtube_format_policy_snapshot(config)
    height_filter = (
        f"[height<=?{policy['maxHeight']}]" if policy["maxHeight"] else ""
    )
    if policy["mode"] == "video_audio":
        selector = (
            f"bv*{height_filter}+mergeall[vcodec=none]"
            if policy["audioTrackMode"] == "all"
            else f"bv*{height_filter}+ba/b{height_filter}"
        )
    elif policy["mode"] == "video_only":
        selector = f"bv{height_filter}"
    else:
        selector = "mergeall[vcodec=none]" if policy["audioTrackMode"] == "all" else "ba"
    format_sort: list[str] = []
    if policy["maxHeight"] and policy["mode"] != "audio_only":
        format_sort.append(f"res:{policy['maxHeight']}")
    if policy["videoCodec"] != "auto" and policy["mode"] != "audio_only":
        format_sort.append(_VIDEO_CODEC_SORT[policy["videoCodec"]])
    if policy["audioCodec"] != "auto" and policy["mode"] != "video_only":
        format_sort.append(_AUDIO_CODEC_SORT[policy["audioCodec"]])
    if policy["preferredLanguages"] and policy["mode"] != "video_only":
        format_sort.insert(0, f"lang:{policy['preferredLanguages'][0]}")
    playlist_switch = (
        "--no-playlist" if reference["referenceType"] == "video" else "--yes-playlist"
    )
    arguments = [
        playlist_switch,
        "--format",
        selector,
        "--output",
        policy["filenameTemplate"],
    ]
    if format_sort:
        arguments.extend(("--format-sort", ",".join(format_sort)))
    collection_order_applied = bool(reference["collection"])
    if collection_order_applied:
        if policy["collectionOrder"] == "reverse":
            arguments.extend(("--no-lazy-playlist", "--playlist-items", "::-1"))
        else:
            arguments.extend(("--playlist-items", "::"))
    requires_ffmpeg = policy["mode"] == "video_audio"
    if policy["audioTrackMode"] == "all" and policy["mode"] != "video_only":
        arguments.append("--audio-multistreams")
        requires_ffmpeg = True
    if policy["subtitleMode"] != "none":
        arguments.extend(("--write-subs", "--sub-langs", ",".join(policy["preferredLanguages"])))
        arguments.extend(("--sub-format", policy["subtitleFormat"]))
        if policy["subtitleMode"] == "manual_auto":
            arguments.append("--write-auto-subs")
        if policy["embedSubtitles"]:
            arguments.append("--embed-subs")
            requires_ffmpeg = True
    sidecar_metadata = (
        policy["writeThumbnail"]
        or policy["writeInfoJson"]
        or policy["writeDescription"]
    )
    if policy["writeThumbnail"]:
        arguments.append("--write-thumbnail")
    if policy["embedThumbnail"]:
        arguments.append("--embed-thumbnail")
        requires_ffmpeg = True
    if policy["writeInfoJson"]:
        arguments.extend(("--write-info-json", "--clean-info-json", "--no-write-comments"))
    if policy["writeDescription"]:
        arguments.append("--write-description")
    if sidecar_metadata:
        arguments.append("--no-write-playlist-metafiles")
    if policy["embedMetadata"]:
        arguments.extend(("--embed-metadata", "--no-embed-info-json"))
        requires_ffmpeg = True
    if policy["embedChapters"]:
        arguments.append("--embed-chapters")
        requires_ffmpeg = True
    elif policy["embedMetadata"]:
        arguments.append("--no-embed-chapters")
    if policy["container"] != "auto" and policy["mode"] != "audio_only":
        arguments.extend(("--merge-output-format", policy["container"]))
        arguments.extend(("--remux-video", policy["container"]))
        requires_ffmpeg = True
    arguments.append(str(url).strip())
    return {
        **policy,
        "reference": reference,
        "formatSelector": selector,
        "formatSort": format_sort,
        "collectionOrderApplied": collection_order_applied,
        "fullCollectionScanRequired": bool(
            collection_order_applied and policy["collectionOrder"] == "reverse"
        ),
        "executable": "yt-dlp",
        "arguments": arguments,
        "requiresYtDlp": True,
        "requiresFfmpeg": requires_ffmpeg,
        "postProcessingRequired": bool(
            policy["embedThumbnail"] or policy["embedMetadata"] or policy["embedChapters"]
        ),
        "postDownloadActions": (
            [
                {
                    "action": "set_mtime_from_upload_date",
                    "sourceField": "upload_date",
                    "sourceTimezone": "UTC",
                    "preserveAccessTime": True,
                }
            ]
            if policy["applyUploadDateMtime"]
            else []
        ),
        "externalRequestRequiresConfirmation": True,
        "networkRequested": False,
        "downloadExecuted": False,
    }


def plan_youtube_execution(
    url: str,
    output_dir: str | Path,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the deterministic yt-dlp CLI contract without starting a request."""
    format_plan = plan_youtube_format(url, config)
    output = Path(os.path.abspath(os.fspath(Path(output_dir).expanduser())))
    if not str(output).strip():
        raise ValueError("YouTube 저장 폴더를 입력해주세요.")
    format_arguments = list(format_plan["arguments"])
    source_url = format_arguments.pop()
    progress_template = (
        f"download:{YOUTUBE_PROGRESS_PREFIX}"
        '{"videoId":%(info.id|null)j,"itemIndex":%(info.playlist_index|0)j,'
        '"itemTotal":%(info.n_entries|0)j,"status":%(progress.status|null)j,'
        '"percent":%(progress._percent_str|0%)j,'
        '"speed":%(progress._speed_str|null)j,"eta":%(progress._eta_str|null)j}'
    )
    item_template = (
        f"before_dl:{YOUTUBE_ITEM_PREFIX}"
        '{"videoId":%(id|null)j,"itemIndex":%(playlist_index|0)j,'
        '"itemTotal":%(n_entries|0)j,"videoTitle":%(title|null)j,'
        '"collectionTitle":%(playlist_title|null)j,"channel":%(channel|null)j}'
    )
    complete_template = (
        f"after_move:{YOUTUBE_COMPLETE_PREFIX}"
        '{"videoId":%(id|null)j,"itemIndex":%(playlist_index|0)j,'
        '"itemTotal":%(n_entries|0)j,"uploadDate":%(upload_date|null)j,'
        '"outputPath":%(filepath|null)j}'
    )
    arguments = [
        "--ignore-config",
        "--no-color",
        "--windows-filenames",
        "--newline",
        "--progress",
        "--progress-delta",
        "0.2",
        "--continue",
        "--no-overwrites",
        "--no-mtime",
        "--paths",
        str(output),
        "--progress-template",
        progress_template,
        "--print",
        item_template,
        "--print",
        complete_template,
        *format_arguments,
        source_url,
    ]
    return {
        **format_plan,
        "outputDir": str(output),
        "arguments": arguments,
        "progressPrefix": YOUTUBE_PROGRESS_PREFIX,
        "itemPrefix": YOUTUBE_ITEM_PREFIX,
        "completePrefix": YOUTUBE_COMPLETE_PREFIX,
        "progressEventIntervalSeconds": 0.2,
        "continuesPartialDownloads": True,
        "overwritesCompletedMedia": False,
        "usesHttpLastModifiedMtime": False,
        "networkRequested": False,
        "downloadExecuted": False,
    }


def youtube_execution_config_snapshot(
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return only normalized YouTube settings safe to pass to the worker."""
    source = config if isinstance(config, dict) else {}
    policy = youtube_format_policy_snapshot(source)
    return {
        "youtubeFormatMode": policy["mode"],
        "youtubeMaxHeight": policy["maxHeight"],
        "youtubeContainer": policy["container"],
        "youtubeVideoCodec": policy["videoCodec"],
        "youtubeAudioCodec": policy["audioCodec"],
        "youtubeFilenameTemplate": policy["filenameTemplate"],
        "youtubePreferredLanguages": list(policy["preferredLanguages"]),
        "youtubeSubtitleMode": policy["subtitleMode"],
        "youtubeSubtitleFormat": policy["subtitleFormat"],
        "youtubeEmbedSubtitles": policy["embedSubtitles"],
        "youtubeAudioTrackMode": policy["audioTrackMode"],
        "youtubeWriteThumbnail": policy["writeThumbnail"],
        "youtubeEmbedThumbnail": policy["embedThumbnail"],
        "youtubeWriteInfoJson": policy["writeInfoJson"],
        "youtubeWriteDescription": policy["writeDescription"],
        "youtubeEmbedMetadata": policy["embedMetadata"],
        "youtubeCollectionOrder": policy["collectionOrder"],
        "youtubeEmbedChapters": policy["embedChapters"],
        "youtubeApplyUploadDateMtime": policy["applyUploadDateMtime"],
    }
