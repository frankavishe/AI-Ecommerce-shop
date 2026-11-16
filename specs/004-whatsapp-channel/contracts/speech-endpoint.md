# Contract: Speech-to-text endpoint (self-hosted whisper)

Constitution III requires an OpenAI-compatible HTTP endpoint whose URL, model and key come from the
environment. This feature uses the OpenAI `audio/transcriptions` route.

## Settings

| Variable | Default (dev) | Notes |
|---|---|---|
| `AI_SPEECH_BASE_URL` | `http://localhost:8091/v1` | In docker: `http://whisper:8091/v1` (`AI_SPEECH_BASE_URL_DOCKER`) |
| `AI_SPEECH_MODEL` | `small` | prod: `large-v3` (or `large-v3-turbo`) |
| `AI_SPEECH_TIMEOUT` | `120` | seconds |
| `AI_API_KEY` | (shared) | Sent as the bearer token, as for the other model endpoints |

## Request

`POST {AI_SPEECH_BASE_URL}/audio/transcriptions`, `multipart/form-data`:

| Field | Value |
|---|---|
| `file` | the audio bytes (WhatsApp voice notes are `audio/ogg; codecs=opus`) |
| `model` | `AI_SPEECH_MODEL` |
| `response_format` | `verbose_json` |
| `language` | omitted (auto-detect) |

## Response (200)

```json
{"text": "mna simu za Samsung?", "language": "swahili", "duration": 3.4}
```

- `language` may be a name or an ISO code. The client maps `sw`/`swahili` → `sw` and
  `en`/`english` → `en`. Anything else keeps the conversation language.
- The client returns `{text, language, duration}`.
- Any connection error, timeout or non-2xx response raises `ModelUnavailable`.

## Sidecar `ai/whisper` (dev + prod)

- FastAPI + `faster-whisper`. The model is loaded once at startup:
  `WHISPER_MODEL` (`small` / `large-v3`), `WHISPER_DEVICE` (`cpu` / `cuda`) and
  `WHISPER_COMPUTE_TYPE` (`int8` / `float16`).
- It implements only the route above, plus `GET /health`. It decodes audio with PyAV, which
  faster-whisper already depends on, so it needs no ffmpeg binary.
- Compose: the `whisper` service is under profile `ai` on port 8091, like `siglip`. The GPU compose
  file gets the same service with `WHISPER_DEVICE=cuda`.
- It can be replaced without code changes by any server that implements the same route (vLLM
  Whisper, speaches).
