#!/usr/bin/env python3
"""
MCP Client Library for SWE-agent

Provides communication with MCP servers using the official FastMCP client.
Supports streamable responses and proper error handling.
Uses registry bundle for configuration management.
"""

import json
import os
import asyncio
from typing import Any, Dict, Optional, Union
from contextlib import asynccontextmanager

# Import registry for configuration management
try:
    from registry import registry
except ImportError:
    # Fallback for when registry is not available
    class MockRegistry:
        def get(self, key, default=None):
            return default
        def __getitem__(self, key):
            raise KeyError(key)
        def __setitem__(self, key, value):
            pass
    registry = MockRegistry()

# Import FastMCP client
try:
    from fastmcp import Client
except ImportError:
    raise ImportError("fastmcp is required. Install with: pip install fastmcp")


class MCPClient:
    """FastMCP client wrapper for communicating with MCP servers."""
    
    def __init__(self, server_name: str = None, server_config: Dict = None):
        """Initialize MCP client with server configuration.
        
        Args:
            server_name: Name of server from MCP_CONFIG registry (e.g., 'default', 'imaging-structural')
            server_config: Direct server configuration dict (overrides server_name)
        """
        if server_config:
            config = server_config
        else:
            # Get MCP configuration from registry
            mcp_config = registry.get("MCP_CONFIG", {})
            servers = mcp_config.get("mcpServers", {})
            
            # Use specified server or default
            server_name = server_name or registry.get("MCP_DEFAULT_SERVER", "default")
            
            if server_name not in servers:
                # Fallback to environment variables for backward compatibility
                config = {
                    "httpUrl": os.environ.get("MCP_SERVER_URL", "http://localhost:3000"),
                    "timeout": int(os.environ.get("MCP_TIMEOUT", "30")) * 1000,  # Convert to ms
                    "trust": True
                }
            else:
                config = servers[server_name]
        
        self.base_url = config.get("httpUrl", "http://localhost:3000")
        self.timeout = config.get("timeout", 30000) / 1000  # Convert ms to seconds
        self.trust = config.get("trust", True)
        self.headers = config.get("headers", {})
        self.max_retries = registry.get("MCP_MAX_RETRIES", 3)
        
        # Store config for FastMCP client creation
        self.config = config
        self.server_name = server_name or "default"
    
    def _create_client_config(self):
        """Create FastMCP client configuration using standard MCP format."""
        # FastMCP expects configuration in MCP standard format
        mcp_config = {
            "mcpServers": {
                self.server_name: {
                    "httpUrl": self.base_url
                }
            }
        }
        
        # Add headers if present
        if self.headers:
            mcp_config["mcpServers"][self.server_name]["headers"] = self.headers
        
        # Add timeout if different from default
        if self.timeout != 30:
            mcp_config["mcpServers"][self.server_name]["timeout"] = int(self.timeout * 1000)  # Convert to ms
        
        return mcp_config
    
    async def _execute_with_client(self, operation):
        """Execute an operation with proper FastMCP client lifecycle management."""
        # Create FastMCP client with MCP configuration format
        client_config = self._create_client_config()
        client = Client(client_config)
        
        # Use async context manager for proper connection lifecycle
        async with client:
            return await operation(client)
    
    def _run_async(self, coro):
        """Run an async coroutine in a sync context."""
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context, need to use a different approach
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, coro)
                return future.result()
        except RuntimeError:
            # No event loop running, create a new one
            return asyncio.run(coro)

    async def _ping_async(self) -> bool:
        """Async version of ping check."""
        try:
            async def ping_operation(client):
                # Try to list tools as a health check
                await client.list_tools()
                return True
            
            return await self._execute_with_client(ping_operation)
        except Exception:
            return False
    
    def ping(self) -> bool:
        """Check if the MCP server is responding."""
        return self._run_async(self._ping_async())
    
    async def _discover_tools_async(self) -> Dict[str, Any]:
        """Async version of discover tools."""
        async def discover_operation(client):
            tools = await client.list_tools()
            return {"result": {"tools": tools}}
        
        return await self._execute_with_client(discover_operation)
    
    def discover_tools(self) -> Dict[str, Any]:
        """Discover available tools from the MCP server."""
        return self._run_async(self._discover_tools_async())
    
    async def _call_tool_async(self, tool_name: str, arguments: Dict = None) -> Dict[str, Any]:
        """Async version of call tool."""
        async def call_operation(client):
            # For multi-server config, need to prefix tool name with server
            prefixed_tool_name = f"{self.server_name}_{tool_name}"
            result = await client.call_tool(prefixed_tool_name, arguments or {})
            
            # FastMCP returns a result object, extract the relevant data
            if hasattr(result, 'content'):
                return {"result": result.content}
            elif hasattr(result, 'data'):
                return {"result": result.data}
            else:
                return {"result": result}
        
        return await self._execute_with_client(call_operation)
    
    def call_tool(self, tool_name: str, arguments: Dict = None) -> Dict[str, Any]:
        """Call a specific tool on the MCP server."""
        return self._run_async(self._call_tool_async(tool_name, arguments))
    
    async def _list_resources_async(self) -> Dict[str, Any]:
        """Async version of list resources."""
        async def list_operation(client):
            resources = await client.list_resources()
            return {"result": {"resources": resources}}
        
        return await self._execute_with_client(list_operation)
    
    def list_resources(self) -> Dict[str, Any]:
        """List available resources on the MCP server."""
        return self._run_async(self._list_resources_async())
    
    async def _get_resource_async(self, uri: str) -> Dict[str, Any]:
        """Async version of get resource."""
        async def get_operation(client):
            # For multi-server config, need to prefix URI with server name
            if "://" not in uri or uri.startswith("file://"):
                # This is a local resource, use as-is
                prefixed_uri = uri
            else:
                # This might be a server-specific resource
                prefixed_uri = f"{self.server_name}://{uri}"
            
            result = await client.read_resource(prefixed_uri)
            return {"result": result}
        
        return await self._execute_with_client(get_operation)
    
    def get_resource(self, uri: str) -> Dict[str, Any]:
        """Get a specific resource from the MCP server."""
        return self._run_async(self._get_resource_async(uri))
    
    def health_check(self) -> Dict[str, Any]:
        """Get detailed health information from the MCP server."""
        try:
            # For FastMCP, we can use the ping as health check
            if self.ping():
                return {"status": "healthy", "service": "mcp-server", "url": self.base_url}
            else:
                return {"status": "unhealthy", "error": "Server not responding", "url": self.base_url}
        except Exception as e:
            return {"status": "unhealthy", "error": str(e), "url": self.base_url}


