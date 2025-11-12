# Stub tests to verify that imports work
# The actual tests are in ../../README.md

from apalache_rpc.client import JsonRpcClient


class TestImports:
    """Simple test to see whether imports work."""

    def test_ok(self):
        """Trivial test"""
        assert JsonRpcClient.__name__ == "JsonRpcClient"
