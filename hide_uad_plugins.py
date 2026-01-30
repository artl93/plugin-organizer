#!/usr/bin/env python3
"""
Hide unlicensed UAD Audio Units in Logic by setting tagset hide flags.

This reads a UA System Profile export, finds installed UAD AU components,
and writes a `hide` key into their Logic tagset files when unlicensed.

Usage:
  python hide_uad_plugins.py reports/UADSystemProfile.txt
  python hide_uad_plugins.py reports/UADSystemProfile.txt --apply
  python hide_uad_plugins.py --restore
"""

import argparse
import base64
import json
import plistlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_COMPONENT_DIRS = [
    Path("/Library/Audio/Plug-Ins/Components"),
    Path("~/Library/Audio/Plug-Ins/Components").expanduser(),
]


@dataclass(frozen=True)
class UadComponent:
    name: str
    normalized: str
    component_path: Path
    au_type: str
    subtype: str
    manufacturer: str

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
        description="Hide unlicensed UAD AU plug-ins in Logic.",
    )
    parser.add_argument(
        "profile",
        nargs="?",
        help="Path to the UA System Profile export file (.txt)",
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
        "--apply",
        action="store_true",
        help="Apply changes (default is dry run).",
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="Restore hide flags using the manifest.",
    )
    parser.add_argument(
        "--manifest",
        default="./reports/uad-hidden-tagsets.json",
        help="Path to manifest file for restore.",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Write a JSON report to this path.",
    )
    return parser.parse_args()


def normalize_plugin_name(name: str) -> str:
    name = name.strip()
    if name.lower().endswith(".component"):
        name = name[: -len(".component")]
    name = re.sub(r"^\s*universal audio\s*:\s*", "", name, flags=re.IGNORECASE)
    if name.upper().startswith("UAD "):
        name = name[4:]
    return re.sub(r"\s+", " ", name).strip().lower()


def parse_system_profile(profile_path: Path) -> set[str]:
    content = profile_path.read_text(encoding="utf-8", errors="replace")
    licensed_plugins: set[str] = set()
    for line in content.splitlines():
        line_stripped = line.strip()
        line_lower = line_stripped.lower()
        if not line_stripped or line_stripped.startswith("-"):
            continue
        if ": " in line_stripped and "uad" in line_lower:
            colon_idx = line_stripped.rfind(": ")
            if colon_idx > 0:
                plugin_name = line_stripped[:colon_idx].strip()
                status = line_stripped[colon_idx + 2 :].strip().lower()
                if "authorized" in status:
                    normalized = normalize_plugin_name(plugin_name)
                    if normalized and len(normalized) > 2:
                        licensed_plugins.add(normalized)
    return licensed_plugins


def fuzzy_match(installed_name: str, licensed_names: set[str]) -> bool:
    if installed_name in licensed_names:
        return True
    for licensed in licensed_names:
        if installed_name in licensed or licensed in installed_name:
            return True
        installed_words = set(installed_name.split())
        licensed_words = set(licensed.split())
        common = installed_words & licensed_words
        if len(common) >= min(len(installed_words), len(licensed_words)) * 0.6:
            return True
    return False


def scan_uad_components(components_dirs: Iterable[Path]) -> list[UadComponent]:
    components: list[UadComponent] = []
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
                name = str(entry.get("name") or "")
                if (
                    "uad" not in name.lower()
                    and not component_path.name.upper().startswith("UAD")
                ):
                    continue
                try:
                    au_type = str(entry["type"])
                    subtype = str(entry["subtype"])
                    manufacturer = str(entry["manufacturer"])
                except KeyError:
                    continue
                normalized = normalize_plugin_name(name)
                components.append(
                    UadComponent(
                        name=name,
                        normalized=normalized,
                        component_path=component_path,
                        au_type=au_type,
                        subtype=subtype,
                        manufacturer=manufacturer,
                    )
                )
    return components


def load_manifest(manifest_path: Path) -> list[dict[str, str]]:
    if not manifest_path.exists():
        return []
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def write_manifest(manifest_path: Path, entries: list[dict[str, str]]) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(entries, indent=2, sort_keys=True), encoding="utf-8"
    )


def dump_plist(plist: dict) -> str:
    return base64.b64encode(plistlib.dumps(plist)).decode("ascii")


def load_plist(encoded: str) -> dict:
    return plistlib.loads(base64.b64decode(encoded.encode("ascii")))


def main() -> None:
    args = parse_args()
    tags_dir = Path(args.tags_dir).expanduser()
    manifest_path = Path(args.manifest).expanduser()

    if args.restore:
        entries = load_manifest(manifest_path)
        if not entries:
            print("No manifest found; nothing to restore.")
            return
        restored = 0
        for entry in entries:
            tagset_path = Path(entry["tagset_path"])
            existed = entry["existed"] == "true"
            if not existed:
                if args.apply and tagset_path.exists():
                    tagset_path.unlink()
                restored += 1
                continue
            if args.apply:
                plist = load_plist(entry["plist_b64"])
                tagset_path.parent.mkdir(parents=True, exist_ok=True)
                with tagset_path.open("wb") as handle:
                    plistlib.dump(plist, handle)
            restored += 1
        if args.apply:
            manifest_path.unlink(missing_ok=True)
        print(f"Restored {restored} tagsets.")
        return

    if not args.profile:
        raise SystemExit("Provide a UA System Profile file or use --restore.")

    profile_path = Path(args.profile).expanduser()
    if not profile_path.exists():
        raise SystemExit(f"Profile not found: {profile_path}")

    components_dirs = args.components_dir or DEFAULT_COMPONENT_DIRS
    components_dirs = [Path(path).expanduser() for path in components_dirs]

    licensed = parse_system_profile(profile_path)
    components = scan_uad_components(components_dirs)

    unlicensed = [
        component
        for component in components
        if not fuzzy_match(component.normalized, licensed)
    ]

    if not unlicensed:
        print("No unlicensed UAD AU components found.")
        return

    report = {
        "profile": str(profile_path),
        "tags_dir": str(tags_dir),
        "components_dirs": [str(path) for path in components_dirs],
        "unlicensed_count": len(unlicensed),
        "unlicensed": [
            {
                "name": component.name,
                "tagset": component.tagset_name(),
                "component": str(component.component_path),
            }
            for component in unlicensed
        ],
    }

    if args.report:
        report_path = Path(args.report).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        print(f"Report written to {report_path}")

    if not args.apply:
        print("Dry run (no files changed). Use --apply to hide tagsets.")
        print(f"Unlicensed components: {len(unlicensed)}")
        for component in sorted(unlicensed, key=lambda c: c.name.lower()):
            print(f"- {component.name}")
        return

    tags_dir.mkdir(parents=True, exist_ok=True)
    manifest_entries: list[dict[str, str]] = []
    hidden = 0
    for component in unlicensed:
        tagset_path = tags_dir / f"{component.tagset_name()}.tagset"
        existed = tagset_path.exists()
        if existed:
            with tagset_path.open("rb") as handle:
                existing_plist = plistlib.load(handle)
        else:
            existing_plist = {}

        manifest_entries.append(
            {
                "tagset_path": str(tagset_path),
                "existed": "true" if existed else "false",
                "plist_b64": dump_plist(existing_plist),
            }
        )

        existing_plist["hide"] = ""
        with tagset_path.open("wb") as handle:
            plistlib.dump(existing_plist, handle)
        hidden += 1

    write_manifest(manifest_path, manifest_entries)
    print(f"Hidden {hidden} UAD AU tagsets.")
    print(f"Manifest saved to {manifest_path}")


if __name__ == "__main__":
    main()
