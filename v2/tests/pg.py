"""Throwaway PostgreSQL cluster for tests (initdb + pg_ctl), or an external server via env."""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class PgServer:
    admin_url: str  # postgresql+psycopg://… to the "postgres" database
    _cleanup: list[Path]
    _data_dir: Path | None = None

    def url_for(self, database: str) -> str:
        base, _, query = self.admin_url.partition("?")
        base = base.rsplit("/", 1)[0] + f"/{database}"
        return f"{base}?{query}" if query else base

    def stop(self) -> None:
        if self._data_dir is not None:
            subprocess.run(
                ["pg_ctl", "-D", str(self._data_dir), "-m", "immediate", "stop"],
                check=False,
                capture_output=True,
            )
        for path in self._cleanup:
            shutil.rmtree(path, ignore_errors=True)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start() -> PgServer:
    external = os.environ.get("BK_TEST_DATABASE_URL")
    if external:
        return PgServer(admin_url=external, _cleanup=[])
    if shutil.which("initdb") is None or shutil.which("pg_ctl") is None:
        raise RuntimeError("PostgreSQL binaries not found; set BK_TEST_DATABASE_URL")
    root = Path(tempfile.mkdtemp(prefix="bkpg-"))
    data, sock = root / "data", root / "sock"
    sock.mkdir()
    subprocess.run(
        ["initdb", "-D", str(data), "-U", "postgres", "--auth=trust", "-E", "UTF8", "--locale=C"],
        check=True,
        capture_output=True,
    )
    port = _free_port()
    options = f"-p {port} -k {sock} -c listen_addresses='' -c fsync=off -c full_page_writes=off"
    subprocess.run(
        ["pg_ctl", "-D", str(data), "-o", options, "-l", str(root / "log"), "-w", "start"],
        check=True,
        capture_output=True,
    )
    url = f"postgresql+psycopg://postgres@/postgres?host={sock}&port={port}"
    deadline = time.time() + 10
    while time.time() < deadline:
        if (sock / f".s.PGSQL.{port}").exists():
            break
        time.sleep(0.1)
    return PgServer(admin_url=url, _cleanup=[root], _data_dir=data)
