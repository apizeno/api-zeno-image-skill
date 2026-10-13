#!/usr/bin/env python3
"""Secure, dependency-free API-Zeno media client for the api-zeno-image skill."""

from __future__ import annotations

import argparse
import base64
import binascii
import getpass
import ipaddress
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_BASE_URL = "https://api-zeno.com/v1"
DEFAULT_MODEL = "gemini-3.1-flash-image-preview"
DEFAULT_SIZE = "1024x1024"
MAX_DOWNLOAD_BYTES = 50 * 1024 * 1024
MAX_VIDEO_BYTES = 500 * 1024 * 1024
MAX_RESPONSE_BYTES = 70 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 1000
DEFAULT_VIDEO_POLL_INTERVAL = 5.0
DEFAULT_VIDEO_POLL_TIMEOUT = 1800
MAX_VIDEO_POLL_TIMEOUT = 24 * 60 * 60
MODELS_PATH = Path(__file__).resolve().parent.parent / "references" / "models.json"


class ImageSkillError(Exception):
    """Expected configuration, transport, API, or response error."""


class APIError(ImageSkillError):
    def __init__(
        self,
        status: int,
        message: str,
        code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.request_id = request_id

    def __str__(self) -> str:
        parts = [f"API request failed ({self.status})"]
        if self.code:
            parts.append(f"code={self.code}")
        if self.request_id:
            parts.append(f"request_id={self.request_id}")
        return ": ".join(parts) + f": {super().__str__()}"


def config_dir() -> Path:
    override = os.environ.get("API_ZENO_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    if os.name == "nt":
        root = os.environ.get("APPDATA")
        if root:
            return Path(root) / "api-zeno-image"
    root = os.environ.get("XDG_CONFIG_HOME")
    if root:
        return Path(root) / "api-zeno-image"
    return Path.home() / ".config" / "api-zeno-image"


def credential_path() -> Path:
    return config_dir() / "credentials.json"


def state_path() -> Path:
    return config_dir() / "state.json"


def _restrict_windows_acl(path: Path, directory: bool = False) -> None:
    if os.name != "nt":
        return
    username = os.environ.get("USERNAME")
    if not username:
        return
    permission = "(OI)(CI)F" if directory else "F"
    try:
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{username}:{permission}"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        # The profile directory and chmod still provide the platform fallback.
        pass


def _ensure_private_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, stat.S_IRWXU)
    except OSError:
        pass
    _restrict_windows_acl(path, directory=True)


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    _ensure_private_dir(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temp_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        os.replace(temp_path, path)
        _restrict_windows_acl(path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ImageSkillError(f"Cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ImageSkillError(f"Expected a JSON object in {path}")
    return value


def _models() -> dict[str, Any]:
    value = _load_json(MODELS_PATH)
    models = value.get("models")
    if not isinstance(models, dict):
        raise ImageSkillError(f"Model catalog is invalid: {MODELS_PATH}")
    return value


def _credential_config() -> dict[str, Any]:
    return _load_json(credential_path())


def _api_key() -> tuple[str, str]:
    env_key = os.environ.get("API_ZENO_KEY", "").strip()
    if env_key:
        return env_key, "environment"
    saved = str(_credential_config().get("api_key", "")).strip()
    if saved:
        return saved, "saved configuration"
    raise ImageSkillError(
        "No API-Zeno key found. Set API_ZENO_KEY or run the configure command."
    )


def _base_url() -> str:
    credentials = _credential_config()
    value = (
        os.environ.get("API_ZENO_BASE_URL")
        or credentials.get("base_url")
        or DEFAULT_BASE_URL
    )
    value = str(value).strip().rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ImageSkillError(f"Invalid API base URL: {value}")
    return value


def _read_secret() -> str:
    if sys.stdin.isatty():
        return getpass.getpass("API-Zeno key: ").strip()
    return sys.stdin.readline().strip()


def configure(base_url: str | None) -> int:
    key = _read_secret()
    if not key:
        raise ImageSkillError("The API-Zeno key cannot be empty")
    config: dict[str, Any] = {
        "api_key": key,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if base_url:
        parsed = urllib.parse.urlsplit(base_url.rstrip("/"))
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ImageSkillError(f"Invalid API base URL: {base_url}")
        config["base_url"] = base_url.rstrip("/")
    _atomic_write_json(credential_path(), config)
    print(
        json.dumps(
            {
                "configured": str(credential_path()),
                "security_reminder": (
                    "Review this key's API-Zeno model allowlist and quota. "
                    "Use an IP allowlist only with a stable public egress IP."
                ),
            },
            indent=2,
        )
    )
    return 0


def clear_key() -> int:
    path = credential_path()
    credentials = _credential_config()
    if "api_key" not in credentials:
        print(json.dumps({"removed": False, "path": str(path)}, indent=2))
        return 0
    credentials.pop("api_key", None)
    credentials["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write_json(path, credentials)
    print(json.dumps({"removed": True, "path": str(path)}, indent=2))
    return 0


def list_models() -> int:
    print(json.dumps(_models(), indent=2, ensure_ascii=True))
    return 0


def status() -> int:
    credentials = _credential_config()
    env_key = bool(os.environ.get("API_ZENO_KEY", "").strip())
    saved_key = bool(str(credentials.get("api_key", "")).strip())
    value = {
        "base_url": _base_url(),
        "key_configured": env_key or saved_key,
        "key_source": "environment" if env_key else "saved configuration" if saved_key else None,
        "config_directory": str(config_dir().resolve()),
        "last_workflow": _load_json(state_path()),
    }
    print(json.dumps(value, indent=2, ensure_ascii=True))
    return 0


def _validate_model_options(
    operation: str,
    model: str,
    quality: str | None,
    n: int,
) -> dict[str, Any]:
    catalog = _models()
    model_info = catalog["models"].get(model)
    if not isinstance(model_info, dict):
        available = ", ".join(sorted(catalog["models"]))
        raise ImageSkillError(f"Unknown model '{model}'. Available models: {available}")
    if operation not in model_info.get("operations", []):
        allowed = ", ".join(model_info.get("operations", []))
        raise ImageSkillError(f"Model '{model}' does not support {operation}; supports: {allowed}")
    max_n = int(model_info.get("max_n", 1))
    if n < 1 or n > max_n:
        raise ImageSkillError(f"Model '{model}' accepts n between 1 and {max_n}")
    qualities = model_info.get("qualities", [])
    if quality and quality not in qualities:
        allowed = ", ".join(qualities) if qualities else "none"
        raise ImageSkillError(f"Model '{model}' does not accept quality '{quality}'; allowed: {allowed}")
    return model_info


def _resolve_options(args: argparse.Namespace, operation: str) -> dict[str, Any]:
    state = _load_json(state_path())
    previous = state.get("options") if isinstance(state.get("options"), dict) else {}
    catalog = _models()
    model = args.model or previous.get("model") or catalog.get("default_model") or DEFAULT_MODEL
    size = args.size or previous.get("size") or catalog.get("default_size") or DEFAULT_SIZE
    n = args.n if args.n is not None else int(previous.get("n", 1))
    quality = args.quality
    model_info = catalog["models"].get(model, {})
    if quality is None and model == previous.get("model"):
        quality = previous.get("quality")
    if quality is None and isinstance(model_info, dict):
        quality = model_info.get("default_quality")
    _validate_model_options(operation, model, quality, n)
    sizes = catalog.get("sizes", [])
    if size not in sizes:
        raise ImageSkillError(f"Unsupported size '{size}'; consult references/models.json")
    resolution = args.resolution or previous.get("resolution")
    if resolution and resolution not in catalog.get("resolutions", []):
        raise ImageSkillError("Resolution must be one of: 1k, 2k, 4k")
    output_format = args.output_format
    formats = model_info.get("output_formats", []) if isinstance(model_info, dict) else []
    if output_format is None and model == previous.get("model"):
        output_format = previous.get("output_format")
    if output_format is None and isinstance(model_info, dict):
        output_format = model_info.get("default_output_format")
    if output_format and output_format not in formats:
        allowed = ", ".join(formats) if formats else "none"
        raise ImageSkillError(
            f"Model '{model}' does not accept output format '{output_format}'; allowed: {allowed}"
        )
    timeout = args.timeout if args.timeout is not None else int(previous.get("timeout", DEFAULT_TIMEOUT_SECONDS))
    if timeout < 1 or timeout > DEFAULT_TIMEOUT_SECONDS:
        raise ImageSkillError(f"Timeout must be between 1 and {DEFAULT_TIMEOUT_SECONDS} seconds")
    return {
        "model": model,
        "size": size,
        "quality": quality,
        "resolution": resolution,
        "n": n,
        "response_format": args.response_format or previous.get("response_format") or "b64_json",
        "output_format": output_format,
        "timeout": timeout,
    }


def _json_request(endpoint: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return _request(endpoint, body, "application/json", timeout)


def _image_mime(path: Path) -> str:
    if not path.is_file():
        raise ImageSkillError(f"Input image not found: {path}")
    size = path.stat().st_size
    if size < 1 or size > MAX_DOWNLOAD_BYTES:
        raise ImageSkillError(f"Input image must be between 1 byte and 50 MiB: {path}")
    with path.open("rb") as handle:
        header = handle.read(12)
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"
    raise ImageSkillError(f"Input image must be PNG, JPEG, or WebP: {path}")


def _multipart_body(
    fields: Iterable[tuple[str, str]],
    files: Iterable[tuple[str, Path]],
) -> tuple[bytes, str]:
    boundary = f"api-zeno-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields:
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                value.encode("utf-8"),
                b"\r\n",
            ]
        )
    for name, path in files:
        mime = _image_mime(path)
        filename = path.name.replace('"', "_").replace("\r", "_").replace("\n", "_")
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {mime}\r\n\r\n".encode(),
                path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


def _request_method(
    endpoint: str,
    body: bytes | None,
    content_type: str | None,
    timeout: int,
    method: str,
) -> dict[str, Any]:
    key, _ = _api_key()
    url = f"{_base_url()}/{endpoint.lstrip('/')}"
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {key}",
            "Accept": "application/json",
            "User-Agent": "api-zeno-media-skill/1.1",
        },
    )
    if content_type:
        request.add_header("Content-Type", content_type)
    try:
        opener = urllib.request.build_opener(_NoRedirectHandler())
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ImageSkillError("API-Zeno response exceeds the 70 MiB limit")
    except urllib.error.HTTPError as exc:
        raw = exc.read(1024 * 1024)
        request_id = exc.headers.get("x-request-id") if exc.headers else None
        code = None
        message = raw.decode("utf-8", errors="replace") or exc.reason
        try:
            parsed = json.loads(raw)
            error = parsed.get("error", parsed) if isinstance(parsed, dict) else {}
            if isinstance(error, dict):
                code = error.get("code") or parsed.get("code")
                message = error.get("message") or parsed.get("message") or message
                request_id = request_id or error.get("request_id") or parsed.get("request_id")
        except (json.JSONDecodeError, UnicodeDecodeError):
            pass
        raise APIError(exc.code, str(message), str(code) if code else None, request_id) from exc
    except urllib.error.URLError as exc:
        raise ImageSkillError(f"Could not reach API-Zeno: {exc.reason}") from exc
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ImageSkillError("API-Zeno returned an invalid JSON response") from exc
    if not isinstance(value, dict):
        raise ImageSkillError("API-Zeno returned an unexpected response shape")
    return value


def _request(endpoint: str, body: bytes, content_type: str, timeout: int) -> dict[str, Any]:
    return _request_method(endpoint, body, content_type, timeout, "POST")


def _get_request(endpoint: str, timeout: int) -> dict[str, Any]:
    return _request_method(endpoint, None, None, timeout, "GET")


def _safe_public_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ImageSkillError("Image URL must use http or https")
    if parsed.username or parsed.password:
        raise ImageSkillError("Image URL credentials are not allowed")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost"):
        raise ImageSkillError("Refusing to download an image from localhost")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise ImageSkillError("Image URL contains an invalid port") from exc
    try:
        addresses = socket.getaddrinfo(
            hostname,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ImageSkillError(f"Could not resolve image host '{hostname}'") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ImageSkillError(f"Refusing to download an image from non-public address {ip}")


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        _safe_public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _download(url: str, timeout: int, *, max_bytes: int = MAX_DOWNLOAD_BYTES, media_name: str = "image") -> bytes:
    _safe_public_url(url)
    opener = urllib.request.build_opener(_SafeRedirectHandler())
    request = urllib.request.Request(url, headers={"User-Agent": "api-zeno-media-skill/1.1"})
    try:
        with opener.open(request, timeout=timeout) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > max_bytes:
                raise ImageSkillError(f"{media_name.capitalize()} download exceeds the {max_bytes // (1024 * 1024)} MiB limit")
            data = response.read(max_bytes + 1)
    except urllib.error.URLError as exc:
        raise ImageSkillError(f"Could not download {media_name} result: {exc.reason}") from exc
    if len(data) > max_bytes:
        raise ImageSkillError(f"{media_name.capitalize()} download exceeds the {max_bytes // (1024 * 1024)} MiB limit")
    return data


def _decode_result(item: dict[str, Any], timeout: int) -> bytes | None:
    encoded = item.get("b64_json")
    if isinstance(encoded, str):
        try:
            return base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ImageSkillError("API-Zeno returned invalid base64 image data") from exc
    url = item.get("url")
    if isinstance(url, str):
        return _download(url, timeout)
    return None


def _available_path(path: Path) -> Path:
    candidate = path
    index = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}-{index}{path.suffix}")
        index += 1
    return candidate


def _result_paths(output: Path, count: int, output_format: str) -> list[Path]:
    suffix = output.suffix or f".{output_format}"
    base = output.with_suffix(suffix)
    if count == 1:
        return [_available_path(base)]
    paths = []
    for index in range(1, count + 1):
        paths.append(_available_path(base.with_name(f"{base.stem}-{index}{base.suffix}")))
    return paths


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _handle_response(
    response: dict[str, Any],
    output: str | None,
    output_format: str | None,
    timeout: int,
) -> list[str]:
    data = response.get("data")
    if not isinstance(data, list) or not data:
        raise ImageSkillError("API-Zeno response contains no image data")
    items = [item for item in data if isinstance(item, dict)]
    if len(items) != len(data):
        raise ImageSkillError("API-Zeno returned an invalid image item")
    if output:
        paths = _result_paths(Path(output).expanduser().resolve(), len(items), output_format or "png")
        for item, path in zip(items, paths):
            image = _decode_result(item, timeout)
            if image is None:
                raise ImageSkillError("Image item contains neither b64_json nor url")
            _atomic_write_bytes(path, image)
        result = [str(path) for path in paths]
        print(json.dumps({"outputs": result}, indent=2))
        return result
    summary = []
    for item in items:
        summary.append(
            {
                "url": item.get("url"),
                "base64_bytes": len(item.get("b64_json", "")),
                "revised_prompt": item.get("revised_prompt"),
            }
        )
    print(json.dumps({"images": summary}, indent=2))
    return []


def _save_state(operation: str, options: dict[str, Any], outputs: list[str]) -> None:
    value = {
        "last_operation": operation,
        "options": {key: value for key, value in options.items() if value is not None},
        "outputs": outputs,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    _atomic_write_json(state_path(), value)


def generate(args: argparse.Namespace) -> int:
    options = _resolve_options(args, "generate")
    request_options = {key: value for key, value in options.items() if key != "timeout" and value is not None}
    payload = {"prompt": args.prompt, **request_options}
    response = _json_request("images/generations", payload, options["timeout"])
    outputs = _handle_response(response, args.output, options["output_format"], options["timeout"])
    _save_state("generate", options, outputs)
    return 0


def edit(args: argparse.Namespace) -> int:
    options = _resolve_options(args, "edit")
    fields = [("prompt", args.prompt)] + [
        (key, str(value)) for key, value in options.items() if key != "timeout" and value is not None
    ]
    files = [("image", Path(value).expanduser().resolve()) for value in args.image]
    if args.mask:
        files.append(("mask", Path(args.mask).expanduser().resolve()))
    body, content_type = _multipart_body(fields, files)
    response = _request("images/edits", body, content_type, options["timeout"])
    outputs = _handle_response(response, args.output, options["output_format"], options["timeout"])
    _save_state("edit", options, outputs)
    return 0


def variation(args: argparse.Namespace) -> int:
    options = _resolve_options(args, "variation")
    fields = [
        (key, str(value)) for key, value in options.items() if key != "timeout" and value is not None
    ]
    files = [("image", Path(args.image).expanduser().resolve())]
    body, content_type = _multipart_body(fields, files)
    response = _request("images/variations", body, content_type, options["timeout"])
    outputs = _handle_response(response, args.output, options["output_format"], options["timeout"])
    _save_state("variation", options, outputs)
    return 0


def _video_model_info(model: str) -> dict[str, Any]:
    catalog = _models()
    model_info = catalog["models"].get(model)
    if not isinstance(model_info, dict):
        available = ", ".join(
            sorted(name for name, info in catalog["models"].items() if isinstance(info, dict) and info.get("media") == "video")
        )
        raise ImageSkillError(f"Unknown video model '{model}'. Available video models: {available or 'none'}")
    if model_info.get("media") != "video" or "generate" not in model_info.get("operations", []):
        raise ImageSkillError(f"Model '{model}' is not a video generation model")
    return model_info


def _image_data_url(path: Path) -> str:
    mime = _image_mime(path)
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _video_payload(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    model = args.model or _models().get("default_video_model")
    if not model:
        raise ImageSkillError("A video model is required; pass --model")
    info = _video_model_info(str(model))
    payload: dict[str, Any] = {"model": str(model), "prompt": args.prompt}
    for key in ("size", "resolution", "duration", "aspect_ratio"):
        value = getattr(args, key, None)
        if value is not None:
            payload[key] = value
    if args.image and args.image_url:
        raise ImageSkillError("Use either --image or --image-url, not both")
    if args.image:
        payload["image_url"] = _image_data_url(Path(args.image).expanduser().resolve())
    elif args.image_url:
        _safe_public_url(args.image_url)
        payload["image_url"] = args.image_url
    allowed_inputs = info.get("input_modes", ["text"])
    if "image_url" in payload and "image" not in allowed_inputs:
        raise ImageSkillError(f"Video model '{model}' does not support image-to-video input")
    poll_interval = float(args.poll_interval)
    if poll_interval < 0.1 or poll_interval > 60:
        raise ImageSkillError("Poll interval must be between 0.1 and 60 seconds")
    poll_timeout = int(args.poll_timeout)
    if poll_timeout < 1 or poll_timeout > MAX_VIDEO_POLL_TIMEOUT:
        raise ImageSkillError(f"Poll timeout must be between 1 and {MAX_VIDEO_POLL_TIMEOUT} seconds")
    timeout = args.timeout if args.timeout is not None else DEFAULT_TIMEOUT_SECONDS
    if timeout < 1 or timeout > DEFAULT_TIMEOUT_SECONDS:
        raise ImageSkillError(f"Timeout must be between 1 and {DEFAULT_TIMEOUT_SECONDS} seconds")
    options = {
        "model": str(model),
        "size": args.size,
        "resolution": args.resolution,
        "duration": args.duration,
        "aspect_ratio": args.aspect_ratio,
        "image": str(Path(args.image).expanduser().resolve()) if args.image else None,
        # Do not persist a possibly signed URL in the non-secret workflow state.
        "image_url": None,
        "poll_interval": poll_interval,
        "poll_timeout": poll_timeout,
        "timeout": timeout,
    }
    return payload, options


def _nested_values(value: Any) -> Iterable[Any]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _nested_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _nested_values(child)


def _video_task_id(response: dict[str, Any]) -> str | None:
    for value in _nested_values(response):
        if not isinstance(value, dict):
            continue
        for key in ("task_id", "taskId", "id"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
    return None


def _video_status(response: dict[str, Any]) -> str | None:
    for value in _nested_values(response):
        if not isinstance(value, dict):
            continue
        for key in ("status", "state"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip().lower()
    return None


def _video_result_bytes(response: dict[str, Any], timeout: int) -> bytes | None:
    base64_keys = ("b64_json", "b64_video", "video_base64", "base64")
    url_keys = ("video_url", "output_url", "download_url", "url")
    for value in _nested_values(response):
        if not isinstance(value, dict):
            continue
        for key in base64_keys:
            encoded = value.get(key)
            if isinstance(encoded, str) and encoded:
                try:
                    return base64.b64decode(encoded, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ImageSkillError("API-Zeno returned invalid base64 video data") from exc
        for key in url_keys:
            url = value.get(key)
            if isinstance(url, str) and url:
                return _download(url, timeout, max_bytes=MAX_VIDEO_BYTES, media_name="video")
    return None


def _video_failure_message(response: dict[str, Any]) -> str:
    for value in _nested_values(response):
        if not isinstance(value, dict):
            continue
        for key in ("message", "error", "failure_reason", "failureReason"):
            message = value.get(key)
            if isinstance(message, str) and message.strip():
                return message.strip()
            if isinstance(message, dict):
                nested = message.get("message")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
    return "API-Zeno video task failed"


def _video_task_result(task_id: str, options: dict[str, Any]) -> bytes:
    deadline = time.monotonic() + options["poll_timeout"]
    while True:
        response = _get_request(
            f"video/generations/{urllib.parse.quote(task_id, safe='')}",
            options["timeout"],
        )
        data = _video_result_bytes(response, options["timeout"])
        if data is not None:
            return data
        status_value = _video_status(response)
        if status_value in {"failed", "failure", "error", "cancelled", "canceled", "rejected"}:
            raise ImageSkillError(_video_failure_message(response))
        if time.monotonic() >= deadline:
            raise ImageSkillError(f"Video task '{task_id}' did not finish within {options['poll_timeout']} seconds")
        time.sleep(min(options["poll_interval"], max(0.1, deadline - time.monotonic())))


def video(args: argparse.Namespace) -> int:
    payload, options = _video_payload(args)
    response = _json_request("video/generations", payload, options["timeout"])
    result = _video_result_bytes(response, options["timeout"])
    task_id = _video_task_id(response)
    if result is None:
        if not task_id:
            raise ImageSkillError("API-Zeno video response contains neither a task ID nor a video result")
        result = _video_task_result(task_id, options)
    output = Path(args.output).expanduser().resolve()
    if not output.suffix:
        output = output.with_suffix(".mp4")
    output = _available_path(output)
    _atomic_write_bytes(output, result)
    outputs = [str(output)]
    print(json.dumps({"outputs": outputs, "task_id": task_id}, indent=2))
    _save_state("video", options, outputs)
    return 0


def _add_shared_options(parser: argparse.ArgumentParser, include_quality: bool = True) -> None:
    parser.add_argument("--model", help="API-Zeno image model ID")
    parser.add_argument("--size", help="Output dimensions, for example 1024x1024")
    parser.add_argument("--resolution", choices=("1k", "2k", "4k"))
    parser.add_argument("--n", type=int, help="Number of images")
    if include_quality:
        parser.add_argument("--quality", choices=("auto", "low", "medium", "high"))
    else:
        parser.set_defaults(quality=None)
    parser.add_argument("--response-format", choices=("b64_json", "url"))
    parser.add_argument("--output-format", choices=("png", "jpeg", "webp"))
    parser.add_argument("--output", help="Local output path")
    parser.add_argument(
        "--timeout",
        type=int,
        help=f"Request timeout in seconds, maximum {DEFAULT_TIMEOUT_SECONDS}",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    configure_parser = subparsers.add_parser("configure", help="Save an API key from stdin")
    configure_parser.add_argument("--base-url", help="OpenAI-compatible base URL ending in /v1")
    configure_parser.set_defaults(handler=lambda args: configure(args.base_url))

    status_parser = subparsers.add_parser("status", help="Show non-secret configuration and state")
    status_parser.set_defaults(handler=lambda _args: status())

    models_parser = subparsers.add_parser("models", help="List supported image and video models")
    models_parser.set_defaults(handler=lambda _args: list_models())

    clear_parser = subparsers.add_parser("clear-key", help="Remove the locally saved API key")
    clear_parser.set_defaults(handler=lambda _args: clear_key())

    generate_parser = subparsers.add_parser("generate", help="Generate an image")
    generate_parser.add_argument("--prompt", required=True)
    _add_shared_options(generate_parser)
    generate_parser.set_defaults(handler=generate)

    edit_parser = subparsers.add_parser("edit", help="Edit one or more local images")
    edit_parser.add_argument("--image", action="append", required=True)
    edit_parser.add_argument("--mask")
    edit_parser.add_argument("--prompt", required=True)
    _add_shared_options(edit_parser)
    edit_parser.set_defaults(handler=edit)

    variation_parser = subparsers.add_parser("variation", help="Create a variation")
    variation_parser.add_argument("--image", required=True)
    _add_shared_options(variation_parser, include_quality=False)
    variation_parser.set_defaults(handler=variation)

    video_parser = subparsers.add_parser("video", help="Generate a video and save the completed result")
    video_parser.add_argument("--prompt", required=True)
    video_parser.add_argument("--model", required=True, help="API-Zeno video model ID")
    video_parser.add_argument("--image", help="Local image for image-to-video models")
    video_parser.add_argument("--image-url", help="Public image URL for image-to-video models")
    video_parser.add_argument("--size", help="Output dimensions when supported by the model")
    video_parser.add_argument("--resolution", help="Output resolution, for example 720p or 1080p")
    video_parser.add_argument("--duration", type=int, help="Video duration in seconds when supported")
    video_parser.add_argument("--aspect-ratio", help="Aspect ratio, for example 16:9")
    video_parser.add_argument("--output", required=True, help="Local output video path")
    video_parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_VIDEO_POLL_INTERVAL,
        help="Seconds between task status requests",
    )
    video_parser.add_argument(
        "--poll-timeout",
        type=int,
        default=DEFAULT_VIDEO_POLL_TIMEOUT,
        help="Maximum seconds to wait for the task",
    )
    video_parser.add_argument(
        "--timeout",
        type=int,
        help=f"HTTP timeout per request in seconds, maximum {DEFAULT_TIMEOUT_SECONDS}",
    )
    video_parser.set_defaults(handler=video)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (ImageSkillError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
