# Contract: model endpoints (configuration)

| Env var | Dev (Ollama, CPU) | Prod (GPU box) | Used for |
|---|---|---|---|
| `AI_CHAT_BASE_URL` | `http://localhost:11434/v1` | `http://gpu:8000/v1` (vLLM) | chat + tool calls |
| `AI_CHAT_MODEL` | `qwen3:4b-instruct-2507-q4_K_M` (not plain `qwen3:4b`, the thinking build) | `Qwen/Qwen3-VL-8B-Instruct` | |
| `AI_CHAT_NO_THINK` | `true` | `false` | appends `/no_think` (R2) |
| `AI_VISION_BASE_URL` | = chat URL | = chat URL | photo captions |
| `AI_VISION_MODEL` | `qwen2.5vl:3b` | `Qwen/Qwen3-VL-8B-Instruct` | |
| `AI_EMBED_BASE_URL` | `http://localhost:11434/v1` | `http://gpu:8080/v1` (TEI) | text embeddings |
| `AI_EMBED_MODEL` | `bge-m3` | `BAAI/bge-m3` | must output 1024 dims |
| `AI_IMAGE_EMBED_URL` | `http://localhost:8090` | `http://gpu:8090` | SigLIP service |
| `AI_API_KEY` | `ollama` (ignored) | shared secret | Bearer for all of the above |
| `AI_CHAT_TIMEOUT` | `90` | `20` | seconds per request overall |
| `AI_MAX_STEPS` | `6` | `6` | |

Inside docker-compose, the dev URLs use `host.docker.internal` instead of `localhost`.

Calls used:
- `POST {AI_CHAT_BASE_URL}/chat/completions` with `tools`, `tool_choice="auto"`, `temperature=0.2`.
- `POST {AI_VISION_BASE_URL}/chat/completions` with an `image_url` data-URI part.
- `POST {AI_EMBED_BASE_URL}/embeddings` with `input: [..]` batched (≤ 32).
- SigLIP service (`ai/siglip/app.py`):
  - `GET /health` → `{"status":"ok","model":"google/siglip2-base-patch16-224","dim":768}`
  - `POST /embed/image` (multipart `file`) → `{"embedding":[768 floats]}` (L2-normalised)
  - `POST /embed/text` `{"text": "..."}` → `{"embedding":[768 floats]}` (kept for future use)
  - Optional `Authorization: Bearer $AI_API_KEY` check when `SIGLIP_API_KEY` is set.

At startup, `manage.py ai_check` pings every endpoint and reports the model, the embedding dimension
match, tool-call support (a one-step tool-call probe) and latency.
