#!/usr/bin/env bash
# deploy.sh — sync DragonEyes to Raspberry Pi via rsync
#
# Usage:
#   ./deploy.sh                          # full deploy (uses PI_HOST env var or prompts)
#   ./deploy.sh pi@192.168.1.42          # full deploy
#   ./deploy.sh pi@192.168.1.42 main.py  # single file
#   ./deploy.sh pi@192.168.1.42 eye/sequence.py
#   PI_HOST=pi@192.168.1.42 ./deploy.sh

set -euo pipefail

REMOTE="${1:-${PI_HOST:-}}"
FILE="${2:-}"

if [[ -z "$REMOTE" ]]; then
  read -rp "Pi user@host (e.g. pi@192.168.1.42): " REMOTE
fi

REMOTE_DIR="/opt/Pi_Eyes"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Patterns used for both rsync excludes and single-file guard.
# Use trailing / for directories (rsync skips the dir entirely).
# is_excluded() converts dir/ → dir/* for bash glob matching.
DEPLOY_EXCLUDED=(
  "run_dev.py"
  "CLAUDE.md"
  "README.md"
  "deploy.sh"
  ".DS_Store"
  ".gitignore"
  "*.pyc"
  "mock/"
  "venv/"
  ".venv*/"
  ".idea/"
  ".claude/"
  "__pycache__/"
  ".git/"
  "notes/"
  "*.egg-info/"
)

RSYNC_EXCLUDES=()
for _pattern in "${DEPLOY_EXCLUDED[@]}"; do
  RSYNC_EXCLUDES+=("--exclude=${_pattern}")
done
unset _pattern

# Changed .c files from the last dir_diff run; populated for full deploy compile step
CHANGED_C_FILES=()

local_hash() { shasum -a 256 "$1" | awk '{print $1}' | cut -c1-12; }
local_date() { stat -f "%Sm" -t "%Y-%m-%d %H:%M" "$1"; }

is_excluded() {
  local f="$1" pattern glob
  for pattern in "${DEPLOY_EXCLUDED[@]}"; do
    # Convert trailing / to /* so dir/ matches dir/file.py
    if [[ "$pattern" == */ ]]; then
      glob="${pattern}*"
    else
      glob="$pattern"
    fi
    # shellcheck disable=SC2254
    case "$f" in
      $glob) return 0 ;;
    esac
  done
  return 1
}

compile_c() {
  local f="$1"
  local binary="${REMOTE_DIR}/${f%.c}"
  echo "→ Compiling ${f} on ${REMOTE}..."
  ssh "${REMOTE}" "sudo gcc -O2 -o '${binary}' '${REMOTE_DIR}/${f}' -lpthread -lm -lX11 -lXext"
  echo "✓ Compiled → ${binary}"
}

confirm() {
  printf "Type anything + Enter to deploy, or just Enter to cancel: "
  read -r answer
  [[ -n "$answer" ]]
}

# --- single file diff ---

