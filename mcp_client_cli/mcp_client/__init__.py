"""Standalone MCP Client Package

A standalone Python client for communicating with Model Context Protocol (MCP) servers.
Supports HTTP communication, tool calling, resource access, and server management.
"""

from .client import MCPClient, MCPError
from .config import MCPConfig

__version__ = "1.0.0"
__all__ = ["MCPClient", "MCPError", "MCPConfig"]