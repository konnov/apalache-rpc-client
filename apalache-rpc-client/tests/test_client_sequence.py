from apalache_rpc.client import (
    InvariantSatisfied,
    JsonRpcClient,
    SequenceExecutionError,
    TransitionEnabled,
)


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


def test_compact_returns_new_snapshot_id():
    client = JsonRpcClient()
    client.session_id = "session-1"
    captured = {}

    def fake_post(*args, **kwargs):
        captured["json"] = kwargs["json"]
        return FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": kwargs["json"]["id"],
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
        captured["json"] = kwargs["json"]
        return FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": kwargs["json"]["id"],
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


def test_sequence_compact_decodes_snapshot_id():
    client = JsonRpcClient()
    client.session_id = "session-1"
    captured = {}

    def fake_post(*args, **kwargs):
        captured["json"] = kwargs["json"]
        return FakeResponse(
            {
                "jsonrpc": "2.0",
                "id": kwargs["json"]["id"],
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
            "id": kwargs["json"]["id"],
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
            "id": kwargs["json"]["id"],
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
