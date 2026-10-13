---
name: api-zeno-image
description: Generate or edit images and generate videos through API-Zeno's media APIs. Use when Codex needs an API-Zeno image or video model, local media output, image editing, image-to-video input, API key configuration, or workflow status.
---

# API-Zeno Media

Use the bundled CLI for deterministic requests, response decoding, secure local credential storage, and workflow state.

## Workflow

1. Ensure the user explicitly asked to run an image or video operation because it may incur API-Zeno usage charges.
2. Read [references/models.json](references/models.json) before choosing a model. Select a model that supports the requested operation.
3. Resolve the model and image layout explicitly. If either is missing for an image request, ask for both in one concise question and offer `gemini-3.1-flash-image-preview` with `1024x1024` as the default choice. For video requests, resolve the video model and ask for duration or aspect ratio only when the model requires it. Do not submit a request until the user chooses a configuration or says to use the default.
4. Check configuration without revealing secrets:

   ```powershell
   python scripts/api_zeno_image.py status
   ```

5. If no key is configured, ask the user to set `API_ZENO_KEY` outside the chat or run `configure` and enter the key through the hidden prompt. Never accept or pass a key as a command-line argument.
   After saving a key, remind the user to review its API-Zeno model allowlist and quota. Recommend an IP allowlist only for a stable public egress IP.
6. Run exactly one image request or one video task submission. API-Zeno performs its own upstream retrying; never resubmit a failed or timed-out task. Video status polling is allowed after a successful task submission.
7. On failure, report the API status, error code, message, and request ID when present. Ask for confirmation before retrying.
8. Confirm that every reported output path exists. Return absolute output paths to the user. Codex can retain a downloaded video as a local file even when the current chat surface does not provide inline video preview.

Read [references/api.md](references/api.md) for authentication, command options, response behavior, and error handling.

## Generate

Always provide an output path when an image file is expected.

```powershell
python scripts/api_zeno_image.py generate --prompt "A precise product photo of a white ceramic lamp" --model gpt-image-2 --size 1024x1024 --quality high --output C:\path\lamp.png
```

For the Gemini image models, omit `--quality`; they support text-to-image only.

## Generate A Video

Use the `video` command for API-Zeno's asynchronous video endpoint. The command submits one task, polls its status, downloads the completed video, and writes it to a local file.

```powershell
python scripts/api_zeno_image.py video --prompt "A slow product reveal on a clean studio set" --model grok-imagine-video-1.5 --duration 6 --aspect-ratio 16:9 --output C:\path\product.mp4
```

For image-to-video models, use a local image or a public image URL:

```powershell
python scripts/api_zeno_image.py video --prompt "Animate the product with a gentle camera move" --model grok-imagine-video-1.5 --image C:\path\product.png --output C:\path\product-motion.mp4
```

Read [references/video.md](references/video.md) for task states, model input modes, polling limits, and provider-specific fields.

## Edit

Use only local input images. Add `--image` more than once for multi-image input. Add a local PNG mask with `--mask` when required.

```powershell
python scripts/api_zeno_image.py edit --image C:\path\source.png --mask C:\path\mask.png --prompt "Replace the background with a white studio sweep" --model gpt-image-2 --size 1024x1024 --output C:\path\edited.png
```

## Create A Variation

```powershell
python scripts/api_zeno_image.py variation --image C:\path\source.png --model gpt-image-2 --size 1024x1024 --output C:\path\variation.png
```

## Continue A Workflow

The CLI records the last successful operation, non-secret options, and output paths. Inspect them with `status`. Reuse them only when they remain appropriate for the current request; never assume that a previous prompt or image input should be reused.
