#!/usr/bin/env python3
"""
Standalone configuration manager for MCP Client.
Handles server configurations without external dependencies.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


class MCPConfig:
    """Standalone configuration manager for MCP client."""
    
    def __init__(self, config_file: Optional[str] = None):
        """Initialize config manager.
        
        Args:
            config_file: Path to configuration file. Defaults to ~/.mcp_config.json
        """
        if config_file:
            self.config_file = Path(config_file).expanduser()
        else:
            self.config_file = Path.home() / ".mcp_config.json"
        
        # Initialize with default config if file doesn't exist
        if not self.config_file.exists():
            self._write_config({
                "mcpServers": {},
                "defaultServer": "default",
                "maxRetries": 3
            })
    
    def _read_config(self) -> Dict[str, Any]:
        """Read configuration from file."""
        try:
            return json.loads(self.config_file.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {"mcpServers": {}, "defaultServer": "default", "maxRetries": 3}
    
    def _write_config(self, config: Dict[str, Any]):
        """Write configuration to file."""
        self.config_file.write_text(json.dumps(config, indent=2))
    
    def get(self, key: str, default: Any = None, fallback_to_env: bool = True) -> Any:
        """Get a value from config or environment.
        
        Args:
            key: Configuration key
            default: Default value if not found
            fallback_to_env: Whether to check environment variables
        """
        config = self._read_config()
        
        # Check environment first if enabled
        if fallback_to_env and key in os.environ:
            env_value = os.environ[key]
            # Try to parse as JSON for complex values
            try:
                return json.loads(env_value)
            except (json.JSONDecodeError, ValueError):
                return env_value
        
        return config.get(key, default)
    
    def set(self, key: str, value: Any):
        """Set a configuration value."""
        config = self._read_config()
        config[key] = value
        self._write_config(config)
    
    def get_server_config(self, server_name: Optional[str] = None) -> Dict[str, Any]:
        """Get server configuration.
        
        Args:
            server_name: Name of server, uses default if None
            
        Returns:
            Server configuration dictionary
        """
        config = self._read_config()
        servers = config.get("mcpServers", {})
        
        if server_name is None:
            server_name = config.get("defaultServer", "default")
        
        if server_name not in servers:
            # Fallback to environment variables
            return {
                "url": os.environ.get("MCP_SERVER_URL", "http://localhost:3000"),
                "timeout": int(os.environ.get("MCP_TIMEOUT", "30000")),
                "trust": True
            }
        
        return servers[server_name]
    
    def add_server(self, name: str, url: str, headers: Optional[Dict[str, str]] = None, 
                   timeout: int = 30000, trust: bool = True):
        """Add a new server configuration."""
        config = self._read_config()
        if "mcpServers" not in config:
            config["mcpServers"] = {}
        
        server_config = {
            "url": url,
            "timeout": timeout,
            "trust": trust
        }
        
        if headers:
            server_config["headers"] = headers
        
        config["mcpServers"][name] = server_config
        self._write_config(config)
    
    def remove_server(self, name: str):
        """Remove a server configuration."""
        config = self._read_config()
        if "mcpServers" in config and name in config["mcpServers"]:
            del config["mcpServers"][name]
            self._write_config(config)
    
    def list_servers(self) -> Dict[str, Dict[str, Any]]:
        """List all configured servers."""
        config = self._read_config()
        return config.get("mcpServers", {})
    
    def set_default_server(self, name: str):
        """Set the default server."""
        config = self._read_config()
        config["defaultServer"] = name
        self._write_config(config)