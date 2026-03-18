from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, PrivateAttr, model_validator

from sweagent.tools.commands import Command
from sweagent.utils.config import _convert_path_to_abspath


class BundleConfig(BaseModel):
    tools: dict[str, dict]
    state_command: str | None = None


class Bundle(BaseModel):
    path: Path
    hidden_tools: list[str] = Field(default_factory=list)
    _config: BundleConfig = PrivateAttr(default=None)

    @model_validator(mode="after")
    def validate_tools(self):
        from sweagent.utils.log import get_logger
        logger = get_logger("swea-bundle", emoji="📦")
        
        self.path = _convert_path_to_abspath(self.path)
        if not self.path.exists():
            msg = f"Bundle path '{self.path}' does not exist."
            logger.error(msg)
            raise ValueError(msg)

        config_path = self.path / "config.yaml"
        if not config_path.exists():
            msg = f"Bundle config file '{config_path}' does not exist."
            logger.error(msg)
            raise ValueError(msg)

        try:
            config_data = yaml.safe_load(config_path.read_text())
            self._config = BundleConfig(**config_data)
            logger.debug(f"Bundle '{self.path.name}' loaded with {len(self._config.tools)} tools: {list(self._config.tools.keys())}")
        except Exception as e:
            logger.error(f"Failed to parse bundle config '{config_path}': {e}")
            raise

        invalid_hidden_tools = set(self.hidden_tools) - set(self._config.tools.keys())
        if invalid_hidden_tools:
            msg = f"Hidden tools {invalid_hidden_tools} do not exist in available tools"
            logger.error(msg)
            raise ValueError(msg)
        return self

    @property
    def state_command(self) -> str | None:
        return self.config.state_command

    @property
    def config(self) -> BundleConfig:
        return self._config

    @property
    def commands(self) -> list[Command]:
        return [
            Command(name=tool, **tool_config.model_dump() if isinstance(tool_config, Command) else tool_config)
            for tool, tool_config in self.config.tools.items()
            if tool not in self.hidden_tools
        ]
