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
    from fastmcp import FastMCPClient
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
        
        # Initialize FastMCP client
        self._client = None
        self._loop = None
    
    async def _get_client(self):
        """Get or create the FastMCP client."""
        if self._client is None:
            self._client = FastMCPClient(
                base_url=self.base_url,
                headers=self.headers,
                timeout=self.timeout
            )
            await self._client.connect()
        return self._client
    
    def __enter__(self):
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            asyncio.run(self._client.disconnect())
    
    def _run_async(self, coro):
        """Run an async coroutine in a sync context."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        return loop.run_until_complete(coro)
    
    def _make_request(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Make HTTP request with retry logic."""
        url = urljoin(self.base_url, endpoint)
        
        for attempt in range(self.max_retries):
            try:
                if method.upper() == "GET":
                    response = self.client.get(url)
                elif method.upper() == "POST":
                    response = self.client.post(url, json=data)
                elif method.upper() == "PUT":
                    response = self.client.put(url, json=data)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")
                
                response.raise_for_status()
                return response.json()
                
            except httpx.HTTPError as e:
                if attempt == self.max_retries - 1:
                    raise MCPError(f"HTTP request failed after {self.max_retries} attempts: {e}")
                time.sleep(2 ** attempt)  # Exponential backoff
                
        raise MCPError("Maximum retries exceeded")
    
    def _make_jsonrpc_request(self, method: str, params: Dict = None) -> Dict:
        """Make a JSON-RPC 2.0 request to the MCP server."""
        request_id = int(time.time() * 1000)  # Use timestamp as ID
        
        jsonrpc_request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {}
        }
        
        try:
            response = self.client.post("", json=jsonrpc_request)
            response.raise_for_status()
            result = response.json()
            
            # Handle JSON-RPC error response
            if "error" in result:
                raise MCPError(f"MCP Error: {result['error'].get('message', 'Unknown error')}")
            
            return result
            
        except httpx.HTTPError as e:
            raise MCPError(f"HTTP request failed: {e}")
        except Exception as e:
            raise MCPError(f"Request failed: {e}")
    
    def discover_tools(self) -> Dict[str, Any]:
        """Discover available tools from the MCP server."""
        return self._make_jsonrpc_request("tools/list")
    
    def call_tool(self, tool_name: str, arguments: Dict = None) -> Dict[str, Any]:
        """Call a specific tool on the MCP server."""
        params = {
            "name": tool_name,
            "arguments": arguments or {}
        }
        return self._make_jsonrpc_request("tools/call", params)
    
    def list_resources(self) -> Dict[str, Any]:
        """List available resources on the MCP server."""
        return self._make_jsonrpc_request("resources/list")
    
    def get_resource(self, uri: str) -> Dict[str, Any]:
        """Get a specific resource from the MCP server."""
        params = {"uri": uri}
        return self._make_jsonrpc_request("resources/read", params)
    
    def ping(self) -> bool:
        """Check if the MCP server is responding using health check endpoint."""
        try:
            # Try the dedicated health check endpoint first
            response = self.client.get("/healthcheck")
            response.raise_for_status()
            return True
        except Exception:
            # Fallback to generic ping endpoint
            try:
                self._make_request("GET", "/mcp/ping")
                return True
            except Exception:
                return False
    
    def health_check(self) -> Dict[str, Any]:
        """Get detailed health information from the MCP server."""
        try:
            response = self.client.get("/healthcheck")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return {"status": "unhealthy", "error": str(e)}


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