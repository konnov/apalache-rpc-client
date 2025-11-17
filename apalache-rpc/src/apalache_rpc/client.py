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
from typing import Any, Dict, List, Optional, Union

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@dataclass
class TransitionDisabled:
    """A value of this class represents a disabled transition.

    Attributes:
        trans_id: The transition identifier
        snapshot_id: The snapshot identifier before assuming the transition
    """

    trans_id: int
    snapshot_id: int


@dataclass
class TransitionEnabled:
    """A value of this class represents an enabled transition.

    Attributes:
        trans_id: The transition identifier
        snapshot_id: The snapshot identifier after assuming the transition
    """

    trans_id: int
    snapshot_id: int


@dataclass
class TransitionUnknown:
    """A value of this class represents a transition with unknown status.

    The status may be unknown due to solver timeout or other issues.

    Attributes:
        trans_id: The transition identifier
        snapshot_id: The snapshot identifier after assuming the transition
    """

    trans_id: int
    snapshot_id: int


EnabledStatus = Union[TransitionEnabled, TransitionDisabled, TransitionUnknown]


@dataclass
class AssumptionDisabled:
    """A value of this class represents a disabled state assumption.

    Attributes:
        snapshot_id: The snapshot identifier before the assumption
    """

    snapshot_id: int


@dataclass
class AssumptionEnabled:
    """A value of this class represents an enabled state assumption.

    Attributes:
        snapshot_id: The snapshot identifier after the assumption
    """

    snapshot_id: int


@dataclass
class AssumptionUnknown:
    """A value of this class represents a state assumption with unknown status.

    The status may be unknown due to solver timeout or other issues.

    Attributes:
        snapshot_id: The snapshot identifier after the assumption
    """

    snapshot_id: int


AssumptionStatus = Union[AssumptionEnabled, AssumptionDisabled, AssumptionUnknown]


@dataclass
class InvariantSatisfied:
    """Represents that all checked invariants are satisfied."""

    pass


@dataclass
class InvariantViolated:
    """Represents a violated invariant with counterexample trace.
       The counterexample trace is a Python representation of the JSON ITF format.

    Attributes:
        invariant_id: The identifier of the violated invariant
        trace: The counterexample trace showing how the invariant was violated
    """

    invariant_id: int
    trace: List[Dict[str, Any]]


@dataclass
class InvariantUnknown:
    """Represents an invariant check with unknown result.

    The result may be unknown due to solver timeout or other issues.

    Attributes:
        invariant_id: The identifier of the invariant
    """

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
    """Represents that the next model computation result is unknown.

    The result may be unknown due to solver timeout or other issues.
    """

    pass


NextModelStatus = Union[NextModelTrue, NextModelFalse, NextModelUnknown]


class JsonRpcError(Exception):
    """JSON-RPC specific error."""

    def __init__(self, code: int, message: str, data: Any = None):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"JSON-RPC Error {code}: {message}")


