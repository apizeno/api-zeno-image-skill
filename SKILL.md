---
name: api-zeno-image
description: Generate, edit, or create variations of images through the API-Zeno OpenAI-compatible image API. Use when Codex needs to create an image with an API-Zeno model, transform a local image from a prompt, apply a local mask, make a variation, save API image results locally, configure an API-Zeno key, or resume the last API-Zeno image workflow.
---

# API-Zeno Image

Use the bundled CLI for deterministic requests, response decoding, secure local credential storage, and workflow state.

## Workflow

1. Ensure the user explicitly asked to run an image operation because it may incur API-Zeno usage charges.
2. Read [references/models.json](references/models.json) before choosing a model. Select a model that supports the requested operation.
3. Resolve the model and layout explicitly. If either is missing, ask for both in one concise question and offer `gpt-image-2` with `1024x1024` as the default choice. Do not submit a request until the user chooses a configuration or says to use the default.
4. Check configuration without revealing secrets:

   ```powershell
   python scripts/api_zeno_image.py status
   ```

5. If no key is configured, ask the user to set `API_ZENO_KEY` outside the chat or run `configure` and enter the key through the hidden prompt. Never accept or pass a key as a command-line argument.
   After saving a key, remind the user to review its API-Zeno model allowlist and quota. Recommend an IP allowlist only for a stable public egress IP.
6. Run exactly one API request. API-Zeno performs its own upstream retrying; never add automatic client retries.
7. On failure, report the API status, error code, message, and request ID when present. Ask for confirmation before retrying.
8. Confirm that every reported output path exists. Return absolute output paths to the user.

Read [references/api.md](references/api.md) for authentication, command options, response behavior, and error handling.

## Generate

Always provide an output path when an image file is expected.

```powershell
python scripts/api_zeno_image.py generate --prompt "A precise product photo of a white ceramic lamp" --model gpt-image-2 --size 1024x1024 --quality high --output C:\path\lamp.png
```

For the Gemini image models, omit `--quality`; they support text-to-image only.

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
