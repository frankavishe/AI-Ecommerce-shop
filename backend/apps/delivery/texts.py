"""Server-built rider texts (contracts/rider-tools.md "Fixed texts"). None of these come from the model."""

TEXTS = {
    "rider_stop": {
        "sw": "Wewe ni msafirishaji: ujumbe wa kazi hauwezi kuzimwa. Muombe msimamizi akuondoe.",
        "en": "You are a rider: job messages can't be turned off. Ask the admin to deactivate you.",
    },
    "inbox_assigned": {"sw": "Kazi mpya: oda {number}", "en": "New job: order {number}"},
    "inbox_removed": {"sw": "Oda {number} imeondolewa kwenye kazi zako", "en": "Order {number} was removed from your jobs"},
    "inbox_cancelled": {"sw": "Oda {number} imesitishwa – usiipeleke", "en": "Order {number} was cancelled – don't deliver it"},
}


def text(key, lang="sw", **kw):
    return TEXTS[key].get(lang if lang in ("sw", "en") else "sw").format(**kw)
