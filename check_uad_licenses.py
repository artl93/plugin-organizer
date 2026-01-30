#!/usr/bin/env python3
"""
Check which UAD plugins are installed but not licensed.

This script compares installed UAD plugins against a UA System Profile export
to identify unlicensed plugins.

To export your UA System Profile:
  1. Open the UA Control Panel or UA Connect app
  2. Go to Help > Save System Profile (or similar)
  3. Save the resulting .txt file
  4. Run this script with the path to that file

Usage:
    python check_uad_licenses.py <system_profile.txt>
    python check_uad_licenses.py --help
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


# Default paths where UAD plugins are installed on macOS
DEFAULT_PLUGIN_DIRS = [
    Path("/Library/Audio/Plug-Ins/Components"),
    Path("/Library/Audio/Plug-Ins/VST/Universal Audio"),
    Path("/Library/Audio/Plug-Ins/VST3/Universal Audio"),
    Path("/Library/Application Support/Avid/Audio/Plug-Ins/Universal Audio"),
]


@dataclass
class PluginStatus:
    name: str
    installed_path: Path | None
    licensed: bool
    plugin_format: str
    match_type: str = ""
    matched_license: str = ""


def log(message: str) -> None:
    print(f"[uad-check] {message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check which UAD plugins are installed but not licensed.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python check_uad_licenses.py ~/Desktop/UASystemProfile.txt
    python check_uad_licenses.py --list-installed
    python check_uad_licenses.py profile.txt --show-all
    python check_uad_licenses.py profile.txt --report report.txt

To export your UA System Profile:
    1. Open the UA Control Panel or UA Connect app
    2. Go to Help > Save System Profile
    3. Save the file and provide its path to this script
""",
    )
    parser.add_argument(
        "profile",
        nargs="?",
        help="Path to the UA System Profile export file (.txt)",
    )
    parser.add_argument(
        "--list-installed",
        action="store_true",
        help="Just list all installed UAD plugins without checking licenses.",
    )
    parser.add_argument(
        "--show-all",
        action="store_true",
        help="Show all plugins, not just unlicensed ones.",
    )
    parser.add_argument(
        "--show-licensed",
        action="store_true",
        help="Show only licensed plugins.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Write a detailed report to this file.",
    )
    parser.add_argument(
        "--plugin-dirs",
        action="append",
        default=[],
        help="Additional plugin directories to scan.",
    )
    return parser.parse_args()


def normalize_plugin_name(name: str) -> str:
    """Normalize a plugin name for comparison."""
    # Remove common prefixes/suffixes and normalize whitespace
    name = name.strip()
    # Remove file extensions
    for ext in [".component", ".vst", ".vst3", ".aaxplugin"]:
        if name.lower().endswith(ext):
            name = name[: -len(ext)]
    # Remove Universal Audio prefix for comparison
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
    # Normalize whitespace and case
    return re.sub(r"\s+", " ", name).strip().lower()


def tokenize(name: str) -> list[str]:
    name = normalize_plugin_name(name)
    name = re.sub(r"[^a-z0-9]+", " ", name)
    return [token for token in name.split() if token]


def is_numeric_token(token: str) -> bool:
    return token.isdigit()


def is_collection_name(name: str) -> bool:
    name = normalize_plugin_name(name)
    return any(
        keyword in name for keyword in ["collection", "bundle", "pack", "series"]
    )


def get_installed_uad_plugins(plugin_dirs: list[Path]) -> dict[str, list[Path]]:
    """
    Scan plugin directories and return installed UAD plugins.
    Returns a dict mapping normalized plugin names to their install paths.
    """
    installed: dict[str, list[Path]] = {}

    for plugin_dir in plugin_dirs:
        if not plugin_dir.exists():
            continue

        # Look for UAD plugins in various formats
        patterns = [
            "UAD *.component",
            "UAD*.component",
            "*.vst",
            "*.vst3",
            "*.aaxplugin",
        ]

        for pattern in patterns:
            for plugin_path in plugin_dir.glob(pattern):
                # Only include UAD plugins
                if not plugin_path.name.upper().startswith("UAD"):
                    continue

                plugin_name = plugin_path.stem
                normalized = normalize_plugin_name(plugin_name)

                if normalized not in installed:
                    installed[normalized] = []
                installed[normalized].append(plugin_path)

    return installed


