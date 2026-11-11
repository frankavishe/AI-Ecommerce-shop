import io

import pytest
from django.core.files.base import ContentFile

from apps.ai import indexing, search
from apps.ai.models import KnowledgeChunk, KnowledgeDocument

pytestmark = pytest.mark.django_db

RETURNS = "Returns: you can return shoes within 7 days with the receipt."
DELIVERY = "Delivery: we deliver in Dar es Salaam within 24 hours. Upcountry delivery takes 3 days."


def pdf_bytes(text):
    """A minimal one-page PDF with `text` in Helvetica (pypdf can read it back)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = out.tell()
    out.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        out.write(b"%010d 00000 n \n" % offset)
    out.write(b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref))
    return out.getvalue()


def docx_bytes(*paragraphs):
    import docx

    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def make_document(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path

    def make(content, name="policy.txt", content_type="text/plain", title="Shop policy"):
        document = KnowledgeDocument(title=title, content_type=content_type)
        document.file.save(name, ContentFile(content), save=True)
        return document

    return make


@pytest.fixture
def policies(make_document):
    returns = make_document(RETURNS.encode(), title="Returns policy")
    delivery = make_document(DELIVERY.encode(), name="delivery.txt", title="Delivery")
    for document in (returns, delivery):
        indexing.index_document(document.pk)
    return returns, delivery


# --- extract_text ------------------------------------------------------------------------------


def test_extract_text_reads_plain_text_in_utf8_and_latin1():
    assert indexing.extract_text(io.BytesIO("Bei ni nafuu – karibu".encode()), "text/plain") == "Bei ni nafuu – karibu"
    assert indexing.extract_text(io.BytesIO("Café".encode("latin-1")), "text/plain") == "Café"


def test_extract_text_reads_docx():
    data = docx_bytes("Returns policy", "You can return shoes within 7 days.")
    text = indexing.extract_text(io.BytesIO(data), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    assert "Returns policy" in text
    assert "return shoes within 7 days" in text


def test_extract_text_reads_pdf():
    text = indexing.extract_text(io.BytesIO(pdf_bytes("Delivery takes 3 days")), "application/pdf")
    assert "Delivery takes 3 days" in text


def test_extract_text_uses_the_file_name_when_the_type_is_missing():
    data = docx_bytes("Hello from Word")
    assert "Hello from Word" in indexing.extract_text(io.BytesIO(data), "", name="notes.docx")


# --- chunk_text ---------------------------------------------------------------------------------


def test_short_text_is_one_chunk():
    assert indexing.chunk_text("  Short policy.  ") == ["Short policy."]
    assert indexing.chunk_text("   \n\n ") == []


def test_long_text_is_split_into_overlapping_chunks_at_paragraphs():
    paragraphs = [f"Paragraph {n}. " + ("word " * 90).strip() + "." for n in range(12)]
    text = "\n\n".join(paragraphs)
    chunks = indexing.chunk_text(text, size=1800, overlap=300)

    assert len(chunks) > 1
    assert all(len(chunk) <= 1800 for chunk in chunks)
    assert all(len(chunk) >= 600 for chunk in chunks[:-1])
    for chunk in chunks[:-1]:
        assert chunk.endswith(".")  # cut at a paragraph boundary, not mid-word
    for previous, chunk in zip(chunks, chunks[1:]):
        assert chunk[:40] in previous  # the overlap repeats the end of the previous chunk
    # Nothing is lost.
    for paragraph in paragraphs:
        assert any(paragraph[:30] in chunk for chunk in chunks)


def test_text_without_breaks_is_still_cut_to_size():
    chunks = indexing.chunk_text("x" * 5000, size=1800, overlap=300)
    assert all(len(chunk) <= 1800 for chunk in chunks)
    assert sum(len(chunk) for chunk in chunks) >= 5000


# --- index_document -----------------------------------------------------------------------------


def test_index_document_creates_chunks_with_vectors(make_document):
    document = make_document(RETURNS.encode())
    indexing.index_document(document.pk)
    document.refresh_from_db()

    assert document.status == KnowledgeDocument.Status.READY
    assert document.chunk_count == 1
    assert document.indexed_at is not None
    chunk = document.chunks.get()
    assert chunk.text == RETURNS
    assert len(chunk.embedding) == 1024
    assert KnowledgeChunk.objects.filter(tsv="receipt").exists()


def test_reindexing_replaces_the_chunks(make_document):
    document = make_document(RETURNS.encode())
    indexing.index_document(document.pk)
    indexing.index_document(document.pk)
    assert document.chunks.count() == 1


def test_empty_document_fails_with_a_reason(make_document):
    document = make_document(b"   \n ")
    indexing.index_document(document.pk)
    document.refresh_from_db()
    assert document.status == KnowledgeDocument.Status.FAILED
    assert document.error == "no extractable text"
    assert document.chunk_count == 0


def test_unreadable_file_fails_with_a_reason(make_document):
    document = make_document(b"not a pdf at all", name="broken.pdf", content_type="application/pdf")
    indexing.index_document(document.pk)
    document.refresh_from_db()
    assert document.status == KnowledgeDocument.Status.FAILED
    assert document.error


def test_embedder_failure_marks_the_document_failed(make_document, embedder):
    embedder.fail = True
    document = make_document(RETURNS.encode())
    indexing.index_document(document.pk)
    document.refresh_from_db()
    assert document.status == KnowledgeDocument.Status.FAILED
    assert "down" in document.error
    assert not document.chunks.exists()


def test_index_document_task_runs(make_document):
    from apps.ai.tasks import index_document

    document = make_document(RETURNS.encode())
    assert index_document.delay(document.pk).get() == "ready"


# --- knowledge search ---------------------------------------------------------------------------


@pytest.mark.parametrize("query", ["return shoes", "kurudisha viatu", "Can I return my shoes?"])
def test_knowledge_search_finds_the_returns_passage(policies, query):
    results = search.knowledge(query)
    assert results
    assert results[0].document.title == "Returns policy"


def test_knowledge_search_finds_delivery(policies):
    assert search.knowledge("delivery Dar es Salaam")[0].document.title == "Delivery"


def test_knowledge_search_returns_nothing_for_unrelated_text(policies):
    assert search.knowledge("xyzzy qwertyuiop") == []


def test_knowledge_search_skips_documents_that_are_not_ready(policies):
    returns, _ = policies
    KnowledgeDocument.objects.filter(pk=returns.pk).update(status=KnowledgeDocument.Status.PROCESSING)
    assert all(chunk.document_id != returns.pk for chunk in search.knowledge("return shoes"))


def test_deleting_a_document_removes_its_chunks(policies):
    returns, _ = policies
    returns.delete()
    assert not KnowledgeChunk.objects.filter(document_id=returns.pk).exists()
    assert all(chunk.document.title != "Returns policy" for chunk in search.knowledge("return shoes"))