file_diff() {
  local lpath="${SCRIPT_DIR}/${FILE}"
  local rpath="${REMOTE_DIR}/${FILE}"

  local lhash ldate
  lhash=$(local_hash "${lpath}")
  ldate=$(local_date "${lpath}")

  local remote_info
  remote_info=$(ssh "${REMOTE}" "
    f='${rpath}'
    if [ -f \"\$f\" ]; then
      h=\$(sha256sum \"\$f\" | awk '{print \$1}' | cut -c1-12)
      d=\$(stat -c '%y' \"\$f\" | cut -d. -f1 | cut -c1-16)
      printf '%s|%s' \"\$h\" \"\$d\"
    else
      printf '(new)|(new)'
    fi
  " 2>/dev/null || echo "(error)|(error)")

  local rhash rdate
  IFS='|' read -r rhash rdate <<< "${remote_info}"

  echo ""
  printf "  %-10s  %-14s  %-16s\n" "" "sha256 (12)" "modified"
  printf "  %-10s  %-14s  %-16s\n" "──────────" "──────────────" "────────────────"
  printf "  %-10s  %-14s  %-16s\n" "local"  "${lhash}" "${ldate}"
  printf "  %-10s  %-14s  %-16s\n" "remote" "${rhash}" "${rdate}"
  echo ""

  if [[ "${lhash}" == "${rhash}" ]]; then
    echo "✓ ${FILE} is identical on both sides — nothing to deploy"
    return 1
  fi
  return 0
}

# --- full dir diff ---

dir_diff() {
  CHANGED_C_FILES=()

  local changed
  changed=$(rsync -n --checksum --itemize-changes -azO \
    "${RSYNC_EXCLUDES[@]}" \
    "${SCRIPT_DIR}/" "${REMOTE}:${REMOTE_DIR}/" 2>/dev/null \
    | grep '^[<>]' | awk '{print $2}' || true)

  if [[ -z "$changed" ]]; then
    echo "✓ Nothing to deploy — all files are up to date"
    return 1
  fi

  local files=()
  while IFS= read -r f; do
    [[ -n "$f" ]] && files+=("$f")
    [[ "$f" == *.c ]] && CHANGED_C_FILES+=("$f")
  done <<< "$changed"

  # One SSH call to get hash|date for every changed file
  local remote_script=""
  for f in "${files[@]}"; do
    remote_script+="f='${REMOTE_DIR}/${f}'; "
    remote_script+="if [ -f \"\$f\" ]; then "
    remote_script+="  h=\$(sha256sum \"\$f\" | awk '{print \$1}' | cut -c1-12); "
    remote_script+="  d=\$(stat -c '%y' \"\$f\" | cut -d. -f1 | cut -c1-16); "
    remote_script+="  printf '%s|%s|%s\n' '${f}' \"\$h\" \"\$d\"; "
    remote_script+="else printf '%s|(new)|(new)\n' '${f}'; fi; "
  done

  local remote_lines=()
  while IFS= read -r line; do
    [[ -n "$line" ]] && remote_lines+=("$line")
  done < <(ssh "${REMOTE}" "${remote_script}" 2>/dev/null || true)

  echo ""
  printf "  %-35s  %-14s  %-14s  %-16s  %-16s\n" \
    "file" "local sha256" "remote sha256" "local date" "remote date"
  printf "  %-35s  %-14s  %-14s  %-16s  %-16s\n" \
    "───────────────────────────────────" "──────────────" "──────────────" \
    "────────────────" "────────────────"

  local i
  for i in "${!files[@]}"; do
    local f="${files[$i]}"
    local lhash ldate rhash rdate
    lhash=$(local_hash "${SCRIPT_DIR}/${f}")
    ldate=$(local_date "${SCRIPT_DIR}/${f}")

    local rline="${remote_lines[$i]:-}"
    IFS='|' read -r _ rhash rdate <<< "${rline:-||}"
    rhash="${rhash:-(?)}"
    rdate="${rdate:-(?)}"

    printf "  %-35s  %-14s  %-14s  %-16s  %-16s\n" \
      "${f}" "${lhash}" "${rhash}" "${ldate}" "${rdate}"
  done
  echo ""
  return 0
}

# --- main ---

if [[ -n "$FILE" ]]; then
  if is_excluded "${FILE}"; then
    echo "✗ ${FILE} is excluded from deployment"
    exit 1
  fi
  echo "→ Checking ${FILE}..."
  if file_diff; then
    confirm || { echo "Cancelled."; exit 0; }
    echo "→ Deploying ${FILE}..."
    rsync -avzO --no-perms --progress \
      "${SCRIPT_DIR}/${FILE}" "${REMOTE}:${REMOTE_DIR}/${FILE}"
    echo "✓ Done — ${REMOTE}:${REMOTE_DIR}/${FILE}"
    if [[ "${FILE}" == *.c ]]; then
      compile_c "${FILE}"
    fi
  fi
else
  echo "→ Comparing with ${REMOTE}:${REMOTE_DIR} ..."
  if dir_diff; then
    confirm || { echo "Cancelled."; exit 0; }
    echo "→ Deploying to ${REMOTE}:${REMOTE_DIR} ..."
    rsync -avzO --no-perms --progress \
      "${RSYNC_EXCLUDES[@]}" \
      "${SCRIPT_DIR}/" "${REMOTE}:${REMOTE_DIR}/"
    echo "✓ Done — ${REMOTE}:${REMOTE_DIR}"
    for _c in "${CHANGED_C_FILES[@]:-}"; do
      [[ -n "$_c" ]] && compile_c "${_c}"
    done
    unset _c
  fi
fi
