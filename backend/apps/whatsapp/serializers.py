from rest_framework import serializers

from .models import WhatsAppOutboundMessage


class LinkStatusSerializer(serializers.Serializer):
    linked = serializers.BooleanField()
    number = serializers.CharField(allow_null=True, help_text="The linked number, masked: +255 742 *** 331.")
    linked_at = serializers.DateTimeField(allow_null=True)
    business_number = serializers.CharField(help_text="The shop's WhatsApp number (E.164).")


class LinkCodeSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="One-time code, e.g. LINK-7KQ4XM. Valid for 10 minutes.")
    expires_at = serializers.DateTimeField()
    wa_link = serializers.URLField(help_text="wa.me link that opens WhatsApp with the code typed in.")


class DetailSerializer(serializers.Serializer):
    detail = serializers.CharField()


# --- Staff tools (contracts/admin-api.md) ----------------------------------------------------------

STAFF_TEXT_MAX = 4096 * 3
STAFF_TEMPLATES = ["follow_up"]


class StaffReplySerializer(serializers.Serializer):
    text = serializers.CharField(required=False, max_length=STAFF_TEXT_MAX, trim_whitespace=True,
                                 help_text="Free text; only while the 24-hour window is open.")
    template = serializers.ChoiceField(choices=STAFF_TEMPLATES, required=False,
                                       help_text="An approved template; can be sent at any time.")

    def validate(self, data):
        if bool(data.get("text")) == bool(data.get("template")):
            raise serializers.ValidationError("Send either a non-empty text or a template.")
        return data


class StaffReplyResultSerializer(serializers.Serializer):
    outbound_id = serializers.IntegerField()
    status = serializers.CharField()


class WindowClosedSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField()
    templates = serializers.ListField(child=serializers.CharField())


class CodeSerializer(serializers.Serializer):
    code = serializers.CharField()
    detail = serializers.CharField(required=False)


class OutboundSerializer(serializers.ModelSerializer):
    contact_number = serializers.CharField(source="contact.phone", read_only=True)
    order_number = serializers.CharField(read_only=True, allow_null=True, default=None)

    class Meta:
        model = WhatsAppOutboundMessage
        fields = ["id", "contact_number", "kind", "trigger", "text", "status", "error_code", "error",
                  "attempts", "created_at", "order_number"]
