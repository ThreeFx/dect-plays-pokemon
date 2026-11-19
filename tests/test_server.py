import base64
import json
import random
import sqlite3
import threading
import zlib

import pytest

flask = pytest.importorskip("flask")
from werkzeug.serving import make_server  # noqa: E402

from dpp.server import MAX_PENDING_CLIENTS, create_app  # noqa: E402

ADMIN = {"Authorization": "Basic " + base64.b64encode(b"admin:secret").decode()}
ID_1 = "1" * 32
ID_2 = "2" * 32


@pytest.fixture
def app(tmp_path):
    return create_app(tmp_path / "server.sqlite3", "secret")


@pytest.fixture
def web(app):
    return app.test_client()


def _register(web, name="pi"):
    reply = web.post("/api/clients", json={"name": name}).get_json()
    return {"Authorization": f"Bearer {reply['token']}"}, reply["code"]


def _accept(web, client_id, snapshot=""):
    return web.post(f"/clients/{client_id}/accept", data={"snapshot": snapshot}, headers=ADMIN)


def _snapshot(parent=None, frame=600, state=b"state"):
    return {
        "parent": parent,
        "frame": frame,
        "inputs": [[10, 1], [18, 0], [30, 64], [38, 0]],
        "metadata": {"player": "RED", "badges": [True] + [False] * 7, "party": [{"nickname": "BULBASAUR", "level": 5}]},
        "state": base64.b64encode(zlib.compress(state)).decode(),
    }


def test_admin_pages_need_the_password(web):
    assert web.get("/").status_code == 401
    wrong = {"Authorization": "Basic " + base64.b64encode(b"admin:nope").decode()}
    assert web.get("/", headers=wrong).status_code == 401
    assert web.post("/clients/1/accept", headers=wrong).status_code == 401
    assert web.get(f"/snapshots/{ID_1}/state").status_code == 401
    assert web.get("/", headers=ADMIN).status_code == 200


def test_cross_site_posts_are_refused(web):
    _register(web)
    response = web.post("/clients/1/accept", headers=ADMIN | {"Sec-Fetch-Site": "cross-site"})
    assert response.status_code == 403


