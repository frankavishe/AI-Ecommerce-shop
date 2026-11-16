import hashlib
import hmac

import psycopg
import pytest
from django.db import connection

from apps.whatsapp.graph import GraphError, classify_error
from apps.whatsapp.locks import advisory_lock
from apps.whatsapp.outbound import split_text
from apps.whatsapp.signature import verify_signature, verify_token


def sign(body, secret="test-secret"):
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# --- verify_signature / verify_token --------------------------------------------------------------


def test_signature_ok():
    body = b'{"object":"whatsapp_business_account"}'
    assert verify_signature(body, sign(body))


@pytest.mark.parametrize("header", [
    None, "", "sha256=deadbeef", "sha1=" + "0" * 40,
])
def test_signature_rejected(header):
    assert not verify_signature(b"{}", header)


def test_signature_wrong_body():
    assert not verify_signature(b'{"a":2}', sign(b'{"a":1}'))


def test_signature_without_prefix_rejected():
    body = b"{}"
    assert not verify_signature(body, sign(body)[len("sha256="):])


def test_signature_empty_secret_always_fails(settings):
    settings.WHATSAPP_APP_SECRET = ""
    body = b"{}"
    assert not verify_signature(body, sign(body, secret=""))


def test_verify_token(settings):
    assert verify_token("test-verify")
    assert not verify_token("nope")
    assert not verify_token(None)
    settings.WHATSAPP_VERIFY_TOKEN = ""
    assert not verify_token("")


# --- split_text -----------------------------------------------------------------------------------


def test_split_short_text_is_one_chunk():
    assert split_text("Habari!", limit=50) == ["Habari!"]


def test_split_prefers_blank_line():
    text = "First paragraph here.\n\nSecond paragraph here."
    assert split_text(text, limit=30) == ["First paragraph here.", "Second paragraph here."]


def test_split_then_newline():
    text = "Line one is here\nLine two is here too"
    assert split_text(text, limit=25) == ["Line one is here", "Line two is here too"]


def test_split_then_sentence_end():
    text = "One sentence here. Another sentence follows"
    assert split_text(text, limit=30) == ["One sentence here.", "Another sentence follows"]


def test_split_then_whitespace():
    text = "aaaa bbbb cccc dddd"
    chunks = split_text(text, limit=10)
    assert all(len(c) <= 10 for c in chunks)
    assert " ".join(chunks) == text


def test_split_never_breaks_url_or_number_or_price():
    url = "https://pay.test/checkout/abcdefghijk"
    text = f"Lipa hapa {url} jumla 50,000 TZS asante sana"
    for limit in range(len(url), len(text)):
        chunks = split_text(text, limit=limit)
        joined = " ".join(chunks)
        assert url in chunks[0] or any(url in c for c in chunks)
        assert any("50,000 TZS" in c for c in chunks), (limit, chunks)
        assert joined.split() == text.split()


def test_split_keeps_every_chunk_under_limit():
    text = ("Viatu vyekundu bei 45,000 TZS. " * 300).strip()
    chunks = split_text(text, limit=4096)
    assert len(chunks) > 1
    assert all(len(c) <= 4096 for c in chunks)
    assert " ".join(chunks).split() == text.split()


# --- classify_error -------------------------------------------------------------------------------


@pytest.mark.parametrize("code", [1, 2, 4, 80007, 130429, 131016, 131048, 131056])
def test_transient_codes(code):
    assert classify_error(code=code, http_status=400).transient


@pytest.mark.parametrize("code", [100, 131026, 131047, 131051, 132000, 132015, 190])
def test_permanent_codes(code):
    assert not classify_error(code=code, http_status=400).transient


def test_http_5xx_and_network_are_transient():
    assert classify_error(code=None, http_status=503).transient
    assert classify_error(code=None, http_status=None).transient


def test_graph_error_fields():
    error = classify_error(code=131026, title="Undeliverable", http_status=400)
    assert isinstance(error, GraphError)
    assert (error.code, error.title, error.http_status) == (131026, "Undeliverable", 400)


# --- advisory_lock --------------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_advisory_lock_blocks_another_connection(settings):
    params = connection.get_connection_params()
    other = psycopg.connect(
        host=params.get("host"), port=params.get("port"), user=params.get("user"),
        password=params.get("password"), dbname=params.get("dbname"), autocommit=True,
    )
    try:
        with advisory_lock(42) as got:
            assert got
            held = other.execute("SELECT pg_try_advisory_lock(%s, %s)",
                                 (settings.WHATSAPP_LOCK_NAMESPACE, 42)).fetchone()[0]
            assert held is False
        free = other.execute("SELECT pg_try_advisory_lock(%s, %s)",
                             (settings.WHATSAPP_LOCK_NAMESPACE, 42)).fetchone()[0]
        assert free is True
        with advisory_lock(42) as got:
            assert got is False
        other.execute("SELECT pg_advisory_unlock(%s, %s)", (settings.WHATSAPP_LOCK_NAMESPACE, 42))
    finally:
        other.close()
