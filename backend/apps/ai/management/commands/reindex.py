from django.core.management.base import BaseCommand

from apps.ai.tasks import reindex


class Command(BaseCommand):
    help = ("Rebuild the assistant's search indexes (products and their photos, knowledge documents). "
            "With no flags, rebuilds everything. Runs here unless --queue is given.")

    def add_arguments(self, parser):
        parser.add_argument("--products", action="store_true", help="Products and product photos.")
        parser.add_argument("--knowledge", action="store_true", help="Knowledge documents.")
        parser.add_argument("--force", action="store_true",
                            help="Re-embed even when the product text is unchanged and photos are ready.")
        parser.add_argument("--queue", action="store_true", help="Send the work to Celery instead.")

    def handle(self, *args, products=False, knowledge=False, force=False, queue=False, **options):
        if not products and not knowledge:
            products = knowledge = True
        counts = reindex(products=products, knowledge=knowledge, force=force, queue=queue)
        verb = "queued" if queue else "processed"
        for kind, count in counts.items():
            self.stdout.write(f"{kind}: {count} {verb}")
