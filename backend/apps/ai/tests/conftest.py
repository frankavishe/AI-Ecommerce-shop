import pytest

# shoe_catalog, conversation and png_bytes live in backend/conftest.py (shared with apps/whatsapp).


@pytest.fixture
def embedder(fake_models):
    return fake_models["embedder"]
