from rest_framework.throttling import SimpleRateThrottle


class ConversationRateThrottle(SimpleRateThrottle):
    """Limits messages per conversation, whoever sends them (scope ai_conversation)."""

    scope = "ai_conversation"

    def get_cache_key(self, request, view):
        token = request.data.get("conversation") if hasattr(request, "data") else None
        if not token:
            return None
        return self.cache_format % {"scope": self.scope, "ident": str(token)[:64]}
