#!/usr/bin/env python3
import argparse
import json
import plistlib
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True)
class Plugin:
    name: str
    manufacturer: str
    subtype: str
    au_type: str
    bundle_id: str
    bundle_name: str
    component_path: Path

    def tagset_name(self) -> str:
        return (
            self.au_type.encode().hex()
            + "-"
            + self.subtype.encode().hex()
            + "-"
            + self.manufacturer.encode().hex()
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Organize Logic Pro AU plug-ins into categories."
    )
    parser.add_argument(
        "--components-dir",
        action="append",
        default=[],
        help=(
            "Audio Units Components directory to scan. May be specified multiple times."
        ),
    )
    parser.add_argument(
        "--tags-dir",
        default="~/Music/Audio Music Apps/Databases/Tags",
        help="Logic Pro Tags directory.",
    )
    parser.add_argument(
        "--mapping",
        default=str(Path(__file__).with_name("plugin_mapping.json")),
        help="Path to plugin mapping JSON.",
    )
    parser.add_argument(
        "--backup-dir",
        default=str(Path(__file__).with_name("backup")),
        help="Directory to store backups.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default is dry run).",
    )
    parser.add_argument(
        "--merge-tags",
        action="store_true",
        help="Merge with existing tags instead of replacing.",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Write JSON report to this path.",
    )
    parser.add_argument(
        "--diagnose",
        action="store_true",
        help="List plugins that fall back to the default category.",
    )
    parser.add_argument(
        "--diagnose-vendor",
        action="append",
        default=[],
        help="Limit diagnose output to a vendor (repeatable).",
    )
    parser.add_argument(
        "--restore-backup",
        default=None,
        help="Restore Tags directory from a backup path.",
    )
    parser.add_argument(
        "--restore-latest",
        action="store_true",
        help="Restore Tags directory from the most recent backup.",
    )
    return parser.parse_args()


def load_mapping(mapping_path: Path) -> dict[str, Any]:
    with mapping_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def strip_vendor_prefix(name: str, vendor: str | None) -> str:
    if not vendor:
        return name
    pattern = r"^\s*" + re.escape(vendor) + r"\s*[:\-]\s*"
    return re.sub(pattern, "", name, flags=re.IGNORECASE)


def detect_vendor(plugin: Plugin, vendor_aliases: dict[str, str]) -> str | None:
    candidates = [
        plugin.bundle_id,
        plugin.bundle_name,
        plugin.name,
        plugin.manufacturer,
    ]
    normalized_candidates = [
        normalize(candidate) for candidate in candidates if candidate
    ]
    for alias, vendor in vendor_aliases.items():
        alias_norm = normalize(alias)
        if not alias_norm:
            continue
        for candidate in normalized_candidates:
            if alias_norm in candidate:
                return vendor
    return None


def load_plugins(components_dirs: Iterable[Path]) -> list[Plugin]:
    plugins: list[Plugin] = []
    for components_dir in components_dirs:
        if not components_dir.exists():
            continue
        for component_path in components_dir.glob("*.component"):
            info_path = component_path / "Contents" / "Info.plist"
            if not info_path.exists():
                continue
            try:
                with info_path.open("rb") as handle:
                    plist = plistlib.load(handle)
            except Exception:
                continue
            audio_components = plist.get("AudioComponents") or []
            if not isinstance(audio_components, list):
                continue
            for entry in audio_components:
                try:
                    plugins.append(
                        Plugin(
                            name=str(entry["name"]),
                            manufacturer=str(entry["manufacturer"]),
                            subtype=str(entry["subtype"]),
                            au_type=str(entry["type"]),
                            bundle_id=str(plist.get("CFBundleIdentifier", "")),
                            bundle_name=str(plist.get("CFBundleName", "")),
                            component_path=component_path,
                        )
                    )
                except KeyError:
                    continue
    return plugins


