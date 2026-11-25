import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError, CommandParser

from evaluation.dataset import load_dataset, validate_split
from evaluation.report import run

ROOT = Path(__file__).resolve().parents[3]


class Command(BaseCommand):
    help = "Validate grouped synthetic data or evaluate dev baseline/replay offline. No paid calls."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--dataset", type=Path, required=True)
        parser.add_argument("--provider", choices=["baseline", "replay"], default="baseline")
        parser.add_argument("--validate-only", action="store_true")
        parser.add_argument("--output", type=Path)

    def handle(self, *args: object, **options: object) -> None:
        path = Path(str(options["dataset"])).resolve()
        try:
            dataset = load_dataset(path)
            other_split = "test" if dataset.manifest.split == "dev" else "dev"
            other = load_dataset(path.parent.parent / other_split / "manifest.json")
            validate_split(dataset, other) if dataset.manifest.split == "dev" else validate_split(
                other, dataset
            )
            if options["validate_only"]:
                self.stdout.write(
                    "Validated both manifests, source hashes, gold anchors and grouped split. "
                    "Human review pending."
                )
                return
            provider = str(options["provider"])
            report = run(dataset, provider)
            destination = (
                Path(str(options["output"]))
                if options["output"]
                else ROOT / "outputs" / f"evaluation-v1-{dataset.manifest.split}-{provider}.json"
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("x", encoding="utf-8") as handle:
                json.dump(report, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except Exception as error:
            code = (
                "output_exists_choose_new_path"
                if isinstance(error, FileExistsError)
                else "evaluation_validation_or_execution_failed"
            )
            raise CommandError(code + "; no source contents logged") from None
        self.stdout.write(
            f"Report: {destination.resolve()}; scheduled={report['counts']['scheduled']}, "
            f"complete={report['counts']['complete']}. No live inference."
        )
