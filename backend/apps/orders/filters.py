from django.core.exceptions import ValidationError
from django_filters import rest_framework as filters
from rest_framework.filters import SearchFilter

from .models import Order
from .services import normalize_phone


class OrderFilter(filters.FilterSet):
    placed_after = filters.DateFilter(field_name="placed_at", lookup_expr="date__gte")
    placed_before = filters.DateFilter(field_name="placed_at", lookup_expr="date__lt")
    paid = filters.BooleanFilter(field_name="paid_at", lookup_expr="isnull", exclude=True)

    class Meta:
        model = Order
        fields = ["status"]


class OrderSearchFilter(SearchFilter):
    """Also matches local phone numbers (0712...) against the stored E.164 form."""

    def get_search_terms(self, request):
        terms = []
        for term in super().get_search_terms(request):
            try:
                terms.append(normalize_phone(term))
            except ValidationError:
                terms.append(term)
        return terms
