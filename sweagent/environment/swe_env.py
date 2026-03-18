import asyncio
import logging
import shlex
from pathlib import PurePath
from typing import Literal, Self

import pexpect
from pydantic import BaseModel, ConfigDict, Field
from swerex.deployment.abstract import AbstractDeployment
from swerex.deployment.config import DeploymentConfig, DockerDeploymentConfig, get_deployment
from swerex.runtime.abstract import (
    BashAction,
    BashInterruptAction,
    CreateBashSessionRequest,
    ReadFileRequest,
    WriteFileRequest,
)
from swerex.runtime.abstract import Command as RexCommand

from sweagent.environment.hooks.abstract import CombinedEnvHooks, EnvHook
from sweagent.environment.repo import Repo, RepoConfig
from sweagent.utils.log import get_logger


class EnvironmentConfig(BaseModel):
    """Configure data sources and setup instructions for the environment in which we solve the tasks."""

    deployment: DeploymentConfig = Field(
        default_factory=lambda: DockerDeploymentConfig(image="python:3.11", python_standalone_dir="/root"),
        description="Deployment options.",
    )
    repo: RepoConfig | None = Field(
        default=None,
        description="Repository options.",
    )
    post_startup_commands: list[str] = []
    """Execute these commands before starting to run the agent but after all other setup steps.
    They will be executed in the same shell as the agent.
    Note: Every command is passed as a string, not a list of arguments.
    """
    post_startup_command_timeout: int = 500
    """Timeout for the post-startup commands.
    NOTE: The timeout applies to every command in `post_startup_commands` separately.
    """

    # pydantic config
    model_config = ConfigDict(extra="forbid")

    name: str = "main"


