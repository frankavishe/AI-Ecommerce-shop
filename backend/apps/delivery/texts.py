"""Server-built rider texts (contracts/rider-tools.md "Fixed texts"). None of these come from the model.

Rider replies about jobs and statuses are built here from database values: the small CPU model
garbled its confirmations and sometimes answered without calling a tool.
"""

TEXTS = {
    "rider_stop": {
        "sw": "Wewe ni msafirishaji: ujumbe wa kazi hauwezi kuzimwa. Muombe msimamizi akuondoe.",
        "en": "You are a rider: job messages can't be turned off. Ask the admin to deactivate you.",
    },
    "inbox_assigned": {"sw": "Kazi mpya: oda {number}", "en": "New job: order {number}"},
    "inbox_removed": {"sw": "Oda {number} imeondolewa kwenye kazi zako", "en": "Order {number} was removed from your jobs"},
    "inbox_cancelled": {"sw": "Oda {number} imesitishwa – usiipeleke", "en": "Order {number} was cancelled – don't deliver it"},
    # rider assistant replies
    "jobs_none": {"sw": "Huna kazi kwa sasa.", "en": "You have no jobs right now."},
    "jobs_header": {"sw": "Kazi zako ({count}):", "en": "Your jobs ({count}):"},
    "which_job": {
        "sw": "Una kazi zaidi ya moja. Ni oda ipi? Tuma pamoja na namba ya oda.",
        "en": "You have more than one job. Which order? Send it again with the order number.",
    },
    "updated_picked_up": {"sw": "Sawa, oda {number} imechukuliwa.", "en": "OK, order {number} is picked up."},
    "updated_on_the_way": {"sw": "Sawa, oda {number} iko njiani.", "en": "OK, order {number} is on the way."},
    "updated_delivered": {
        "sw": "Asante! Oda {number} imefikishwa.", "en": "Thanks! Order {number} is delivered.",
    },
    "updated_failed": {
        "sw": "Sawa, oda {number} imeandikwa kuwa imeshindikana. Msimamizi ataamua hatua inayofuata.",
        "en": "OK, order {number} is marked as failed. The admin will decide what happens next.",
    },
    "already": {"sw": "Oda {number} tayari iko: {status}.", "en": "Order {number} is already {status}."},
    "not_found": {"sw": "Oda {number} haipo kwenye kazi zako.", "en": "Order {number} is not among your jobs."},
    "not_yours_anymore": {
        "sw": "Oda {number} imehamishiwa kwa msafirishaji mwingine.",
        "en": "Order {number} was moved to another rider.",
    },
    "invalid_transition": {
        "sw": "Oda {number} haiwezi kuwekwa \"{target}\" sasa; hali yake ni: {status}.",
        "en": "Order {number} can't be set to \"{target}\" now; it is {status}.",
    },
    "reason_required": {
        "sw": "Tafadhali eleza kwa nini oda {number} imeshindikana, mfano: \"imeshindikana {number}, mteja hapatikani\".",
        "en": "Please say why order {number} failed, e.g. \"failed {number}, customer not reachable\".",
    },
    "available_on": {"sw": "Sawa, uko tayari kupokea kazi mpya.", "en": "OK, you're available for new jobs."},
    "available_off": {
        "sw": "Sawa, hutapewa kazi mpya. Kazi ulizonazo ({count}) bado ni zako.",
        "en": "OK, you won't get new jobs. Your current jobs ({count}) stay with you.",
    },
    "details": {
        "sw": "Oda {number} ({status})\nMteja: {name}, {phone}\nAnwani: {address}\nBidhaa: {items}",
        "en": "Order {number} ({status})\nCustomer: {name}, {phone}\nAddress: {address}\nItems: {items}",
    },
    "details_notes": {"sw": "Maelezo ya mteja: {notes}", "en": "Customer notes: {notes}"},
}

STATUS = {
    "waiting": {"sw": "inasubiri msafirishaji", "en": "waiting for a rider"},
    "assigned": {"sw": "umepewa", "en": "assigned"},
    "picked_up": {"sw": "imechukuliwa", "en": "picked up"},
    "on_the_way": {"sw": "iko njiani", "en": "on the way"},
    "delivered": {"sw": "imefikishwa", "en": "delivered"},
    "failed": {"sw": "imeshindikana", "en": "failed"},
    "cancelled": {"sw": "imesitishwa", "en": "cancelled"},
}


def _lang(lang):
    return lang if lang in ("sw", "en") else "sw"


def text(key, lang="sw", **kw):
    return TEXTS[key][_lang(lang)].format(**kw)


def status_label(status, lang="sw"):
    return STATUS.get(str(status), {}).get(_lang(lang), str(status))


def _address(order):
    return ", ".join(part for part in (order.street, order.district, order.region) if part)


def jobs_text(deliveries, lang="sw"):
    deliveries = list(deliveries)
    if not deliveries:
        return text("jobs_none", lang)
    lines = [text("jobs_header", lang, count=len(deliveries))]
    lines += [f"• {d.order.number} – {_address(d.order)} ({status_label(d.status, lang)})" for d in deliveries]
    return "\n".join(lines)


def details_text(delivery, lang="sw"):
    order = delivery.order
    items = ", ".join(f"{item.quantity} × {item.product_name}" for item in order.items.all())
    body = text("details", lang, number=order.number, status=status_label(delivery.status, lang),
                name=order.contact_name, phone=order.contact_phone, address=_address(order), items=items)
    if order.notes:
        body += "\n" + text("details_notes", lang, notes=order.notes)
    return body


def update_text(number, result, lang="sw", requested=""):
    """The reply to an update_delivery result (contracts/rider-tools.md)."""
    error = result.get("error")
    if error == "invalid_transition":
        return text(error, lang, number=number, status=status_label(result.get("current", ""), lang),
                    target=status_label(requested, lang))
    if error in ("not_found", "not_yours_anymore", "reason_required"):
        return text(error, lang, number=number)
    status = str(result.get("status", ""))
    if result.get("already"):
        return text("already", lang, number=number, status=status_label(status, lang))
    return text(f"updated_{status}", lang, number=number)
