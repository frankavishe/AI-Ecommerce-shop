"""Catalog changes -> index tasks after the transaction commits (research R5)."""

from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.catalog.models import Category, Product, ProductImage


def _queue(product_ids):
    from .tasks import index_product

    for product_id in product_ids:
        transaction.on_commit(lambda pid=product_id: index_product.delay(pid))


@receiver(post_save, sender=Product, dispatch_uid="ai_index_product")
def product_saved(sender, instance, raw=False, **kwargs):
    if not raw:
        _queue([instance.pk])


@receiver(post_save, sender=Category, dispatch_uid="ai_index_category")
def category_saved(sender, instance, created=False, raw=False, **kwargs):
    if raw or created:
        return
    ids, frontier = set(), [instance.pk]
    while frontier:  # this category and its subcategories (names are part of the index text)
        ids.update(Product.objects.filter(category_id__in=frontier).values_list("pk", flat=True))
        frontier = list(Category.objects.filter(parent_id__in=frontier).values_list("pk", flat=True))
    _queue(sorted(ids))


@receiver(post_save, sender=ProductImage, dispatch_uid="ai_index_product_image")
def product_image_saved(sender, instance, raw=False, **kwargs):
    if raw:
        return
    from .tasks import index_product_image

    transaction.on_commit(lambda pk=instance.pk: index_product_image.delay(pk))
