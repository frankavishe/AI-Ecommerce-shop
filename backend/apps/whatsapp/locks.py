"""Per-number serialization with a session-level Postgres advisory lock (research R3).

The lock belongs to the database connection, so a crashed worker frees it. It is taken outside any
atomic block; a turn's tools commit on their own while it is held.
"""

from contextlib import contextmanager

from django.conf import settings
from django.db import connection


@contextmanager
def advisory_lock(contact_id):
    namespace = settings.WHATSAPP_LOCK_NAMESPACE
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", [namespace, contact_id])
        got = bool(cursor.fetchone()[0])
    try:
        yield got
    finally:
        if got:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s, %s)", [namespace, contact_id])
