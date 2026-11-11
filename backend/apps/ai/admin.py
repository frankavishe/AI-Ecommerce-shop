from django.contrib import admin

from .models import ChatMessage, Conversation, KnowledgeChunk, KnowledgeDocument, ProductImageIndex, ProductIndex


class ChatMessageInline(admin.TabularInline):
    model = ChatMessage
    extra = 0
    can_delete = False
    fields = ["created_at", "role", "text", "image", "error", "steps", "latency_ms"]
    readonly_fields = fields


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ["id", "channel", "state", "language", "user", "updated_at"]
    list_filter = ["state", "channel", "language"]
    search_fields = ["handoff_reason", "user__username"]
    readonly_fields = ["token", "created_at", "updated_at"]
    inlines = [ChatMessageInline]


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ["title", "language", "status", "chunk_count", "created_at", "indexed_at"]
    list_filter = ["status", "language"]
    readonly_fields = ["status", "error", "chunk_count", "indexed_at"]


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(admin.ModelAdmin):
    list_display = ["document", "position"]
    exclude = ["embedding", "tsv"]


@admin.register(ProductIndex)
class ProductIndexAdmin(admin.ModelAdmin):
    list_display = ["product", "status", "indexed_at"]
    list_filter = ["status"]
    exclude = ["text_vec", "tsv"]


@admin.register(ProductImageIndex)
class ProductImageIndexAdmin(admin.ModelAdmin):
    list_display = ["image", "product", "status", "indexed_at"]
    list_filter = ["status"]
    exclude = ["image_vec"]
