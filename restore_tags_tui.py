#!/usr/bin/env python3
"""
Restore Logic Tags from a backup using a curses TUI.
"""

import argparse
import curses
import shutil
from pathlib import Path


def log(message: str) -> None:
    print(f"[restore] {message}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Restore Logic Tags from backup (curses UI).",
    )
    parser.add_argument(
        "--backup-dir",
        default=str(Path(__file__).with_name("backup")),
        help="Directory where tag backups are stored.",
    )
    parser.add_argument(
        "--tags-dir",
        default="~/Music/Audio Music Apps/Databases/Tags",
        help="Logic Pro Tags directory.",
    )
    return parser.parse_args()


def list_backups(backup_root: Path) -> list[Path]:
    if not backup_root.exists():
        return []
    backups = [
        path
        for path in backup_root.iterdir()
        if path.is_dir() and path.name.startswith("Tags-backup-")
    ]
    return sorted(backups, key=lambda p: p.name, reverse=True)


def restore_tags(backup_dir: Path, tags_dir: Path) -> None:
    if tags_dir.exists():
        shutil.rmtree(tags_dir)
    shutil.copytree(backup_dir, tags_dir)


def draw_menu(stdscr: curses.window, backups: list[Path], selected: int) -> None:
    stdscr.clear()
    stdscr.addstr(0, 0, "Select a Tags backup to restore (Enter to restore, q to quit)")
    for idx, backup in enumerate(backups):
        prefix = "> " if idx == selected else "  "
        stdscr.addstr(idx + 2, 0, f"{prefix}{backup.name}")
    stdscr.refresh()


def curses_main(stdscr: curses.window, backups: list[Path]) -> Path | None:
    curses.curs_set(0)
    selected = 0
    while True:
        draw_menu(stdscr, backups, selected)
        key = stdscr.getch()
        if key in (curses.KEY_UP, ord("k")):
            selected = max(0, selected - 1)
        elif key in (curses.KEY_DOWN, ord("j")):
            selected = min(len(backups) - 1, selected + 1)
        elif key in (ord("q"), 27):
            return None
        elif key in (curses.KEY_ENTER, 10, 13):
            return backups[selected]


def main() -> None:
    args = parse_args()
    backup_root = Path(args.backup_dir).expanduser()
    tags_dir = Path(args.tags_dir).expanduser()

    backups = list_backups(backup_root)
    if not backups:
        log(f"No backups found in {backup_root}")
        return

    selection = curses.wrapper(curses_main, backups)
    if selection is None:
        log("Restore cancelled.")
        return

    restore_tags(selection, tags_dir)
    log(f"Restored Tags from {selection}")


if __name__ == "__main__":
    main()
