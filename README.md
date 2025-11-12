# Apalache RPC Client

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

from apalache_rpc.server import ApalacheServer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[ logging.StreamHandler(sys.stdout) ]
)

server = ApalacheServer(log_dir="_logs", hostname="localhost", port=18080)
assert server.start_server(), "Failed to start the Apalache server"
time.sleep(5)  # Let the server run for a bit
assert server.stop_server(), "Failed to stop the Apalache server"
```

[Apalache JSON-RPC API]: https://github.com/apalache-mc/apalache/tree/main/json-rpc
[Apalache Installation Instructions]: https://apalache-mc.org/docs/apalache/installation/index.html