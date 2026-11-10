from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from . import indexing
from .models import ChatMessage, Conversation, IndexStatus, KnowledgeDocument

CONVERSATION_RETENTION = timedelta(days=90)
PHOTO_RETENTION = timedelta(days=30)


@shared_task(bind=True, max_retries=3)
def index_product(self, product_id, force=False):
    entry = indexing.index_product(product_id, force=force)
    if entry is not None and entry.status == IndexStatus.FAILED and not self.request.is_eager:
        raise self.retry(countdown=30 * (2 ** self.request.retries))
    return entry.status if entry else "deleted"


@shared_task(bind=True, max_retries=3)
def index_document(self, document_id):
    document = indexing.index_document(document_id)
    if document is None:
        return "deleted"
    if getattr(document, "retryable", False) and not self.request.is_eager:
        raise self.retry(countdown=30 * (2 ** self.request.retries))
    return document.status


@shared_task(bind=True, max_retries=3)
def index_product_image(self, image_id):
    entry = indexing.index_product_image(image_id)
    if entry is None:
        return "deleted"
    if getattr(entry, "retryable", False) and not self.request.is_eager:
        raise self.retry(countdown=30 * (2 ** self.request.retries))
    return entry.status


def reindex(products=True, knowledge=True, force=False, queue=True):
    """Rebuild the indexes, through Celery (`queue`) or right here. Returns how many items were sent.
    Product text is re-embedded only when it changed unless `force`; photos have no content hash, so
    they are redone when `force` or when not ready. Documents (few, and cheap) are always redone."""
    from apps.catalog.models import Product, ProductImage

    in_process = {index_product: indexing.index_product, index_product_image: indexing.index_product_image,
                  index_document: indexing.index_document}

    def run(task, *args, **kwargs):
        (task.delay if queue else in_process[task])(*args, **kwargs)

    counts = {"products": 0, "images": 0, "knowledge": 0}
    if products:
        for pk in Product.objects.values_list("pk", flat=True):
            run(index_product, pk, force=force)
            counts["products"] += 1
        images = ProductImage.objects.all()
        if not force:
            images = images.exclude(ai_index__status=IndexStatus.READY)
        for pk in images.values_list("pk", flat=True):
            run(index_product_image, pk)
            counts["images"] += 1
    if knowledge:
        for pk in KnowledgeDocument.objects.values_list("pk", flat=True):
            run(index_document, pk)
            counts["knowledge"] += 1
    return counts


@shared_task
def reindex_all(products=True, knowledge=True, force=False):
    return reindex(products, knowledge, force, queue=True)


@shared_task
def purge_old_conversations():
    """Retention (spec): conversations idle for 90 days are deleted; shopper photos after 30 days."""
    now = timezone.now()
    old = Conversation.objects.filter(updated_at__lt=now - CONVERSATION_RETENTION)
    for message in ChatMessage.objects.filter(conversation__in=old).exclude(image="").exclude(image=None):
        message.image.delete(save=False)
    conversations = old.count()
    old.delete()

    photos = 0
    stale = (ChatMessage.objects.filter(created_at__lt=now - PHOTO_RETENTION, image_deleted=False)
             .exclude(image="").exclude(image=None))
    for message in stale:
        message.image.delete(save=False)
        message.image = None
        message.image_deleted = True
        message.save(update_fields=["image", "image_deleted"])
        photos += 1
    return {"conversations": conversations, "images": photos}
