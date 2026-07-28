#!/usr/bin/env bash
#
# Restore a co-scientist backup created by scripts/backup.sh.
#
# Usage:
#   scripts/restore.sh ARCHIVE [DEST_DIR] [--force]
#
#   ARCHIVE    Path to a *-backup-*.tar.gz produced by backup.sh.
#   DEST_DIR   Where to extract (default: ./restored-<timestamp>). The archive's
#              top-level project directory is created inside DEST_DIR.
#   --force    Allow extracting into a DEST_DIR that already exists and is non-empty.
#
# After restoring, rebuild the environment inside the extracted project:
#   uv sync                # recreate .venv (excluded from the backup)
#   alembic upgrade head   # only if restoring schema onto a fresh/empty database
set -euo pipefail

ARCHIVE=""
DEST_DIR=""
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --help|-h) sed -n '2,18p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) if [ -z "$ARCHIVE" ]; then ARCHIVE="$arg"; else DEST_DIR="$arg"; fi ;;
  esac
done

[ -n "$ARCHIVE" ] || { echo "error: ARCHIVE path required (see --help)" >&2; exit 2; }
[ -f "$ARCHIVE" ] || { echo "error: archive not found: $ARCHIVE" >&2; exit 1; }
command -v python3 >/dev/null || { echo "error: python3 is required" >&2; exit 1; }

DEST_DIR="${DEST_DIR:-./restored-$(date +%Y%m%d_%H%M%S)}"

echo "→ verifying archive integrity"
gzip -t "$ARCHIVE"

# The archive contains a single top-level project directory. Disable pipefail for this
# pipeline: `head` closes the pipe early, sending SIGPIPE to tar, which would otherwise
# abort the script under `set -o pipefail`.
TOP_DIR="$(set +o pipefail; tar -tzf "$ARCHIVE" | head -1 | cut -d/ -f1)"
TARGET="$DEST_DIR/$TOP_DIR"

if [ -e "$TARGET" ] && [ -n "$(ls -A "$TARGET" 2>/dev/null)" ] && [ "$FORCE" -eq 0 ]; then
  echo "error: $TARGET already exists and is non-empty; pass --force to overwrite" >&2
  exit 1
fi

echo "→ extracting into $DEST_DIR"
mkdir -p "$DEST_DIR"
tar -xzf "$ARCHIVE" -C "$DEST_DIR"

DB_NAME="${CS_DB_NAME:-coscientist.db}"
if [ -f "$TARGET/$DB_NAME" ]; then
  echo "→ verifying restored database"
  python3 - "$TARGET/$DB_NAME" <<'PY'
import sqlite3, sys
c = sqlite3.connect(sys.argv[1])
tables = c.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
result = c.execute("PRAGMA integrity_check").fetchone()[0]
c.close()
print(f"  tables={tables}  integrity_check={result}")
PY
fi

echo
echo "restore complete: $TARGET"
echo "next steps:"
echo "  cd $TARGET"
echo "  uv sync                # recreate .venv (was excluded from the backup)"
echo "  # alembic upgrade head # only when restoring schema onto an empty database"
