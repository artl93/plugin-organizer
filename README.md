# Logic Pro Plug-in Organizer

Organize Logic Pro Audio Unit plug-ins into custom categories by writing directly to Logic's Tags database. The mapping is deterministic and portable, so you get consistent results across machines.

## What this does

- Scans installed AU plug-ins in your Components folders.
- Assigns each plug-in to a category based on `plugin_mapping.json`.
- Updates Logic Pro tag databases in `~/Music/Audio Music Apps/Databases/Tags`.
- Creates a backup before writing changes.

## Requirements

- macOS with Logic Pro installed
- Python 3.10+
- Logic Pro must be closed when running the script

## Usage

Recommended workflow (keeps Logic's built-in categories intact):

```bash
python list_logic_tags.py --output "./reports/logic-tags.json"
python organize_logic_plugins.py --apply
```

Dry run (default):

```bash
python organize_logic_plugins.py
```

Apply changes:

```bash
python organize_logic_plugins.py --apply
```

By default this preserves Logic's existing categories. To overwrite categories from the mapping file:

```bash
python organize_logic_plugins.py --apply --update-categories
```

Export current Logic categories/tags:

```bash
python list_logic_tags.py
python list_logic_tags.py --output "./reports/logic-tags.json"
python list_logic_tags.py --include-tagsets --output "./reports/logic-tags-full.json"
```

Optional flags:

```bash
python organize_logic_plugins.py \
  --components-dir "/Library/Audio/Plug-Ins/Components" \
  --components-dir "~/Library/Audio/Plug-Ins/Components" \
  --tags-dir "~/Music/Audio Music Apps/Databases/Tags" \
  --mapping "./plugin_mapping.json" \
  --backup-dir "./backup" \
  --report "./reports/plugin-organizer-report.json"
```

Hide unlicensed UAD plug-ins in Logic:

```bash
python hide_uad_plugins.py "./reports/UADSystemProfile.txt"
python hide_uad_plugins.py "./reports/UADSystemProfile.txt" --apply
python hide_uad_plugins.py --restore --apply
```

Diagnose plugins that fall into the fallback category:

```bash
python organize_logic_plugins.py --diagnose
python organize_logic_plugins.py --diagnose --diagnose-unmapped
python organize_logic_plugins.py --diagnose --diagnose-vendor "Arturia" --diagnose-vendor "Universal Audio"
```

Restore from a backup (undo changes):

```bash
python organize_logic_plugins.py --restore-latest
python organize_logic_plugins.py --restore-backup "./backup/Tags-backup-20260128221629"
```

## Mapping file

All categorization logic lives in `plugin_mapping.json`.

- `categories`: ordered list of category names used in Logic (defaults to Logic's built-in set).
- `vendor_aliases`: maps bundle identifiers or manufacturer codes to vendor names.
- `overrides`: exact or pattern-based matches that take precedence.
- `vendor_rules`: regex rules scoped to a specific vendor.
- `rules`: global regex rules for any plug-in.
- `exclude`: list of plug-ins to skip entirely (useful for players or placeholders).
- `fallback_category`: default category when no rule matches.

Adjust the mapping to fit your library or studio workflow. The rules are evaluated in this order:

1. Overrides
2. Vendor rules
3. Global rules
4. Fallback category

## Notes

- The script writes to Logic's Tags database. A backup is created before any changes.
- Some plug-ins may not have a tagset file yet if Logic has never scanned them. Those are reported and skipped.
- If you want to preserve existing tags instead of replacing them, pass `--merge-tags`.
- Use `--restore-latest` to undo the most recent apply and start over.
- Use `--update-categories` only if you want to overwrite Logic's category list.
- If Logic's built-in categories change after an update, re-run `list_logic_tags.py` and update `plugin_mapping.json` accordingly.
