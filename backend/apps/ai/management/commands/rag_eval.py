"""Measure search quality on the labelled Swahili/English eval set (research R15).

    python manage.py rag_eval --seed                  # DEBUG only: load the eval catalog + knowledge, index, score
    python manage.py rag_eval --min-product 0.8 --min-knowledge 0.85 --min-photo 0.7

Cases go through the same search functions the assistant's tools use, and a case is a hit when an
expected product (by SKU) or document (by title) is in the top K (default 5).
"""

import json
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand, CommandError

from apps.ai import indexing, search, signals
from apps.ai.models import KnowledgeDocument
from apps.catalog.models import Category, Product, ProductImage

EVAL_DIR = Path(__file__).resolve().parents[2] / "eval"
KINDS = ("product", "knowledge", "photo")
KIND_ALIASES = {"products": "product", "photos": "photo"}


def _kind(value):
    value = KIND_ALIASES.get(value, value)
    if value not in KINDS:
        raise ValueError(value)
    return value


class Command(BaseCommand):
    help = "Score product, knowledge and photo search (hit-rate@K per kind and language)."

    def add_arguments(self, parser):
        parser.add_argument("--seed", action="store_true",
                            help="Load the eval catalog and knowledge into this database first (DEBUG only).")
        parser.add_argument("--kind", action="append", type=_kind, metavar="{product,knowledge,photo}",
                            help="Only these kinds (repeatable). Default: all.")
        parser.add_argument("--cases", type=Path, default=EVAL_DIR / "cases.json")
        parser.add_argument("--photos", type=Path, default=EVAL_DIR / "photos.json")
        parser.add_argument("--k", type=int, default=5)
        for kind in KINDS:
            parser.add_argument(f"--min-{kind}", type=float, default=None,
                                help=f"Fail (exit 1) when the {kind} hit-rate is below this (0-1).")

    def handle(self, *args, **options):
        kinds = tuple(dict.fromkeys(options["kind"] or KINDS))
        if options["seed"]:
            if not settings.DEBUG:
                raise CommandError("--seed writes demo data and only runs with DEBUG=True.")
            self.seed()

        cases = []
        if {"product", "knowledge"} & set(kinds):
            cases += [c for c in json.loads(options["cases"].read_text(encoding="utf-8")) if c["kind"] in kinds]
        if "photo" in kinds:
            cases += self.photo_cases(options["photos"])

        results = defaultdict(lambda: [0, 0])  # (kind, lang) -> [hits, total]
        for case in cases:
            hit, found = self.run_case(case, options["k"])
            for key in ((case["kind"], case["lang"]), (case["kind"], "all")):
                results[key][0] += hit
                results[key][1] += 1
            if not hit:
                self.stdout.write(f"MISS {case['kind']} {case['lang']} {case.get('query') or case.get('file')!r}"
                                  f" -> {found}")

        self.stdout.write("")
        self.stdout.write(f"{'kind':<11}{'lang':<6}{'hits':>8}{'rate':>8}")
        for (kind, lang), (hits, total) in sorted(results.items(), key=lambda kv: (KINDS.index(kv[0][0]),
                                                                                   kv[0][1] == "all", kv[0][1])):
            self.stdout.write(f"{kind:<11}{lang:<6}{f'{hits}/{total}':>8}{hits / total:>8.0%}")

        below = []
        for kind in KINDS:
            minimum = options[f"min_{kind}"]
            hits, total = results.get((kind, "all"), (0, 0))
            if minimum is not None and total and hits / total < minimum:
                below.append(f"{kind} {hits / total:.0%} < {minimum:.0%}")
        if below:
            raise CommandError("Below the minimum hit-rate: " + ", ".join(below))

    # --- cases ----------------------------------------------------------------------------------

    def run_case(self, case, k):
        if case["kind"] == "knowledge":
            titles = [chunk.document.title for chunk in search.knowledge(case["query"], limit=k)]
            return case["expect_document"] in titles, titles
        if case["kind"] == "photo":
            products = search.by_image(case["bytes"], note=case.get("note", ""), limit=k).products
        else:
            products = search.hybrid_products(case["query"], in_stock_only=False, limit=k)
        skus = [p.sku for p in products]
        return bool(set(case["expect"]) & set(skus)), skus

    def photo_cases(self, path):
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        cases, missing = [], []
        for case in data.get("cases", []):
            file = path.parent / case["file"]
            if not file.exists():
                missing.append(case["file"])
                continue
            cases.append({**case, "kind": "photo", "bytes": file.read_bytes()})
        if missing:
            self.stdout.write(f"Skipped {len(missing)} photo case(s) with no file (see eval/photos/README.md).")
        return cases

    # --- seed -----------------------------------------------------------------------------------

    def seed(self):
        catalog = json.loads((EVAL_DIR / "catalog.json").read_text(encoding="utf-8"))
        photos = json.loads((EVAL_DIR / "photos.json").read_text(encoding="utf-8"))
        with signals.paused():
            categories = {}
            for row in catalog["categories"]:
                category, _ = Category.objects.update_or_create(
                    name=row["name"],
                    defaults={"name_sw": row.get("name_sw", ""), "parent": categories.get(row.get("parent"))},
                )
                categories[row["key"]] = category
            products = []
            for row in catalog["products"]:
                product, _ = Product.objects.update_or_create(sku=row["sku"], defaults={
                    "name": row["name"], "category": categories[row["category"]],
                    "price": Decimal(str(row["price"])), "stock": row.get("stock", 10),
                    "tags": row.get("tags", ""), "attributes": row.get("attributes", {}),
                    "description": row.get("description", ""), "description_sw": row.get("description_sw", ""),
                    "is_active": True,
                })
                products.append(product)
            images = self.seed_images(photos.get("catalog_images", {}))
            documents = self.seed_knowledge()

        for product in products:
            indexing.index_product(product.pk)
        for image in images:
            indexing.index_product_image(image.pk)
        for document in documents:
            indexing.index_document(document.pk)
        failed = KnowledgeDocument.objects.filter(status=KnowledgeDocument.Status.FAILED).count()
        self.stdout.write(f"Seeded {len(products)} products, {len(images)} photos, {len(documents)} documents"
                          + (f" ({failed} failed to index)" if failed else "") + ".")

    def seed_images(self, catalog_images):
        images = []
        for sku, files in catalog_images.items():
            product = Product.objects.filter(sku=sku).first()
            for name in files:
                file = EVAL_DIR / name
                if product is None or not file.exists():
                    continue
                if product.images.filter(alt_text=f"eval:{name}").exists():
                    continue
                image = ProductImage(product=product, alt_text=f"eval:{name}")
                with file.open("rb") as handle:
                    image.image.save(file.name, File(handle), save=True)
                images.append(image)
        return images

    def seed_knowledge(self):
        documents = []
        for file in sorted((EVAL_DIR / "knowledge").glob("*.txt")):
            text = file.read_text(encoding="utf-8")
            title = text.splitlines()[0].strip() or file.stem
            for old in KnowledgeDocument.objects.filter(title=title):
                old.file.delete(save=False)
                old.delete()
            document = KnowledgeDocument(title=title, content_type="text/plain",
                                         language=KnowledgeDocument.DocLanguage.MIXED)
            document.file.save(file.name, ContentFile(text.encode("utf-8")), save=True)
            documents.append(document)
        return documents
