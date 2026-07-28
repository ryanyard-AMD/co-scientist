#!/usr/bin/env bash
#
# Back up the co-scientist project (source, git history, config, and a consistent
# snapshot of the SQLite database) into a single timestamped tar.gz.
#
# Usage:
#   scripts/backup.sh [DEST_DIR] [--no-secrets]
#
#   DEST_DIR       Where to write the archive (default: /opt/backups, or $CS_BACKUP_DIR).
#   --no-secrets   Exclude the .env file (which holds API keys) from the archive.
#
# The database is captured with SQLite's online-backup API (not a raw file copy),
# so the snapshot is consistent even if something is mid-write. .venv, caches, and
# older *.db.bak.* files are excluded — the venv is regenerable with `uv sync`.
#
# Restore with scripts/restore.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_NAME="$(basename "$REPO_ROOT")"
DB_NAME="${CS_DB_NAME:-coscientist.db}"

DEST_DIR="${CS_BACKUP_DIR:-/opt/backups}"
INCLUDE_SECRETS=1
for arg in "$@"; do
  case "$arg" in
    --no-secrets) INCLUDE_SECRETS=0 ;;
    --help|-h) sed -n '2,20p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    -*) echo "unknown option: $arg" >&2; exit 2 ;;
    *) DEST_DIR="$arg" ;;
  esac
done

command -v rsync >/dev/null || { echo "error: rsync is required" >&2; exit 1; }
command -v python3 >/dev/null || { echo "error: python3 is required" >&2; exit 1; }

TS="$(date +%Y%m%d_%H%M%S)"
STAGE_ROOT="$(mktemp -d)"
STAGE="$STAGE_ROOT/$PROJECT_NAME"
OUT="$DEST_DIR/${PROJECT_NAME}-backup-${TS}.tar.gz"
trap 'rm -rf "$STAGE_ROOT"' EXIT

mkdir -p "$DEST_DIR"
mkdir -p "$STAGE"

echo "→ staging project (excluding .venv, caches, old ${DB_NAME}.bak.*)"
RSYNC_EXCLUDES=(
  --exclude='.venv/'
  --exclude='.pytest_cache/'
  --exclude='__pycache__/'
  --exclude="${DB_NAME}"
  --exclude="${DB_NAME}.bak.*"
  --exclude="${DB_NAME}-journal"
  --exclude="${DB_NAME}-wal"
  --exclude="${DB_NAME}-shm"
)
if [ "$INCLUDE_SECRETS" -eq 0 ]; then
  RSYNC_EXCLUDES+=(--exclude='.env')
  echo "  (excluding .env — --no-secrets)"
fi
rsync -a "${RSYNC_EXCLUDES[@]}" "$REPO_ROOT/" "$STAGE/"

if [ -f "$REPO_ROOT/$DB_NAME" ]; then
  echo "→ snapshotting database ($DB_NAME) via SQLite online backup"
  python3 - "$REPO_ROOT/$DB_NAME" "$STAGE/$DB_NAME" <<'PY'
import sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(src)
d = sqlite3.connect(dst)
with d:
    s.backup(d)
result = d.execute("PRAGMA integrity_check").fetchone()[0]
s.close(); d.close()
if result == "ok":
    print("  integrity_check: ok")
else:
    print(f"  WARNING integrity_check: {result}", file=sys.stderr)
PY
else
  echo "  WARNING: $DB_NAME not found — archive will contain no database" >&2
fi

echo "→ writing archive"
tar -czf "$OUT" -C "$STAGE_ROOT" "$PROJECT_NAME"

echo "→ verifying archive"
gzip -t "$OUT"

SIZE="$(du -h "$OUT" | cut -f1)"
echo
echo "backup complete: $OUT ($SIZE)"