def parse_system_profile(profile_path: Path) -> set[str]:
    """
    Parse a UA System Profile export file to extract licensed plugin names.
    Returns a set of normalized plugin names that are licensed.

    The profile format has lines like:
        UAD Plugin Name: Authorized for all devices
        UAD Plugin Name: Demo not started
        UAD Plugin Name: Demo expired
    """
    if not profile_path.exists():
        raise FileNotFoundError(f"System profile not found: {profile_path}")

    content = profile_path.read_text(encoding="utf-8", errors="replace")
    licensed_plugins: set[str] = set()

    for line in content.splitlines():
        line_stripped = line.strip()
        line_lower = line_stripped.lower()

        # Skip empty lines and section headers
        if not line_stripped or line_stripped.startswith("-"):
            continue

        # Look for lines with authorization status
        # Format: "UAD Plugin Name: Authorized for all devices"
        if ": " in line_stripped and "uad" in line_lower:
            # Split on the LAST colon to handle plugin names with colons
            colon_idx = line_stripped.rfind(": ")
            if colon_idx > 0:
                plugin_name = line_stripped[:colon_idx].strip()
                status = line_stripped[colon_idx + 2 :].strip().lower()

                # Check if this plugin is authorized
                if "authorized" in status:
                    normalized = normalize_plugin_name(plugin_name)
                    if normalized and len(normalized) > 2:
                        licensed_plugins.add(normalized)

    return licensed_plugins


def match_license(
    installed_name: str, licensed_names: set[str]
) -> tuple[bool, str, str]:
    """Return (matched, match_type, matched_license_name)."""
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

    return False, "", ""


def get_plugin_format(path: Path) -> str:
    """Determine the plugin format from its path/extension."""
    if path.suffix == ".component":
        return "AU"
    elif path.suffix == ".vst":
        return "VST"
    elif path.suffix == ".vst3":
        return "VST3"
    elif path.suffix == ".aaxplugin":
        return "AAX"
    return "Unknown"


