import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.ai import indexing
from apps.ai.models import (
    ChatMessage, Conversation, IndexStatus, KnowledgeChunk, KnowledgeDocument, ProductIndex,
)

pytestmark = pytest.mark.django_db

BASE = "/api/ai/admin"
POLICY = b"Returns: you can return shoes within 7 days with the receipt."


@pytest.fixture(autouse=True)
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def admin(auth_client, admin_user):
    return auth_client(admin_user)


@pytest.fixture
def upload(admin, django_capture_on_commit_callbacks):
    def send(content=POLICY, name="returns.txt", content_type="text/plain", **fields):
        file = SimpleUploadedFile(name, content, content_type=content_type)
        with django_capture_on_commit_callbacks(execute=True):
            return admin.post(f"{BASE}/knowledge/", {"file": file, **fields}, format="multipart")

    return send


# --- knowledge documents -------------------------------------------------------------------------


def test_upload_indexes_the_document(admin, upload):
    res = upload(title="Returns policy", language="en")
    assert res.status_code == 201, res.data
    assert res.data["status"] == "processing"
    assert res.data["title"] == "Returns policy"

    document = KnowledgeDocument.objects.get(pk=res.data["id"])
    assert document.status == KnowledgeDocument.Status.READY  # the task ran on commit
    assert document.language == "en"
    assert document.chunk_count == 1

    detail = admin.get(f"{BASE}/knowledge/{document.pk}/").json()
    assert detail["status"] == "ready"
    listing = admin.get(f"{BASE}/knowledge/").json()
    assert listing["count"] == 1
    assert set(listing["results"][0]) >= {"id", "title", "language", "status", "error", "chunk_count",
                                          "created_at", "indexed_at"}


def test_title_defaults_to_the_file_name(upload, admin_user):
    res = upload(name="delivery-info.md", content_type="text/markdown")
    assert res.status_code == 201
    document = KnowledgeDocument.objects.get(pk=res.data["id"])
    assert document.title == "delivery-info"
    assert document.uploaded_by == admin_user


@pytest.mark.parametrize("name, content_type", [("tool.exe", "application/octet-stream"),
                                                ("photo.png", "image/png")])
def test_unsupported_files_are_rejected(upload, name, content_type):
    assert upload(name=name, content_type=content_type).status_code == 400
    assert not KnowledgeDocument.objects.exists()


def test_files_over_the_limit_are_rejected(upload, settings):
    settings.AI_UPLOAD_MAX_BYTES = 20
    res = upload()
    assert res.status_code == 400
    assert "10" in str(res.data) or "large" in str(res.data)


def test_delete_removes_the_document_its_chunks_and_file(admin, upload, media):
    document = KnowledgeDocument.objects.get(pk=upload().data["id"])
    path = document.file.path
    assert admin.delete(f"{BASE}/knowledge/{document.pk}/").status_code == 204
    assert not KnowledgeDocument.objects.exists()
    assert not KnowledgeChunk.objects.exists()
    import os
    assert not os.path.exists(path)


def test_reindex_one_document(admin, upload, embedder, django_capture_on_commit_callbacks):
    document_id = upload().data["id"]
    before = embedder.calls
    with django_capture_on_commit_callbacks(execute=True):
        res = admin.post(f"{BASE}/knowledge/{document_id}/reindex/")
    assert res.status_code == 202
    assert embedder.calls == before + 1
    assert KnowledgeDocument.objects.get(pk=document_id).status == "ready"


# --- index status and full reindex ---------------------------------------------------------------


def test_index_status_counts_and_failures(admin, shoe_catalog, upload, make_product, embedder):
    embedder.fail = True
    broken = make_product(name="Broken Lamp")
    indexing.index_product(broken.pk)
    embedder.fail = False
    make_product(name="Never Indexed")  # no index row yet: counted as pending
    upload()

    body = admin.get(f"{BASE}/index-status/").json()
    assert body["products"] == {"ready": 5, "pending": 1, "failed": 1}
    assert body["knowledge"] == {"ready": 1, "pending": 0, "failed": 0}
    assert body["images"] == {"ready": 0, "pending": 0, "failed": 0}
    [failure] = body["failures"]
    assert failure["kind"] == "product"
    assert failure["id"] == broken.pk
    assert failure["name"] == "Broken Lamp"
    assert "down" in failure["error"]


