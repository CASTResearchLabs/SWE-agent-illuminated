#!/bin/bash

# MCP Client Tool Installation Script for SWE-agent

set -e

echo "Installing MCP Client tool dependencies..."

# Install required Python packages - use fastmcp client
pip install fastmcp

# Make all bin scripts executable
chmod +x bin/*

echo "MCP Client tool installation completed successfully!"
echo ""
echo "⚠️  IMPORTANT: This tool requires the registry bundle to be loaded first!"
echo "   Add this to your SWE-agent config:"
echo "   bundles:"
echo "     - path: tools/registry      # Required first!"
echo "     - path: tools/mcp_client"
echo ""
echo "Configuration:"
echo "  Uses registry-based configuration for MCP servers"
echo "  Supports standard MCP JSON configuration format with FastMCP client"
echo "  Max retries: ${MCP_MAX_RETRIES:-3}"
echo ""
echo "Usage examples:"
echo "  mcp_list_servers                                   # List configured servers"
echo "  mcp_add_server imaging http://host:8282/mcp        # Add new server"
echo "  mcp_discover imaging                               # Discover tools"
echo "  mcp_call search '{\"query\": \"test\"}' imaging      # Call tool"
echo ""
echo "Quick setup for your imaging servers:"
echo "  mcp_add_server imaging-structural http://172.31.237.125:8282/mcp '{\"x-api-key\": \"your-key\"}'"
echo "  mcp_add_server imaging-semantic http://172.31.237.125:8286/mcp"