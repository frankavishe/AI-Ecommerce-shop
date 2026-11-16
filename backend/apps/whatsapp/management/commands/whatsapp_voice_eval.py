"""Voice-note evaluation (SC-007): transcribe labelled clips and check the assistant finds the product.

    python manage.py whatsapp_voice_eval --dir apps/whatsapp/eval/voice --min 0.8

`<dir>/cases.json` is a list of {"file": "viatu_sw_01.ogg", "language": "sw", "expect_product": "..."}.
`expect_product` is a product name or slug (case-insensitive). A clip is a hit when that product is
among the products the assistant showed (or is named in its reply text). Each clip runs on a
throwaway conversation and guest cart, which are deleted afterwards. It uses the configured speech
and chat models, so run it on the hardware you want numbers for (CPU numbers are informative only).
"""

import json
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.ai import agent, clients
from apps.ai.models import Conversation
from apps.orders.models import Cart

DEFAULT_DIR = Path(__file__).resolve().parents[2] / "eval" / "voice"


def is_hit(reply, expected):
    expected = expected.strip().lower()
    for card in reply.payload.get("products") or []:
        if expected in {(card.get("name") or "").lower(), (card.get("slug") or "").lower(),
                        (card.get("sku") or "").lower()}:
            return True
    return expected in (reply.text or "").lower()


class Command(BaseCommand):
    help = "Transcribe labelled voice clips and score whether the assistant finds the expected product."

    def add_arguments(self, parser):
        parser.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="Folder with cases.json and the clips.")
        parser.add_argument("--min", type=float, default=None, help="Fail (exit 1) when the hit-rate is below this.")

    def handle(self, *args, **options):
        folder = options["dir"]
        cases_file = folder / "cases.json"
        if not cases_file.is_file():
            raise CommandError(f"No {cases_file}. Add [{{\"file\", \"language\", \"expect_product\"}}, ...].")
        cases = json.loads(cases_file.read_text(encoding="utf-8"))
        if not cases:
            raise CommandError("cases.json is empty.")

        hits, totals = defaultdict(int), defaultdict(int)
        for case in cases:
            language = case.get("language", "sw")
            totals[language] += 1
            hit, detail = self.run_case(folder, case)
            hits[language] += hit
            mark = self.style.SUCCESS("hit ") if hit else self.style.ERROR("miss")
            self.stdout.write(f"{mark} [{language}] {case['file']}: {detail}")

        self.stdout.write("")
        for language in sorted(totals):
            rate = hits[language] / totals[language]
            self.stdout.write(f"{language}: {hits[language]}/{totals[language]} = {rate:.0%}")
        overall = sum(hits.values()) / sum(totals.values())
        self.stdout.write(f"all: {sum(hits.values())}/{sum(totals.values())} = {overall:.0%}")
        if options["min"] is not None and overall < options["min"]:
            raise CommandError(f"Hit-rate {overall:.0%} is below --min {options['min']:.0%}.")

    def run_case(self, folder, case):
        path = folder / case["file"]
        if not path.is_file():
            return False, "file not found"
        try:
            heard = clients.transcribe(path.read_bytes(), path.name)
        except clients.ModelUnavailable as exc:
            raise CommandError(f"Speech model unavailable: {exc}") from exc
        transcript = " ".join((heard.get("text") or "").split())
        if not transcript:
            return False, "empty transcript"

        cart = Cart.objects.create()
        conversation = Conversation.objects.create(channel=Conversation.Channel.WHATSAPP, cart=cart)
        try:
            reply = agent.handle_message(conversation, text=transcript, language=heard.get("language"))
        finally:
            conversation.delete()
            cart.delete()
        if reply.error:
            return False, f'"{transcript}" -> model error {reply.error}'
        return is_hit(reply, case["expect_product"]), f'"{transcript}"'
