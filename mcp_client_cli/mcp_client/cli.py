#!/usr/bin/env python3
"""
Command Line Interface for MCP Client
"""

import argparse
import json
import sys
import asyncio
from typing import Any, Dict

from .client import MCPClient, MCPError
from .config import MCPConfig


def format_response(response: Any, compact: bool = False) -> str:
    """Format response for display."""
    if isinstance(response, dict):
        indent = None if compact else 2
        return json.dumps(response, indent=indent, ensure_ascii=False)
    else:
        return str(response)


async def cmd_call_tool(args):
    """Call a tool on the MCP server."""
    try:
        # Parse arguments
        tool_args = {}
        if args.arguments:
            try:
                tool_args = json.loads(args.arguments)
            except json.JSONDecodeError as e:
                print(f"Error: Invalid JSON arguments: {e}", file=sys.stderr)
                return 1
        
        # Create client and call tool
        client = MCPClient(args.server, config_file=args.config)
        result = await client.call_tool(args.tool_name, tool_args)
        print(format_response(result, args.compact))
        return 0
        
    except MCPError as e:
        print(f"MCP Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


async def cmd_list_tools(args):
    """List available tools."""
    try:
        client = MCPClient(args.server, config_file=args.config)
        tools = await client.list_tools()
        print(format_response(tools, args.compact))
        return 0
        
    except MCPError as e:
        print(f"MCP Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


async def cmd_list_resources(args):
    """List available resources."""
    try:
        client = MCPClient(args.server, config_file=args.config)
        resources = await client.list_resources()
        print(format_response(resources, args.compact))
        return 0
        
    except MCPError as e:
        print(f"MCP Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


async def cmd_get_resource(args):
    """Get a specific resource."""
    try:
        client = MCPClient(args.server, config_file=args.config)
        resource = await client.get_resource(args.uri)
        print(format_response(resource, args.compact))
        return 0
        
    except MCPError as e:
        print(f"MCP Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_add_server(args):
    """Add a new server configuration."""
    try:
        config = MCPConfig(args.config)
        
        headers = None
        if args.headers:
            try:
                headers = json.loads(args.headers)
            except json.JSONDecodeError as e:
                print(f"Error: Invalid JSON headers: {e}", file=sys.stderr)
                return 1
        
        config.add_server(args.name, args.url, headers, args.timeout, args.trust)
        print(f"Server '{args.name}' added successfully")
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_remove_server(args):
    """Remove a server configuration."""
    try:
        config = MCPConfig(args.config)
        config.remove_server(args.name)
        print(f"Server '{args.name}' removed successfully")
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_list_servers(args):
    """List configured servers."""
    try:
        config = MCPConfig(args.config)
        servers = config.list_servers()
        print(format_response(servers, args.compact))
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_set_default(args):
    """Set default server."""
    try:
        config = MCPConfig(args.config)
        config.set_default_server(args.name)
        print(f"Default server set to '{args.name}'")
        return 0
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="MCP Client - Command line interface for Model Context Protocol servers",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--config", 
        help="Path to configuration file (default: ~/.mcp_config.json)"
    )
    parser.add_argument(
        "--compact", 
        action="store_true", 
        help="Compact JSON output"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Tool commands
    tool_parser = subparsers.add_parser("call", help="Call a tool")
    tool_parser.add_argument("tool_name", help="Name of the tool to call")
    tool_parser.add_argument("arguments", nargs="?", help="JSON string of arguments")
    tool_parser.add_argument("--server", help="MCP server name")
    
    tools_parser = subparsers.add_parser("tools", help="List available tools")
    tools_parser.add_argument("--server", help="MCP server name")
    
    # Resource commands
    resources_parser = subparsers.add_parser("resources", help="List available resources")
    resources_parser.add_argument("--server", help="MCP server name")
    
    resource_parser = subparsers.add_parser("resource", help="Get a specific resource")
    resource_parser.add_argument("uri", help="Resource URI")
    resource_parser.add_argument("--server", help="MCP server name")
    
    # Server management commands
    add_parser = subparsers.add_parser("add-server", help="Add a new server")
    add_parser.add_argument("name", help="Server name")
    add_parser.add_argument("url", help="Server URL")
    add_parser.add_argument("--headers", help="JSON string of headers")
    add_parser.add_argument("--timeout", type=int, default=30000, help="Timeout in ms")
    add_parser.add_argument("--no-trust", dest="trust", action="store_false", help="Disable SSL trust")
    
    remove_parser = subparsers.add_parser("remove-server", help="Remove a server")
    remove_parser.add_argument("name", help="Server name")
    
    subparsers.add_parser("list-servers", help="List configured servers")
    
    default_parser = subparsers.add_parser("set-default", help="Set default server")
    default_parser.add_argument("name", help="Server name")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Route to appropriate function
    if args.command == "call":
        return asyncio.run(cmd_call_tool(args))
    elif args.command == "tools":
        return asyncio.run(cmd_list_tools(args))
    elif args.command == "resources":
        return asyncio.run(cmd_list_resources(args))
    elif args.command == "resource":
        return asyncio.run(cmd_get_resource(args))
    elif args.command == "add-server":
        return cmd_add_server(args)
    elif args.command == "remove-server":
        return cmd_remove_server(args)
    elif args.command == "list-servers":
        return cmd_list_servers(args)
    elif args.command == "set-default":
        return cmd_set_default(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())