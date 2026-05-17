# Beam

**Terminal UI tool for SSH/SFTP file deployment**

Beam is a TUI application for deploying files to SSH servers quickly and safely. Using only your keyboard, select local files and upload them to a remote server — with instant rollback to any previous state.

---

## Features

- **Workspace management** — Save and switch between multiple servers (dev / staging / production, etc.)
- **Side-by-side file view** — Local and remote files shown in one screen
- **Diff indicators** — Real-time `+` (new) / `M` (modified) tags on local files
- **Multi-file deployment** — Select files with Space, select all with Ctrl+A, deploy in one shot
- **Remote file deletion** — Select files in the remote panel and delete directly
- **Session rollback** — Automatic snapshot before each deploy; restore any previous version instantly
- **Diff threshold warning** — Alert when local/remote directory divergence exceeds a configured threshold
- **SSH key & password auth** — Both authentication methods supported
- **Custom port** — Configure any port (default: 22)

---

## Requirements

| Item | Version |
|---|---|
| Python | 3.9+ |
| pipx | Latest recommended (install script handles this automatically) |
| SSH access | Remote server must have the SFTP subsystem enabled |

> **Note**: The remote server must allow SFTP over SSH. This is enabled by default on most Linux servers.

---

## Installation

### Option 1 — One-touch install (recommended)

Install with a single command. pipx is installed automatically if not present.

```bash
curl -s https://raw.githubusercontent.com/woogiekim/beam/main/install.sh | bash
```

After installation, open a new shell or run:

```bash
export PATH="$HOME/.local/bin:$PATH"
beam
```

### Option 2 — Install from local clone

```bash
git clone https://github.com/woogiekim/beam.git
cd beam
./install.sh
```

### Option 3 — Install with pip

```bash
pip install -e .
```

Or with a manually managed virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
beam
```

---

## Usage

### Running

```bash
beam
```

### Basic workflow

1. The **workspace selection screen** opens.
2. Press `Ctrl+N` to add a new workspace.
3. Select a workspace and press `Enter` to connect.
4. In the file view, check local (left) and remote (right) files.
5. In the local panel, select files with `Space`, then press `Ctrl+U` to deploy.
6. To undo a deployment or restore a previous state, press `Ctrl+R` to open the rollback panel.

### Keyboard shortcuts

#### Workspace screen

| Shortcut | Action |
|---|---|
| `Ctrl+N` | Add workspace |
| `Ctrl+E` | Edit workspace |
| `Ctrl+D` | Delete workspace |
| `Enter` | Open workspace (connect) |

#### File view screen

| Shortcut | Action |
|---|---|
| `Space` | Select / deselect file (local or remote panel) |
| `Ctrl+A` | Select all / deselect all local files |
| `Ctrl+U` | Deploy selected local files to remote |
| `Ctrl+D` | Delete selected remote files (when remote panel is focused) |
| `Ctrl+R` | Open rollback panel / execute rollback for selected file |
| `F5` | Refresh file list |
| `Esc` | Go back / close rollback panel |
| `Ctrl+Q` | Quit app |

#### Workspace form screen

| Shortcut | Action |
|---|---|
| `Ctrl+S` | Save |
| `Esc` | Cancel |

### File status indicators

Each file in the local panel is prefixed with a status tag:

| Tag | Meaning |
|---|---|
| `+` (green) | New file — not present on remote |
| `M` (yellow) | Modified — size differs from remote |
| (none) | In sync with remote |

---

## Configuration

The config file is stored at `~/.beam/workspaces.json`.  
Edit it directly, or add/edit workspaces through the TUI — changes are saved automatically.

### Workspace fields

| Field | Required | Description | Default |
|---|---|---|---|
| `name` | Yes | Workspace display name | — |
| `local_root` | Yes | Absolute path to local project root | — |
| `host` | Yes | Remote server hostname or IP | — |
| `user` | Yes | SSH username | — |
| `remote_root` | Yes | Absolute path on the remote server (must start with `/`) | — |
| `port` | No | SSH port | `22` |
| `password` | Conditional | SSH password (required when `key_path` is not set) | — |
| `key_path` | Conditional | Path to SSH private key (required when `password` is not set) | — |
| `diff_threshold` | No | Warning threshold for local/remote divergence (0.0 – 1.0) | `0.30` |

> Either `password` or `key_path` must be provided.

### Example config

```json
{
  "workspaces": [
    {
      "name": "production",
      "local_root": "/home/me/myproject",
      "host": "server.example.com",
      "port": 22,
      "user": "deploy",
      "password": null,
      "key_path": "~/.ssh/id_rsa",
      "remote_root": "/var/www/myproject",
      "diff_threshold": 0.3
    },
    {
      "name": "staging",
      "local_root": "/home/me/myproject",
      "host": "staging.example.com",
      "port": 2222,
      "user": "deploy",
      "password": "my-secret",
      "key_path": null,
      "remote_root": "/srv/staging",
      "diff_threshold": 0.5
    }
  ]
}
```

### `diff_threshold` explained

When the mismatch ratio between local and remote directory contents exceeds this value, a warning is shown before deploying.

- `0.0` — warn if even one file differs
- `0.30` (default) — warn when more than 30% of files differ
- `1.0` — disable warnings

This acts as a safety guard against accidentally deploying to the wrong directory.

---

## Development setup

```bash
git clone https://github.com/woogiekim/beam.git
cd beam
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
beam
```

### Project structure

```
beam/
├── beam/
│   ├── app.py        # TUI app entry point and all screen definitions
│   ├── config.py     # Workspace config load/save (WorkspaceConfig)
│   ├── diff.py       # Local/remote directory diff calculation
│   ├── rollback.py   # Session rollback snapshot management
│   └── sftp.py       # paramiko-based SFTP client wrapper
├── install.sh        # One-touch installer (pipx-based)
└── pyproject.toml    # Package metadata and dependencies
```

### Dependencies

| Package | Purpose |
|---|---|
| [textual](https://github.com/Textualize/textual) | Terminal UI framework |
| [paramiko](https://www.paramiko.org/) | SSH/SFTP client |

---

## License

See the repository for license information.