def match_override(
    plugin: Plugin, vendor: str | None, cleaned_name: str, override: dict[str, Any]
) -> bool:
    for key, value in override.items():
        if key == "category":
            continue
        if key == "name":
            if normalize(cleaned_name) != normalize(str(value)):
                return False
        elif key == "bundle_id":
            if normalize(plugin.bundle_id) != normalize(str(value)):
                return False
        elif key == "vendor":
            if vendor is None or normalize(vendor) != normalize(str(value)):
                return False
        elif key == "pattern":
            if not re.search(str(value), cleaned_name, re.IGNORECASE):
                return False
    return True


def is_excluded(
    plugin: Plugin,
    vendor: str | None,
    cleaned_name: str,
    exclusions: list[dict[str, Any]],
) -> bool:
    for exclusion in exclusions:
        if match_override(plugin, vendor, cleaned_name, exclusion):
            return True
    return False


def match_rules(name: str, rules: list[dict[str, Any]]) -> str | None:
    for rule in rules:
        pattern = rule.get("pattern")
        category = rule.get("category")
        if not pattern or not category:
            continue
        if re.search(pattern, name, re.IGNORECASE):
            return category
    return None


def categorize_plugin(
    plugin: Plugin, mapping: dict[str, Any], vendor_aliases: dict[str, str]
) -> tuple[str | None, str | None, bool]:
    vendor = detect_vendor(plugin, vendor_aliases)
    cleaned_name = strip_vendor_prefix(plugin.name, vendor)

    if is_excluded(plugin, vendor, cleaned_name, mapping.get("exclude", [])):
        return None, vendor, True

    for override in mapping.get("overrides", []):
        if match_override(plugin, vendor, cleaned_name, override):
            return override["category"], vendor, False

    if vendor:
        vendor_rules = mapping.get("vendor_rules", {}).get(vendor, [])
        category = match_rules(cleaned_name, vendor_rules)
        if category:
            return category, vendor, False

    category = match_rules(cleaned_name, mapping.get("rules", []))
    if category:
        return category, vendor, False

    fallback = mapping.get("fallback_category", "Other")
    return fallback, vendor, False