def test_reindex_everything(admin, shoe_catalog, upload, embedder, django_capture_on_commit_callbacks):
    upload()
    ProductIndex.objects.update(status=IndexStatus.FAILED)
    before = embedder.calls
    with django_capture_on_commit_callbacks(execute=True):
        res = admin.post(f"{BASE}/reindex/", {"products": True, "knowledge": True, "force": True}, format="json")
    assert res.status_code == 202
    assert ProductIndex.objects.filter(status=IndexStatus.READY).count() == 5
    assert embedder.calls - before == 5 + 1  # every product and the document were re-embedded


def test_reindex_knowledge_only(admin, shoe_catalog, upload, embedder, django_capture_on_commit_callbacks):
    upload()
    before = embedder.calls
    with django_capture_on_commit_callbacks(execute=True):
        res = admin.post(f"{BASE}/reindex/", {"products": False, "knowledge": True}, format="json")
    assert res.status_code == 202
    assert embedder.calls - before == 1


# --- conversations -------------------------------------------------------------------------------


@pytest.fixture
def handed_off(customer):
    conversation = Conversation.objects.create(user=customer, state=Conversation.State.NEEDS_HUMAN,
                                               handoff_reason="late order", language="en")
    ChatMessage.objects.create(conversation=conversation, role="user", text="Where is my order?")
    ChatMessage.objects.create(conversation=conversation, role="assistant", text="Let me check.",
                               tool_calls=[{"name": "order_status", "arguments": {}, "ok": True, "ms": 3}])
    Conversation.objects.create()  # an active guest chat
    return conversation


def test_conversation_list_filters_by_state(admin, handed_off):
    assert admin.get(f"{BASE}/conversations/").json()["count"] == 2
    body = admin.get(f"{BASE}/conversations/?state=needs_human").json()
    assert body["count"] == 1
    [row] = body["results"]
    assert row["id"] == str(handed_off.pk)
    assert row["handoff_reason"] == "late order"
    assert row["user"] == "amina"
    assert row["last_message"] == "Let me check."
    assert "token" not in row


def test_conversation_detail_has_the_messages(admin, handed_off):
    body = admin.get(f"{BASE}/conversations/{handed_off.pk}/").json()
    assert [m["text"] for m in body["messages"]] == ["Where is my order?", "Let me check."]
    assert body["messages"][1]["tool_calls"][0]["name"] == "order_status"
    assert body["messages"][0]["image"] is None


def test_release_returns_the_conversation_to_the_assistant(admin, handed_off, api_client, chat_model):
    res = admin.post(f"{BASE}/conversations/{handed_off.pk}/release/")
    assert res.status_code == 200
    assert res.data["state"] == "active"
    handed_off.refresh_from_db()
    assert handed_off.state == Conversation.State.ACTIVE
    assert handed_off.handoff_reason == ""


# --- permissions ---------------------------------------------------------------------------------


ENDPOINTS = [
    ("get", "/knowledge/"), ("post", "/knowledge/"), ("get", "/knowledge/{doc}/"),
    ("delete", "/knowledge/{doc}/"), ("post", "/knowledge/{doc}/reindex/"),
    ("get", "/index-status/"), ("post", "/reindex/"),
    ("get", "/conversations/"), ("get", "/conversations/{conv}/"), ("post", "/conversations/{conv}/release/"),
]


@pytest.mark.parametrize("who", ["guest", "customer", "rider"])
@pytest.mark.parametrize("method, path", ENDPOINTS)
def test_non_admins_are_refused(who, method, path, auth_client, customer, handed_off):
    document = KnowledgeDocument.objects.create(title="x", file="ai/knowledge/x.txt")
    if who == "guest":
        client = APIClient()
    elif who == "customer":
        client = auth_client(customer)
    else:
        client = auth_client(User.objects.create_user("rider1", password="pw", role=User.Role.RIDER))
    url = BASE + path.format(doc=document.pk, conv=handed_off.pk)
    res = getattr(client, method)(url)
    assert res.status_code in (401, 403)
    assert KnowledgeDocument.objects.filter(pk=document.pk).exists()
    handed_off.refresh_from_db()
    assert handed_off.state == Conversation.State.NEEDS_HUMAN
