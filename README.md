# Apalache RPC Client

[![CI](https://github.com/konnov/apalache-rpc-client/actions/workflows/ci.yml/badge.svg)](https://github.com/konnov/apalache-rpc-client/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/konnov/apalache-rpc-client/branch/main/graph/badge.svg)](https://codecov.io/gh/konnov/apalache-rpc-client)
[![PyPI version](https://badge.fury.io/py/apalache-rpc-client.svg)](https://badge.fury.io/py/apalache-rpc-client)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/github/license/konnov/apalache-rpc-client)](LICENSE)

Minimalistic Python client for interaction with the Apalache model checker over
JSON RPC.

**Why?** Because now you can write your own test harnesses and symbolic search
tools that interact with TLA<sup>+</sup> and Quint specifications. Use it with
an AI agent, and you have got superpowers!

**Minimalistic.** Connections usually require tinkering with the parameters.
This library only provides a thin wrapper around the JSON-RPC calls to the
Apalache server. Start with this library, to get the initial setup working.
Once, you have hit the limits, just fork this project and extend it to your
needs.

**Server API**. Refer to the [Apalache JSON-RPC API][] for the interaction
details.

## Installation

You can install the package via pip:

```bash
pip install apalache-rpc-client
```

Make sure you have Apalache installed. Follow the [Apalache Installation Instructions][].

## Usage

### Install Apalache

```shell
# Install Java if you don't have it yet, e.g., on macOS:
brew install temurin@21
# Download Apalache if you don't have it yet
curl -L -o apalache.tgz https://github.com/apalache-mc/apalache/releases/latest/download/apalache.tgz
tar -xzf apalache.tgz
export APALACHE_HOME="$PWD/apalache"
```

### Start and Stop the Apalache Server

<!-- name: test_server -->
```python
import logging
import sys
import time
from tempfile import TemporaryDirectory

from apalache_rpc.server import ApalacheServer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[ logging.StreamHandler(sys.stdout) ]
)

with TemporaryDirectory() as log_dir:
    server = ApalacheServer(log_dir=log_dir, hostname="localhost", port=18080)
    assert server.start_server(), "Failed to start the Apalache server"
    time.sleep(5)  # Let the server run for a bit
    assert server.stop_server(), "Failed to stop the Apalache server"
```

### Call JSON-RPC Methods on the Circular Buffer Example

This example loads [`examples/circular-buffer/MC10u8_BuggyCircularBuffer.tla`](./examples/circular-buffer/MC10u8_BuggyCircularBuffer.tla)
and the imported base module, chooses an initial state, queries an exported
operator, checks invariants, explores a `Put` transition, and rolls back to the
initial snapshot.

<!-- name: test_circular_buffer_json_rpc -->
```python
from pathlib import Path
from tempfile import TemporaryDirectory

from apalache_rpc.client import (
    InvariantSatisfied,
    JsonRpcClient,
    NextModelFalse,
    NextModelTrue,
    TransitionEnabled,
)
from apalache_rpc.server import ApalacheServer

repo_root = Path.cwd()
if not (repo_root / "examples").exists():
    repo_root = repo_root.parent

examples_dir = repo_root / "examples" / "circular-buffer"
sources = [
    str(examples_dir / "MC10u8_BuggyCircularBuffer.tla"),
    str(examples_dir / "BuggyCircularBuffer.tla"),
]

with TemporaryDirectory() as log_dir:
    server = ApalacheServer(log_dir=log_dir, hostname="localhost", port=18081)
    assert server.start_server(), "Failed to start the Apalache server"

    try:
        with JsonRpcClient(port=18081, solver_timeout=30) as client:
            # Call loadSpec to register the TLA+ sources and named operators.
            spec = client.load_spec(
                sources=sources,
                init="Init",
                next="Next",
                invariants=["SafeInv"],
                view="CountView",
            )
            assert spec is not None
            assert spec["next"] == [
                {"index": 0, "labels": ["Put"]},
                {"index": 1, "labels": ["Get"]},
            ]

            # Call assumeTransition on the single initial transition.
            init_status = client.assume_transition(spec["init"][0]["index"])
            assert isinstance(init_status, TransitionEnabled)

            # Call nextStep to advance to the next frame (symbolic state).
            # This does not fix any initial state!
            init_snapshot = client.next_step()

            # Call query with OPERATOR to evaluate the exported CountView operator.
            count_view = client.query(["OPERATOR"], operator="CountView")
            assert count_view == {"operatorValue": {"#tup": [{"#bigint": "0"}]}}

            # Call checkInvariant for each registered invariant through check_invariants.
            inv_status = client.check_invariants(
                len(spec["state"]),
                len(spec["action"]),
            )
            assert isinstance(inv_status, InvariantSatisfied)

            # Call assumeTransition on the Put action from the current state.
            put_status = client.assume_transition(spec["next"][0]["index"])
            assert isinstance(put_status, TransitionEnabled)

            # Call nextModel to ask whether CountView can change in the next state.
            next_model = client.next_model("CountView")
            assert next_model["oldValue"] == {"#tup": [{"#bigint": "0"}]}
            assert isinstance(next_model["hasOld"], NextModelTrue)
            assert isinstance(next_model["hasNext"], NextModelFalse)

            # Call rollback to return to the saved initial snapshot.
            client.rollback(init_snapshot)

            # Call query again to confirm the rollback restored the old view.
            assert client.query(["OPERATOR"], operator="CountView") == count_view

            # Call disposeSpec to release the server-side session explicitly.
            client.dispose_spec()
    finally:
        assert server.stop_server(), "Failed to stop the Apalache server"
```

[Apalache JSON-RPC API]: https://github.com/apalache-mc/apalache/tree/main/json-rpc
[Apalache Installation Instructions]: https://apalache-mc.org/docs/apalache/installation/index.html
