"""Builds the search indexes: products (research R5) and knowledge documents (R6)."""

import hashlib
import io
import logging
import re

from django.contrib.postgres.search import SearchVector
from django.db import transaction
from django.db.models import TextField, Value
from django.utils import timezone

from apps.catalog.models import Product

from . import clients
from .models import IndexStatus, KnowledgeChunk, KnowledgeDocument, ProductIndex

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


# --- Knowledge documents ------------------------------------------------------------------------

DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _kind(content_type, name):
    content_type = (content_type or "").lower()
    name = (name or "").lower()
    if content_type == "application/pdf" or name.endswith(".pdf"):
        return "pdf"
    if content_type == DOCX_TYPE or name.endswith(".docx"):
        return "docx"
    return "text"


def extract_text(file, content_type="", name=""):
    """Plain text from a PDF, DOCX or text/markdown file (a file object or bytes)."""
    data = file if isinstance(file, bytes) else file.read()
    kind = _kind(content_type, name)
    if kind == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
    if kind == "docx":
        import docx

        document = docx.Document(io.BytesIO(data))
        return "\n\n".join(p.text.strip() for p in document.paragraphs if p.text.strip())
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


_SENTENCE_END = re.compile(r"[.!?](\s|$)|\n")


def _clean(text):
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _cut_point(window, minimum):
    """Where to end a chunk inside `window`: the last paragraph break, else the last sentence end,
    else the last space, as long as it falls after `minimum`; otherwise the full window."""
    cut = window.rfind("\n\n")
    if cut >= minimum:
        return cut
    ends = [m.end() for m in _SENTENCE_END.finditer(window) if m.end() >= minimum]
    if ends:
        return ends[-1]
    cut = window.rfind(" ")
    return cut if cut >= minimum else len(window)


def chunk_text(text, size=1800, overlap=300):
    """Split text into chunks of at most `size` characters that overlap by about `overlap`,
    preferring paragraph and then sentence boundaries."""
    text = _clean(text)
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            end = start + _cut_point(text[start:end], size // 2)
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        next_start = max(end - overlap, start + 1)
        space = text.find(" ", next_start, end)  # start the overlap on a word boundary
        if space != -1 and space - next_start < 40:
            next_start = space + 1
        start = next_start
    return chunks


def _fail_document(document, error):
    logger.warning("Indexing knowledge document %s failed: %s", document.pk, error)
    document.status = KnowledgeDocument.Status.FAILED
    document.error = str(error)[:1000]
    document.chunk_count = 0
    document.save(update_fields=["status", "error", "chunk_count"])
    return document


def index_document(document_id):
    """Extract, chunk, embed and store a knowledge document. Never raises: failures are recorded
    on the document."""
    document = KnowledgeDocument.objects.filter(pk=document_id).first()
    if document is None:
        return None
    try:
        with document.file.open("rb") as handle:
            text = extract_text(handle, document.content_type, document.file.name)
    except Exception as exc:  # noqa: BLE001 - any parser error means the file can't be read
        with transaction.atomic():
            document.chunks.all().delete()
        return _fail_document(document, f"could not read the file: {exc}")
    chunks = chunk_text(text)
    if not chunks:
        with transaction.atomic():
            document.chunks.all().delete()
        return _fail_document(document, "no extractable text")
    try:
        vectors = clients.embed_texts(chunks)
    except clients.ModelUnavailable as exc:
        with transaction.atomic():
            document.chunks.all().delete()
        document.retryable = True  # the model server was down; the Celery task retries
        return _fail_document(document, exc)
    with transaction.atomic():
        document.chunks.all().delete()
        KnowledgeChunk.objects.bulk_create([
            KnowledgeChunk(document=document, position=n, text=chunk, embedding=vector)
            for n, (chunk, vector) in enumerate(zip(chunks, vectors))
        ])
        document.chunks.update(tsv=SearchVector("text", config="simple"))
        document.status = KnowledgeDocument.Status.READY
        document.error = ""
        document.chunk_count = len(chunks)
        document.indexed_at = timezone.now()
        document.save(update_fields=["status", "error", "chunk_count", "indexed_at"])
    return document
