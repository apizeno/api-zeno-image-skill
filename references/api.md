# API-Zeno Image API

## Connection

- Base URL: `https://api-zeno.com/v1`
- Key environment variable: `API_ZENO_KEY`
- Base URL override: `API_ZENO_BASE_URL`
- Optional configuration-directory override: `API_ZENO_CONFIG_DIR`
- Authentication header: `Authorization: Bearer <key>`
- Generate: `POST /images/generations` with JSON
- Edit: `POST /images/edits` with multipart form data
- Variation: `POST /images/variations` with multipart form data

The environment variables take precedence over saved configuration. `configure` reads the key from a hidden stdin prompt and stores it in the current user's configuration directory. The CLI never accepts a key argument and `status` never prints a key.

## Commands

```text
api_zeno_image.py configure [--base-url URL]
api_zeno_image.py status
api_zeno_image.py models
api_zeno_image.py clear-key
api_zeno_image.py generate --prompt TEXT [options]
api_zeno_image.py edit --image FILE [--image FILE ...] --prompt TEXT [options]
api_zeno_image.py variation --image FILE [options]
api_zeno_image.py video --prompt TEXT --model MODEL --output FILE [options]
```

Shared request options include `--model`, `--size`, `--resolution`, `--n`, `--response-format`, `--output-format`, `--output`, and `--timeout`. Generation and edit also accept `--quality`. The edit command accepts `--mask`. Only pass `--quality` or `--output-format` to models that advertise those capabilities in `models.json`.

Use `--response-format b64_json` for stable local saving. URL responses are supported, but downloads reject non-HTTP schemes, credentials in URLs, redirects to unsafe hosts, and loopback, private, link-local, reserved, multicast, or unspecified addresses.

When `--output` is given and the API returns multiple items, the CLI adds `-1`, `-2`, and so on before the extension. Current API-Zeno model bindings allow `n=1`.

## State And Credentials

On Windows, files live under `%APPDATA%\api-zeno-image` unless `API_ZENO_CONFIG_DIR` is set. On Linux and macOS, they live under `$XDG_CONFIG_HOME/api-zeno-image` or `~/.config/api-zeno-image`.

- `credentials.json` contains the saved key and optional base URL.
- `state.json` contains only non-secret details from the last successful request.

Writes use a temporary file plus atomic replacement. The CLI applies owner-only file permissions where the operating system supports them and also attempts a current-user-only ACL on Windows.

After saving a key, review its API-Zeno model allowlist and quota. Use an IP allowlist only when the machine has a stable public egress IP.

## Failure Handling

API-Zeno authentication failures can include `missing_api_key`, `key_disabled`, `key_expired`, `ip_not_allowed`, and `key_quota_exceeded`. Preserve the server's error code and request ID in user-facing reports.

The CLI intentionally sends each invocation once. Do not wrap it in an automatic retry loop. Ask the user before retrying an unsuccessful request.

## Video Tasks

Video generation uses `POST /video/generations` and then polls `GET /video/generations/{task_id}` until a completed result is returned. The CLI accepts `--duration`, `--aspect-ratio`, `--resolution`, `--size`, `--image`, and `--image-url` when the selected upstream supports them. Set `--poll-timeout` to control the maximum wait; the default is 1,800 seconds and the maximum is 86,400 seconds. Video URLs are downloaded with a 500 MiB limit and saved to the required `--output` path.
