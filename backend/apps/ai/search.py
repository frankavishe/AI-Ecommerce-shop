"""Hybrid search: pgvector cosine + Postgres full-text, fused with Reciprocal Rank Fusion (R3)."""

import logging
import re

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F, Q
from pgvector.django import CosineDistance

from apps.catalog.models import Category, Product

from . import clients

logger = logging.getLogger(__name__)

CANDIDATES = 50


def rrf(*ranked_lists, k=60):
    """Fuse ranked id lists; earlier lists win ties."""
    scores, first_seen = {}, {}
    for list_no, ranked in enumerate(ranked_lists):
        for rank, item in enumerate(ranked):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank + 1)
            first_seen.setdefault(item, (list_no, rank))
    return sorted(scores, key=lambda item: (-scores[item], first_seen[item]))


def keyword_query(text):
    """OR of prefix terms, so "red shoes under 50000" still matches "Red Sneakers"."""
    terms = [t for t in re.findall(r"\w+", (text or "").lower()) if len(t) >= 2]
    terms = list(dict.fromkeys(terms))[:16]
    if not terms:
        return None
    return SearchQuery(" | ".join(f"{t}:*" for t in terms), config="simple", search_type="raw")


def category_ids(name_or_slug):
    """The matching category (by slug, English or Swahili name) and all its subcategories."""
    if not name_or_slug:
        return None
    value = str(name_or_slug).strip()
    roots = list(Category.objects.filter(
        Q(slug__iexact=value) | Q(name__iexact=value) | Q(name_sw__iexact=value)
    ).values_list("pk", flat=True))
    if not roots:
        return None
    ids, frontier = set(roots), roots
    while frontier:
        frontier = [pk for pk in Category.objects.filter(parent_id__in=frontier).values_list("pk", flat=True)
                    if pk not in ids]
        ids.update(frontier)
    return ids


def _sellable(min_price=None, max_price=None, category=None, in_stock_only=True):
    qs = Product.objects.filter(is_active=True)
    if in_stock_only:
        qs = qs.filter(stock__gt=0)
    if min_price is not None:
        qs = qs.filter(price__gte=min_price)
    if max_price is not None:
        qs = qs.filter(price__lte=max_price)
    ids = category_ids(category)
    if ids:  # an unknown category name is ignored rather than hiding everything
        qs = qs.filter(category_id__in=ids)
    return qs


def _vector_ids(qs, query):
    try:
        vector = clients.embed_texts([query])[0]
    except clients.ModelUnavailable as exc:
        logger.warning("Vector search skipped: %s", exc)
        return []
    max_distance = 1.0 - settings.AI_PRODUCT_MIN_SIMILARITY
    return list(
        qs.filter(ai_index__text_vec__isnull=False)
        .annotate(distance=CosineDistance("ai_index__text_vec", vector))
        .filter(distance__lte=max_distance)
        .order_by("distance", "pk")
        .values_list("pk", flat=True)[:CANDIDATES]
    )


def _keyword_ids(qs, query):
    tsquery = keyword_query(query)
    if tsquery is None:
        return []
    return list(
        qs.filter(ai_index__tsv=tsquery)
        .annotate(rank=SearchRank(F("ai_index__tsv"), tsquery))
        .order_by("-rank", "pk")
        .values_list("pk", flat=True)[:CANDIDATES]
    )


def hybrid_products(query, min_price=None, max_price=None, category=None, in_stock_only=True, limit=8):
    """Products for a shopper query, best first. Prices/stock come from the live Product rows."""
    qs = _sellable(min_price, max_price, category, in_stock_only)
    query = (query or "").strip()
    if not query:
        return list(qs.select_related("category").order_by("-created_at")[:limit])
    ids = rrf(_vector_ids(qs, query), _keyword_ids(qs, query))[:limit]
    products = Product.objects.select_related("category").prefetch_related("images").in_bulk(ids)
    return [products[pk] for pk in ids if pk in products]