def main() -> None:
    args = parse_args()

    # Build list of plugin directories
    plugin_dirs = DEFAULT_PLUGIN_DIRS.copy()
    for extra_dir in args.plugin_dirs:
        plugin_dirs.append(Path(extra_dir).expanduser())

    # Get installed plugins
    log("Scanning for installed UAD plugins")
    installed = get_installed_uad_plugins(plugin_dirs)

    if not installed:
        log("No UAD plugins found in the scanned directories.")
        print("Scanned directories:")
        for d in plugin_dirs:
            print(f"  - {d}")
        return

    # Just list installed plugins if requested
    if args.list_installed:
        print(f"Found {len(installed)} UAD plugins installed:\n")
        for name in sorted(installed.keys()):
            paths = installed[name]
            display_name = paths[0].stem if paths else name
            formats = ", ".join(sorted(set(get_plugin_format(p) for p in paths)))
            print(f"  {display_name} ({formats})")
        return

    # Need a profile file to check licenses
    if not args.profile:
        log("Error: profile file is required")
        print("Please provide a UA System Profile file path.\n")
        print("To export your UA System Profile:")
        print("  1. Open the UA Control Panel or UA Connect app")
        print("  2. Go to Help > Save System Profile")
        print("  3. Save the file and run:")
        print(f"     python {sys.argv[0]} <path_to_profile.txt>")
        print("\nOr use --list-installed to just see installed plugins.")
        sys.exit(1)

    profile_path = Path(args.profile).expanduser()

    try:
        licensed = parse_system_profile(profile_path)
    except FileNotFoundError as e:
        log(f"Error: {e}")
        sys.exit(1)

    if not licensed:
        log("Warning: could not find licensed plugins in the system profile.")
        print("The file format may not be recognized or the file may be empty.")
        print(f"Profile file: {profile_path}")
        print("\nPlease ensure you exported the system profile from:")
        print("  UA Control Panel > Help > Save System Profile")
        sys.exit(1)

    # Compare installed vs licensed
    unlicensed: list[PluginStatus] = []
    licensed_installed: list[PluginStatus] = []

    for norm_name, paths in installed.items():
        is_licensed, match_type, match_name = match_license(norm_name, licensed)
        display_name = paths[0].stem if paths else norm_name
        formats = ", ".join(sorted(set(get_plugin_format(p) for p in paths)))

        status = PluginStatus(
            name=display_name,
            installed_path=paths[0] if paths else None,
            licensed=is_licensed,
            plugin_format=formats,
            match_type=match_type,
            matched_license=match_name,
        )

        if is_licensed:
            licensed_installed.append(status)
        else:
            unlicensed.append(status)

    # Sort by name
    unlicensed.sort(key=lambda x: x.name.lower())
    licensed_installed.sort(key=lambda x: x.name.lower())

    # Output results
    if args.show_all:
        print("=== UAD Plugin License Check ===\n")
        print(f"Profile: {profile_path}")
        print(f"Licensed plugins found in profile: {len(licensed)}")
        print(f"Installed UAD plugins: {len(installed)}")
        print()

        if licensed_installed:
            print(f"✓ Licensed ({len(licensed_installed)}):")
            for p in licensed_installed:
                match = (
                    f" [{p.match_type}: {p.matched_license}]" if p.match_type else ""
                )
                print(f"    {p.name} ({p.plugin_format}){match}")
            print()

        if unlicensed:
            print(f"✗ Unlicensed ({len(unlicensed)}):")
            for p in unlicensed:
                print(f"    {p.name} ({p.plugin_format})")
    elif args.show_licensed:
        if licensed_installed:
            print(f"Licensed UAD plugins ({len(licensed_installed)}):\n")
            for p in licensed_installed:
                match = (
                    f" [{p.match_type}: {p.matched_license}]" if p.match_type else ""
                )
                print(f"  ✓ {p.name} ({p.plugin_format}){match}")
        else:
            print("No licensed UAD plugins found installed.")
    else:
        # Default: show only unlicensed
        if unlicensed:
            print(f"Unlicensed UAD plugins ({len(unlicensed)}):\n")
            for p in unlicensed:
                print(f"  ✗ {p.name} ({p.plugin_format})")
            print(
                f"\nTotal: {len(unlicensed)} unlicensed out of {len(installed)} installed"
            )
        else:
            print("All installed UAD plugins are licensed! ✓")
            print(f"({len(licensed_installed)} plugins checked)")

    # Write report if requested
    if args.report:
        with args.report.open("w", encoding="utf-8") as f:
            f.write("UAD Plugin License Report\n")
            f.write("=" * 50 + "\n\n")
            f.write(f"Profile: {profile_path}\n")
            f.write(f"Licensed in profile: {len(licensed)}\n")
            f.write(f"Installed: {len(installed)}\n")
            f.write(f"Licensed & installed: {len(licensed_installed)}\n")
            f.write(f"Unlicensed: {len(unlicensed)}\n\n")

            f.write("Licensed Plugins:\n")
            f.write("-" * 30 + "\n")
            for p in licensed_installed:
                match = (
                    f" [{p.match_type}: {p.matched_license}]" if p.match_type else ""
                )
                f.write(f"  ✓ {p.name} ({p.plugin_format}){match}\n")

            f.write("\nUnlicensed Plugins:\n")
            f.write("-" * 30 + "\n")
            for p in unlicensed:
                f.write(f"  ✗ {p.name} ({p.plugin_format})\n")
                if p.installed_path:
                    f.write(f"      Path: {p.installed_path}\n")

        log(f"Report written to: {args.report}")


if __name__ == "__main__":
    main()
