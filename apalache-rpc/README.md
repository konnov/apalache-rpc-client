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

[apalache-rpc-client]: https://github.com/konnov/apalache-rpc-client