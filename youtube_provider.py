from __future__ import annotations

import re
from typing import Any
from urllib.parse import parse_qs, urlsplit


YOUTUBE_FORMAT_MODES = ("video_audio", "video_only", "audio_only")
YOUTUBE_MAX_HEIGHTS = (0, 2160, 1440, 1080, 720, 480, 360, 240, 144)
YOUTUBE_CONTAINERS = ("auto", "mp4", "mkv", "webm")
YOUTUBE_VIDEO_CODECS = ("auto", "h264", "h265", "vp9", "av1")
YOUTUBE_AUDIO_CODECS = ("auto", "aac", "opus")
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
    if not video_id and not playlist_id:
        raise YouTubePolicyError(
            "youtube.reference_missing", "동영상 또는 재생목록 식별자를 찾을 수 없습니다."
        )
    return {
        "ok": True,
        "host": host,
        "videoId": video_id,
        "playlistId": playlist_id,
        "referenceType": "video" if video_id else "playlist",
        "networkRequested": False,
    }


def youtube_format_policy_snapshot(config: dict[str, Any] | None = None) -> dict[str, Any]:
    source = config if isinstance(config, dict) else {}
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
        selector = f"bv*{height_filter}+ba/b{height_filter}"
    elif policy["mode"] == "video_only":
        selector = f"bv{height_filter}"
    else:
        selector = "ba"
    format_sort: list[str] = []
    if policy["maxHeight"] and policy["mode"] != "audio_only":
        format_sort.append(f"res:{policy['maxHeight']}")
    if policy["videoCodec"] != "auto" and policy["mode"] != "audio_only":
        format_sort.append(_VIDEO_CODEC_SORT[policy["videoCodec"]])
    if policy["audioCodec"] != "auto" and policy["mode"] != "video_only":
        format_sort.append(_AUDIO_CODEC_SORT[policy["audioCodec"]])
    playlist_switch = "--no-playlist" if reference["videoId"] else "--yes-playlist"
    arguments = [
        playlist_switch,
        "--format",
        selector,
        "--output",
        policy["filenameTemplate"],
    ]
    if format_sort:
        arguments.extend(("--format-sort", ",".join(format_sort)))
    requires_ffmpeg = policy["mode"] == "video_audio"
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
        "executable": "yt-dlp",
        "arguments": arguments,
        "requiresYtDlp": True,
        "requiresFfmpeg": requires_ffmpeg,
        "externalRequestRequiresConfirmation": True,
        "networkRequested": False,
        "downloadExecuted": False,
    }