class SWEEnv:
    def __init__(
        self,
        *,
        deployment: AbstractDeployment,
        repo: Repo | RepoConfig | None,
        post_startup_commands: list[str],
        post_startup_command_timeout: int = 500,
        hooks: list[EnvHook] | None = None,
        name: str = "main",
    ):
        """This class represents the environment in which we solve the tasks.

        Args:
            deployment: SWE-ReX deployment instance
            repo: Repository configuration object, or anything following the `Repo` protocol
            post_startup_commands: Commands to execute before starting the agent
            hooks: Environment hooks (used to inject custom functionality)
                Equivalent to calling `add_hook` for each hook after initialization.
            name: Name of the environment
        """
        super().__init__()
        self.deployment = deployment
        self.repo = repo
        self._post_startup_commands = post_startup_commands
        self.post_startup_command_timeout = post_startup_command_timeout
        self.logger = get_logger("swea-env", emoji="🪴")
        self.name = name
        self.clean_multi_line_functions = lambda x: x
        self._chook = CombinedEnvHooks()
        self._shell_crashed = False  # Track when shell needs restart
        self._initializing_shell = False  # Track when shell is being initialized
        for hook in hooks or []:
            self.add_hook(hook)

    @classmethod
    def from_config(cls, config: EnvironmentConfig) -> Self:
        """Create an environment instance from a configuration object.
        This is the recommended way to create an environment instance, unless you need
        more flexibility.
        """
        # Always copy config to avoid shared state between different instances
        config = config.model_copy(deep=True)
        return cls(
            deployment=get_deployment(config.deployment),
            repo=config.repo,
            post_startup_commands=config.post_startup_commands,
            post_startup_command_timeout=config.post_startup_command_timeout,
            name=config.name,
        )

    def add_hook(self, hook: EnvHook) -> None:
        """Add `EnvHook` to the environment.

        This allows to inject custom functionality at different stages of the environment
        lifecycle, in particular to connect SWE-agent to a new interface (like a GUI).
        """
        hook.on_init(env=self)
        self._chook.add_hook(hook)

    def start(self) -> None:
        """Start the environment and reset it to a clean state."""
        self._init_deployment()
        self._shell_crashed = False  # Reset crash flag on start
        self._initializing_shell = False  # Ensure initialization flag is reset
        self.reset()
        for command in self._post_startup_commands:
            self.communicate(command, check="raise", timeout=self.post_startup_command_timeout)

    def _copy_repo(self) -> None:
        """Clone/copy repository/codebase in container"""
        if self.repo is None:
            return

        folders = self.communicate(input="ls", check="raise").split("\n")
        if self.repo.repo_name in folders:
            return

        self._chook.on_copy_repo_started(repo=self.repo)
        self.repo.copy(self.deployment)

    def hard_reset(self):
        """Resets the environment and deployment, i.e., completely restarts the
        deployment.
        """
        self.logger.info("Performing hard reset of environment...")
        self.close()
        self.start()
        # Note: PATH persistence via .bashrc should maintain tool availability

    def reset(self):
        """Reset the environment to a clean state.
        Gets called by `start`, but can also be called independently to reset the
        environment to a clean state before a new attempt.

        Returns:
            observation: output from container
            info: additional information (e.g. debugging information)
        """
        self.communicate(input="cd /", check="raise")
        self._copy_repo()
        self._reset_repository()
        self._chook.on_environment_startup()

    def _reset_repository(self) -> None:
        """Clean repository of any modifications + Checkout base commit"""
        if self.repo is not None:
            self.logger.debug("Resetting repository %s to commit %s", self.repo.repo_name, self.repo.base_commit)
            # todo: Currently has swe-ft specific change: The original repo.copy isn't called, because the repo is already
            # present. However, reset --hard <BRANCH> also doesn't work. So modified it here to do a checkout instead.
            startup_commands = [
                f"cd /{self.repo.repo_name}",
                "export ROOT=$(pwd -P)",
                *self.repo.get_reset_commands(),
            ]
            self.communicate(
                input=" && ".join(startup_commands),
                check="raise",
                error_msg="Failed to clean repository",
                # Sometimes this is slow because it rebuilds some index
                timeout=120,
            )

    def close(self) -> None:
        """Shutdown SWE-ReX deployment etc."""
        self.logger.info("Beginning environment shutdown...")
        asyncio.run(self.deployment.stop())
        self._chook.on_close()

    # MARK: Helper functions #

    def _init_deployment(
        self,
    ) -> None:
        """Handles container initialization. Defines container name and creates it.
        If cached_image is provided, it will use that image name instead of the default.
        """
        self._initializing_shell = True  # Prevent crash recovery during init
        try:
            self._chook.on_start_deployment()
            asyncio.run(self.deployment.start())
            asyncio.run(
                self.deployment.runtime.create_session(
                    CreateBashSessionRequest(startup_source=["/root/.bashrc"], startup_timeout=10)
                )
            )
            self.set_env_variables({"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PIP_PROGRESS_BAR": "off", "PAGER": "cat"})
            
            # Source bashrc to pick up any persistent PATH modifications
            self.communicate("source /root/.bashrc 2>/dev/null || true", check="ignore", timeout=5)
            
            self.logger.info("Environment Initialized")
        finally:
            self._initializing_shell = False  # Always reset flag

    def diagnose_tools(self) -> str:
        """Diagnostic command to check tool/bundle loading status"""
        try:
            # Check if common tools are available
            tools_to_check = ["submit", "_state_anthropic", "str_replace_editor", "find_file", "edit"]
            results = {}
            
            for tool in tools_to_check:
                result = self.communicate(f"which {tool}", check="ignore", timeout=5)
                results[tool] = result.strip() if result.strip() else "NOT FOUND"
            
            # Check PATH
            path = self.communicate("echo $PATH", check="ignore", timeout=5)
            
            # Check if tool directories exist and are in PATH
            path_check = self.communicate("ls -la /root/tools/*/bin/ 2>/dev/null | head -10", check="ignore", timeout=5)
            
            # Check .bashrc for PATH modifications
            bashrc_content = self.communicate("grep -n 'PATH.*tools' /root/.bashrc 2>/dev/null || echo 'No PATH modifications found'", check="ignore", timeout=5)
            
            diagnostic_output = f"""
=== SWE-Agent Tools Diagnostic ===
Tool Availability:
{chr(10).join(f"  {tool}: {path}" for tool, path in results.items())}

Current PATH: {path.strip()}

Tool Directories in /root/tools:
{path_check}

.bashrc PATH Modifications:
{bashrc_content}

=== End Diagnostic ===
"""
            self.logger.info("Tools diagnostic completed")
            return diagnostic_output
            
        except Exception as e:
            self.logger.error(f"Tools diagnostic failed: {e}")
            return f"ERROR: Tools diagnostic failed: {e}"

    def interrupt_session(self):
        self.logger.info("Interrupting session")
        try:
            asyncio.run(self.deployment.runtime.run_in_session(BashInterruptAction()))
        except pexpect.exceptions.EOF as e:
            # Handle cases where the bash shell has already died
            self.logger.warning("Cannot interrupt session - bash shell has already terminated: %s", e)
            return  # Session is already dead, no need to interrupt
        except Exception as e:
            # Handle other runtime errors during interrupt
            self.logger.error("Failed to interrupt session: %s", e)
            raise

    # todo: return exit code?
    def _is_mcp_command(self, input_str: str) -> bool:
        """Check if the command is likely an MCP tool command that might crash the shell."""
        mcp_indicators = [
            "run_structural_search_function",
            "get_structural_search_function_syntax",
            "mcp_castimaging_",
            "structural_search_function",
            "_castimaging_",
        ]
        return any(indicator in input_str for indicator in mcp_indicators)
    
    def _safe_execute_command(self, input_str: str, timeout: int | float, rex_check: str) -> tuple[str | None, int | None]:
        """Safely execute a command with MCP tool crash protection.
        
        Returns:
            tuple: (output, exit_code) if successful, (None, None) if the command should be retried 
            after recovery, or (error_message, None) for unrecoverable errors.
        """
        try:
            r = asyncio.run(
                self.deployment.runtime.run_in_session(BashAction(command=input_str, timeout=timeout, check=rex_check))
            )
            return r.output, r.exit_code
        except pexpect.exceptions.EOF as e:
            self.logger.error("Bash shell terminated unexpectedly during command execution: %s", e)
            self.logger.error("Command that caused termination: %s", input_str)
            
            # Don't set crash flag during initialization to prevent infinite loops
            if not self._initializing_shell:
                self._shell_crashed = True
            else:
                self.logger.warning("Shell crashed during initialization - will not trigger restart to prevent infinite loop")
            
            # If it's an MCP command, try to provide graceful fallback
            if self._is_mcp_command(input_str):
                self.logger.warning("MCP tool appears to have crashed the shell. Shell will be restarted.")
                return None, None  # Signal that retry after restart is needed
            else:
                # For non-MCP commands, return error immediately
                error_output = f"ERROR: Bash shell terminated unexpectedly during command execution.\nCommand: {input_str}\nError: {e}\n\nThe shell will be restarted before the next command."
                return error_output, None
        except Exception as e:
            self.logger.error("Unexpected error during command execution: %s", e)
            error_output = f"ERROR: Command execution failed. Command: {input_str}\nError: {e}"
            return error_output, None

    def communicate(
        self,
        input: str,
        timeout: int | float = 25,
        *,
        check: Literal["warn", "ignore", "raise"] = "ignore",
        error_msg: str = "Command failed",
    ) -> str:
        """Executes a command in the running shell. The details of this are handled by
        the SWE-ReX deployment/runtime.

        Args:
            input: input to send to container
            timeout_duration: duration to wait for output
            check: `ignore`: do not extract exit code (more stable), `warn`: extract exit code and log error if
                exit code is non-zero, `raise`: raise error if exit code is non-zero
            error_msg: error message to raise if the command fails

        Returns:
            output: output from container
        """
        # Check if shell crashed and restart it (but not during initialization)
        if self._shell_crashed and not self._initializing_shell:
            self.logger.info("Shell crashed previously. Attempting automatic restart...")
            try:
                self.hard_reset()
                self.logger.info("Shell successfully restarted.")
            except Exception as e:
                self.logger.error("Failed to restart shell: %s", e)
                if check == "raise":
                    raise RuntimeError(f"Shell restart failed after crash: {e}")
                return f"ERROR: Shell restart failed after previous crash: {e}"
        
        self.logger.log(logging.TRACE, "Input:\n%s", input)  # type: ignore
        
        rex_check = "silent" if check else "ignore"
        
        # Try safe execution with crash handling
        output, exit_code = self._safe_execute_command(input, int(timeout), rex_check)
        
        if output is None:
            # This means an MCP command crashed and we should retry after restart
            if self._shell_crashed:
                try:
                    self.logger.info("Restarting shell after MCP tool crash...")
                    self.hard_reset()
                    # Retry the command once after restart
                    output, exit_code = self._safe_execute_command(input, int(timeout), rex_check)
                    if output is None:  # Still failed after restart
                        error_output = f"ERROR: Command failed even after shell restart.\nCommand: {input}\n\nThis usually indicates a persistent issue with the command or environment."
                        if check == "raise":
                            raise RuntimeError(error_output)
                        return error_output
                except Exception as e:
                    self.logger.error("Failed to restart shell after MCP crash: %s", e)
                    error_output = f"ERROR: Shell restart failed after MCP tool crash: {e}"
                    if check == "raise":
                        raise RuntimeError(error_output)
                    return error_output
            else:
                # Shouldn't happen, but handle gracefully
                error_output = f"ERROR: Unexpected state during command execution. Command: {input}"
                if check == "raise":
                    raise RuntimeError(error_output)
                return error_output
        
        self.logger.log(logging.TRACE, "Output:\n%s", output)  # type: ignore
        
        # For commands that ran successfully, check exit code if requested
        if check != "ignore" and exit_code is not None and exit_code != 0:
            self.logger.error(f"{error_msg}:\n{output}")
            
            # Special handling for submit command failures
            if "submit: command not found" in str(output) or ("submit" in input and "command not found" in str(output)):
                self.logger.warning("Submit command failure detected - running tools diagnostic...")
                try:
                    diagnostic_info = self.diagnose_tools()
                    self.logger.warning("Submit failure diagnostic:")
                    self.logger.warning(diagnostic_info)
                except Exception as diag_e:
                    self.logger.error(f"Failed to run diagnostic after submit failure: {diag_e}")
            
            msg = f"Command {input!r} failed ({exit_code=}): {error_msg}"
            self.logger.error(msg)
            if check == "raise":
                self.close()
                raise RuntimeError(msg)
        elif check != "ignore" and "ERROR:" in str(output):
            # Handle error messages from our crash recovery
            if check == "warn":
                self.logger.warning(f"{error_msg}:\n{output}")
            elif check == "raise":
                raise RuntimeError(f"Command {input!r} failed: {error_msg}")
            
        return output

    def read_file(self, path: str | PurePath, encoding: str | None = None, errors: str | None = None) -> str:
        """Read file contents from container

        Args:
            path: Absolute path to file
            encoding: Encoding to use when reading the file. None means default encoding.
                This is the same as the `encoding` argument of `Path.read_text()`
            errors: Error handling to use when reading the file. None means default error handling.
                This is the same as the `errors` argument of `Path.read_text()`

        Returns:
            file_contents: Contents of file as string
        """
        r = asyncio.run(
            self.deployment.runtime.read_file(ReadFileRequest(path=str(path), encoding=encoding, errors=errors))
        )
        return r.content

    def write_file(self, path: str | PurePath, content: str) -> None:
        """Write content to file in container"""
        asyncio.run(self.deployment.runtime.write_file(WriteFileRequest(path=str(path), content=content)))

    def set_env_variables(self, env_variables: dict[str, str]) -> None:
        """Set environment variables in the environment."""
        if not env_variables:
            self.logger.debug("No environment variables to set")
            return
        _env_setters = [f"export {k}={shlex.quote(str(v))}" for k, v in env_variables.items()]
        command = " && ".join(_env_setters)
        # Use check="warn" instead of "raise" to avoid infinite recursion during shell restart
        # When shell is restarting, failing to set env vars should not trigger another restart
        self.communicate(command, check="warn")

    def execute_command(
        self,
        command: str,
        shell: bool = True,
        check: bool = False,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        """Execute a command in the environment independent of the session (i.e., as a subprocess)"""
        asyncio.run(
            self.deployment.runtime.execute(RexCommand(command=command, shell=shell, check=check, env=env, cwd=cwd))
        )
