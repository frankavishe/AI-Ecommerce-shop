"""SigLIP2 image/text embedding service (specs/003-ai-core/contracts/model-endpoints.md).

GET  /health       -> {"status": "ok", "model": ..., "dim": 768}
POST /embed/image  multipart `file` -> {"embedding": [768 floats]}, L2-normalised
POST /embed/text   {"text": "..."}  -> {"embedding": [768 floats]}, L2-normalised

Set SIGLIP_API_KEY to require `Authorization: Bearer <key>` on the embed endpoints.
"""

import io
import os
from contextlib import asynccontextmanager

import torch
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field
from transformers import AutoModel, AutoProcessor

MODEL_ID = os.environ.get("SIGLIP_MODEL", "google/siglip2-base-patch16-224")
API_KEY = os.environ.get("SIGLIP_API_KEY", "")
MAX_UPLOAD_BYTES = int(os.environ.get("SIGLIP_MAX_UPLOAD_BYTES", 10 * 1024 * 1024))
torch.set_num_threads(int(os.environ.get("SIGLIP_THREADS", os.cpu_count() or 4)))

state = {}


@asynccontextmanager
async def lifespan(app):
    state["processor"] = AutoProcessor.from_pretrained(MODEL_ID)
    state["model"] = AutoModel.from_pretrained(MODEL_ID).eval()
    yield
    state.clear()


app = FastAPI(title="siglip", lifespan=lifespan)


def require_key(authorization: str | None = Header(default=None)):
    if API_KEY and authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


def _vector(features):
    return torch.nn.functional.normalize(features, dim=-1)[0].tolist()


@app.get("/health")
def health():
    model = state.get("model")
    if model is None:
        return {"status": "loading", "model": MODEL_ID, "dim": None}
    return {"status": "ok", "model": MODEL_ID, "dim": model.config.vision_config.hidden_size}


@app.post("/embed/image", dependencies=[Depends(require_key)])
def embed_image(file: UploadFile = File(...)):
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image too large.")
    try:
        image = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise HTTPException(status_code=400, detail="Not a readable image.") from exc
    inputs = state["processor"](images=[image], return_tensors="pt")
    with torch.no_grad():
        features = state["model"].get_image_features(**inputs)
    return {"embedding": _vector(features)}


class TextIn(BaseModel):
    text: str = Field(min_length=1, max_length=500)


@app.post("/embed/text", dependencies=[Depends(require_key)])
def embed_text(body: TextIn):
    # SigLIP2 was trained on lowercased text padded to 64 tokens.
    inputs = state["processor"](text=[body.text.lower()], padding="max_length", max_length=64,
                                truncation=True, return_tensors="pt")
    with torch.no_grad():
        features = state["model"].get_text_features(**inputs)
    return {"embedding": _vector(features)}
