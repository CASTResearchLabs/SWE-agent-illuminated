# MCP Client CLI

A standalone command-line client for Model Context Protocol (MCP) servers. This package provides both a Python library and CLI tools for communicating with MCP servers over HTTP.

## Features

- **Standalone**: No external dependencies beyond FastMCP
- **Configuration Management**: JSON-based configuration with environment variable fallback
- **Multiple Server Support**: Manage multiple MCP servers with named configurations
- **Tool Calling**: Call any MCP tool with JSON arguments
- **Resource Access**: List and retrieve resources from MCP servers
- **CLI Interface**: Complete command-line interface for all operations
- **Python API**: Use as a library in your own Python projects

## Installation

### From Source

```bash
cd mcp_client_cli
pip install -e .
```

### From PyPI (when published)

```bash
pip install mcp-client-cli
```

## Quick Start

### Command Line Usage

```bash
# Add a server
mcp-client add-server imaging "http://172.31.237.125:8282/mcp" --headers '{"x-api-key": "your-key"}'

# Set as default
mcp-client set-default imaging

# List available tools
mcp-client tools

# Call a tool
mcp-client call applications '{}'

# List servers
mcp-client list-servers
```

### Python API Usage

```python
from mcp_client import MCPClient, MCPConfig
import asyncio

# Create client with direct configuration
client = MCPClient(server_config={
    "url": "http://172.31.237.125:8282/mcp",
    "headers": {"x-api-key": "your-key"},
    "timeout": 300000
})

# Or use named configuration
config = MCPConfig()
config.add_server("imaging", "http://172.31.237.125:8282/mcp", 
                 headers={"x-api-key": "your-key"})
client = MCPClient("imaging")

# Call tools
async def main():
    # List applications
    apps = await client.call_tool("applications", {})
    print(apps)
    
    # Get architectural stats
    stats = await client.call_tool("stats", {"application": "shopizer_back_end"})
    print(stats)

asyncio.run(main())
```

## Configuration

The client uses a JSON configuration file stored at `~/.mcp_config.json` by default:

```json
{
  "mcpServers": {
    "imaging": {
      "url": "http://172.31.237.125:8282/mcp",
      "headers": {
        "x-api-key": "your-key-here"
      },
      "timeout": 300000,
      "trust": true
    },
    "local": {
      "url": "http://localhost:3000",
      "timeout": 30000,
      "trust": true
    }
  },
  "defaultServer": "imaging",
  "maxRetries": 3
}
```

### Environment Variable Fallback

If no configuration is found, the client falls back to environment variables:

- `MCP_SERVER_URL`: Server URL (default: `http://localhost:3000`)
- `MCP_TIMEOUT`: Timeout in milliseconds (default: `30000`)
- `MCP_CONFIG_JSON`: JSON string with full configuration

## CLI Commands

### Server Management

```bash
# Add a server
mcp-client add-server <name> <url> [--headers '{"key": "value"}'] [--timeout 30000]

# Remove a server
mcp-client remove-server <name>

# List servers
mcp-client list-servers

# Set default server
mcp-client set-default <name>
```

### Tool Operations

```bash
# List available tools
mcp-client tools [--server <name>]

# Call a tool
mcp-client call <tool_name> [arguments_json] [--server <name>]

# Examples:
mcp-client call applications '{}'
mcp-client call stats '{"application": "shopizer_back_end"}'
mcp-client call transaction_details '{"application": "shopizer_back_end", "id": "240217"}'
```

### Resource Operations

```bash
# List available resources
mcp-client resources [--server <name>]

# Get a specific resource
mcp-client resource <uri> [--server <name>]
```

## Python API Reference

### MCPClient

```python
class MCPClient:
    def __init__(self, server_name=None, server_config=None, config_file=None)
    async def call_tool(self, tool_name: str, arguments: dict = None) -> dict
    async def list_tools(self) -> List[dict]
    async def list_resources(self) -> List[dict]
    async def get_resource(self, uri: str) -> dict
```

### MCPConfig

```python
class MCPConfig:
    def __init__(self, config_file=None)
    def add_server(self, name, url, headers=None, timeout=30000, trust=True)
    def remove_server(self, name)
    def list_servers(self) -> dict
    def set_default_server(self, name)
    def get_server_config(self, server_name=None) -> dict
```

### Synchronous Wrappers

```python
# For simple use cases without async/await
from mcp_client import call_tool_sync, list_tools_sync

result = call_tool_sync("applications", {}, "imaging")
tools = list_tools_sync("imaging")
```

## Examples

### Structural Code Analysis with CAST Imaging

```python
import asyncio
from mcp_client import MCPClient

async def analyze_application():
    # Setup client for CAST Imaging server
    client = MCPClient(server_config={
        "url": "http://172.31.237.125:8282/mcp",
        "headers": {"x-api-key": "your-key"},
        "timeout": 300000
    })
    
    # Get application overview
    apps = await client.call_tool("applications", {})
    print(f"Available applications: {len(apps['content'])}")
    
    # Analyze shopizer_back_end
    app = "shopizer_back_end"
    
    # Get comprehensive stats
    stats = await client.call_tool("stats", {"application": app})
    print(f"App stats: {stats['content']}")
    
    # Get architectural structure
    arch = await client.call_tool("architectural_graph", {
        "application": app,
        "level": "component",
        "mode": "nodes"
    })
    print(f"Architecture components: {len(arch['content'])} components")
    
    # Get API endpoints
    transactions = await client.call_tool("transactions", {
        "application": app,
        "items_per_page": 10
    })
    print(f"Found {len(transactions['content'])} API endpoints")
    
    # Get quality insights
    quality = await client.call_tool("quality_insights", {
        "application": app,
        "nature": "cve"
    })
    print(f"CVE analysis: {len(quality['content'])} security issues found")

asyncio.run(analyze_application())
```

### Batch Analysis

```python
import asyncio
from mcp_client import MCPClient

async def batch_analysis():
    client = MCPClient("imaging")  # Use configured server
    
    # Get all applications
    apps_result = await client.call_tool("applications", {})
    
    # Analyze each application
    for app_data in apps_result['content']:
        app_name = app_data['name']
        print(f"\nAnalyzing {app_name}...")
        
        # Get basic stats
        stats = await client.call_tool("stats", {"application": app_name})
        nb_elements = stats['content']['nb_elements']
        technologies = stats['content']['technologies']
        
        print(f"  - Elements: {nb_elements}")
        print(f"  - Technologies: {', '.join(technologies)}")
        
        # Get quality overview
        quality = await client.call_tool("quality_insights", {
            "application": app_name,
            "nature": "structural-flaws"
        })
        print(f"  - Structural flaws: {len(quality['content'])}")

asyncio.run(batch_analysis())
```

## Error Handling

The client provides structured error handling:

```python
from mcp_client import MCPClient, MCPError

async def safe_call():
    client = MCPClient("imaging")
    
    try:
        result = await client.call_tool("nonexistent_tool", {})
    except MCPError as e:
        print(f"MCP Error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")
```

## License

MIT License - see LICENSE file for details.