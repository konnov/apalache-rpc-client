# [0.7.0] - 2026-03-20

## Added

 - Enable gzip compression for JSON-RPC requests and responses by default.
   Requests larger than 512 bytes are gzip-compressed (`Content-Encoding: gzip`)
   and compressed responses are requested via `Accept-Encoding: gzip`.
   Pass `compression=False` to `JsonRpcClient` to disable.
   Requires Apalache server with compression support (Jetty `CompressionHandler`).

# [0.6.0] - 2026-03-20

## Changed

 - Add direct and ordered-sequence support for Apalache's `STATE` query kind to fetch the current state without serializing the full trace.

# [0.5.0] - 2026-03-18

## Changed

 - Add direct and ordered-sequence support for Apalache's `compact` JSON-RPC method.
 - Document `compact` in the README and validate the client against the local Apalache checkout.

# [0.4.0] - 2026-03-18

## Changed

 - Add and validate support for Apalache's ordered JSON-RPC method `applyInOrder`.
 - Verify `apalache-rpc-client` against a local Apalache build newer than `v0.52.3`.

# [0.3.0] - 2026-03-16

## Changed

 - Support Python 3.11+ and depend on `itf-py` 0.5.0.
 - Expand the README with a worked JSON-RPC example for `examples/circular-buffer/MC10u8_BuggyCircularBuffer.tla`.

# [0.1.0] - 2025-11-12

## Added

 - Initial release of the Apalache RPC Client library for Python.
