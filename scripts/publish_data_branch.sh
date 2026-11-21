#!/usr/bin/env bash
# Publish the landing zone and snapshot state to the orphan `data` branch.
#
# The branch always holds exactly one commit (force-pushed), so data history does not
# accumulate in git: the landing zone is the history. The warehouse file is not
# published; it is rebuilt from raw/ on every run.
#
# Usage: scripts/publish_data_branch.sh <data-dir> [remote]
set -euo pipefail

DATA_DIR=${1:?usage: publish_data_branch.sh <data-dir> [remote]}
REMOTE=${2:-origin}
# In Actions, pass an authenticated PUSH_URL: the temporary repo below does not
# inherit the credentials actions/checkout configured for the workspace.
REMOTE_URL=${PUSH_URL:-$(git remote get-url "$REMOTE")}

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

mkdir -p "$WORK/repo"
cp -R "$DATA_DIR/raw" "$WORK/repo/raw"
if [ -d "$DATA_DIR/state" ]; then cp -R "$DATA_DIR/state" "$WORK/repo/state"; fi
cat > "$WORK/repo/README.md" <<'EOF'
# oss-pulse data branch

Landing zone (`raw/`) and SCD2 snapshot state (`state/`) for the daily pipeline on
`main`. Every GitHub login in these files is a salted SHA-256 pseudonym; see
docs/governance.md on `main`. This branch is force-pushed as a single commit.
EOF
printf 'warehouse.duckdb\n*.tmp\n' > "$WORK/repo/.gitignore"

cd "$WORK/repo"
git init -q -b data
git config user.name "${GIT_AUTHOR_NAME:-oss-pulse}"
git config user.email "${GIT_AUTHOR_EMAIL:-oss-pulse@users.noreply.github.com}"
git add -A
git commit -q -m "Data as of $(date -u +%Y-%m-%dT%H:%MZ)"
git push -q --force "$REMOTE_URL" data:data
echo "published $(git ls-files | wc -l) files to $REMOTE/data"
