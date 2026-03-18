# Apalache RPC Client

Minimalistic Python client for interaction with the Apalache model checker over
JSON RPC.

This project is hosted at GitHub. See [apalache-rpc-client][].

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

For an end-to-end JSON-RPC example that loads and explores
`examples/circular-buffer/MC10u8_BuggyCircularBuffer.tla`, see the repository
README at the project root.

For ordered multi-step exploration in one round trip, use the sequence builder:

```python
with client.sequence() as seq:
    init = seq.assume_transition(0)
    step = seq.next_step()
    view = seq.query(["OPERATOR", "TRACE"], operator="View")

assert init.result.snapshot_id >= 0
assert step.result >= 0
assert "operatorValue" in view.result
assert "trace" in view.result
```

[apalache-rpc-client]: https://github.com/konnov/apalache-rpc-client
