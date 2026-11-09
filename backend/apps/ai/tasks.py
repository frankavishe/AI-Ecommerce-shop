from celery import shared_task

from . import indexing
from .models import IndexStatus


@shared_task(bind=True, max_retries=3)
def index_product(self, product_id, force=False):
    entry = indexing.index_product(product_id, force=force)
    if entry is not None and entry.status == IndexStatus.FAILED and not self.request.is_eager:
        raise self.retry(countdown=30 * (2 ** self.request.retries))
    return entry.status if entry else "deleted"


@shared_task
def purge_old_conversations():
    """Filled in by US5 (T043)."""
    return 0