class MCPError(Exception):
    """Custom exception for MCP-related errors."""
    pass


def get_mcp_client(server_name: str = None, server_config: Dict = None) -> MCPClient:
    """Factory function to create an MCP client.
    
    Args:
        server_name: Name of server from MCP_CONFIG registry
        server_config: Direct server configuration dict
        
    Returns:
        Configured MCPClient instance
    """
    return MCPClient(server_name, server_config)


def list_available_servers() -> Dict[str, Any]:
    """List all configured MCP servers from registry."""
    mcp_config = registry.get("MCP_CONFIG", {})
    return mcp_config.get("mcpServers", {})


def get_server_config(server_name: str) -> Dict[str, Any]:
    """Get configuration for a specific server."""
    servers = list_available_servers()
    return servers.get(server_name, {})


def format_mcp_response(response: Dict[str, Any]) -> str:
    """Format MCP response for display in SWE-agent."""
    if "error" in response:
        return f"MCP Error: {response['error'].get('message', 'Unknown error')}"
    
    if "result" in response:
        result = response["result"]
        if isinstance(result, dict):
            if "content" in result:
                # Handle content response
                content = result["content"]
                if isinstance(content, list):
                    return "\n".join(item.get("text", str(item)) for item in content)
                return str(content)
            elif "tools" in result:
                # Handle tools discovery response
                tools = result["tools"]
                output = ["Available MCP Tools:"]
                for tool in tools:
                    output.append(f"  {tool['name']}: {tool.get('description', 'No description')}")
                return "\n".join(output)
            elif "resources" in result:
                # Handle resources list response
                resources = result["resources"]
                output = ["Available MCP Resources:"]
                for resource in resources:
                    output.append(f"  {resource['uri']}: {resource.get('description', 'No description')}")
                return "\n".join(output)
        return json.dumps(result, indent=2)
    
    return json.dumps(response, indent=2)