import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction

from accounts.models import Membership, Workspace


class Command(BaseCommand):
    help = "Create a local workspace and user. Password is prompted, never a command argument."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--username", required=True)
        parser.add_argument("--workspace", required=True)
        parser.add_argument("--role", choices=["viewer", "reviewer"], default="reviewer")

    def handle(self, *args: object, **options: object) -> None:
        username = str(options["username"])
        if get_user_model().objects.filter(username=username).exists():
            raise CommandError("User already exists; bootstrap does not modify existing users.")
        password = getpass.getpass("New password (at least 12 characters): ")
        if len(password) < 12 or password != getpass.getpass("Confirm password: "):
            raise CommandError("Password is too short or confirmation does not match.")
        with transaction.atomic():
            user = get_user_model().objects.create_user(username=username, password=password)
            workspace = Workspace.objects.create(name=str(options["workspace"]))
            Membership.objects.create(user=user, workspace=workspace, role=str(options["role"]))
        self.stdout.write("Workspace and membership created. Sign in and select your workspace.")
