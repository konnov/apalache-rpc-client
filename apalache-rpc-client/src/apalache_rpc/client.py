"""
JSON-RPC Client for communicating with the Apalache server.

This module provides a client interface to interact with the JSON-RPC
server that implements the Apalache Model Checker API in the explorer mode.

See: https://github.com/apalache-mc/apalache/tree/main/json-rpc

Igor Konnov, 2025
"""

import base64
import json
import logging
from dataclasses import dataclass
from typing import (
    Any,
    Callable,
    cast,
    Dict,
    Generic,
    Iterator,
    List,
    Optional,
    TypeVar,
    Union,
)

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@dataclass
class TransitionDisabled:
    """A value of this class represents a disabled transition."""

    trans_id: int
    snapshot_id: int


@dataclass
class TransitionEnabled:
    """A value of this class represents an enabled transition."""

    trans_id: int
    snapshot_id: int


@dataclass
class TransitionUnknown:
    """A value of this class represents a transition with unknown status."""

    trans_id: int
    snapshot_id: int


EnabledStatus = Union[TransitionEnabled, TransitionDisabled, TransitionUnknown]


@dataclass
class AssumptionDisabled:
    """A value of this class represents a disabled state assumption."""

    snapshot_id: int


@dataclass
class AssumptionEnabled:
    """A value of this class represents an enabled state assumption."""

    snapshot_id: int


@dataclass
class AssumptionUnknown:
    """A value of this class represents a state assumption with unknown status."""

    snapshot_id: int


AssumptionStatus = Union[AssumptionEnabled, AssumptionDisabled, AssumptionUnknown]


@dataclass
class InvariantSatisfied:
    """Represents that all checked invariants are satisfied."""

    pass


@dataclass
class InvariantViolated:
    """Represents a violated invariant with counterexample trace."""

    invariant_id: int
    trace: List[Dict[str, Any]]


@dataclass
class InvariantUnknown:
    """Represents an invariant check with unknown result."""

    invariant_id: int


InvariantStatus = Union[InvariantSatisfied, InvariantViolated, InvariantUnknown]


@dataclass
class NextModelTrue:
    """Represents that the next model computation returned True."""

    pass


@dataclass
class NextModelFalse:
    """Represents that the next model computation returned False."""

    pass


@dataclass
class NextModelUnknown:
    """Represents that the next model computation result is unknown."""

    pass


NextModelStatus = Union[NextModelTrue, NextModelFalse, NextModelUnknown]
T = TypeVar("T")


class JsonRpcError(Exception):
    """JSON-RPC specific error."""

    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"JSON-RPC Error {code}: {message}")


class SequenceExecutionError(Exception):
    """Raised when a sequence cannot produce a valid result."""


@dataclass
class SequenceStepError:
    """Structured step error returned by applyInOrder."""

    code: int
    message: str
    data: Any = None


@dataclass
class ScheduledStep:
    """A low-level step submitted to applyInOrder."""

    method: str
    params: Dict[str, Any]


class StepHandle(Generic[T]):
    """Handle to a scheduled step inside an ordered sequence."""

    def __init__(
        self,
        index: int,
        method: str,
        resolver: Callable[[Any], T],
        aggregate: Optional[Callable[[], T]] = None,
    ):
        self.index = index
        self.method = method
        self._resolver = resolver
        self._aggregate = aggregate
        self._done = False
        self._executed = False
        self._error: Optional[SequenceStepError] = None
        self._raw_result: Any = None
        self._result: Optional[T] = None
        self._has_result = False

    @property
    def done(self) -> bool:
        return self._done

    @property
    def executed(self) -> bool:
        return self._executed

    @property
    def error(self) -> Optional[SequenceStepError]:
        return self._error

    @property
    def result(self) -> T:
        if not self._done:
            raise SequenceExecutionError(
                f"Step {self.index} ({self.method}) has not been executed yet"
            )
        if self._error is not None:
            raise JsonRpcError(self._error.code, self._error.message, self._error.data)
        if not self._executed:
            raise SequenceExecutionError(
                f"Step {self.index} ({self.method}) was not executed"
            )
        if self._has_result:
            return self._result  # type: ignore[return-value]
        value = (
            self._aggregate()
            if self._aggregate is not None
            else self._resolver(self._raw_result)
        )
        self._result = value
        self._has_result = True
        return value

    def _set_raw_result(self, raw_result: Any) -> None:
        self._raw_result = raw_result
        self._done = True
        self._executed = True

    def _set_error(self, error: SequenceStepError) -> None:
        self._error = error
        self._done = True
        self._executed = True

    def _set_not_executed(self) -> None:
        self._done = True
        self._executed = False

    def _mark_aggregate_ready(self) -> None:
        self._done = True
        self._executed = True


