# API-Zeno Video Tasks

API-Zeno exposes video generation as an asynchronous task API:

- Submit: `POST https://api-zeno.com/v1/video/generations`
- Poll: `GET https://api-zeno.com/v1/video/generations/{task_id}`
- Authentication: `Authorization: Bearer <API_ZENO_KEY>`

The CLI submits a task once and polls only the returned task. Polling is required for asynchronous completion and is not a second submission. A failed or timed-out task must be reported before asking whether the user wants to submit another task.

## Model Inputs

Read `references/models.json` before choosing a model. The public API-Zeno catalog currently lists:

- `grok-imagine-video`: text-to-video
- `grok-imagine-video-1.5`: text-to-video and image-to-video

The CLI sends a local `--image` or public `--image-url` as the `image_url` request field. Local images are encoded as a data URL so the API can receive them without a separate upload endpoint. Use a public HTTPS URL when the upstream model does not accept data URLs.

The API documentation states that task fields depend on the configured upstream. The CLI therefore sends only `model`, `prompt`, and explicitly supplied common fields (`image_url`, `size`, `resolution`, `duration`, and `aspect_ratio`). If an upstream requires a different field name, update the model adapter and its tests together.

## Results

The CLI accepts common task response shapes, including a top-level or nested `task_id`/`id`, `status`, `video_url`, `output_url`, `url`, `b64_video`, `video_base64`, and `base64`. It downloads URL results only from public HTTP(S) hosts and limits video downloads to 500 MiB. Results are saved with an `.mp4` suffix when the requested output path has no suffix; existing files receive `-1`, `-2`, and later suffixes.

The current Codex chat surface may not render a local video inline. Always return the absolute output path so the user can open or download the file from the workspace.