def test_client_can_do_nothing_until_accepted(web):
    token, code = _register(web)
    assert web.get("/api/client", headers=token).get_json() == {"status": "pending", "start_snapshot": None}
    assert web.put(f"/api/snapshots/{ID_1}", json=_snapshot(), headers=token).status_code == 403
    assert web.get(f"/api/snapshots/{ID_1}/state", headers=token).status_code == 403
    assert web.get("/api/client", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert code in web.get("/", headers=ADMIN).text


def test_accepted_client_uploads_and_the_next_client_continues_from_it(web):
    first, _ = _register(web, "first")
    assert _accept(web, 1).status_code == 302
    assert web.get("/api/client", headers=first).get_json() == {"status": "accepted", "start_snapshot": None}

    assert web.put(f"/api/snapshots/{ID_1}", json=_snapshot(), headers=first).status_code == 201
    assert web.put(f"/api/snapshots/{ID_1}", json=_snapshot(), headers=first).status_code == 200  # retry
    assert web.put(f"/api/snapshots/{ID_2}", json=_snapshot(ID_1, 1200, b"later"), headers=first).status_code == 201

    page = web.get("/", headers=ADMIN).text
    assert "2 snapshots, 4 button presses" in page
    assert "BULBASAUR L5" in page

    second, _ = _register(web, "second")
    page = web.get("/", headers=ADMIN).text
    assert page.index(ID_2) < page.index(ID_1), "the most recent snapshot is offered first"
    _accept(web, 2, ID_2)
    assert web.get("/api/client", headers=second).get_json() == {"status": "accepted", "start_snapshot": ID_2}
    assert zlib.decompress(web.get(f"/api/snapshots/{ID_2}/state", headers=second).data) == b"later"
    assert zlib.decompress(web.get(f"/snapshots/{ID_2}/state", headers=ADMIN).data) == b"later"

    # Only one client plays: the first one is out.
    assert web.get("/api/client", headers=first).get_json()["status"] == "replaced"
    assert web.put(f"/api/snapshots/{'3' * 32}", json=_snapshot(ID_2), headers=first).status_code == 403


def test_rejected_client(web):
    token, _ = _register(web)
    web.post("/clients/1/reject", headers=ADMIN)
    assert web.get("/api/client", headers=token).get_json()["status"] == "rejected"


@pytest.mark.parametrize(
    "change",
    [
        {"frame": -1},
        {"frame": "600"},
        {"parent": "not-an-id"},
        {"inputs": [[1, 2, 3]]},
        {"inputs": [[1, 5000]]},
        {"inputs": "nope"},
        {"metadata": []},
        {"state": "***"},
        {"state": ""},
    ],
)
def test_malformed_uploads_are_refused(web, change):
    token, _ = _register(web)
    _accept(web, 1)
    assert web.put(f"/api/snapshots/{ID_1}", json=_snapshot() | change, headers=token).status_code == 400
    assert web.put("/api/snapshots/short", json=_snapshot(), headers=token).status_code == 400


def test_accepting_needs_a_real_snapshot_and_a_pending_client(web):
    _register(web)
    assert _accept(web, 1, ID_1).status_code == 400
    assert _accept(web, 99).status_code == 404
    assert _accept(web, 1).status_code == 302
    assert _accept(web, 1).status_code == 404


def test_registration_is_bounded(web):
    for _ in range(MAX_PENDING_CLIENTS):
        assert web.post("/api/clients", json={"name": "x"}).status_code == 201
    assert web.post("/api/clients", json={"name": "x"}).status_code == 429
    assert web.post("/api/clients", json={"name": ""}).status_code == 400
    assert web.post("/api/clients", json=["x"]).status_code == 400


def test_client_names_are_escaped_on_the_admin_page(web):
    _register(web, "<script>alert(1)</script>")
    page = web.get("/", headers=ADMIN).text
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page


# ---- the real client against a real HTTP server ----------------------------


@pytest.fixture
def live_server(app):
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", app.test_client()
    server.shutdown()


def test_uploaded_inputs_replay_to_the_uploaded_state(live_server, emu, rom, tmp_path):
    """Play with random phone presses, upload twice, then rebuild the second state from the first plus its inputs."""
    import hashlib

    from dpp.emulator import Emulator
    from dpp.input import PHONE_KEYS, InputQueue
    from dpp.sync import Server, Uplink

    url, web = live_server
    server = Server(url, "test client")
    code = server.register()
    assert server.poll() == ("pending", None)
    assert code in web.get("/", headers=ADMIN).text
    _accept(web, 1)
    assert server.poll() == ("accepted", None)

    def ram(e):
        return hashlib.sha1(e.read(0x02000000, 0x40000) + e.read(0x03000000, 0x8000)).hexdigest()

    rng = random.Random(7)
    inputs = InputQueue()
    uplink = Uplink(server, emu, parent=None)

    def play(frames):
        for _ in range(frames):
            if rng.random() < 0.1:
                inputs.press_phone_key(rng.choice(list(PHONE_KEYS)))
            held = inputs.next_frame()
            uplink.record(held)
            emu.run_frame(held)

    play(1500)
    uplink.upload()
    play(1503)  # not a multiple of the press length, so a press is cut by the upload
    uplink.upload()
    expected = ram(emu)
    assert server.flush(10)

    db = sqlite3.connect(tmp_path / "server.sqlite3")
    (first_seq, first_id, first_frame), (second_seq, second_id, second_frame) = db.execute(
        "SELECT seq, id, frame FROM snapshots ORDER BY seq"
    ).fetchall()
    assert (first_frame, second_frame) == (1500, 3003)
    assert db.execute("SELECT parent_id FROM snapshots WHERE seq = ?", (second_seq,)).fetchone()[0] == first_id
    metadata = json.loads(db.execute("SELECT metadata FROM snapshots WHERE seq = ?", (second_seq,)).fetchone()[0])
    assert metadata["badges"] == [False] * 8 and metadata["party"] == []
    changes = dict(db.execute("SELECT frame, keys FROM inputs WHERE snapshot_seq = ?", (second_seq,)).fetchall())
    assert changes and min(changes) == first_frame

    # A second client is told to continue from the first snapshot and replays the logged inputs.
    replayer = Server(url, "replayer")
    replayer.register()
    _accept(web, 2, first_id)
    assert replayer.poll() == ("accepted", first_id)
    other = Emulator(rom)
    other.load_state(replayer.fetch_state(first_id))
    assert other.frame == first_frame
    keys = 0
    while other.frame < second_frame:
        keys = changes.get(other.frame, keys)
        other.run_frame(keys)
    assert ram(other) == expected

    other.load_state(replayer.fetch_state(second_id))
    assert ram(other) == expected
