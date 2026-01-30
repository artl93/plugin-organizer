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
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


DEFAULT_COMPONENT_DIRS = [
    Path("/Library/Audio/Plug-Ins/Components"),
    Path("~/Library/Audio/Plug-Ins/Components").expanduser(),
]


def log(message: str) -> None:
    print(f"[uad-hide] {message}")


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
        "--backup-dir",
        default=str(Path(__file__).with_name("backup")),
        help="Directory to store Tags backups.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default is dry run).",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear hide flags for all UAD AU tagsets.",
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
    name = re.sub(
        r"^\s*universal audio(\s*\(uad[^\)]*\))?\s*:\s*",
        "",
        name,
        flags=re.IGNORECASE,
    )
    if name.upper().startswith("UAD "):
        name = name[4:]
    if name.upper().startswith("UADX "):
        name = name[5:]
    if name.upper().startswith("UAD-2 "):
        name = name[6:]
    name = re.sub(r"\s+", " ", name).strip().lower()
    return name


def tokenize(name: str) -> list[str]:
    name = normalize_plugin_name(name)
    name = re.sub(r"[^a-z0-9]+", " ", name)
    return [token for token in name.split() if token]


def canonicalize(name: str) -> str:
    name = normalize_plugin_name(name)
    return re.sub(r"[^a-z0-9]+", "", name)


def is_numeric_token(token: str) -> bool:
    return token.isdigit()


def is_collection_name(name: str) -> bool:
    name = normalize_plugin_name(name)
    return any(
        keyword in name for keyword in ["collection", "bundle", "pack", "series"]
    )


def is_uadx_component(name: str) -> bool:
    return "uadx" in name.lower()


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


def match_license(
    installed_name: str, licensed_names: set[str]
) -> tuple[bool, str, str]:
    installed_norm = normalize_plugin_name(installed_name)
    if installed_norm in licensed_names:
        return True, "exact", installed_norm

    base_stopwords = {
        "uad",
        "ua",
        "uadx",
        "universal",
        "audio",
        "plugin",
        "plugins",
        "collection",
        "bundle",
        "pack",
        "series",
        "edition",
        "legacy",
        "mk",
        "mk2",
        "mkii",
        "mono",
        "stereo",
        "mix",
        "master",
        "limited",
        "expanded",
        "version",
    }
    descriptor_stopwords = {
        "digital",
        "analog",
        "reverb",
        "delay",
        "echo",
        "tape",
        "mastering",
        "recorder",
        "pitch",
        "shifter",
        "amp",
        "amplifier",
        "guitar",
        "bass",
        "classic",
        "super",
        "lead",
        "deluxe",
        "silver",
        "jubilee",
        "bluesbreaker",
        "tweed",
        "vintage",
        "leveler",
        "jr",
        "sr",
        "el7",
        "el8",
        "room",
        "channel",
        "strip",
        "compressor",
        "limiter",
        "eq",
        "preamp",
        "preamplifier",
        "mic",
        "microphone",
    }

    for licensed in licensed_names:
        licensed_norm = normalize_plugin_name(licensed)
        installed_tokens = set(tokenize(installed_norm))
        licensed_tokens = set(tokenize(licensed_norm))
        if not installed_tokens or not licensed_tokens:
            continue

        common = installed_tokens & licensed_tokens
        if not common:
            continue

        if is_collection_name(licensed_norm):
            collection_tokens = licensed_tokens - base_stopwords - descriptor_stopwords
            if collection_tokens and collection_tokens.issubset(
                installed_tokens - base_stopwords
            ):
                return True, "collection-token", licensed
            if installed_norm in licensed_norm or licensed_norm in installed_norm:
                return True, "collection-substring", licensed
            continue

        installed_diff = (
            (installed_tokens - common) - base_stopwords - descriptor_stopwords
        )
        licensed_diff = (
            (licensed_tokens - common) - base_stopwords - descriptor_stopwords
        )
        if not installed_diff and not licensed_diff:
            return True, "token-compatible", licensed

        installed_core = installed_tokens - base_stopwords - descriptor_stopwords
        licensed_core = licensed_tokens - base_stopwords - descriptor_stopwords
        if installed_core and installed_core.issubset(licensed_core):
            return True, "core-subset", licensed

        extra_installed = installed_core - licensed_core
        if extra_installed and all(
            is_numeric_token(token) for token in extra_installed
        ):
            return True, "core-plus-numeric", licensed

        installed_canonical = canonicalize(installed_norm)
        licensed_canonical = canonicalize(licensed_norm)
        if installed_canonical and licensed_canonical:
            if (
                installed_canonical in licensed_canonical
                or licensed_canonical in installed_canonical
            ):
                return True, "canonical-substring", licensed

    return False, "", ""


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


