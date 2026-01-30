#!/usr/bin/env python3
import argparse
import json
import plistlib
from pathlib import Path
from typing import Any


def log(message: str) -> None:
    print(f"[tags] {message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List current Logic Pro tag categories and usage."
    )
    parser.add_argument(
        "--tags-dir",
        default="~/Music/Audio Music Apps/Databases/Tags",
        help="Logic Pro Tags directory.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write JSON output to this path.",
    )
    parser.add_argument(
        "--include-tagsets",
        action="store_true",
        help="Include per-tagset tag usage in output.",
    )
    return parser.parse_args()


def load_plist(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return plistlib.load(handle)


def list_categories(tags_dir: Path) -> dict[str, Any]:
    properties_path = tags_dir / "MusicApps.properties"
    tagpool_path = tags_dir / "MusicApps.tagpool"

    properties = load_plist(properties_path)
    tagpool = load_plist(tagpool_path)

    sorting = properties.get("sorting") or []
    tagpool_categories = [key for key in tagpool.keys() if key]

    return {
        "sorting": sorting,
        "tagpool": sorted(tagpool_categories, key=lambda x: x.lower()),
    }


def list_tagsets(tags_dir: Path) -> list[dict[str, Any]]:
    tagsets = []
    for tagset_path in sorted(tags_dir.glob("*.tagset")):
        try:
            tagset = load_plist(tagset_path)
        except Exception:
            continue
        tags = tagset.get("tags") or {}
        if not isinstance(tags, dict):
            tags = {}
        tagsets.append(
            {
                "tagset": tagset_path.stem,
                "tags": sorted(tags.keys(), key=lambda x: x.lower()),
            }
        )
    return tagsets


def main() -> None:
    args = parse_args()
    tags_dir = Path(args.tags_dir).expanduser()
    if not tags_dir.exists():
        raise SystemExit(f"Tags directory not found: {tags_dir}")

    log(f"Reading tags from {tags_dir}")

    result = {
        "tags_dir": str(tags_dir),
        "categories": list_categories(tags_dir),
    }

    if args.include_tagsets:
        result["tagsets"] = list_tagsets(tags_dir)

    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
        log(f"Output written to {output_path}")
        return

    print("Categories in sorting order:")
    for category in result["categories"]["sorting"]:
        print(f"- {category}")

    print("\nCategories in tagpool:")
    for category in result["categories"]["tagpool"]:
        print(f"- {category}")

    if args.include_tagsets:
        print("\nTagset usage:")
        for entry in result["tagsets"]:
            tags = ", ".join(entry["tags"]) if entry["tags"] else "(none)"
            print(f"- {entry['tagset']}: {tags}")


if __name__ == "__main__":
    main()
