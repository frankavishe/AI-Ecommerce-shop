"""Server-built WhatsApp texts (contracts/outbound.md). None of these come from the model."""

from decimal import Decimal

from apps.ai.tools import money

TEXTS = {
    "payment_mobile": {
        "sw": "Oda {number}: jumla {total} TZS. Angalia simu yako ({phone}) uweke PIN kukamilisha malipo.",
        "en": "Order {number}: total {total} TZS. Check your phone ({phone}) and enter your PIN to pay.",
    },
    "payment_card": {
        "sw": "Oda {number}: jumla {total} TZS. Lipa hapa: {link}",
        "en": "Order {number}: total {total} TZS. Pay here: {link}",
    },
    "confirm_body": {
        "sw": "Jumla: {total} TZS (pamoja na usafirishaji {fee}). Thibitisha oda?",
        "en": "Total: {total} TZS (incl. delivery {fee}). Confirm the order?",
    },
    "confirm_button": {"sw": "Thibitisha", "en": "Confirm"},
    "change_button": {"sw": "Badilisha", "en": "Change"},
    "change_request": {"sw": "Nataka kubadilisha kitu", "en": "I want to change something"},
    "summary_outdated": {
        "sw": "Kikapu kimebadilika tangu muhtasari ule. Huu ndio muhtasari mpya:",
        "en": "Your cart changed since that summary. Here is the new one:",
    },
    "heard": {"sw": "🎤 Nimesikia: \"{text}\"", "en": "🎤 I heard: \"{text}\""},
    "voice_retry": {
        "sw": "Samahani, sikuweza kusikia vizuri. Tafadhali andika ujumbe au tuma sauti fupi (chini ya dakika 2).",
        "en": "Sorry, I couldn't make that out. Please type your message or send a shorter voice note (under 2 minutes).",
    },
    "media_retry": {
        "sw": "Samahani, sikuweza kupakua faili. Tafadhali itume tena.",
        "en": "Sorry, I couldn't download that. Please send it again.",
    },
    "image_rejected": {
        "sw": "Tafadhali tuma picha ya JPEG, PNG au WebP isiyozidi MB 10.",
        "en": "Please send a JPEG, PNG or WebP photo up to 10 MB.",
    },
    "unsupported": {
        "sw": "Ninaweza kusoma ujumbe wa maandishi, picha na sauti tu.",
        "en": "I can read text messages, photos and voice notes.",
    },
    "slow_down": {
        "sw": "Unatuma ujumbe mwingi kwa haraka. Tafadhali subiri kidogo.",
        "en": "You're sending messages very quickly. Please wait a moment.",
    },
    "stopped": {
        "sw": "Sawa, hutapokea taarifa za oda tena. Tuma ANZA kuziwasha.",
        "en": "OK, you won't get order updates any more. Send START to turn them back on.",
    },
    "started": {"sw": "Taarifa za oda zimewashwa.", "en": "Order updates are on."},
    "cart_pruned": {
        "sw": "Karibu tena! Bidhaa hizi hazipatikani tena na zimeondolewa kwenye kikapu: {names}.",
        "en": "Welcome back! These items are no longer available and were removed from your cart: {names}.",
    },
    "link_ok": {
        "sw": "Namba hii sasa imeunganishwa na akaunti yako.",
        "en": "This number is now linked to your account.",
    },
    "link_failed": {
        "sw": "Samahani, msimbo huo haufanyi kazi. Pata msimbo mpya kwenye ukurasa wa akaunti.",
        "en": "Sorry, that code didn't work. Get a new one on your account page.",
    },
    "link_taken": {
        "sw": "Namba hii tayari imeunganishwa na akaunti nyingine.",
        "en": "This number is already linked to another account.",
    },
    "button_expired": {"sw": "Kitufe hicho kimeisha muda.", "en": "That button has expired."},
    "follow_up": {
        "sw": "Habari! Mhudumu wetu anafuatilia ujumbe wako na atakujibu hivi punde.",
        "en": "Hello! A member of our team is following up on your message and will reply shortly.",
    },
}

HEARD_MAX = 200


def text(key, lang="sw", **kw):
    variants = TEXTS[key]
    return variants.get(lang if lang in ("sw", "en") else "sw").format(**kw)


def format_tzs(value):
    """45000 -> "45,000"; 1500.5 -> "1,500.50" (rounded like ai.tools.money)."""
    if value is None:
        return ""
    plain = money(Decimal(value))
    whole, _, cents = plain.partition(".")
    sign = "-" if whole.startswith("-") else ""
    grouped = f"{int(whole.lstrip('-')):,}"
    return f"{sign}{grouped}" + (f".{cents}" if cents else "")


def heard(transcript, lang="sw"):
    quote = " ".join((transcript or "").split())
    line = text("heard", lang, text=quote)
    if len(line) > HEARD_MAX:
        overflow = len(line) - HEARD_MAX + 1
        line = text("heard", lang, text=quote[: max(0, len(quote) - overflow)].rstrip() + "…")
    return line
