import time

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import DatabaseError, close_old_connections

from documents.services import process_one_job
from extraction.live import process_live_once


class Command(BaseCommand):
    help = "Process queued parsing and confirmed live attempts outside HTTP. --once drains work."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--once", action="store_true")

    def handle(self, *args: object, **options: object) -> None:
        while True:
            close_old_connections()
            try:
                processed = process_one_job()
                processed = process_live_once() or processed
            except DatabaseError:
                raise CommandError(
                    "Database operation failed. Parse jobs use leases; submitted live attempts "
                    "require owner reconciliation and are never retried."
                ) from None
            if not processed:
                if options["once"]:
                    return
                time.sleep(1)
