# MCP Client Tool for SWE-agent

This tool provides a bridge between SWE-agent and Model Context Protocol (MCP) servers via HTTP. It uses the registry bundle for configuration management, supports standard MCP JSON configuration format, and is built with the official FastMCP client library.

## Features

- **FastMCP Integration**: Uses official FastMCP client library for proper MCP protocol support
- **Registry-based configuration**: Uses SWE-agent's registry bundle for persistent config
- **Standard MCP format**: Compatible with standard MCP JSON configuration
- **Multiple server support**: Manage multiple MCP servers with named configurations
- **Dynamic tool discovery**: Automatically discover available tools from MCP servers
- **Generic tool calling**: Call any MCP tool with JSON arguments
- **Resource access**: Retrieve resources from MCP servers
- **Authentication**: Support for API keys and custom headers

## Installation

```bash
cd tools/mcp_client
./install.sh
```

This will install FastMCP and all required dependencies.

## Testing Procedure

### 1. Setup Virtual Environment (Recommended)

```bash
# Create and activate virtual environment
python3 -m venv venv_mcp_test
source venv_mcp_test/bin/activate

# Install the MCP client tools
cd tools/mcp_client
./install.sh
```

### 2. Test FastMCP Installation

```bash
# Verify FastMCP is properly installed
python -c "import fastmcp; print('✓ FastMCP installed successfully')"

# Discover FastMCP package structure
python discover_fastmcp.py

# Expected output should show:
# ✅ fastmcp.Client - available (correct)
# ❌ fastmcp.FastMCPClient - not available (this is expected, we now use Client)
```

### 3. Test MCP Client Library

```bash
# Setup environment for command testing
export PYTHONPATH="tools/mcp_client/lib:tools/registry/lib:$PYTHONPATH"

# Create test registry
export SWE_AGENT_ENV_FILE="/tmp/mcp_test_registry.json"
cat > "$SWE_AGENT_ENV_FILE" << EOF
{
  "MCP_CONFIG": {
    "mcpServers": {
      "imaging-structural": {
        "url": "http://172.31.237.125:8282/mcp",
        "headers": {
          "x-api-key": "YOUR_API_KEY_HERE"
        },
        "timeout": 300000,
        "trust": true
      }
    }
  },
  "MCP_DEFAULT_SERVER": "imaging-structural",
  "MCP_MAX_RETRIES": 3
}
EOF

# Test aligned FastMCP implementation
python test_aligned_fastmcp.py

# Note: Implementation now follows official FastMCP patterns:
# - Uses "url" instead of "httpUrl" in configurations (IMPORTANT: update existing configs!)
# - Automatic tool/resource prefixing for multi-server setups
# - Proper async context manager lifecycle
```

### 4. Test Individual Commands

```bash
# Setup environment for command testing
export PYTHONPATH="tools/mcp_client/lib:tools/registry/lib:$PYTHONPATH"

# Create test registry
export SWE_AGENT_ENV_FILE="/tmp/mcp_test_registry.json"
cat > "$SWE_AGENT_ENV_FILE" << EOF
{
  "MCP_CONFIG": {
    "mcpServers": {
      "imaging-structural": {
        "url": "http://172.31.237.125:8282/mcp",
        "headers": {
          "x-api-key": "YOUR_API_KEY_HERE"
        },
        "timeout": 300000,
        "trust": true
      }
    }
  },
  "MCP_DEFAULT_SERVER": "imaging-structural",
  "MCP_MAX_RETRIES": 3
}
EOF

# Test server management commands
cd tools/mcp_client
export PYTHONPATH="lib:../registry/lib:$PYTHONPATH" && echo "Python path set: $PYTHONPATH"
python bin/mcp_list_servers
python bin/mcp_add_server test-local http://localhost:3000
python bin/mcp_set_default_server test-local
```

### 5. Test with Real MCP Server

```bash
# Set your actual API key
export MCP_API_KEY="your-actual-api-key"

# Update the registry with your key
python -c "
import json, os
registry_file = '/tmp/mcp_test_registry.json'
with open(registry_file, 'r') as f:
    config = json.load(f)
config['MCP_CONFIG']['mcpServers']['imaging-structural']['headers']['x-api-key'] = os.environ['MCP_API_KEY']
with open(registry_file, 'w') as f:
    json.dump(config, f, indent=2)
print('✓ API key updated in registry')
"

# Test discovery and tool calling
python bin/mcp_list_tools imaging-structural
python bin/mcp_list_resources imaging-structural
python bin/mcp_call get_structural_search_function_syntax '{"function_names":["applications","list_functions"]}' imaging-structural
python bin/mcp_call run_structural_search_function '{"function_name":"applications", "arguments": {}}' imaging-structural
```

### 6. Test Health Check

```bash
# Test server health directly
python -c "
import httpx
url = 'http://172.31.237.125:8282/mcp/healthcheck'
try:
    response = httpx.get(url, timeout=10)
    print(f'Health check: {response.status_code} - {response.json()}')
except Exception as e:
    print(f'Health check failed: {e}')
"
```

### 7. Common Test Issues & Solutions

