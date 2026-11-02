# myapp/apps.py
#
# Single MyappConfig — earlier version had TWO classes with the
# same name, so Django only saw the last one and SQLite WAL pragmas
# never registered.

from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _sqlite_pragmas(sender, connection, **kwargs):
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