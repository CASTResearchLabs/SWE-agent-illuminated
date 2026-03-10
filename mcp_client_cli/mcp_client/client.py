#!/usr/bin/env python3
"""
Standalone MCP Client

Provides communication with MCP servers using the official FastMCP client.
Supports streamable responses and proper error handling.
"""

import json
import asyncio
from typing import Any, Dict, List, Optional, Union
from contextlib import asynccontextmanager

from .config import MCPConfig

# Import FastMCP client
try:
    from fastmcp import Client
except ImportError:
    raise ImportError("fastmcp is required. Install with: pip install fastmcp")


class MCPError(Exception):
    """Custom exception for MCP-related errors."""
    pass


class MCPClient:
    """FastMCP client wrapper for communicating with MCP servers."""
    
    def __init__(self, server_name: Optional[str] = None, server_config: Optional[Dict] = None,
                 config_file: Optional[str] = None):
        """Initialize MCP client with server configuration.
        
        Args:
            server_name: Name of server from config (e.g., 'default', 'imaging-structural')
            server_config: Direct server configuration dict (overrides server_name)
            config_file: Path to custom config file
        """
        self.config_manager = MCPConfig(config_file)
        
        if server_config:
            config = server_config
            self.server_name = "direct"
        else:
            config = self.config_manager.get_server_config(server_name)
            self.server_name = server_name or self.config_manager.get("defaultServer", "default")
        
        self.base_url = config.get("url", "http://localhost:3000")
        self.timeout = config.get("timeout", 30000) / 1000  # Convert ms to seconds
        self.trust = config.get("trust", True)
        self.headers = config.get("headers", {})
        self.max_retries = self.config_manager.get("maxRetries", 3)
        
        # Store config for FastMCP client creation
        self.config = config
    
    def _create_client_config(self):
        """Create FastMCP client configuration using standard MCP format."""
        # For single server, we can just use the URL directly
        if not self.headers:
            return self.base_url
        
        # Complex case: use configuration dictionary with proper FastMCP format
        mcp_config = {
            "mcpServers": {
                self.server_name: {
                    "url": self.base_url
                }
            }
        }
        
        # Add headers if present
        if self.headers:
            mcp_config["mcpServers"][self.server_name]["headers"] = self.headers
        
        # Add timeout if different from default
        if self.timeout != 30:
            mcp_config["mcpServers"][self.server_name]["timeout"] = int(self.timeout * 1000)
        
        return mcp_config
    
    @asynccontextmanager
    async def get_client(self):
        """Get FastMCP client instance as async context manager."""
        client_config = self._create_client_config()
        
        # Create FastMCP client
        async with Client(client_config) as client:
            yield client
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any] = None) -> Dict[str, Any]:
        """Call a tool on the MCP server."""
        if arguments is None:
            arguments = {}
        
        for attempt in range(self.max_retries):
            try:
                async with self.get_client() as client:
                    # Get the server client (for multi-server configs)
                    if isinstance(self._create_client_config(), dict):
                        server_client = getattr(client, self.server_name)
                    else:
                        server_client = client
                    
                    # Call the tool
                    result = await server_client.call_tool(tool_name, arguments)
                    
                    # Handle different result types
                    if hasattr(result, 'content'):
                        # Extract content from result
                        if isinstance(result.content, list) and len(result.content) > 0:
                            first_content = result.content[0]
                            if hasattr(first_content, 'text'):
                                return {'content': first_content.text}
                        elif hasattr(result.content, 'text'):
                            return {'content': result.content.text}
                        else:
                            return {'content': str(result.content)}
                    else:
                        return {'content': str(result)}
                        
            except Exception as e:
                if attempt == self.max_retries - 1:
                    raise MCPError(f"Failed to call tool {tool_name} after {self.max_retries} attempts: {str(e)}")
                await asyncio.sleep(0.5 * (attempt + 1))  # Exponential backoff
    
    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools on the MCP server."""
        try:
            async with self.get_client() as client:
                # Get the server client
                if isinstance(self._create_client_config(), dict):
                    server_client = getattr(client, self.server_name)
                else:
                    server_client = client
                
                tools = await server_client.list_tools()
                
                # Convert tools to list of dicts
                tool_list = []
                for tool in tools.tools:
                    tool_dict = {
                        'name': tool.name,
                        'description': getattr(tool, 'description', ''),
                    }
                    if hasattr(tool, 'inputSchema'):
                        tool_dict['inputSchema'] = tool.inputSchema
                    tool_list.append(tool_dict)
                
                return tool_list
                
        except Exception as e:
            raise MCPError(f"Failed to list tools: {str(e)}")
    
    async def list_resources(self) -> List[Dict[str, Any]]:
        """List available resources on the MCP server."""
        try:
            async with self.get_client() as client:
                # Get the server client
                if isinstance(self._create_client_config(), dict):
                    server_client = getattr(client, self.server_name)
                else:
                    server_client = client
                
                resources = await server_client.list_resources()
                
                # Convert resources to list of dicts
                resource_list = []
                for resource in resources.resources:
                    resource_dict = {
                        'uri': resource.uri,
                        'name': getattr(resource, 'name', ''),
                        'description': getattr(resource, 'description', ''),
                        'mimeType': getattr(resource, 'mimeType', '')
                    }
                    resource_list.append(resource_dict)
                
                return resource_list
                
        except Exception as e:
            raise MCPError(f"Failed to list resources: {str(e)}")
    
    async def get_resource(self, uri: str) -> Dict[str, Any]:
        """Get a specific resource from the MCP server."""
        try:
            async with self.get_client() as client:
                # Get the server client
                if isinstance(self._create_client_config(), dict):
                    server_client = getattr(client, self.server_name)
                else:
                    server_client = client
                
                resource = await server_client.read_resource(uri)
                
                # Convert resource to dict
                return {
                    'uri': uri,
                    'contents': [{
                        'uri': content.uri,
                        'mimeType': getattr(content, 'mimeType', ''),
                        'text': getattr(content, 'text', ''),
                        'blob': getattr(content, 'blob', None)
                    } for content in resource.contents]
                }
                
        except Exception as e:
            raise MCPError(f"Failed to get resource {uri}: {str(e)}")


# Synchronous wrapper functions for convenience
def create_client(server_name: Optional[str] = None, server_config: Optional[Dict] = None,
                 config_file: Optional[str] = None) -> MCPClient:
    """Create an MCP client instance."""
    return MCPClient(server_name, server_config, config_file)


def call_tool_sync(tool_name: str, arguments: Dict[str, Any] = None, 
                  server_name: Optional[str] = None) -> Dict[str, Any]:
    """Synchronous wrapper for calling tools."""
    client = create_client(server_name)
    return asyncio.run(client.call_tool(tool_name, arguments))


def list_tools_sync(server_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Synchronous wrapper for listing tools."""
    client = create_client(server_name)
    return asyncio.run(client.list_tools())