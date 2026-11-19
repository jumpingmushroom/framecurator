#!/usr/bin/env bash
# Export tracked files as a one-commit public repo; refuse if any private string is present.
set -euo pipefail

target=${1:?usage: export_public.sh <target-dir>}
root=$(git rev-parse --show-toplevel)
cd "$root"

strings="$root/.private-strings"
[ -f "$strings" ] || { echo "error: .private-strings missing" >&2; exit 1; }
# Drop CR (CRLF files) and blank lines: a stray CR never matches, an empty pattern matches everything.
patterns=$(mktemp)
tr -d '\r' < "$strings" | grep . > "$patterns" || true
[ -s "$patterns" ] || { rm -f "$patterns"; echo "error: .private-strings has no patterns" >&2; exit 1; }
if [ -e "$target" ] && [ -n "$(ls -A "$target")" ]; then
  rm -f "$patterns"; echo "error: $target is not empty" >&2; exit 1
fi

created=0; done_ok=0
[ -e "$target" ] || created=1
cleanup() {
  rm -f "$patterns"
  # Only remove what this run created; a pre-existing empty target is just emptied.
  if [ "$done_ok" = 0 ] && [ -d "$target" ]; then
    if [ "$created" = 1 ]; then rm -rf "$target"; else find "$target" -mindepth 1 -delete; fi
  fi
}
trap cleanup EXIT

mkdir -p "$target"
target=$(cd "$target" && pwd)
# -P keeps symlinks as links; "--" keeps leading-dash names from being read as options.
git ls-files -z | grep -zv -e '^CLAUDE\.md$' -e '^docs/superpowers/' | xargs -0 cp -P --parents -t "$target" --

matches=$(grep -rniF -f "$patterns" "$target" || true)
names=$(cd "$target" && find . -print | grep -iF -f "$patterns" || true)
if [ -n "$matches$names" ]; then
  [ -z "$matches" ] || echo "$matches"
  [ -z "$names" ] || echo "$names"
  echo "error: private strings found, export deleted" >&2
  exit 1
fi

git -C "$target" init -q -b main
git -C "$target" add -A
git -C "$target" commit -qm "v0.1.0"
done_ok=1
echo "Exported to $target (1 commit). Next: review it, then"
echo "  git -C $target remote add origin <url> && git -C $target push -u origin main"
echo "  git -C $target tag v0.1.0 && git -C $target push origin v0.1.0"
