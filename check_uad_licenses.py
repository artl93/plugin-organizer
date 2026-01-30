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
    # Remove "UAD " prefix for comparison
    if name.upper().startswith("UAD "):
        name = name[4:]
    # Normalize whitespace and case
    return re.sub(r"\s+", " ", name).strip().lower()


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
        patterns = ["UAD *.component", "UAD*.component", "*.vst", "*.vst3", "*.aaxplugin"]

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


def fuzzy_match(installed_name: str, licensed_names: set[str]) -> bool:
    """Check if an installed plugin name matches any licensed plugin name."""
    # Exact match
    if installed_name in licensed_names:
        return True

    # Check if installed name is contained in any licensed name or vice versa
    for licensed in licensed_names:
        if installed_name in licensed or licensed in installed_name:
            return True

        # Handle common variations
        # e.g., "1176 limiter" vs "ua 1176 limiter collection"
        installed_words = set(installed_name.split())
        licensed_words = set(licensed.split())

        # If most significant words match
        common = installed_words & licensed_words
        if len(common) >= min(len(installed_words), len(licensed_words)) * 0.6:
            return True

    return False


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
    installed = get_installed_uad_plugins(plugin_dirs)

    if not installed:
        print("No UAD plugins found in the scanned directories.")
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
        print("Error: Please provide a UA System Profile file path.\n")
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
        print(f"Error: {e}")
        sys.exit(1)

    if not licensed:
        print("Warning: Could not find any licensed plugins in the system profile.")
        print("The file format may not be recognized or the file may be empty.")
        print(f"Profile file: {profile_path}")
        print("\nPlease ensure you exported the system profile from:")
        print("  UA Control Panel > Help > Save System Profile")
        sys.exit(1)

    # Compare installed vs licensed
    unlicensed: list[PluginStatus] = []
    licensed_installed: list[PluginStatus] = []

    for norm_name, paths in installed.items():
        is_licensed = fuzzy_match(norm_name, licensed)
        display_name = paths[0].stem if paths else norm_name
        formats = ", ".join(sorted(set(get_plugin_format(p) for p in paths)))

        status = PluginStatus(
            name=display_name,
            installed_path=paths[0] if paths else None,
            licensed=is_licensed,
            plugin_format=formats,
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
        print(f"=== UAD Plugin License Check ===\n")
        print(f"Profile: {profile_path}")
        print(f"Licensed plugins found in profile: {len(licensed)}")
        print(f"Installed UAD plugins: {len(installed)}")
        print()

        if licensed_installed:
            print(f"✓ Licensed ({len(licensed_installed)}):")
            for p in licensed_installed:
                print(f"    {p.name} ({p.plugin_format})")
            print()

        if unlicensed:
            print(f"✗ Unlicensed ({len(unlicensed)}):")
            for p in unlicensed:
                print(f"    {p.name} ({p.plugin_format})")
    elif args.show_licensed:
        if licensed_installed:
            print(f"Licensed UAD plugins ({len(licensed_installed)}):\n")
            for p in licensed_installed:
                print(f"  ✓ {p.name} ({p.plugin_format})")
        else:
            print("No licensed UAD plugins found installed.")
    else:
        # Default: show only unlicensed
        if unlicensed:
            print(f"Unlicensed UAD plugins ({len(unlicensed)}):\n")
            for p in unlicensed:
                print(f"  ✗ {p.name} ({p.plugin_format})")
            print(f"\nTotal: {len(unlicensed)} unlicensed out of {len(installed)} installed")
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
                f.write(f"  ✓ {p.name} ({p.plugin_format})\n")

            f.write("\nUnlicensed Plugins:\n")
            f.write("-" * 30 + "\n")
            for p in unlicensed:
                f.write(f"  ✗ {p.name} ({p.plugin_format})\n")
                if p.installed_path:
                    f.write(f"      Path: {p.installed_path}\n")

        print(f"\nReport written to: {args.report}")


if __name__ == "__main__":
    main()
