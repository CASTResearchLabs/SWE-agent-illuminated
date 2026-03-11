#!/usr/bin/env python3
"""
Demo script showing MCP client integration with a mock server.
"""

import sys
import json
from pathlib import Path

# Add lib directory to path
lib_path = str(Path(__file__).resolve().parent / "lib")
sys.path.insert(0, lib_path)

from mcp_client import MCPClient, MCPError


def demo_mcp_integration():
    """Demonstrate MCP client capabilities."""
    
    print("=== MCP Client Demo ===\n")
    
    # This would connect to a real MCP server
    # For demo purposes, we'll show the expected interface
    server_url = "http://localhost:3000"
    
    print(f"Attempting to connect to MCP server: {server_url}")
    
    try:
        with MCPClient(base_url=server_url) as client:
            print(f"✓ Connected to {client.base_url}")
            
            # Example: Discover tools
            print("\n1. Discovering available tools...")
            try:
                tools_response = client.discover_tools()
                print(f"Expected response format: {json.dumps(tools_response, indent=2)}")
            except Exception as e:
                print(f"Note: This is expected if no MCP server is running: {e}")
            
            # Example: Call a tool
            print("\n2. Example tool call...")
            try:
                result = client.call_tool("search", {"query": "example"})
                print(f"Tool call result: {json.dumps(result, indent=2)}")
            except Exception as e:
                print(f"Note: This is expected if no MCP server is running: {e}")
                
            # Example: List resources
            print("\n3. Example resource listing...")
            try:
                resources = client.list_resources()
                print(f"Resources: {json.dumps(resources, indent=2)}")
            except Exception as e:
                print(f"Note: This is expected if no MCP server is running: {e}")
                
    except MCPError as e:
        print(f"Expected MCP connection error (no server running): {e}")
    
    print("\n=== Integration Complete ===")
    print("To use with a real MCP server:")
    print("1. Start your MCP server on http://localhost:3000")
    print("2. Run: mcp_discover")
    print("3. Run: mcp_call <tool_name> '{\"arg\": \"value\"}'")
    print("4. Use in SWE-agent by adding this tool to your config")


if __name__ == "__main__":
    demo_mcp_integration()