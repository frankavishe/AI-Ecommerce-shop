from rest_framework import serializers


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
