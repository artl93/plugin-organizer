#!/usr/bin/env python3
"""
Run the full Logic plug-in organization workflow.
"""

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def log(message: str) -> None:
    print(f"[workflow] {message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the full plug-in organization workflow.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes (default is dry run).",
    )
    parser.add_argument(
        "--tags-dir",
        default="~/Music/Audio Music Apps/Databases/Tags",
        help="Logic Pro Tags directory.",
    )
    parser.add_argument(
        "--backup-dir",
        default=str(Path(__file__).with_name("backup")),
        help="Directory to store tag backups.",
    )
    parser.add_argument(
        "--profile",
        default="./reports/UADSystemProfile.txt",
        help="UA System Profile export path.",
    )
    parser.add_argument(
        "--mapping",
        default=str(Path(__file__).with_name("plugin_mapping.json")),
        help="Base mapping file path.",
    )
    parser.add_argument(
        "--generated-mapping",
        default="./plugin_mapping.generated.json",
        help="AI-generated mapping output path.",
    )
    parser.add_argument(
        "--max-bytes",
        type=int,
        default=100000,
        help="Maximum AI input size in bytes (default 100000).",
    )
    parser.add_argument(
        "--restore",
        action="store_true",
        help="Restore tags from backup using the TUI.",
    )
    parser.add_argument(
        "--skip-uad",
        action="store_true",
        help="Skip UAD hide step (for systems without UAD).",
    )
    return parser.parse_args()


def run_step(command: list[str]) -> subprocess.CompletedProcess[str]:
    log(f"Running: {' '.join(command)}")
    return subprocess.run(command, text=True)


def backup_tags(tags_dir: Path, backup_root: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_dir = backup_root / f"Tags-backup-{timestamp}"
    backup_root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(tags_dir, backup_dir)
    return backup_dir


def main() -> None:
    args = parse_args()
    tags_dir = Path(args.tags_dir).expanduser()
    backup_root = Path(args.backup_dir).expanduser()
    reports_dir = Path("./reports")
    reports_dir.mkdir(parents=True, exist_ok=True)

    if args.restore:
        run_step(
            [sys.executable, "restore_tags_tui.py", "--backup-dir", str(backup_root)]
        )
        return

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    workflow_report = reports_dir / f"workflow-{timestamp}.json"
    steps: list[str] = []
    summary: dict[str, str | bool | list[str]] = {
        "apply": bool(args.apply),
        "steps": steps,
    }

    if args.apply:
        if not tags_dir.exists():
            raise SystemExit(f"Tags directory not found: {tags_dir}")
        log("Creating initial Tags backup")
        backup_path = backup_tags(tags_dir, backup_root)
        log(f"Backup created at {backup_path}")
        summary["initial_backup"] = str(backup_path)
    else:
        log("Dry run: no backup created")

    if args.skip_uad:
        log("Skipping UAD hide step")
        steps.append("hide_uad_plugins (skipped)")
    else:
        log("Hiding unlicensed UAD plug-ins")
        profile_path = Path(args.profile).expanduser()
        if not profile_path.exists():
            raise SystemExit(f"Profile not found: {profile_path}")
        hide_command = [
            sys.executable,
            "hide_uad_plugins.py",
            str(profile_path),
            "--report",
            f"./reports/uad-hide-report-{timestamp}.json",
        ]
        if args.apply:
            hide_command.append("--apply")
        result = run_step(hide_command)
        steps.append("hide_uad_plugins")
        if result.returncode != 0:
            raise SystemExit("Failed to hide unlicensed UAD plug-ins.")

    log("Exporting Logic tags")
    result = run_step(
        [sys.executable, "list_logic_tags.py", "--output", "./reports/logic-tags.json"]
    )
    steps.append("list_logic_tags")
    if result.returncode != 0:
        raise SystemExit("Failed to export Logic tags.")

    log("Exporting AU list for AI")
    result = run_step(
        [
            sys.executable,
            "export_plugins_for_ai.py",
            "--output",
            "./reports/au-plugins.json",
            "--max-bytes",
            str(args.max_bytes),
        ]
    )
    steps.append("export_plugins_for_ai")
    if result.returncode != 0:
        raise SystemExit("Failed to export AU list.")

    log("Running AI mapping generation")
    result = run_step(
        [
            sys.executable,
            "run_ai_mapping.py",
            "--input",
            "./reports/au-plugins.json",
            "--output",
            args.generated_mapping,
        ]
    )
    steps.append("run_ai_mapping")
    if result.returncode != 0:
        raise SystemExit("AI mapping step failed.")

    generated_path = Path(args.generated_mapping)
    if not generated_path.exists():
        raise SystemExit("Generated mapping not found.")

    if not args.apply:
        log(
            "Dry run complete. Review plugin_mapping.generated.json and rerun with --apply."
        )
        summary["generated_mapping"] = str(generated_path)
        workflow_report.write_text(json.dumps(summary, indent=2, sort_keys=True))
        log(f"Workflow report written to {workflow_report}")
        return

    log("Applying plugin mapping")
    organizer_report = f"./reports/plugin-organizer-report-{timestamp}.json"
    result = run_step(
        [
            sys.executable,
            "organize_logic_plugins.py",
            "--apply",
            "--mapping",
            str(generated_path),
            "--report",
            organizer_report,
        ]
    )
    steps.append("organize_logic_plugins")
    if result.returncode != 0:
        raise SystemExit("Failed to apply plugin mapping.")

    organizer_report_path = Path(organizer_report)
    if organizer_report_path.exists():
        report_data = json.loads(organizer_report_path.read_text(encoding="utf-8"))
        fallback = report_data.get("fallback_matches", [])
        missing = report_data.get("missing_tagsets", [])
        summary["fallback_matches"] = fallback
        summary["missing_tagsets"] = missing
        if fallback:
            log(f"Uncategorized plugins (fallback): {len(fallback)}")
            for item in fallback:
                log(f"- {item.get('name')}")
        if missing:
            log(f"Missing tagsets: {len(missing)}")
            for item in missing:
                log(f"- {item.get('name')}")

    summary["generated_mapping"] = str(generated_path)
    workflow_report.write_text(json.dumps(summary, indent=2, sort_keys=True))
    log(f"Workflow report written to {workflow_report}")


if __name__ == "__main__":
    main()
