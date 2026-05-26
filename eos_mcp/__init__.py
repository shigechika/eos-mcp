"""eos-mcp: MCP server for Arista EOS device operations via eAPI."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("eos-mcp")
except PackageNotFoundError:
    __version__ = "0.2.0"
