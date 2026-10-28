"""A throwaway PostgreSQL server for tests and the backend benchmark (PROD-001).

``temporary_server()`` finds PostgreSQL's own programs (``initdb``,
``pg_ctl``), makes a new database cluster in a temporary folder, starts it
on a free port of 127.0.0.1 only, and stops and deletes it afterwards.
Nothing is installed and no existing server is touched. Each caller gets
fresh databases from ``new_database``.

If the programs aren't on this computer, or the process runs as root
(PostgreSQL refuses to), it raises ``PostgresUnavailable`` and tests skip.
``KE_TEST_POSTGRES_URL`` points at an existing server instead.

Talking points:
    - "The PostgreSQL tests start their own private server in a temp
      folder, so CI needs no database service and nothing is left behind."
"""

from __future__ import annotations

import glob
import os
import shutil
import socket
import subprocess
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from itertools import count
from pathlib import Path

_numbers = count(1)


class PostgresUnavailable(RuntimeError):
    """No PostgreSQL to test against (the message says why)."""


def _binary(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    exe = name + (".exe" if os.name == "nt" else "")
    patterns = [os.path.join(os.environ.get("PGBIN", ""), exe)]
    patterns += sorted(glob.glob(f"/usr/lib/postgresql/*/bin/{exe}"), reverse=True)
    patterns += sorted(glob.glob(f"C:/Program Files/PostgreSQL/*/bin/{exe}"), reverse=True)
    for candidate in patterns:
        if os.path.isfile(candidate):
            return candidate
    raise PostgresUnavailable(f"{name} not found (install PostgreSQL or set PGBIN)")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


@contextmanager
def temporary_server() -> Iterator[str]:
    """Yield the base URL (``postgresql+psycopg://ke@127.0.0.1:PORT``) of a new server.

    Raises:
        PostgresUnavailable: No programs, or running as root.
    """
    existing = os.environ.get("KE_TEST_POSTGRES_URL")
    if existing:
        yield existing.rstrip("/")
        return
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        raise PostgresUnavailable("PostgreSQL refuses to run as root")
    initdb, pg_ctl = _binary("initdb"), _binary("pg_ctl")
    folder = Path(tempfile.mkdtemp(prefix="ke-pg-"))
    data, port = folder / "data", _free_port()
    try:
        subprocess.run(
            [initdb, "-D", str(data), "-A", "trust", "-U", "ke", "-E", "UTF8", "--no-locale"],
            check=True,
            capture_output=True,
        )
        options = f"-p {port} -c listen_addresses=127.0.0.1 -c unix_socket_directories="
        subprocess.run(
            [pg_ctl, "-D", str(data), "-o", options, "-l", str(folder / "log"), "-w", "start"],
            check=True,
            capture_output=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        shutil.rmtree(folder, ignore_errors=True)
        raise PostgresUnavailable(f"could not start PostgreSQL: {error}") from error
    try:
        yield f"postgresql+psycopg://ke@127.0.0.1:{port}"
    finally:
        subprocess.run(
            [pg_ctl, "-D", str(data), "-m", "immediate", "-w", "stop"], capture_output=True
        )
        shutil.rmtree(folder, ignore_errors=True)


def new_database(base_url: str) -> str:
    """Create an empty database on the server and return its URL."""
    from sqlalchemy import create_engine, text

    name = f"ke_{os.getpid()}_{next(_numbers)}"
    admin = create_engine(f"{base_url}/postgres", isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        admin.dispose()
    return f"{base_url}/{name}"