def backup_tags(tags_dir: Path, backup_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_dir = backup_root / f"Tags-backup-{timestamp}"
    backup_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(tags_dir, backup_dir)
    return backup_dir


def main() -> None:
    args = parse_args()
    tags_dir = Path(args.tags_dir).expanduser()
    manifest_path = Path(args.manifest).expanduser()
    backup_root = Path(args.backup_dir).expanduser()

    if args.restore:
        log("Restoring hide flags")
        entries = load_manifest(manifest_path)
        if not entries:
            log("No manifest found; nothing to restore.")
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
        log(f"Restored {restored} tagsets.")
        return

    if args.clear:
        components_dirs = args.components_dir or DEFAULT_COMPONENT_DIRS
        components_dirs = [Path(path).expanduser() for path in components_dirs]
        log("Scanning UAD AU components")
        components = scan_uad_components(components_dirs)
        log(f"Found {len(components)} UAD AU entries")

        if not args.apply:
            log("Dry run (no files changed). Use --apply to clear hide flags.")
            for component in components:
                tagset_path = tags_dir / f"{component.tagset_name()}.tagset"
                if tagset_path.exists():
                    log(f"Would clear hide: {tagset_path.name}")
            return

        if not tags_dir.exists():
            raise SystemExit(f"Tags directory not found: {tags_dir}")

        log("Creating Tags backup")
        backup_path = backup_tags(tags_dir, backup_root)
        log(f"Backup created at {backup_path}")

        cleared = 0
        for component in components:
            tagset_path = tags_dir / f"{component.tagset_name()}.tagset"
            if not tagset_path.exists():
                continue
            with tagset_path.open("rb") as handle:
                plist = plistlib.load(handle)
            if "hide" not in plist:
                continue
            plist.pop("hide", None)
            with tagset_path.open("wb") as handle:
                plistlib.dump(plist, handle)
            cleared += 1
        log(f"Cleared hide flags for {cleared} tagsets.")
        return

    if not args.profile:
        raise SystemExit("Provide a UA System Profile file or use --restore.")

    profile_path = Path(args.profile).expanduser()
    if not profile_path.exists():
        raise SystemExit(f"Profile not found: {profile_path}")

    components_dirs = args.components_dir or DEFAULT_COMPONENT_DIRS
    components_dirs = [Path(path).expanduser() for path in components_dirs]

    log("Parsing UA System Profile")
    licensed = parse_system_profile(profile_path)
    log("Scanning UAD AU components")
    components = scan_uad_components(components_dirs)
    log(f"Found {len(components)} UAD AU entries")

    licensed_matches = []
    unlicensed = []
    for component in components:
        if is_uadx_component(component.name):
            matched, match_type, match_name = True, "uadx", "uadx"
        else:
            matched, match_type, match_name = match_license(
                component.normalized, licensed
            )
        record = {
            "name": component.name,
            "tagset": component.tagset_name(),
            "component": str(component.component_path),
            "match_type": match_type,
            "matched_license": match_name,
        }
        if matched:
            licensed_matches.append(record)
        else:
            unlicensed.append(component)
    log(f"Unlicensed AU entries: {len(unlicensed)}")

    if not unlicensed:
        log("No unlicensed UAD AU components found.")
        return

    report = {
        "profile": str(profile_path),
        "tags_dir": str(tags_dir),
        "components_dirs": [str(path) for path in components_dirs],
        "unlicensed_count": len(unlicensed),
        "licensed_count": len(licensed_matches),
        "unlicensed": [
            {
                "name": component.name,
                "tagset": component.tagset_name(),
                "component": str(component.component_path),
            }
            for component in unlicensed
        ],
        "licensed": licensed_matches,
    }

    if not args.apply:
        log("Dry run (no files changed). Use --apply to hide tagsets.")
        log(f"Unlicensed components: {len(unlicensed)}")
        for component in sorted(unlicensed, key=lambda c: c.name.lower()):
            print(f"- {component.name}")
        if args.report:
            report_path = Path(args.report).expanduser()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(
                json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
            )
            log(f"Report written to {report_path}")
        return

    if not tags_dir.exists():
        raise SystemExit(f"Tags directory not found: {tags_dir}")

    log("Creating Tags backup")
    backup_path = backup_tags(tags_dir, backup_root)
    log(f"Backup created at {backup_path}")
    report["backup"] = str(backup_path)

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
    log(f"Hidden {hidden} UAD AU tagsets.")
    log(f"Manifest saved to {manifest_path}")

    if args.report:
        report_path = Path(args.report).expanduser()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
        )
        log(f"Report written to {report_path}")


if __name__ == "__main__":
    main()
