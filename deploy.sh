#!/usr/bin/env bash
# deploy.sh — sync DragonEyes to Raspberry Pi via rsync
#
# Usage:
#   ./deploy.sh                          # full deploy (uses PI_HOST env var or prompts)
#   ./deploy.sh pi@192.168.1.42          # full deploy
#   PI_HOST=pi@192.168.1.42 ./deploy.sh

set -euo pipefail  # -e: exit on error  -u: error on unset vars  -o pipefail: catch pipe failures

REMOTE="${1:-${PI_HOST:-}}"

if [[ -z "$REMOTE" ]]; then
    read -rp "Pi user@host (e.g. pi@192.168.1.42): " REMOTE
fi

REMOTE_DIR="/opt/Pi_Eyes"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Patterns used for both rsync excludes and single-file guard. Use trailing / for directories (rsync skips the dir entirely).
DEPLOY_EXCLUDED=(
    ".idea/" ".git/" ".claude/" ".gitignore" ".DS_Store" "*.md"
    "venv/" ".venv*/" "notes/" "mock/" "deploy.sh"
    "*.pyc" "__pycache__/" "*.egg-info/"
)

RSYNC_EXCLUDES=()
for _pattern in "${DEPLOY_EXCLUDED[@]}"; do
    RSYNC_EXCLUDES+=("--exclude=${_pattern}")
done
unset _pattern

# Changed .c files from the last dir_diff run; populated for full deploy compile step
CHANGED_C_FILES=()

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

dir_diff() {
    CHANGED_C_FILES=()

    local changed
    changed=$(rsync -n --checksum --itemize-changes -azO "${RSYNC_EXCLUDES[@]}" "${SCRIPT_DIR}/" \
        "${REMOTE}:${REMOTE_DIR}/" 2>/dev/null | grep '^[<>]' | awk '{print $2}' || true)

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

    local rows=()
    rows+=("file"$'\t'"local sha256"$'\t'"remote sha256"$'\t'"local date"$'\t'"remote date")

    local i
    for i in "${!files[@]}"; do
        local f="${files[$i]}"
        local lhash ldate rhash rdate
        lhash=$(shasum -a 256 "${SCRIPT_DIR}/${f}" | awk '{print $1}' | cut -c1-12)
        ldate=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M" "${SCRIPT_DIR}/${f}")

        local rline="${remote_lines[$i]:-}"
        IFS='|' read -r _ rhash rdate <<< "${rline:-||}"
        rhash="${rhash:-(?)}"
        rdate="${rdate:-(?)}"

        rows+=("${f}"$'\t'"${lhash}"$'\t'"${rhash}"$'\t'"${ldate}"$'\t'"${rdate}")
    done

    echo ""
    printf '%s\n' "${rows[@]}" | column -t -s $'\t'
    echo ""
    return 0
}

# --- main ---
echo "→ Comparing with ${REMOTE}:${REMOTE_DIR} ..."
if dir_diff; then
    confirm || { echo "Cancelled."; exit 0; }

    echo "→ Deploying to ${REMOTE}:${REMOTE_DIR} ..."
    rsync -avzO --no-perms --progress "${RSYNC_EXCLUDES[@]}" "${SCRIPT_DIR}/" "${REMOTE}:${REMOTE_DIR}/"
    echo "✓ Done — ${REMOTE}:${REMOTE_DIR}"

    if [[ ${#CHANGED_C_FILES[@]} -gt 0 ]]; then
        for _c in "${CHANGED_C_FILES[@]}"; do
            compile_c "${_c}"
        done
        unset _c
    fi
fi
