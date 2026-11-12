"""AI assistant data (specs/003-ai-core/data-model.md).

Vector sizes are fixed by migration 0001: text 1024 (bge-m3), image 768 (siglip2-base).
"""

import secrets
import uuid

from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from pgvector.django import HnswIndex, VectorField

TEXT_DIM = 1024
IMAGE_DIM = 768


def new_conversation_token():
    return secrets.token_urlsafe(32)


class Language(models.TextChoices):
    SWAHILI = "sw", "Swahili"
    ENGLISH = "en", "English"


class IndexStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    READY = "ready", "Ready"
    FAILED = "failed", "Failed"


class Conversation(models.Model):
    class Channel(models.TextChoices):
        API = "api", "API"
        WHATSAPP = "whatsapp", "WhatsApp"

    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        NEEDS_HUMAN = "needs_human", "Needs a human"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    token = models.CharField(max_length=64, unique=True, default=new_conversation_token)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE,
        related_name="ai_conversations",
    )
    cart = models.ForeignKey(
        "orders.Cart", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    channel = models.CharField(max_length=16, choices=Channel.choices, default=Channel.API)
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.SWAHILI)
    state = models.CharField(max_length=16, choices=State.choices, default=State.ACTIVE)
    handoff_reason = models.TextField(blank=True)
    checkout_details = models.JSONField(default=dict, blank=True)
    pending_checkout_at = models.DateTimeField(null=True, blank=True)
    last_order = models.ForeignKey(
        "orders.Order", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["state", "updated_at"])]
        ordering = ["-updated_at"]

    def __str__(self):
        return f"Conversation {self.id}"


class ChatMessage(models.Model):
    class Role(models.TextChoices):
        USER = "user", "User"
        ASSISTANT = "assistant", "Assistant"
        SYSTEM_NOTE = "system_note", "System note"
        STAFF = "staff", "Staff"

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    role = models.CharField(max_length=16, choices=Role.choices)
    text = models.TextField(blank=True)
    image = models.ImageField(upload_to="ai/chat/%Y/%m/", null=True, blank=True)
    image_deleted = models.BooleanField(default=False)
    language = models.CharField(max_length=2, choices=Language.choices, default=Language.SWAHILI)
    tool_calls = models.JSONField(default=list, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    steps = models.PositiveSmallIntegerField(default=0)
    latency_ms = models.PositiveIntegerField(null=True, blank=True)
    error = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]


class KnowledgeDocument(models.Model):
    class DocLanguage(models.TextChoices):
        SWAHILI = "sw", "Swahili"
        ENGLISH = "en", "English"
        MIXED = "mixed", "Mixed"

    class Status(models.TextChoices):
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    title = models.CharField(max_length=200)
    file = models.FileField(upload_to="ai/knowledge/")
    content_type = models.CharField(max_length=100, blank=True)
    language = models.CharField(max_length=5, choices=DocLanguage.choices, default=DocLanguage.MIXED)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PROCESSING)
    error = models.TextField(blank=True)
    chunk_count = models.PositiveIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    indexed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.title


class KnowledgeChunk(models.Model):
    document = models.ForeignKey(KnowledgeDocument, on_delete=models.CASCADE, related_name="chunks")
    position = models.PositiveIntegerField()
    text = models.TextField()
    embedding = VectorField(dimensions=TEXT_DIM)
    tsv = SearchVectorField(null=True)

    class Meta:
        ordering = ["document", "position"]
        constraints = [
            models.UniqueConstraint(fields=["document", "position"], name="ai_chunk_document_position")
        ]
        indexes = [
            HnswIndex(name="ai_chunk_embedding_hnsw", fields=["embedding"],
                      m=16, ef_construction=64, opclasses=["vector_cosine_ops"]),
            GinIndex(name="ai_chunk_tsv_gin", fields=["tsv"]),
        ]


class ProductIndex(models.Model):
    product = models.OneToOneField(
        "catalog.Product", primary_key=True, on_delete=models.CASCADE, related_name="ai_index"
    )
    text = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    text_vec = VectorField(dimensions=TEXT_DIM, null=True, blank=True)
    tsv = SearchVectorField(null=True)
    status = models.CharField(max_length=8, choices=IndexStatus.choices, default=IndexStatus.PENDING)
    error = models.TextField(blank=True)
    indexed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            HnswIndex(name="ai_product_text_vec_hnsw", fields=["text_vec"],
                      m=16, ef_construction=64, opclasses=["vector_cosine_ops"]),
            GinIndex(name="ai_product_tsv_gin", fields=["tsv"]),
        ]


class ProductImageIndex(models.Model):
    image = models.OneToOneField(
        "catalog.ProductImage", primary_key=True, on_delete=models.CASCADE, related_name="ai_index"
    )
    product = models.ForeignKey("catalog.Product", on_delete=models.CASCADE, related_name="+")
    image_vec = VectorField(dimensions=IMAGE_DIM, null=True, blank=True)
    status = models.CharField(max_length=8, choices=IndexStatus.choices, default=IndexStatus.PENDING)
    error = models.TextField(blank=True)
    indexed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            HnswIndex(name="ai_image_vec_hnsw", fields=["image_vec"],
                      m=16, ef_construction=64, opclasses=["vector_cosine_ops"]),
        ]
