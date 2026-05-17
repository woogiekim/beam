#!/usr/bin/env bash
# install.sh — one-touch beam installer (pipx edition)
# Usage (local):  ./install.sh
# Usage (remote): curl -s https://raw.githubusercontent.com/woogiekim/beam/main/install.sh | bash
# No manual venv activation required — pipx handles PATH registration automatically.
set -euo pipefail

# ---------------------------------------------------------------------------
# 1. Find a suitable Python interpreter (>= 3.9)
# ---------------------------------------------------------------------------
find_python() {
    for candidate in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
        if command -v "$candidate" &>/dev/null; then
            local ver
            ver=$("$candidate" -c "import sys; print(sys.version_info >= (3, 9))" 2>/dev/null || echo "False")
            if [ "$ver" = "True" ]; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON=$(find_python) || {
    echo "error: Python 3.9+ not found. Install it before running this script." >&2
    exit 1
}
echo "Using Python: $PYTHON"

# ---------------------------------------------------------------------------
# 2. Ensure pipx is installed
# ---------------------------------------------------------------------------
if ! command -v pipx &>/dev/null; then
    echo "pipx not found — installing ..."
    if "$PYTHON" -m pip install --user pipx 2>/dev/null; then
        echo "pipx installed via pip."
    elif command -v brew &>/dev/null; then
        echo "pip install failed; trying brew install pipx ..."
        brew install pipx
    else
        echo "error: Could not install pipx. Install it manually: https://pipx.pypa.io/stable/installation/" >&2
        exit 1
    fi
    "$PYTHON" -m pipx ensurepath 2>/dev/null || true
    export PATH="$HOME/.local/bin:$PATH"
fi

# ---------------------------------------------------------------------------
# 3. Detect execution mode
#    When piped via curl, BASH_SOURCE[0] is empty or equals "bash".
#    When run locally,  BASH_SOURCE[0] is the real path to this file.
# ---------------------------------------------------------------------------
_src="${BASH_SOURCE[0]:-}"
if [ -z "$_src" ] || [ "$_src" = "bash" ]; then
    # ---- Mode 1: curl | bash -----------------------------------------------
    BEAM_REMOTE="https://github.com/woogiekim/beam.git"
    BEAM_DIR="$HOME/.beam"

    if [ -d "$BEAM_DIR/.git" ]; then
        echo "Updating existing beam clone at $BEAM_DIR ..."
        git -C "$BEAM_DIR" pull origin main
    else
        echo "Cloning beam into $BEAM_DIR ..."
        git clone "$BEAM_REMOTE" "$BEAM_DIR"
    fi

    REPO_ROOT="$BEAM_DIR"
else
    # ---- Mode 2: ./install.sh (local) --------------------------------------
    REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi

# ---------------------------------------------------------------------------
# 4. Install (or reinstall) beam via pipx
# ---------------------------------------------------------------------------
if pipx list --short 2>/dev/null | grep -q "^beam "; then
    echo "beam already installed via pipx — reinstalling from $REPO_ROOT ..."
    pipx reinstall beam
else
    echo "Installing beam via pipx from $REPO_ROOT ..."
    pipx install -e "$REPO_ROOT"
fi

# ---------------------------------------------------------------------------
# 5. Ensure ~/.local/bin is on PATH (idempotent, zsh + bash)
# ---------------------------------------------------------------------------
_ensure_path_entry() {
    local shell_rc="$1"
    local entry='export PATH="$HOME/.local/bin:$PATH"'
    if [ -f "$shell_rc" ] && grep -qF '.local/bin' "$shell_rc" 2>/dev/null; then
        return 0
    fi
    echo "" >> "$shell_rc"
    echo "# beam — added by install.sh" >> "$shell_rc"
    echo "$entry" >> "$shell_rc"
    echo "Added ~/.local/bin to PATH in $shell_rc"
}

export PATH="$HOME/.local/bin:$PATH"

if [ -n "${ZSH_VERSION:-}" ] || [ -f "$HOME/.zshrc" ]; then
    _ensure_path_entry "$HOME/.zshrc"
fi
if [ -n "${BASH_VERSION:-}" ] || [ -f "$HOME/.bashrc" ]; then
    _ensure_path_entry "$HOME/.bashrc"
fi

# ---------------------------------------------------------------------------
# 6. Verify installation
# ---------------------------------------------------------------------------
if command -v beam &>/dev/null; then
    echo ""
    echo "beam installed successfully."
    echo "Run: beam"
else
    echo ""
    echo "beam was installed but the 'beam' command is not yet on your current PATH."
    echo "Restart your shell or run:"
    echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    echo "  beam"
fi