**Issue: `ModuleNotFoundError: No module named 'fastmcp'`**
```bash
# Solution: Ensure you're in the virtual environment
source venv_mcp_test/bin/activate
pip list | grep fastmcp  # Should show fastmcp package
```

**Issue: `ModuleNotFoundError: No module named 'registry'`**
```bash
# Solution: Set Python path correctly
export PYTHONPATH="tools/registry/lib:tools/mcp_client/lib:$PYTHONPATH"
```

**Issue: MCP server connection fails**
```bash
# Solution: Check server health and API key
curl -H "x-api-key: YOUR_KEY" http://172.31.237.125:8282/mcp/healthcheck
```

**Issue: Registry file not found**
```bash
# Solution: Create test registry file
echo '{"MCP_CONFIG": {"mcpServers": {}}}' > /tmp/mcp_test_registry.json
export SWE_AGENT_ENV_FILE="/tmp/mcp_test_registry.json"
```

## Configuration

**⚠️ IMPORTANT:** This tool now follows the **official FastMCP configuration format**. If you have existing configurations, please update `"httpUrl"` to `"url"` in your server configurations to match the standard MCP format.

The tool uses the registry bundle to store MCP server configurations. Configuration is automatically managed through the tool commands, but you can also set it in your SWE-agent config:

```yaml
agent:
  tools:
    registry_variables:
      MCP_CONFIG:
        mcpServers:
          imaging-structural:
            url: "http://172.31.237.125:8282/mcp"
            headers:
              x-api-key: "Q5Fxrp3E.W7U4HfovfeE4HGHM3FacfsTyLEDcgQHf"
            timeout: 300000
            trust: true
          imaging-semantic:
            url: "http://172.31.237.125:8286/mcp"
            timeout: 300000
            trust: true
      MCP_DEFAULT_SERVER: "imaging-structural"
    bundles:
      - path: tools/registry  # Required for registry support
      - path: tools/mcp_client
```

## Server Management

### List Configured Servers
```bash
mcp_list_servers
```

### Add a New Server
```bash
# Basic server
mcp_add_server structural http://172.31.237.125:8282/mcp

# Server with authentication
mcp_add_server structural http://172.31.237.125:8282/mcp '{"x-api-key": "your-api-key"}'
```

### Set Default Server
```bash
mcp_set_default_server structural
```

## Tool Operations

### Discover Available Tools
```bash
mcp_list_tools                    # Use default server
mcp_list_tools structural         # Use specific server
```

### Call Tools
```bash
mcp_call search '{"query": "test", "limit": 10}'                    # Default server
mcp_call search '{"query": "test", "limit": 10}' structural         # Specific server
```

### Resource Management
```bash
mcp_list_resources                              # List all resources
mcp_get_resource file:///path/to/file           # Get specific resource
mcp_get_resource file:///path/to/file structural # Use specific server
```

## Integration with SWE-agent

Add this tool to your SWE-agent configuration:

```yaml
agent:
  tools:
    bundles:
      - path: tools/registry    # Required first!
      - path: tools/mcp_client
```

## Example Usage in Agent Session

```
# List available servers
mcp_list_servers

# Add your MCP servers
mcp_add_server imaging http://172.31.237.125:8282/mcp '{"x-api-key": "your-key"}'

# Discover what tools are available
mcp_list_tools imaging

# Call MCP tools
mcp_call quality_insight_occurrences '{"application": "myapp"}' imaging
mcp_call transactions_using_object '{"object": "UserService"}' imaging

# Get resources
mcp_list_resources imaging
mcp_get_resource file:///workspace/config.json
```

## FastMCP Compatibility

This tool is **fully aligned** with the official FastMCP client library and follows the patterns from [gofastmcp.com/clients/client](https://gofastmcp.com/clients/client):

### Key FastMCP Patterns Implemented:
- **Simple HTTP URLs**: `Client("https://api.example.com/mcp")` for basic connections
- **Configuration-based clients**: Using `mcpServers` with `"url"` (not `"httpUrl"`) 
- **Automatic tool prefixing**: FastMCP handles server prefixing for multi-server configs
- **Proper async context**: `async with client:` for connection lifecycle
- **Result data access**: Uses `result.data` following FastMCP conventions

### Supported MCP Operations:
- JSON-RPC 2.0 over HTTP
- Standard tool discovery via `tools/list`
- Tool calling via `tools/call` with automatic server prefixing
- Resource listing via `resources/list`
- Resource reading via `resources/read` with automatic URI handling

## Error Handling

The tool provides clear error messages for common issues:
- Connection failures
- Authentication errors
- Invalid server names
- Invalid tool names or arguments
- Server timeouts
- JSON parsing errors
- FastMCP client errors

## Development

The tool is structured as:
- `config.yaml`: Tool definitions for SWE-agent with registry configuration
- `lib/mcp_client.py`: Core FastMCP client library with registry integration
- `bin/`: Executable scripts for each command
- `install.sh`: Installation script

To extend the tool, add new commands by:
1. Adding the tool definition to `config.yaml`
2. Creating a new script in `bin/`
3. Using the shared `mcp_client` library for FastMCP communication
4. Using the `registry` for configuration access