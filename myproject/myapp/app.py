# myapp/apps.py

from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _sqlite_pragmas(sender, connection, **kwargs):
    """
    Enable WAL mode + busy timeout on every new SQLite connection.

    Why:
        - Default SQLite allows only ONE writer at a time.
        - When 2 players join simultaneously → "database is locked".
        - WAL = multiple readers + one writer, much better concurrency.
        - busy_timeout = 30s → waits instead of crashing immediately.
    """
    if connection.vendor == "sqlite":
        try:
            with connection.cursor() as cursor:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA busy_timeout=30000;")
                cursor.execute("PRAGMA foreign_keys=ON;")
        except Exception:
            pass


class MyappConfig(AppConfig):

    default_auto_field = "django.db.models.BigAutoField"

    name = "myapp"

    def ready(self):
        connection_created.connect(_sqlite_pragmas)