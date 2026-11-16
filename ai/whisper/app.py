"""faster-whisper speech-to-text service (specs/004-whatsapp-channel/contracts/speech-endpoint.md).

GET  /health                    -> {"status": "ok" | "loading", "model": ..., "device": ...}
POST /v1/audio/transcriptions   multipart `file` (+ `model`, `response_format`, optional `language`)
                                -> {"text": "...", "language": "sw", "duration": 3.4}

OpenAI-compatible, so the backend's `openai` client talks to it unchanged. The `model` field is
accepted and ignored: the model is the one loaded at startup (WHISPER_MODEL). Audio is decoded with
PyAV (a faster-whisper dependency), so no ffmpeg binary is needed.

Set WHISPER_API_KEY to require `Authorization: Bearer <key>` on the transcription route.
"""

import io
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from faster_whisper import WhisperModel

MODEL = os.environ.get("WHISPER_MODEL", "small")
DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
API_KEY = os.environ.get("WHISPER_API_KEY", "")
MAX_UPLOAD_BYTES = int(os.environ.get("WHISPER_MAX_UPLOAD_BYTES", 25 * 1024 * 1024))
BEAM_SIZE = int(os.environ.get("WHISPER_BEAM_SIZE", 5))

state = {}


@asynccontextmanager
async def lifespan(app):
    state["model"] = WhisperModel(MODEL, device=DEVICE, compute_type=COMPUTE_TYPE,
                                  download_root=os.environ.get("HF_HOME"))
    yield
    state.clear()


app = FastAPI(title="whisper", lifespan=lifespan)


def require_key(authorization: str | None = Header(default=None)):
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


@app.get("/health")
def health():
    status = "ok" if state.get("model") is not None else "loading"
    return {"status": status, "model": MODEL, "device": DEVICE, "compute_type": COMPUTE_TYPE}


@app.post("/v1/audio/transcriptions", dependencies=[Depends(require_key)])
def transcriptions(
    file: UploadFile = File(...),
    model: str = Form(default=""),  # noqa: ARG001 - accepted for OpenAI compatibility
    response_format: str = Form(default="json"),
    language: str | None = Form(default=None),
):
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Audio too large.")
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio file.")
    whisper = state.get("model")
    if whisper is None:
        raise HTTPException(status_code=503, detail="Model is loading.")
    try:
        segments, info = whisper.transcribe(io.BytesIO(data), language=language or None,
                                            beam_size=BEAM_SIZE, vad_filter=True)
        text = " ".join(segment.text.strip() for segment in segments).strip()
    except Exception as exc:  # undecodable audio and the like
        raise HTTPException(status_code=400, detail=f"Could not transcribe the audio: {exc}") from exc
    if response_format == "text":
        return text
    result = {"text": text}
    if response_format == "verbose_json":
        result.update(language=info.language, duration=round(float(info.duration), 2))
    return result
