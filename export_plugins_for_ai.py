#!/usr/bin/env python3
"""
Export installed AU plug-ins and Logic categories for AI mapping.
"""

import argparse
import json
import plistlib
from datetime import datetime
from pathlib import Path
from typing import Iterable


def log(message: str) -> None:
    print(f"[export] {message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export installed AU plug-ins for AI mapping.",
    )
    parser.add_argument(
        "--components-dir",
        action="append",
        default=[],
        help="Audio Units Components directory to scan (repeatable).",
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
        "--output",
        default="./reports/au-plugins.json",
        help="Write JSON output to this path.",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=100000,
        help="Maximum output size in bytes (default 100000).",
    )
    return parser.parse_args()


def load_tags_categories(tags_dir: Path) -> dict[str, list[str]]:
    properties_path = tags_dir / "MusicApps.properties"
    tagpool_path = tags_dir / "MusicApps.tagpool"
    categories = {"sorting": [], "tagpool": []}

    if properties_path.exists():
        with properties_path.open("rb") as handle:
            props = plistlib.load(handle)
        categories["sorting"] = props.get("sorting") or []

    if tagpool_path.exists():
        with tagpool_path.open("rb") as handle:
            tagpool = plistlib.load(handle)
        categories["tagpool"] = sorted([key for key in tagpool.keys() if key])

    return categories


def scan_components(components_dirs: Iterable[Path]) -> list[dict[str, str]]:
    plugins: list[dict[str, str]] = []
    for components_dir in components_dirs:
        if not components_dir.exists():
            continue
        log(f"Scanning {components_dir}")
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
                    au_type = str(entry["type"])
                    subtype = str(entry["subtype"])
                    manufacturer = str(entry["manufacturer"])
                    tagset = (
                        au_type.encode().hex()
                        + "-"
                        + subtype.encode().hex()
                        + "-"
                        + manufacturer.encode().hex()
                    )
                    plugins.append(
                        {
                            "name": str(entry["name"]),
                            "manufacturer": manufacturer,
                            "au_type": au_type,
                            "subtype": subtype,
                            "bundle_id": str(plist.get("CFBundleIdentifier", "")),
                            "bundle_name": str(plist.get("CFBundleName", "")),
                            "component_path": str(component_path),
                            "tagset": tagset,
                        }
                    )
                except KeyError:
                    continue
    return plugins


def load_hidden_tagsets(tags_dir: Path) -> set[str]:
    hidden: set[str] = set()
    if not tags_dir.exists():
        return hidden
    for tagset_path in tags_dir.glob("*.tagset"):
        try:
            with tagset_path.open("rb") as handle:
                plist = plistlib.load(handle)
        except Exception:
            continue
        if "hide" in plist:
            hidden.add(tagset_path.stem)
    return hidden


def load_mapping(mapping_path: Path) -> dict:
    if not mapping_path.exists():
        return {}
    return json.loads(mapping_path.read_text(encoding="utf-8"))


def main() -> None:
    args = parse_args()
    components_dirs = args.components_dir or [
        "/Library/Audio/Plug-Ins/Components",
        "~/Library/Audio/Plug-Ins/Components",
    ]
    components_dirs = [Path(path).expanduser() for path in components_dirs]
    tags_dir = Path(args.tags_dir).expanduser()
    output_path = Path(args.output).expanduser()
    mapping_path = Path(args.mapping).expanduser()

    log("Loading Logic categories")
    categories = load_tags_categories(tags_dir)

    log("Scanning Audio Units components")
    plugins = scan_components(components_dirs)
    log(f"Found {len(plugins)} AU entries")

    log("Loading hidden tagsets")
    hidden_tagsets = load_hidden_tagsets(tags_dir)
    if hidden_tagsets:
        before_count = len(plugins)
        plugins = [p for p in plugins if p.get("tagset") not in hidden_tagsets]
        log(f"Filtered hidden tagsets: {before_count - len(plugins)} removed")

    log("Loading current plugin mapping")
    mapping = load_mapping(mapping_path)

    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tags_dir": str(tags_dir),
        "components_dirs": [str(path) for path in components_dirs],
        "categories": categories,
        "plugins": plugins,
        "current_mapping": mapping,
    }

    output_json = json.dumps(output, indent=2, sort_keys=True)
    if len(output_json.encode("utf-8")) > args.max_bytes:
        log("Output exceeds max size; trimming plugin list")
        trimmed = plugins
        while len(trimmed) > 0:
            trimmed = trimmed[: max(1, int(len(trimmed) * 0.8))]
            output["plugins"] = trimmed
            output_json = json.dumps(output, indent=2, sort_keys=True)
            if len(output_json.encode("utf-8")) <= args.max_bytes:
                break
        if len(output_json.encode("utf-8")) > args.max_bytes:
            output["plugins"] = trimmed[: max(1, int(len(trimmed) * 0.5))]
            output_json = json.dumps(output, indent=2, sort_keys=True)
        log(f"Trimmed plugins to {len(output['plugins'])} entries")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(output_json, encoding="utf-8")
    log(f"Wrote {output_path} ({len(output_json.encode('utf-8'))} bytes)")


if __name__ == "__main__":
    main()
