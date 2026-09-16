#!/usr/bin/env python3
"""Convert legacy nine-file scenario bundles to schema version 2."""

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from app.domain.scenarios.compiler import ScenarioCompiler, ScenarioValidationError


def dump_yaml(value: dict[str, object]) -> str:
    return yaml.safe_dump(value, sort_keys=False, allow_unicode=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert legacy scenario directories without modifying the source files. "
            "Existing destination directories are never overwritten."
        )
    )
    parser.add_argument(
        "source",
        type=Path,
        help="Directory containing legacy nine-file scenario directories",
    )
    parser.add_argument(
        "destination",
        type=Path,
        help="Destination for version-2 scenario directories",
    )
    parser.add_argument(
        "--catalogs",
        type=Path,
        required=True,
        help="Directory containing version-2 roles.yaml and external_entities.yaml catalogs",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source = args.source.resolve()
    destination = args.destination.resolve()
    catalogs = args.catalogs.resolve()

    if not source.is_dir():
        raise SystemExit(f"Source directory does not exist: {source}")
    if not catalogs.is_dir():
        raise SystemExit(f"Catalog directory does not exist: {catalogs}")

    legacy_directories = [
        path
        for path in sorted(source.iterdir())
        if path.is_dir() and (path / "scenario.yaml").is_file()
    ]
    if not legacy_directories:
        raise SystemExit(f"No legacy scenario directories found in {source}")

    legacy_compiler = ScenarioCompiler()
    version_two_compiler = ScenarioCompiler(catalogs)
    planned = []
    for legacy_directory in legacy_directories:
        compiled = legacy_compiler.compile(legacy_directory)
        target = destination / compiled.scenario.id
        if target.exists():
            raise SystemExit(
                f"Destination already exists; refusing to overwrite: {target}"
            )
        definition = version_two_compiler.serialize_definition(compiled, target)
        variants = version_two_compiler.serialize_variants(compiled)
        planned.append((compiled, target, definition, variants))

    destination.mkdir(parents=True, exist_ok=True)
    for compiled, target, definition, variants in planned:
        with TemporaryDirectory(prefix=".scenario-migration-", dir=destination) as name:
            staged = Path(name) / compiled.scenario.id
            staged.mkdir()
            (staged / "definition.yaml").write_text(
                dump_yaml(definition), encoding="utf-8"
            )
            (staged / "variants.yaml").write_text(
                dump_yaml(variants), encoding="utf-8"
            )
            verified = version_two_compiler.compile(staged)
            if verified.model_dump(mode="json") != compiled.model_dump(mode="json"):
                raise ScenarioValidationError(
                    f"Round-trip verification failed for {compiled.scenario.id}"
                )
            staged.replace(target)
        print(f"Migrated {compiled.scenario.id} -> {target}")

    print(f"Migrated {len(planned)} scenario(s); legacy sources were not changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
