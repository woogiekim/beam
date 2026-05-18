# Beam SSH Test Environment

A minimal Docker Compose setup that runs an OpenSSH server for local end-to-end testing of beam's deploy and SFTP features.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with the Compose plugin (or `docker-compose` v2)

## Usage

### Start

```bash
cd tests/docker
docker compose up -d
```

### Stop

```bash
docker compose down
```

### Check logs

```bash
docker compose logs -f
```

## Connection details

| Setting       | Value          |
|---------------|----------------|
| Host          | `localhost`    |
| Port          | `2222`         |
| Username      | `testuser`     |
| Password      | `testpass`     |
| Remote root   | `/remote-root` |

## Beam workspace configuration

Add an entry like the following to `~/.beam/workspaces.json`:

```json
{
  "workspaces": {
    "docker-test": {
      "host": "localhost",
      "port": 2222,
      "user": "testuser",
      "password": "testpass",
      "remote_root": "/remote-root"
    }
  }
}
```

Then use `beam` as normal, selecting `docker-test` as the active workspace.

## Notes

- The `remote-root/` directory is bind-mounted into the container at `/remote-root` so files deployed by beam are visible on the host under `tests/docker/remote-root/`.
- The contents of `remote-root/` are ignored by git (only the directory itself is tracked via `.gitkeep`).
- Password authentication is enabled via `PASSWORD_ACCESS=true`; no SSH key setup is required.
