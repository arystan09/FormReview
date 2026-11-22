import os
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from extraction.config import live_config
from extraction.live import KEY_ENV, key_fingerprint
from extraction.models import LiveAllowance, LiveAttempt


class Command(BaseCommand):
    help = "Local-owner live admission configuration. No network call; limits never auto-replenish."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--enable", action="store_true")
        parser.add_argument("--disable", action="store_true")
        parser.add_argument("--prompt-file", type=Path)
        parser.add_argument(
            "--limit", type=int, help="Absolute lifetime request ceiling, not additional credits"
        )
        parser.add_argument("--input-price", help="USD per million input tokens")
        parser.add_argument("--output-price", help="USD per million output tokens")
        parser.add_argument("--price-checked-on", help="YYYY-MM-DD, within seven days")
        parser.add_argument("--price-source")
        parser.add_argument("--reconcile-unknown", type=uuid.UUID)
        parser.add_argument(
            "--confirm-provider-finished",
            action="store_true",
            help="Owner attests worker stopped AND provider request finished; never retries it",
        )

    @transaction.atomic
    def handle(self, *args: object, **options: object) -> None:
        LiveAllowance.objects.get_or_create(pk=1)
        policy = LiveAllowance.objects.select_for_update().get(pk=1)
        if options["disable"]:
            policy.enabled = False
            policy.version += 1
            policy.save()
            self.stdout.write("Paid admission disabled. Existing submitted calls are not retried.")
            return
        if options["reconcile_unknown"]:
            if not options["confirm_provider_finished"]:
                raise CommandError(
                    "Explicit worker-stopped/provider-finished attestation required."
                )
            attempt = (
                LiveAttempt.objects.select_for_update()
                .filter(pk=str(options["reconcile_unknown"]))
                .first()
            )
            if (
                attempt is None
                or policy.active_attempt != attempt.id
                or attempt.status not in {"unknown", "submitted"}
            ):
                raise CommandError("No matching unresolved attempt.")
            attempt.status = "unknown"
            attempt.error_code = "owner_reconciled_no_retry"
            attempt.finished_at = timezone.now()
            attempt.save()
            policy.active_attempt = None
            policy.save()
            self.stdout.write(
                "Uncertain slot released by owner; consumed allowance unchanged. No retry."
            )
            return
        if settings.PUBLIC_DEMO or not options["enable"] or policy.active_attempt:
            raise CommandError(
                "Enable explicitly outside public demo, with no active/uncertain attempt."
            )
        key = os.environ.get(KEY_ENV, "")
        if not key:
            raise CommandError(
                "Worker key environment variable is required; never pass a key as an argument."
            )
        try:
            limit = int(str(options["limit"]))
            input_price = Decimal(str(options["input_price"]))
            output_price = Decimal(str(options["output_price"]))
            checked = date.fromisoformat(str(options["price_checked_on"]))
            source = str(options["price_source"])
            prompt = Path(str(options["prompt_file"])).read_text(encoding="utf-8")
            if not policy.consumed <= limit <= 1000 or limit < 1:
                raise ValueError
            if not all(
                rate.is_finite() and 0 < rate <= 1000 for rate in [input_price, output_price]
            ):
                raise ValueError
            if not 0 <= (timezone.localdate() - checked).days <= 7 or not source.startswith(
                "https://developers.openai.com/"
            ):
                raise ValueError
            config = live_config(prompt)
        except (ValueError, OSError, InvalidOperation):
            raise CommandError(
                "Supply valid prompt, finite lifetime limit, current official price and date."
            ) from None
        policy.config = config
        policy.enabled = True
        policy.key_fingerprint = key_fingerprint(key)
        policy.request_limit = limit
        policy.input_price, policy.output_price = input_price, output_price
        policy.price_checked_on, policy.price_source = checked, source
        policy.version += 1
        policy.save()
        self.stdout.write(
            f"Live config {config.id} enabled; "
            f"{policy.consumed}/{limit} lifetime requests consumed. "
            "Reviewer confirmation still required."
        )
