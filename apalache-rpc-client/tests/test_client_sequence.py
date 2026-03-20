import json

from apalache_rpc.client import (
    InvariantSatisfied,
    JsonRpcClient,
    SequenceExecutionError,
    TransitionEnabled,
)


def _payload(kwargs):
    """Extract the JSON-RPC payload from post() kwargs."""
    return json.loads(kwargs["data"])


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_query_returns_both_trace_and_operator_value():
    client = JsonRpcClient()
    client.session_id = "session-1"
    client._session.post = lambda *args, **kwargs: FakeResponse(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "operatorValue": {"#bigint": "1"},
                "trace": [{"state": 1}],
            },
        }
    )

    result = client.query(["OPERATOR", "TRACE"], operator="View")

    assert result == {
        "operatorValue": {"#bigint": "1"},
        "trace": [{"state": 1}],
    }


def test_query_returns_state():
    client = JsonRpcClient()
    client.session_id = "session-1"
    client._session.post = lambda *args, **kwargs: FakeResponse(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "state": {"counter": {"#bigint": "1"}},
            },
        }
    )

    result = client.query(["STATE"])

    assert result == {
        "state": {"counter": {"#bigint": "1"}},
    }


def test_compact_returns_new_snapshot_id():
    client = JsonRpcClient()
    client.session_id = "session-1"
    captured = {}

    def fake_post(*args, **kwargs):
        captured["json"] = _payload(kwargs)
        return FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": captured["json"]["id"],
                "result": {"sessionId": "session-1", "snapshotId": 7},
            }
        )

    client._session.post = fake_post

    result = client.compact(3)

    assert captured["json"]["method"] == "compact"
    assert captured["json"]["params"] == {
        "sessionId": "session-1",
        "snapshotId": 3,
        "timeoutSec": client.solver_timeout,
    }
    assert result == 7


def test_sequence_executes_one_apply_in_order_request():
    client = JsonRpcClient()
    client.session_id = "session-1"
    captured = {}

    def fake_post(*args, **kwargs):
        captured["json"] = _payload(kwargs)
        return FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": captured["json"]["id"],
                "result": {
                    "calls": [
                        {
                            "ok": True,
                            "method": "assumeTransition",
                            "result": {"snapshotId": 3, "status": "ENABLED"},
                        },
                        {
                            "ok": True,
                            "method": "nextStep",
                            "result": {"snapshotId": 4, "newStepNo": 1},
                        },
                        {
                            "ok": True,
                            "method": "query",
                            "result": {
                                "operatorValue": {"#bigint": "1"},
                                "trace": None,
                            },
                        },
                    ]
                },
            }
        )

    client._session.post = fake_post

    with client.sequence() as seq:
        transition = seq.assume_transition(0)
        snapshot = seq.next_step()
        view = seq.query(["OPERATOR"], operator="View")

    assert captured["json"]["method"] == "applyInOrder"
    assert len(captured["json"]["params"]["calls"]) == 3
    assert isinstance(transition.result, TransitionEnabled)
    assert snapshot.result == 4
    assert view.result == {"operatorValue": {"#bigint": "1"}}
    assert list(seq.results()) == [transition, snapshot, view]


def test_sequence_query_returns_state():
    client = JsonRpcClient()
    client.session_id = "session-1"
    captured = {}

    def fake_post(*args, **kwargs):
        captured["json"] = _payload(kwargs)
        return FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": captured["json"]["id"],
                "result": {
                    "calls": [
                        {
                            "ok": True,
                            "method": "query",
                            "result": {
                                "state": {"counter": {"#bigint": "2"}},
                            },
                        },
                    ]
                },
            }
        )

    client._session.post = fake_post

    with client.sequence() as seq:
        state = seq.query(["STATE"])

    assert captured["json"]["method"] == "applyInOrder"
    assert captured["json"]["params"]["calls"] == [
        {
            "method": "query",
            "params": {
                "sessionId": "session-1",
                "timeoutSec": client.solver_timeout,
                "kinds": ["STATE"],
            },
        }
    ]
    assert state.result == {"state": {"counter": {"#bigint": "2"}}}
    assert list(seq.results()) == [state]


def test_sequence_compact_decodes_snapshot_id():
    client = JsonRpcClient()
    client.session_id = "session-1"
    captured = {}

    def fake_post(*args, **kwargs):
        captured["json"] = _payload(kwargs)
        return FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": captured["json"]["id"],
                "result": {
                    "calls": [
                        {
                            "ok": True,
                            "method": "compact",
                            "result": {
                                "sessionId": "session-1",
                                "snapshotId": 9,
                            },
                        }
                    ]
                },
            }
        )

    client._session.post = fake_post

    with client.sequence() as seq:
        compacted = seq.compact(3)

    assert captured["json"]["method"] == "applyInOrder"
    assert captured["json"]["params"]["calls"] == [
        {
            "method": "compact",
            "params": {
                "sessionId": "session-1",
                "snapshotId": 3,
                "timeoutSec": client.solver_timeout,
            },
        }
    ]
    assert compacted.result == 9