class OrderedSequenceBuilder:
    """Collects exploration steps and executes them with applyInOrder."""

    def __init__(self, client: "JsonRpcClient", strict: bool = False):
        self._client = client
        self._strict = strict
        self._executed = False
        self._steps: List[ScheduledStep] = []
        self._step_handles: List[StepHandle[Any]] = []
        self._aggregate_handles: List[StepHandle[Any]] = []
        self._public_handles: List[StepHandle[Any]] = []

    def __enter__(self) -> "OrderedSequenceBuilder":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is None:
            self.execute()

    def _ensure_not_executed(self) -> None:
        if self._executed:
            raise SequenceExecutionError("This sequence has already been executed")

    def _schedule(
        self, method: str, params: Dict[str, Any], resolver: Callable[[Any], T]
    ) -> StepHandle[T]:
        self._ensure_not_executed()
        handle: StepHandle[T] = StepHandle(len(self._public_handles), method, resolver)
        self._steps.append(ScheduledStep(method=method, params=params))
        self._step_handles.append(handle)
        self._public_handles.append(handle)
        return handle

    def _schedule_aggregate(
        self, method: str, aggregate: Callable[[], T]
    ) -> StepHandle[T]:
        resolver = cast(Callable[[Any], T], lambda _: None)
        handle: StepHandle[T] = StepHandle(
            len(self._public_handles),
            method,
            resolver,
            aggregate=aggregate,
        )
        self._aggregate_handles.append(handle)
        self._public_handles.append(handle)
        return handle

    def assume_transition(
        self, transition_id: int, check_enabled: bool = True
    ) -> StepHandle[EnabledStatus]:
        return self._schedule(
            "assumeTransition",
            {
                "sessionId": self._client.session_id,
                "transitionId": transition_id,
                "checkEnabled": check_enabled,
                "timeoutSec": self._client.solver_timeout,
            },
            lambda response: self._client._decode_assume_transition(
                transition_id, check_enabled, response
            ),
        )

    def assume_state(
        self, equalities: Dict[str, Any], check_enabled: bool = True
    ) -> StepHandle[AssumptionStatus]:
        return self._schedule(
            "assumeState",
            {
                "sessionId": self._client.session_id,
                "equalities": equalities,
                "checkEnabled": check_enabled,
                "timeoutSec": self._client.solver_timeout,
            },
            lambda response: self._client._decode_assume_state(check_enabled, response),
        )

    def next_step(self) -> StepHandle[int]:
        return self._schedule(
            "nextStep",
            {"sessionId": self._client.session_id},
            self._client._decode_next_step,
        )

    def query(self, kinds: List[str], **kwargs: Any) -> StepHandle[Dict[str, Any]]:
        return self._schedule(
            "query",
            {
                **kwargs,
                "sessionId": self._client.session_id,
                "timeoutSec": self._client.solver_timeout,
                "kinds": kinds,
            },
            lambda response: self._client._decode_query(kinds, response),
        )

    def next_model(self, operator: str) -> StepHandle[Dict[str, Any]]:
        return self._schedule(
            "nextModel",
            {
                "sessionId": self._client.session_id,
                "timeoutSec": self._client.solver_timeout,
                "operator": operator,
            },
            self._client._decode_next_model,
        )

    def rollback(self, snapshot_id: int) -> StepHandle[None]:
        return self._schedule(
            "rollback",
            {
                "sessionId": self._client.session_id,
                "snapshotId": snapshot_id,
            },
            lambda response: None,
        )

    def check_invariants(
        self, nstate: int, naction: int
    ) -> StepHandle[InvariantStatus]:
        child_handles: List[StepHandle[InvariantStatus]] = []
        for kind, inv_id in [("STATE", i) for i in range(nstate)] + [
            ("ACTION", i) for i in range(naction)
        ]:

            def decode_check_invariant(
                response: Any, inv_id: int = inv_id
            ) -> InvariantStatus:
                return self._client._decode_check_invariant(inv_id, response)

            child_handles.append(
                self._schedule(
                    "checkInvariant",
                    {
                        "sessionId": self._client.session_id,
                        "invariantId": inv_id,
                        "kind": kind,
                        "timeoutSec": self._client.solver_timeout,
                    },
                    decode_check_invariant,
                )
            )

        def aggregate() -> InvariantStatus:
            for handle in child_handles:
                result = handle.result
                if isinstance(result, InvariantViolated):
                    return result
                if isinstance(result, InvariantUnknown):
                    return result
            return InvariantSatisfied()

        return self._schedule_aggregate("checkInvariants", aggregate)

    def execute(self) -> "OrderedSequenceBuilder":
        self._ensure_not_executed()
        self._executed = True
        step_results = self._client.apply_in_order_raw(self._steps)

        for handle, step_result in zip(self._step_handles, step_results):
            if step_result.get("ok", False):
                handle._set_raw_result(step_result.get("result"))
            else:
                error = step_result.get("error", {})
                handle._set_error(
                    SequenceStepError(
                        error.get("code", -4),
                        error.get("message", "Unknown applyInOrder call error"),
                        error.get("data"),
                    )
                )
                break

        for handle in self._step_handles[len(step_results) :]:
            handle._set_not_executed()

        for handle in self._aggregate_handles:
            handle._mark_aggregate_ready()

        if self._strict:
            for handle in self._step_handles:
                if handle.error is not None:
                    _ = handle.result
        return self

    def results(self) -> Iterator[StepHandle[Any]]:
        if not self._executed:
            raise SequenceExecutionError("The sequence has not been executed yet")
        return iter(self._public_handles)