def backup_tags(tags_dir: Path, backup_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_dir = backup_root / f"Tags-backup-{timestamp}"
    backup_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(tags_dir, backup_dir)
    return backup_dir


def update_properties(tags_dir: Path, categories: list[str]) -> None:
    properties_path = tags_dir / "MusicApps.properties"
    with properties_path.open("rb") as handle:
        props = plistlib.load(handle)
    props["sorting"] = categories
    with properties_path.open("wb") as handle:
        plistlib.dump(props, handle)


def update_tagpool(tags_dir: Path, categories: list[str]) -> None:
    tagpool_path = tags_dir / "MusicApps.tagpool"
    with tagpool_path.open("rb") as handle:
        tagpool = plistlib.load(handle)
    for key in list(tagpool.keys()):
        if key != "":
            tagpool.pop(key, None)
    for category in categories:
        tagpool[category] = 0
    with tagpool_path.open("wb") as handle:
        plistlib.dump(tagpool, handle)


def write_tagset(
    tags_dir: Path, plugin: Plugin, category: str, merge_tags: bool
) -> bool:
    tagset_path = tags_dir / f"{plugin.tagset_name()}.tagset"
    if not tagset_path.exists():
        return False
    with tagset_path.open("rb") as handle:
        tagset = plistlib.load(handle)
    tags = tagset.get("tags")
    if not isinstance(tags, dict) or not merge_tags:
        tags = {}
    tags[category] = "user"
    tagset["tags"] = tags
    with tagset_path.open("wb") as handle:
        plistlib.dump(tagset, handle)
    return True


def restore_tags(backup_dir: Path, tags_dir: Path) -> None:
    if not backup_dir.exists():
        raise SystemExit(f"Backup not found: {backup_dir}")
    if tags_dir.exists():
        shutil.rmtree(tags_dir)
    shutil.copytree(backup_dir, tags_dir)


def find_latest_backup(backup_root: Path) -> Path | None:
    if not backup_root.exists():
        return None
    backups = [
        path
        for path in backup_root.iterdir()
        if path.is_dir() and path.name.startswith("Tags-backup-")
    ]
    if not backups:
        return None
    return sorted(backups, key=lambda p: p.name)[-1]


def main() -> None:
    args = parse_args()
    mapping_path = Path(args.mapping).expanduser()
    tags_dir = Path(args.tags_dir).expanduser()
    backup_root = Path(args.backup_dir).expanduser()

    if args.restore_backup or args.restore_latest:
        if args.apply or args.diagnose:
            raise SystemExit("Restore modes cannot be combined with apply/diagnose.")
        if args.restore_backup:
            backup_dir = Path(args.restore_backup).expanduser()
        else:
            backup_dir = find_latest_backup(backup_root)
            if backup_dir is None:
                raise SystemExit(f"No backups found in {backup_root}")
        restore_tags(backup_dir, tags_dir)
        print(f"Tags restored from {backup_dir}")
        return

    components_dirs = args.components_dir or [
        "/Library/Audio/Plug-Ins/Components",
        "~/Library/Audio/Plug-Ins/Components",
    ]
    components_dirs = [Path(path).expanduser() for path in components_dirs]

    mapping = load_mapping(mapping_path)
    categories = mapping.get("categories", [])
    vendor_aliases = mapping.get("vendor_aliases", {})
    fallback_category = mapping.get("fallback_category", "Other")

    plugins = load_plugins(components_dirs)
    results: list[dict[str, Any]] = []
    missing_tagsets: list[dict[str, Any]] = []
    fallback_matches: list[dict[str, Any]] = []
    excluded_plugins: list[dict[str, Any]] = []

    for plugin in plugins:
        category, vendor, excluded = categorize_plugin(plugin, mapping, vendor_aliases)
        result = {
            "name": plugin.name,
            "bundle_id": plugin.bundle_id,
            "vendor": vendor,
            "category": category,
            "tagset": plugin.tagset_name(),
            "excluded": excluded,
        }
        results.append(result)
        if excluded:
            excluded_plugins.append(result)
        elif category == fallback_category:
            fallback_matches.append(result)

    if args.apply:
        if not tags_dir.exists():
            raise SystemExit(f"Tags directory not found: {tags_dir}")
        backup_dir = backup_tags(tags_dir, backup_root)
        print(f"Backup created at {backup_dir}")
        update_properties(tags_dir, categories)
        update_tagpool(tags_dir, categories)

        for plugin in plugins:
            result = next(
                item for item in results if item["tagset"] == plugin.tagset_name()
            )
            if result.get("excluded"):
                continue
            if not write_tagset(tags_dir, plugin, result["category"], args.merge_tags):
                missing_tagsets.append(
                    {
                        "name": plugin.name,
                        "bundle_id": plugin.bundle_id,
                        "tagset": plugin.tagset_name(),
                    }
                )
    else:
        print("Dry run (no files changed). Use --apply to write changes.")

    categorized = len(results)
    missing = len(missing_tagsets)
    print(f"Plugins detected: {categorized}")
    if args.apply:
        print(f"Tagsets missing (not updated): {missing}")

    if args.diagnose:
        vendor_filters = {normalize(v) for v in args.diagnose_vendor if v}
        filtered = []
        for item in fallback_matches:
            vendor_norm = normalize(item.get("vendor") or "")
            if vendor_filters and vendor_norm not in vendor_filters:
                continue
            filtered.append(item)
        print(f"Fallback category matches ({fallback_category}): {len(filtered)}")
        for item in sorted(filtered, key=lambda x: (x.get("vendor") or "", x["name"])):
            vendor_label = item.get("vendor") or "Unknown Vendor"
            bundle_id = item.get("bundle_id") or ""
            suffix = f" [{bundle_id}]" if bundle_id else ""
            print(f"- {vendor_label}: {item['name']}{suffix}")

    if args.report:
        report_path = Path(args.report).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "components_dirs": [str(path) for path in components_dirs],
            "tags_dir": str(tags_dir),
            "apply": bool(args.apply),
            "fallback_category": fallback_category,
            "fallback_matches": fallback_matches,
            "results": results,
            "missing_tagsets": missing_tagsets,
            "excluded": excluded_plugins,
        }
        with report_path.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
        print(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