def test_sequence_marks_unexecuted_steps_after_failure():
    client = JsonRpcClient()
    client.session_id = "session-1"
    client._session.post = lambda *args, **kwargs: FakeResponse(
        {
            "jsonrpc": "2.0",
            "id": _payload(kwargs)["id"],
            "result": {
                "calls": [
                    {
                        "ok": False,
                        "method": "assumeTransition",
                        "error": {"code": -32000, "message": "boom"},
                    }
                ]
            },
        }
    )

    with client.sequence() as seq:
        first = seq.assume_transition(0)
        later = seq.next_step()

    assert first.error is not None
    assert later.executed is False
    try:
        _ = later.result
        assert False, "Expected SequenceExecutionError"
    except SequenceExecutionError:
        pass


def test_sequence_check_invariants_aggregates_results():
    client = JsonRpcClient()
    client.session_id = "session-1"
    client._session.post = lambda *args, **kwargs: FakeResponse(
        {
            "jsonrpc": "2.0",
            "id": _payload(kwargs)["id"],
            "result": {
                "calls": [
                    {
                        "ok": True,
                        "method": "checkInvariant",
                        "result": {"invariantStatus": "SATISFIED", "trace": None},
                    },
                    {
                        "ok": True,
                        "method": "checkInvariant",
                        "result": {"invariantStatus": "SATISFIED", "trace": None},
                    },
                ]
            },
        }
    )

    with client.sequence() as seq:
        aggregate = seq.check_invariants(2, 0)

    assert isinstance(aggregate.result, InvariantSatisfied)


# ── Compression tests ──────────────────────────────────────────────


import gzip


def test_large_payload_is_gzip_compressed():
    client = JsonRpcClient()
    client.session_id = "session-1"
    captured = {}

    def fake_post(*args, **kwargs):
        captured.update(kwargs)
        return FakeResponse(
            {"jsonrpc": "2.0", "id": 1, "result": {"snapshotId": 3}}
        )

    client._session.post = fake_post

    # Build a payload large enough to exceed MIN_COMPRESS_SIZE (512 bytes)
    big_equalities = {f"var_{i}": i for i in range(100)}
    client._rpc_call("assumeState", {"sessionId": "session-1", "equalities": big_equalities})

    # Verify the body was gzip-compressed
    assert "Content-Encoding" in captured.get("headers", {}), "Expected Content-Encoding header"
    assert captured["headers"]["Content-Encoding"] == "gzip"
    decompressed = gzip.decompress(captured["data"])
    parsed = json.loads(decompressed)
    assert parsed["method"] == "assumeState"


def test_small_payload_is_not_compressed():
    client = JsonRpcClient()
    client.session_id = "session-1"
    captured = {}

    def fake_post(*args, **kwargs):
        captured.update(kwargs)
        return FakeResponse(
            {"jsonrpc": "2.0", "id": 1, "result": {}}
        )

    client._session.post = fake_post

    client._rpc_call("disposeSpec", {"sessionId": "session-1"})

    # Small payloads should not have Content-Encoding
    assert "headers" not in captured or "Content-Encoding" not in captured.get("headers", {})
    # Body is plain JSON bytes
    parsed = json.loads(captured["data"])
    assert parsed["method"] == "disposeSpec"


def test_compression_disabled_sends_plain_json():
    client = JsonRpcClient(compression=False)
    client.session_id = "session-1"
    captured = {}

    def fake_post(*args, **kwargs):
        captured.update(kwargs)
        return FakeResponse(
            {"jsonrpc": "2.0", "id": 1, "result": {"snapshotId": 3}}
        )

    client._session.post = fake_post

    # Even with a large payload, compression=False should send plain JSON
    big_equalities = {f"var_{i}": i for i in range(100)}
    client._rpc_call("assumeState", {"sessionId": "session-1", "equalities": big_equalities})

    assert "headers" not in captured or "Content-Encoding" not in captured.get("headers", {})
    parsed = json.loads(captured["data"])
    assert parsed["method"] == "assumeState"


def test_compression_disabled_no_accept_encoding():
    client = JsonRpcClient(compression=False)
    assert client._session.headers["Accept-Encoding"] == "identity"


def test_compression_enabled_sets_accept_encoding():
    client = JsonRpcClient(compression=True)
    assert client._session.headers["Accept-Encoding"] == "gzip"