class JsonRpcClient:
    """Client for JSON-RPC communication with Apalache server."""

    def __init__(
        self, hostname: str = "localhost", port: int = 8822, solver_timeout: int = 600
    ):
        self.rpc_url = f"http://{hostname}:{port}/rpc"
        self.port = port
        self.conn_timeout = 10.0
        self.solver_timeout = solver_timeout
        self.session_id: Optional[str] = None
        self._request_id = 0
        self.log = logging.getLogger(__name__)
        self._session = requests.Session()
        self._session.headers.update(
            {"Connection": "keep-alive", "Content-Type": "application/json"}
        )

        retry_strategy = Retry(
            total=3,
            backoff_factor=0.1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["POST"],
        )
        adapter = HTTPAdapter(
            pool_connections=1,
            pool_maxsize=10,
            max_retries=retry_strategy,
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def _info(self, msg: str) -> None:
        self.log.info(msg)

    def _error(self, msg: str) -> None:
        self.log.error(msg)

    def _next_request_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _rpc_payload(self, method: str, params: Any = None) -> Dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self._next_request_id(),
        }

    def _rpc_call(
        self, method: str, params: Any = None, timeout: Optional[int] = None
    ) -> Any:
        if timeout is None:
            long_running_methods = {
                "loadSpec",
                "assumeTransition",
                "assumeState",
                "checkInvariant",
                "nextStep",
                "query",
                "nextModel",
                "applyInOrder",
            }
            if method in long_running_methods:
                timeout = self.solver_timeout + 30
            else:
                timeout = max(60, int(self.conn_timeout * 6))

        payload = self._rpc_payload(method, params)

        try:
            response = self._session.post(self.rpc_url, json=payload, timeout=timeout)
            response.raise_for_status()
        except requests.exceptions.Timeout as e:
            raise JsonRpcError(-1, f"Request timed out after {timeout}s: {e}")
        except requests.exceptions.HTTPError as e:
            raise JsonRpcError(-2, f"HTTP error: {e}")
        except requests.exceptions.RequestException as e:
            raise JsonRpcError(-3, f"Request failed: {e}")

        data = response.json()
        if "error" in data:
            error = data["error"]
            raise JsonRpcError(
                error.get("code", -4),
                error.get("message", str(error)),
                error.get("data"),
            )
        return data.get("result")

    def _decode_assume_transition(
        self, transition_id: int, check_enabled: bool, response: Dict[str, Any]
    ) -> EnabledStatus:
        status = response["status"]
        snapshot_id = response["snapshotId"]
        if status == "ENABLED":
            return TransitionEnabled(transition_id, snapshot_id)
        if status == "DISABLED":
            return TransitionDisabled(transition_id, snapshot_id)
        if check_enabled:
            return TransitionUnknown(transition_id, snapshot_id)
        return TransitionEnabled(transition_id, snapshot_id)

    def _decode_assume_state(
        self, check_enabled: bool, response: Dict[str, Any]
    ) -> AssumptionStatus:
        status = response["status"]
        snapshot_id = response["snapshotId"]
        if status == "ENABLED":
            return AssumptionEnabled(snapshot_id)
        if status == "DISABLED":
            return AssumptionDisabled(snapshot_id)
        if check_enabled:
            return AssumptionUnknown(snapshot_id)
        return AssumptionEnabled(snapshot_id)

    def _decode_check_invariant(
        self, inv_id: int, response: Dict[str, Any]
    ) -> InvariantStatus:
        status = response["invariantStatus"]
        if status == "VIOLATED":
            return InvariantViolated(invariant_id=inv_id, trace=response["trace"])
        if status == "UNKNOWN":
            return InvariantUnknown(invariant_id=inv_id)
        return InvariantSatisfied()

    def _decode_next_step(self, response: Dict[str, Any]) -> int:
        return int(response["snapshotId"])

    def _decode_query(
        self, kinds: List[str], response: Dict[str, Any]
    ) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        if "OPERATOR" in kinds:
            result["operatorValue"] = response["operatorValue"]
        if "TRACE" in kinds:
            result["trace"] = response["trace"]
        return result

    def _decode_next_model(self, response: Dict[str, Any]) -> Dict[str, Any]:
        def to_status(status: str) -> NextModelStatus:
            if status == "TRUE":
                return NextModelTrue()
            if status == "FALSE":
                return NextModelFalse()
            return NextModelUnknown()

        return {
            "oldValue": response["oldValue"],
            "hasOld": to_status(response["hasOld"]),
            "hasNext": to_status(response["hasNext"]),
        }

    def load_spec(
        self,
        sources: List[str],
        init: str,
        next: str,
        invariants: List[str],
        view: Optional[str],
    ) -> Any:
        self._info(f"Loading specification from: {', '. join(sources)}")

        sources_base64 = []
        for filename in sources:
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    text = f.read()
                    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
                    sources_base64.append(encoded)
            except Exception as e:
                self._error(f"Error reading specification file: {e}")
                return None

        params = {
            "sources": sources_base64,
            "init": init,
            "next": next,
            "invariants": invariants,
            "exports": [view] if view else [],
        }

        try:
            response = self._rpc_call("loadSpec", params)

            self.session_id = response["sessionId"]
            snapshot_id = response["snapshotId"]
            spec_params = response["specParameters"]
            init_transitions = spec_params.get("initTransitions", [])
            next_transitions = spec_params.get("nextTransitions", [])
            state_invariants = spec_params.get("stateInvariants", [])
            action_invariants = spec_params.get("actionInvariants", [])

            self._info("Specification loaded successfully!")
            self._info(f"Session ID: {self.session_id}")
            self._info(f"Initial transitions: {len(init_transitions)}")
            self._info(f"Next transitions: {len(next_transitions)}")
            self._info(f"State invariants: {len(state_invariants)}")
            self._info(f"Action invariants: {len(action_invariants)}")

            return {
                "init": init_transitions,
                "next": next_transitions,
                "state": state_invariants,
                "action": action_invariants,
                "snapshot_id": snapshot_id,
            }
        except Exception as e:
            self._error(f"Error loading specification: {e}")
            return None

    def dispose_spec(self) -> None:
        if self.session_id:
            try:
                self._rpc_call("disposeSpec", {"sessionId": self.session_id})
                self._info("Specification session disposed")
            except Exception as e:
                self._error(f"Error disposing specification: {e}")

    def check_invariants(self, nstate: int, naction: int) -> InvariantStatus:
        request_timeout = self.solver_timeout + 60

        for kind, inv_id in [("STATE", i) for i in range(nstate)] + [
            ("ACTION", i) for i in range(naction)
        ]:
            try:
                response = self._rpc_call(
                    "checkInvariant",
                    {
                        "sessionId": self.session_id,
                        "invariantId": inv_id,
                        "kind": kind,
                        "timeoutSec": self.solver_timeout,
                    },
                    timeout=request_timeout,
                )
                result = self._decode_check_invariant(inv_id, response)
                if isinstance(result, InvariantViolated):
                    self._info(f"Invariant ID {inv_id} is violated!")
                    if response["trace"]:
                        self._info(json.dumps(response["trace"], indent=2))
                    return result
                if isinstance(result, InvariantUnknown):
                    self._info(f"Invariant {inv_id}: UNKNOWN (timeout or solver issue)")
                    return result
            except Exception as e:
                self._error(f"Error checking invariant {inv_id}: {e}")
                return InvariantUnknown(invariant_id=inv_id)

        return InvariantSatisfied()

    def rollback(self, snapshot_id: int) -> None:
        self._rpc_call(
            "rollback",
            {
                "sessionId": self.session_id,
                "snapshotId": snapshot_id,
            },
        )

    def assume_transition(
        self, transition_id: int, check_enabled: bool = True
    ) -> EnabledStatus:
        response = self._rpc_call(
            "assumeTransition",
            {
                "sessionId": self.session_id,
                "transitionId": transition_id,
                "checkEnabled": check_enabled,
                "timeoutSec": self.solver_timeout,
            },
        )
        result = self._decode_assume_transition(transition_id, check_enabled, response)
        if isinstance(result, TransitionEnabled):
            self._info(f"Transition {transition_id}: ENABLED")
        elif isinstance(result, TransitionDisabled):
            self._info(f"Transition {transition_id}: DISABLED")
        else:
            self._error(f"Transition {transition_id}: UNKNOWN")
        return result

    def assume_state(
        self, equalities: Dict[str, Any], check_enabled: bool = True
    ) -> AssumptionStatus:
        response = self._rpc_call(
            "assumeState",
            {
                "sessionId": self.session_id,
                "equalities": equalities,
                "checkEnabled": check_enabled,
                "timeoutSec": self.solver_timeout,
            },
        )
        result = self._decode_assume_state(check_enabled, response)
        if isinstance(result, AssumptionEnabled):
            self._info("AssumeState: ENABLED")
        elif isinstance(result, AssumptionDisabled):
            self._info("AssumeState: DISABLED")
        else:
            self._error("AssumeState: UNKNOWN")
        return result

    def next_step(self) -> int:
        response = self._rpc_call("nextStep", {"sessionId": self.session_id})
        self._info(f"Moved to step {response['newStepNo']}")
        return self._decode_next_step(response)

    def query(self, kinds: List[str], **kwargs: Any) -> Dict[str, Any]:
        response = self._rpc_call(
            "query",
            {
                **kwargs,
                "sessionId": self.session_id,
                "timeoutSec": self.solver_timeout,
                "kinds": kinds,
            },
        )
        return self._decode_query(kinds, response)

    def next_model(self, operator: str) -> Dict[str, Any]:
        response = self._rpc_call(
            "nextModel",
            {
                "sessionId": self.session_id,
                "timeoutSec": self.solver_timeout,
                "operator": operator,
            },
        )
        return self._decode_next_model(response)

    def apply_in_order_raw(self, steps: List[ScheduledStep]) -> List[Dict[str, Any]]:
        if self.session_id is None:
            raise SequenceExecutionError("No active session. Call load_spec() first.")
        response = self._rpc_call(
            "applyInOrder",
            {
                "sessionId": self.session_id,
                "calls": [
                    {"method": step.method, "params": step.params} for step in steps
                ],
            },
        )
        return cast(List[Dict[str, Any]], response["calls"])

    def sequence(self, strict: bool = False) -> OrderedSequenceBuilder:
        if self.session_id is None:
            raise SequenceExecutionError("No active session. Call load_spec() first.")
        return OrderedSequenceBuilder(self, strict=strict)

    def set_solver_timeout(self, timeout: int) -> None:
        self.solver_timeout = timeout
        self._info(f"Solver timeout updated to {timeout} seconds")

    def close(self) -> None:
        if hasattr(self, "_session") and self._session:
            self._session.close()

    def __enter__(self) -> "JsonRpcClient":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
