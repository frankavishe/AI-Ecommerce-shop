from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AdminConversationViewSet, ChatView, IndexStatusView, KnowledgeDocumentViewSet, ReindexView

router = DefaultRouter()
router.include_root_view = False
router.register("knowledge", KnowledgeDocumentViewSet, basename="ai-knowledge")
router.register("conversations", AdminConversationViewSet, basename="ai-conversation")

urlpatterns = [
    path("chat/", ChatView.as_view(), name="ai-chat"),
    path("admin/index-status/", IndexStatusView.as_view(), name="ai-index-status"),
    path("admin/reindex/", ReindexView.as_view(), name="ai-reindex"),
    path("admin/", include(router.urls)),
]
