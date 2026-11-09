"""Builds the search index for products (research R5). Knowledge documents and images come later."""

import hashlib
import logging

from django.contrib.postgres.search import SearchVector
from django.db.models import TextField, Value
from django.utils import timezone

from apps.catalog.models import Product

from . import clients
from .models import IndexStatus, ProductIndex

logger = logging.getLogger(__name__)


def _category_names(category):
    names = []
    while category is not None and len(names) < 6:
        names += [category.name, category.name_sw]
        category = category.parent
    return [n for n in names if n]


def _attributes(product):
    attrs = product.attributes if isinstance(product.attributes, dict) else {}
    return [f"{key}: {value}" for key, value in attrs.items() if value not in (None, "")]


def _weighted_parts(product):
    """(A, B, C) text for the full-text vector: names, keywords, descriptions."""
    a = " ".join([product.name, *_category_names(product.category)])
    b = " ".join(filter(None, [product.tags.replace(",", " "), product.sku or "", *_attributes(product)]))
    c = " ".join(filter(None, [product.description, product.description_sw]))
    return a, b, c


def build_product_text(product):
    """What gets embedded: everything a shopper might describe the product by (no price/stock,
    which are read live at search time)."""
    lines = [
        product.name,
        " / ".join(_category_names(product.category)),
        product.tags,
        product.sku or "",
        ", ".join(_attributes(product)),
        product.description,
        product.description_sw,
    ]
    return "\n".join(line.strip() for line in lines if line and line.strip())


def content_hash(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _update_tsv(product):
    a, b, c = _weighted_parts(product)
    vector = (
        SearchVector(Value(a, output_field=TextField()), config="simple", weight="A")
        + SearchVector(Value(b, output_field=TextField()), config="simple", weight="B")
        + SearchVector(Value(c, output_field=TextField()), config="simple", weight="C")
    )
    ProductIndex.objects.filter(pk=product.pk).update(tsv=vector)


def index_product(product_id, force=False):
    """Create or refresh one product's index entry. Never raises for model errors: the entry is
    marked failed instead (the Celery task decides whether to retry)."""
    product = Product.objects.select_related("category__parent__parent").filter(pk=product_id).first()
    if product is None:
        ProductIndex.objects.filter(product_id=product_id).delete()
        return None
    text = build_product_text(product)
    digest = content_hash(text)
    entry, _ = ProductIndex.objects.get_or_create(product=product)
    _update_tsv(product)
    if not force and entry.status == IndexStatus.READY and entry.content_hash == digest:
        return entry
    entry.text = text
    try:
        entry.text_vec = clients.embed_texts([text])[0]
    except clients.ModelUnavailable as exc:
        logger.warning("Indexing product %s failed: %s", product_id, exc)
        entry.status = IndexStatus.FAILED
        entry.error = str(exc)[:1000]
        entry.save(update_fields=["text", "status", "error"])
        return entry
    entry.content_hash = digest
    entry.status = IndexStatus.READY
    entry.error = ""
    entry.indexed_at = timezone.now()
    entry.save(update_fields=["text", "text_vec", "content_hash", "status", "error", "indexed_at"])
    return entry
