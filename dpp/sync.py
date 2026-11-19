"""The client's side of the server protocol: register, wait for approval, fetch a state, upload snapshots."""

from __future__ import annotations

import base64
import dataclasses
import json
import queue
import threading
import time
import urllib.error
import urllib.request
import uuid
import zlib

from .emulator import Emulator
from .firered import read_player_name, read_position, read_stats
from .input import Button

RETRY_SECONDS = 5


class Server:
    """One registration with the server. Uploads happen on a background thread and are retried until they succeed."""

    def __init__(self, url: str, name: str):
        self._url = url.rstrip("/")
        self._name = name
        self._token: str | None = None
        self._uploads: queue.Queue[tuple[str, dict, bytes]] = queue.Queue()
        self._worker: threading.Thread | None = None
        # "ok", "retrying" (server unreachable or failing; uploads wait) or "refused" (the server
        # rejected an upload, e.g. because another client was accepted; nothing more is sent)
        self.sync_status = "ok"

    def _request(self, method: str, path: str, body: dict | None = None) -> bytes:
        request = urllib.request.Request(self._url + path, method=method)
        if self._token:
            request.add_header("Authorization", f"Bearer {self._token}")
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, data, timeout=10) as response:
            return response.read()

    def register(self) -> str:
        """Ask to be accepted; returns the code to show so the admin can tell clients apart."""
        self._token = None
        reply = json.loads(self._request("POST", "/api/clients", {"name": self._name}))
        self._token = reply["token"]
        return reply["code"]

    def poll(self) -> tuple[str, str | None]:
        """Returns (status, start snapshot id); status is pending, accepted, rejected or replaced."""
        reply = json.loads(self._request("GET", "/api/client"))
        return reply["status"], reply["start_snapshot"]

    def fetch_state(self, snapshot_id: str) -> bytes:
        return zlib.decompress(self._request("GET", f"/api/snapshots/{snapshot_id}/state"))

    def upload(self, snapshot_id: str, snapshot: dict, state: bytes) -> None:
        """Queue a snapshot; state is the raw emulator state."""
        self._uploads.put((snapshot_id, snapshot, state))
        if self._worker is None:
            self._worker = threading.Thread(target=self._send_uploads, daemon=True)
            self._worker.start()

    def _send_uploads(self) -> None:
        while True:
            snapshot_id, snapshot, state = self._uploads.get()
            body = snapshot | {"state": base64.b64encode(zlib.compress(state)).decode()}
            while self.sync_status != "refused":
                try:
                    self._request("PUT", f"/api/snapshots/{snapshot_id}", body)
                    if self.sync_status != "ok":
                        print("uploads to the server work again")
                    self.sync_status = "ok"
                    break
                except urllib.error.HTTPError as error:
                    if error.code < 500:
                        self.sync_status = "refused"
                        print(f"the server refused an upload ({error.code} {error.reason}); uploads stopped")
                    else:
                        self._retry_later(error)
                except OSError as error:
                    self._retry_later(error)
            self._uploads.task_done()

    def _retry_later(self, error: Exception) -> None:
        if self.sync_status == "ok":
            print(f"upload to the server failed ({error}); retrying every {RETRY_SECONDS} s")
        self.sync_status = "retrying"
        time.sleep(RETRY_SECONDS)

    def flush(self, timeout: float) -> bool:
        """Wait until queued uploads are sent; False if that takes longer than timeout seconds."""
        deadline = time.monotonic() + timeout
        while self._uploads.unfinished_tasks:
            if time.monotonic() > deadline:
                return False
            time.sleep(0.05)
        return self.sync_status == "ok"


class Uplink:
    """Records the inputs of a running game and uploads them together with a snapshot.

    Every upload names the previous one as its parent and carries the key mask
    changes since then, so replaying them on the parent's state gives this state.
    """

    def __init__(self, server: Server, emu: Emulator, parent: str | None):
        self._server = server
        self._emu = emu
        self._parent = parent
        self._inputs: list[tuple[int, int]] = []
        self._last: Button | None = None

    def record(self, keys: Button) -> None:
        """Call with the key mask of the frame about to be emulated."""
        if keys != self._last:
            self._inputs.append((self._emu.frame, int(keys)))
            self._last = keys

    def upload(self) -> None:
        emu = self._emu
        snapshot_id = uuid.uuid4().hex
        stats = read_stats(emu)
        snapshot = {
            "parent": self._parent,
            "frame": emu.frame,
            "inputs": self._inputs,
            "metadata": {
                "player": read_player_name(emu),
                "position": read_position(emu),
                "badges": stats.badges,
                "party": [dataclasses.asdict(mon) for mon in stats.party],
                "client_time": time.time(),
            },
        }
        self._server.upload(snapshot_id, snapshot, emu.save_state())
        self._parent = snapshot_id
        self._inputs = []
        self._last = None  # the next segment starts by stating its key mask