class JsonRpcClient:
    """Client for JSON-RPC communication with Apalache server."""

    def __init__(
        self, hostname: str = "localhost", port: int = 8822, solver_timeout: int = 600
    ):
        """Initialize the JSON-RPC client.

        Args:
            hostname: Hostname of the JSON-RPC server (default: "localhost")
            port: Port of the JSON-RPC server (default: 8822)
            solver_timeout: Timeout for solver operations in seconds (default: 600)
        """
        self.rpc_url = f"http://{hostname}:{port}/rpc"
        self.port = port
        self.conn_timeout = 10.0  # seconds
        self.solver_timeout = solver_timeout  # seconds
        self.session_id: Optional[str] = None
        self._request_id = 0
        self.log = logging.getLogger(__name__)

        # Create a persistent session for connection reuse
        self._session = requests.Session()

        # Set keep-alive headers
        self._session.headers.update(
            {"Connection": "keep-alive", "Content-Type": "application/json"}
        )

        # Configure connection pooling with retry strategy
        retry_strategy = Retry(
            total=3,  # Total number of retries
            backoff_factor=0.1,  # Backoff factor between retries
            status_forcelist=[429, 500, 502, 503, 504],  # HTTP status codes to retry
            allowed_methods=["POST"],  # Only retry POST requests
        )

        adapter = HTTPAdapter(
            pool_connections=1,  # Number of connection pools
            pool_maxsize=10,  # Number of connections to save in the pool
            max_retries=retry_strategy,  # Retry strategy
        )
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

    def _info(self, msg: str) -> None:
        """Log an info message.

        Args:
            msg: The message to log
        """
        self.log.info(msg)

    def _error(self, msg: str) -> None:
        """Log an error message.

        Args:
            msg: The error message to log
        """
        self.log.error(msg)

    def _next_request_id(self) -> int:
        """Generate next request ID.

        Returns:
            The next sequential request ID
        """
        self._request_id += 1
        return self._request_id

    def _rpc_call(
        self, method: str, params: Any = None, timeout: Optional[int] = None
    ) -> Any:
        """Execute a JSON-RPC call to the server.

        Args:
            method: The RPC method name to call
            params: Optional parameters for the RPC method
            timeout: Optional timeout in seconds (auto-determined if not provided)

        Returns:
            The result from the RPC call

        Raises:
            JsonRpcError: If the RPC call fails or times out
        """
        # Use solver timeout for long-running operations, connection timeout for others
        if timeout is None:
            # Long-running operations that might need more time
            long_running_methods = {
                "loadSpec",
                "assumeTransition",
                "assumeState",
                "checkInvariant",
                "nextStep",
                "query",
                "nextModel",
            }
            if method in long_running_methods:
                timeout = self.solver_timeout + 30  # Add buffer to solver timeout
            else:
                timeout = max(
                    60, int(self.conn_timeout * 6)
                )  # Minimum 60s for other operations

        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
            "id": self._next_request_id(),
        }

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

    def load_spec(
        self,
        sources: List[str],
        init: str,
        next: str,
        invariants: List[str],
        view: Optional[str],
    ) -> Any:
        """Load a TLA+ specification into the Apalache server.

        Args:
            sources: List of file paths to TLA+ specification files
            init: Name of the initialization predicate
            next: Name of the next-state relation
            invariants: List of invariant names to check
            view: Optional view operator name for state projection

        Returns:
            Dictionary containing:
                - init: List of initial transitions
                - next: List of next transitions
                - state: List of state invariants
                - action: List of action invariants
                - snapshot_id: The snapshot ID after loading
            Returns None if loading fails

        Raises:
            JsonRpcError: If the RPC call fails
        """
        self._info(f"Loading specification from: {', '. join(sources)}")

        sources_base64 = []
        # Read the specification file
        for filename in sources:
            try:
                with open(filename, "r", encoding="utf-8") as f:
                    text = f.read()
                    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
                    sources_base64.append(encoded)
            except Exception as e:
                self._error(f"Error reading specification file: {e}")
                return None

        # Make the loadSpec RPC call
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
            initTransitions = spec_params.get("initTransitions", [])
            nextTransitions = spec_params.get("nextTransitions", [])
            stateInvariants = spec_params.get("stateInvariants", [])
            actionInvariants = spec_params.get("actionInvariants", [])

            self._info("Specification loaded successfully!")
            self._info(f"Session ID: {self.session_id}")
            self._info(f"Initial transitions: {len(initTransitions)}")
            self._info(f"Next transitions: {len(nextTransitions)}")
            self._info(f"State invariants: {len(stateInvariants)}")
            self._info(f"Action invariants: {len(actionInvariants)}")

            return {
                "init": initTransitions,
                "next": nextTransitions,
                "state": stateInvariants,
                "action": actionInvariants,
                "snapshot_id": snapshot_id,
            }

        except Exception as e:
            self._error(f"Error loading specification: {e}")
            return None

    def dispose_spec(self) -> None:
        """Dispose of the current specification session.

        Cleans up resources associated with the current session on the server.
        Should be called when done working with a specification.
        """
        if self.session_id:
            params = {"sessionId": self.session_id}
            try:
                self._rpc_call("disposeSpec", params)
                self._info("Specification session disposed")
            except Exception as e:
                self._error(f"Error disposing specification: {e}")

    def check_invariants(self, nstate: int, naction: int) -> InvariantStatus:
        """Check all invariants against the current state.

        Iterates through all state and action invariants, checking each one
        using the solver. Returns immediately if a violation is found.

        Args:
            nstate: Number of state invariants to check
            naction: Number of action invariants to check

        Returns:
            InvariantSatisfied if all invariants hold,
            InvariantViolated with counterexample if a violation is found,
            InvariantUnknown if the solver times out or encounters an error

        Raises:
            JsonRpcError: If the RPC call fails
        """
        # Use a longer timeout for invariant checking if not specified
        request_timeout = self.solver_timeout + 60

        for kind, inv_id in [("STATE", i) for i in range(nstate)] + [
            ("ACTION", i) for i in range(naction)
        ]:
            params = {
                "sessionId": self.session_id,
                "invariantId": inv_id,
                "kind": kind,
                "timeoutSec": self.solver_timeout,
            }

            try:
                response = self._rpc_call(
                    "checkInvariant", params, timeout=request_timeout
                )
                status = response["invariantStatus"]

                if status == "VIOLATED":
                    self._info(f"Invariant ID {inv_id} is violated!")
                    self._info("Counterexample:")
                    if response["trace"]:
                        self._info(json.dumps(response["trace"], indent=2))
                    return InvariantViolated(
                        invariant_id=inv_id, trace=response["trace"]
                    )
                elif status == "UNKNOWN":
                    self._info(
                        f"Invariant {inv_id}: UNKNOWN " "(timeout or solver issue)"
                    )
                    return InvariantUnknown(invariant_id=inv_id)

            except Exception as e:
                self._error(f"Error checking invariant {inv_id}: {e}")
                return InvariantUnknown(invariant_id=inv_id)

        return InvariantSatisfied()

    def rollback(self, snapshot_id: int) -> None:
        """Roll back the exploration state to an earlier snapshot.

        Args:
            snapshot_id: The snapshot ID to roll back to

        Raises:
            JsonRpcError: If the RPC call fails
        """
        params = {
            "sessionId": self.session_id,
            "snapshotId": snapshot_id,
        }

        self._rpc_call("rollback", params)

    def assume_transition(
        self, transition_id: int, check_enabled: bool = True
    ) -> EnabledStatus:
        """Assume a transition is taken and check if it's enabled.

        Constrains the current exploration state by assuming the specified
        transition is taken, and optionally checks if it's actually enabled.

        Args:
            transition_id: The ID of the transition to assume
            check_enabled: Whether to check if the transition is enabled
                (default: True)

        Returns:
            TransitionEnabled if the transition is enabled,
            TransitionDisabled if the transition is disabled,
            TransitionUnknown if the solver cannot determine the status

        Raises:
            JsonRpcError: If the RPC call fails
        """
        params = {
            "sessionId": self.session_id,
            "transitionId": transition_id,
            "checkEnabled": check_enabled,
            "timeoutSec": self.solver_timeout,
        }

        response = self._rpc_call("assumeTransition", params)
        status = response["status"]
        snapshot_id = response["snapshotId"]

        if status == "ENABLED":
            self._info(f"Transition {transition_id}: ENABLED")
            return TransitionEnabled(transition_id, snapshot_id)
        elif status == "DISABLED":
            self._info(f"Transition {transition_id}: DISABLED")
            return TransitionDisabled(transition_id, snapshot_id)
        else:  # UNKNOWN
            if check_enabled:
                self._error(f"Transition {transition_id}: UNKNOWN")
                return TransitionUnknown(transition_id, snapshot_id)
            else:
                # assume it's enabled for exploration
                return TransitionEnabled(transition_id, snapshot_id)

    def assume_state(
        self, equalities: Dict[str, Any], check_enabled: bool = True
    ) -> AssumptionStatus:
        """Assume state equalities hold and check if the assumption is satisfiable.

        Constrains the current exploration state by assuming certain variables
        are equal to specific values.

        Args:
            equalities: Dictionary mapping variable names to their assumed values
            check_enabled: Whether to check if the assumption is satisfiable
                (default: True)

        Returns:
            AssumptionEnabled if the assumption is satisfiable,
            AssumptionDisabled if the assumption is unsatisfiable,
            AssumptionUnknown if the solver cannot determine the status

        Raises:
            JsonRpcError: If the RPC call fails
        """
        params = {
            "sessionId": self.session_id,
            "equalities": equalities,
            "checkEnabled": check_enabled,
            "timeoutSec": self.solver_timeout,
        }

        response = self._rpc_call("assumeState", params)
        status = response["status"]
        snapshot_id = response["snapshotId"]

        if status == "ENABLED":
            self._info("AssumeState: ENABLED")
            return AssumptionEnabled(snapshot_id)
        elif status == "DISABLED":
            self._info("AssumeState: DISABLED")
            return AssumptionDisabled(snapshot_id)
        else:  # UNKNOWN
            if check_enabled:
                self._error("AssumeState: UNKNOWN")
                return AssumptionUnknown(snapshot_id)
            else:
                # assume it's enabled for exploration
                return AssumptionEnabled(snapshot_id)

    def next_step(self) -> int:
        """Move to the next step in the exploration.

        Advances the exploration by one step, creating a new snapshot.

        Returns:
            The snapshot ID of the new step

        Raises:
            JsonRpcError: If the RPC call fails
        """
        params = {"sessionId": self.session_id}

        response = self._rpc_call("nextStep", params)
        new_step = response["newStepNo"]

        self._info(f"Moved to step {new_step}")
        return int(response["snapshotId"])

    def query(self, kinds: List[str], **kwargs: Any) -> Dict[str, Any]:
        """Execute a query against the current exploration context.

        Args:
            kinds: List of query kinds (e.g., ["OPERATOR"] or ["TRACE"])
            **kwargs: Additional query-specific parameters

        Returns:
            Dictionary containing query results based on the requested kinds

        Raises:
            JsonRpcError: If the RPC call fails
        """
        params = {
            **kwargs,
            "sessionId": self.session_id,
            "timeoutSec": self.solver_timeout,
            "kinds": kinds,
        }

        response = self._rpc_call("query", params)
        result = {}
        if "OPERATOR" in kinds:
            result["operatorValue"] = response["operatorValue"]
        elif "TRACE" in kinds:
            result["trace"] = response["trace"]

        return result

    def next_model(self, operator: str) -> Dict[str, Any]:
        """Attempt to compute the next model for a given operator.

        Args:
            operator: The operator expression to evaluate for the next model

        Returns:
            Dictionary containing:
                - oldValue: The old value of the operator
                - hasOld: Status indicating if old value exists (NextModelStatus)
                - hasNext: Status indicating if next value exists (NextModelStatus)

        Raises:
            JsonRpcError: If the RPC call fails
        """
        params = {
            "sessionId": self.session_id,
            "timeoutSec": self.solver_timeout,
            "operator": operator,
        }

        response = self._rpc_call("nextModel", params)

        def to_status(s: str) -> NextModelStatus:
            if s == "TRUE":
                return NextModelTrue()
            elif s == "FALSE":
                return NextModelFalse()
            else:
                return NextModelUnknown()

        return {
            "oldValue": response["oldValue"],
            "hasOld": to_status(response["hasOld"]),
            "hasNext": to_status(response["hasNext"]),
        }

    def set_solver_timeout(self, timeout: int) -> None:
        """Update the solver timeout for long-running operations.

        Args:
            timeout: New solver timeout in seconds
        """
        self.solver_timeout = timeout
        self._info(f"Solver timeout updated to {timeout} seconds")

    def close(self) -> None:
        """Close the HTTP session and clean up resources.

        Should be called when done with the client to properly release
        network connections. Automatically called when using the client
        as a context manager.
        """
        if hasattr(self, "_session") and self._session:
            self._session.close()

    def __enter__(self) -> "JsonRpcClient":
        """Enter the context manager.

        Returns:
            The client instance for use in the context

        Example:
            with JsonRpcClient() as client:
                client.load_spec(...)
        """
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the context manager and clean up resources.

        Args:
            exc_type: Exception type if an exception occurred
            exc_val: Exception value if an exception occurred
            exc_tb: Exception traceback if an exception occurred
        """
        self.close()
