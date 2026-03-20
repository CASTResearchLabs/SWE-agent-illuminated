#!/usr/bin/env python3
"""
SWE-Agent Trajectory Analyzer

Extracts key information from SWE-agent trajectory files including:
1. Problem statement
2. Resulting patch
3. Model statistics
4. Sequence of actions
"""

import json
import os
import re
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict
import argparse


@dataclass
class ModelStats:
    """Model performance statistics"""
    instance_cost: float
    tokens_sent: int
    tokens_received: int
    api_calls: int


@dataclass
class ActionSummary:
    """Summary of a single action in the trajectory"""
    step: int
    action: str
    execution_time: float
    success: bool
    error: Optional[str] = None
    working_dir: Optional[str] = None
    observation_length: int = 0


@dataclass
class TrajectoryAnalysis:
    """Complete analysis of a trajectory file"""
    file_path: Path
    trajectory_id: str
    mcp_context: str  # MCP server availability context (e.g., "(current code base is available as application...)") 
    problem_statement: str
    resulting_patch: str
    model_stats: ModelStats
    actions: List[ActionSummary]
    exit_status: str
    exit_status_type: str  # "manual_submission", "auto_format_errors", "auto_other", "unknown" 
    exit_status_details: str  # Additional context about submission type
    total_execution_time: float
    swe_agent_version: str
    success_ratio: float
    success: bool
    with_mcp: bool  # Problem statement mentions MCP server availability
    mcp_usage: float  # Ratio of actions involving MCP operations (mcp_list_servers, mcp_list_tools, mcp_call)
    mcp_cli_mode: bool  # Whether MCP access is via bash CLI wrappers (affects performance/syntax)
    model: str      # Model name from replay_config
    date: str       # File modification timestamp


class TrajectoryAnalyzer:
    """Analyzer for SWE-agent trajectory files"""
    
    def __init__(self):
        self.results: List[TrajectoryAnalysis] = []
        
    def _create_task_grouping_key(self, result: TrajectoryAnalysis) -> Tuple[str, str, str]:
        """Create a grouping key based on normalized task statement, model, and config"""
        # Handle None problem statement gracefully
        problem_text = result.problem_statement or ""
        
        # Use first 200 chars of cleaned problem statement as task identifier
        normalized_task = problem_text[:200].strip().replace('\n', ' ') if problem_text else "Unknown Task"
        
        # Extract config from file path or use default
        config = "unknown"
        try:
            # Look for config pattern in file path
            path_str = str(result.file_path)
            if "adaptive_engineering" in path_str:
                config = "adaptive_engineering"
            elif "default" in path_str:
                config = "default"
            else:
                config = "unknown"
        except:
            config = "unknown"
            
        # Handle None model gracefully
        model = result.model or "unknown"
            
        return (normalized_task, model, config)
    
    def group_trajectories_by_task(self, results: List[TrajectoryAnalysis]) -> Dict[Tuple[str, str, str], Dict[str, List[TrajectoryAnalysis]]]:
        """Group trajectories by normalized task + model + config, then by MCP usage"""
        grouped = defaultdict(lambda: {"with_mcp": [], "without_mcp": []})
        
        for result in results:
            task_key = self._create_task_grouping_key(result)
            if result.with_mcp:
                grouped[task_key]["with_mcp"].append(result)
            else:
                grouped[task_key]["without_mcp"].append(result)
                
        return dict(grouped)
    
    def extract_problem_statement(self, trajectory_data: Dict) -> str:
        """Extract the problem statement from trajectory data"""
        try:
            # Look for problem statement in the initial system/user messages
            if 'trajectory' in trajectory_data and len(trajectory_data['trajectory']) > 0:
                for action in trajectory_data['trajectory']:
                    if 'query' in action:
                        for message in action['query']:
                            if message.get('role') == 'user':
                                content = message.get('content', '')
                                if isinstance(content, list):
                                    # Handle content as list of objects
                                    for item in content:
                                        if isinstance(item, dict) and 'text' in item:
                                            text = item['text']
                                            # Look for task description
                                            if '<task_description>' in text:
                                                start = text.find('<task_description>') + len('<task_description>')
                                                end = text.find('</task_description>')
                                                if end != -1:
                                                    extracted = text[start:end].strip()
                                                    # Process escaped newlines and clean up
                                                    extracted = extracted.replace('\\n', '\n')
                                                    return extracted
                                            # Fallback: return first substantial user content
                                            if len(text.strip()) > 100:
                                                processed_text = text.replace('\\n', '\n')
                                                return processed_text.strip()[:1000] + "..." if len(processed_text) > 1000 else processed_text.strip()
                                elif isinstance(content, str) and len(content.strip()) > 100:
                                    processed_content = content.replace('\\n', '\n')
                                    return processed_content.strip()[:1000] + "..." if len(processed_content) > 1000 else processed_content.strip()
            return "Problem statement not found"
        except Exception as e:
            return f"Error extracting problem statement: {str(e)}"
    
    def extract_resulting_patch(self, trajectory_data: Dict) -> str:
        """Extract the resulting patch from trajectory data"""
        try:
            if 'info' in trajectory_data and 'submission' in trajectory_data['info']:
                return trajectory_data['info']['submission']
            return "No patch found"
        except Exception as e:
            return f"Error extracting patch: {str(e)}"
    
    def extract_model_stats(self, trajectory_data: Dict) -> ModelStats:
        """Extract model statistics from trajectory data"""
        try:
            if 'info' in trajectory_data and 'model_stats' in trajectory_data['info']:
                stats = trajectory_data['info']['model_stats']
                return ModelStats(
                    instance_cost=stats.get('instance_cost', 0.0),
                    tokens_sent=stats.get('tokens_sent', 0),
                    tokens_received=stats.get('tokens_received', 0),
                    api_calls=stats.get('api_calls', 0)
                )
            return ModelStats(0.0, 0, 0, 0)
        except Exception as e:
            return ModelStats(0.0, 0, 0, 0)
    
    def extract_actions(self, trajectory_data: Dict) -> List[ActionSummary]:
        """Extract sequence of actions from trajectory data"""
        actions = []
        try:
            if 'trajectory' not in trajectory_data:
                return actions
            
            for i, action_data in enumerate(trajectory_data['trajectory']):
                try:
                    action_name = action_data.get('action', 'unknown')
                    execution_time = action_data.get('execution_time', 0.0)
                    observation = action_data.get('observation', '')
                    observation_length = len(str(observation)) if observation else 0
                    
                    # Determine success based on various indicators
                    success = True
                    error = None
                    
                    # Check for error indicators in observation
                    if observation:
                        obs_str = str(observation).lower()
                        if any(indicator in obs_str for indicator in ['error', 'failed', 'exception', 'traceback']):
                            success = False
                            error = "Error detected in observation"
                    
                    # Extract working directory
                    working_dir = None
                    if 'state' in action_data and 'working_dir' in action_data['state']:
                        working_dir = action_data['state']['working_dir']
                    
                    actions.append(ActionSummary(
                        step=i + 1,
                        action=action_name,
                        execution_time=execution_time,
                        success=success,
                        error=error,
                        working_dir=working_dir,
                        observation_length=observation_length
                    ))
                    
                except Exception as e:
                    # Add error action for failed parsing
                    actions.append(ActionSummary(
                        step=i + 1,
                        action="parsing_error",
                        execution_time=0.0,
                        success=False,
                        error=f"Failed to parse action: {str(e)}"
                    ))
        
        except Exception as e:
            print(f"Error extracting actions: {str(e)}")
        
        return actions
    
    def _has_meaningful_patch(self, patch: str) -> bool:
        """Check if a patch contains meaningful content (not just empty or minimal changes)"""
        if not patch or patch.strip() == "":
            return False
        
        # Remove common empty patch indicators
        cleaned_patch = patch.strip()
        if cleaned_patch in ["No patch found", "No patch", "no patch"]:
            return False
        
        # Check if patch has substantial content (more than just diff headers)
        lines = cleaned_patch.split('\n')
        content_lines = [line for line in lines if not line.startswith(('diff --git', 'index ', '--- ', '+++ ', '@@'))]
        meaningful_lines = [line for line in content_lines if line.strip() and not line.strip().startswith(('#', '//', '/*', '*'))]
        
        # Consider it meaningful if it has at least 3 lines of actual content or is longer than 100 chars
        return len(meaningful_lines) >= 3 or len(cleaned_patch) > 100
    
    def _extract_mcp_context(self, problem_statement: str) -> str:
        """Extract MCP context from the beginning of problem statement"""
        if not problem_statement:
            return ""
        
        # Look for MCP context pattern - make it more flexible
        patterns = [
            r'^\s*\([^)]*via [^)]*MCP server\)',  # Original pattern
            r'^\s*\(current code base is available as application [^)]*via [^)]*MCP server\)'  # More specific pattern
        ]
        
        import re
        for pattern in patterns:
            match = re.search(pattern, problem_statement, re.IGNORECASE | re.MULTILINE)
            if match:
                return match.group(0).strip()
        return ""
    
    def _clean_problem_statement(self, problem_statement: str, mcp_context: str) -> str:
        """Remove MCP context from problem statement and clean up"""
        if not problem_statement:
            return ""
        
        cleaned = problem_statement
        if mcp_context:
            # Remove the MCP context from the beginning
            cleaned = cleaned.replace(mcp_context, "", 1)
        
        # Clean up extra whitespace and newlines at the beginning
        cleaned = cleaned.strip()
        while cleaned.startswith('\n'):
            cleaned = cleaned[1:].strip()
        
        return cleaned
    
    def _detect_mcp_availability(self, problem_statement: str) -> bool:
        """Detect if problem statement mentions MCP server availability"""
        if not problem_statement:
            return False
        
        # Check multiple patterns for MCP availability
        patterns = [
            r'\(current code base is available as application .* via imaging-structural MCP server\)',
            r'\([^)]*via [^)]*imaging-structural MCP server\)',
            r'\([^)]*via [^)]*MCP server\)',  # More general fallback
        ]
        
        import re
        for pattern in patterns:
            if re.search(pattern, problem_statement, re.IGNORECASE | re.MULTILINE):
                return True
        
        return False
    
    def _analyze_exit_status(self, exit_status: str) -> tuple[str, str]:
        """Analyze exit status to determine type and provide detailed context"""
        status = exit_status.lower()
        
        if status == "submitted":
            return "manual_submission", "Normal successful manual submission"
        elif "exit_format" in status:
            return "auto_format_errors", "Auto-submitted due to repeated format/blocklist/bash syntax errors (likely MCP tool instability)"
        elif "autosubmitted" in status or "auto" in status:
            return "auto_other", "Auto-submitted due to other system constraints (timeout, cost, etc.)"
        elif status.startswith("submitted"):
            # Handle any other "submitted (...)" variants
            details = status.replace("submitted", "").strip("() ")
            return "auto_other", f"Auto-submitted due to: {details}"
        else:
            return "unknown", f"Non-submission exit: {exit_status}"
    
    def _detect_mcp_cli_mode(self, actions: List[ActionSummary]) -> bool:
        """Detect if MCP access is via bash CLI wrappers (Princeton SWE-agent setup)"""
        # Look for patterns that indicate bash CLI wrapper usage for MCP
        mcp_action_count = 0
        cli_wrapper_indicators = 0
        
        for action in actions:
            if (action.action.startswith('mcp_call') or 
                action.action.startswith('mcp_list')):
                mcp_action_count += 1
                
                # Check for bash CLI wrapper patterns
                action_text = action.action.lower()
                if any(indicator in action_text for indicator in [
                    'bash', 'shell', 'echo', 'curl', 'python -c', 'subprocess', 'os.system'
                ]):
                    cli_wrapper_indicators += 1
        
        # If we have MCP actions and signs of CLI wrappers, likely using CLI mode
        return mcp_action_count > 0 and (cli_wrapper_indicators > 0 or mcp_action_count >= 3)
        
        for action in actions:
            if (action.action.startswith('mcp_call') or 
                action.action.startswith('mcp_list')):
                mcp_action_count += 1
                
                # Check for bash CLI wrapper patterns
                action_text = action.action.lower()
                if any(indicator in action_text for indicator in [
                    'bash', 'shell', 'echo', 'curl', 'python -c', 'subprocess', 'os.system'
                ]):
                    cli_wrapper_indicators += 1
        
        # If we have MCP actions and signs of CLI wrappers, likely using CLI mode
        return mcp_action_count > 0 and (cli_wrapper_indicators > 0 or mcp_action_count >= 3)
    
    def _calculate_mcp_usage(self, actions: List[ActionSummary]) -> float:
        """Calculate the ratio of actions involving MCP operations"""
        if not actions:
            return 0.0
        
        mcp_actions = 0
        for action in actions:
            if (action.action.startswith('mcp_call') or 
                action.action.startswith('mcp_list_servers') or 
                action.action.startswith('mcp_list_tools')):
                mcp_actions += 1
        
        return mcp_actions / len(actions)
    
    def _extract_model_name(self, trajectory_data: Dict) -> str:
        """Extract model name from replay_config"""
        try:
            replay_config_str = trajectory_data.get('replay_config', '{}')
            if isinstance(replay_config_str, str):
                import json
                replay_config = json.loads(replay_config_str)
                # Model is nested under agent.model.name
                agent_info = replay_config.get('agent', {})
                model_info = agent_info.get('model', {})
                return model_info.get('name', 'unknown')
            return 'unknown'
        except Exception as e:
            return 'unknown'
    
    def _get_file_date(self, file_path: Path) -> str:
        """Get file modification date as ISO string"""
        try:
            import datetime
            timestamp = file_path.stat().st_mtime
            dt = datetime.datetime.fromtimestamp(timestamp)
            return dt.isoformat()
        except Exception as e:
            return 'unknown'
    
    def analyze_trajectory_file(self, file_path: Path) -> Optional[TrajectoryAnalysis]:
        """Analyze a single trajectory file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                trajectory_data = json.load(f)
            
            # Extract trajectory ID from filename
            trajectory_id = file_path.stem
            
            # Extract all components
            raw_problem_statement = self.extract_problem_statement(trajectory_data)
            mcp_context = self._extract_mcp_context(raw_problem_statement)
            problem_statement = self._clean_problem_statement(raw_problem_statement, mcp_context)
            resulting_patch = self.extract_resulting_patch(trajectory_data)
            model_stats = self.extract_model_stats(trajectory_data)
            actions = self.extract_actions(trajectory_data)
            
            # Extract metadata from info section
            info = trajectory_data.get('info', {})
            exit_status = info.get('exit_status', 'unknown')
            swe_agent_version = info.get('swe_agent_version', 'unknown')
            
            # Calculate total execution time
            total_execution_time = sum(action.execution_time for action in actions)
            
            # Calculate success ratio
            if actions:
                successful_actions = sum(1 for action in actions if action.success)
                success_ratio = successful_actions / len(actions)
            else:
                success_ratio = 0.0
            
            # Analyze exit status for detailed information
            exit_status_type, exit_status_details = self._analyze_exit_status(exit_status)
            
            # Determine overall success - manual submissions or high success ratio auto-submissions
            # But NOT auto-submissions due to format errors which indicate incomplete work
            success = (
                exit_status.startswith('submitted') and 
                success_ratio >= 0.7 and
                exit_status_type != "auto_format_errors"  # Format errors indicate premature termination
            )
            
            # Detect MCP usage (use raw problem statement for detection)
            with_mcp = self._detect_mcp_availability(raw_problem_statement)
            mcp_usage = self._calculate_mcp_usage(actions)
            mcp_cli_mode = self._detect_mcp_cli_mode(actions)
            
            # Extract model and date information
            model = self._extract_model_name(trajectory_data)
            date = self._get_file_date(file_path)
            
            return TrajectoryAnalysis(
                file_path=file_path,
                trajectory_id=trajectory_id,
                mcp_context=mcp_context,
                problem_statement=problem_statement,
                resulting_patch=resulting_patch,
                model_stats=model_stats,
                actions=actions,
                exit_status=exit_status,
                exit_status_type=exit_status_type,
                exit_status_details=exit_status_details,
                total_execution_time=total_execution_time,
                swe_agent_version=swe_agent_version,
                success_ratio=success_ratio,
                success=success,
                with_mcp=with_mcp,
                mcp_usage=mcp_usage,
                mcp_cli_mode=mcp_cli_mode,
                model=model,
                date=date
            )
            
        except Exception as e:
            print(f"Error analyzing {file_path}: {str(e)}")
            return None
    
    def analyze_directory(self, directory: Path, pattern: str = "**/*.traj", 
                         filter_submitted: bool = False, filter_non_empty_patch: bool = False,
                         filter_model: Optional[str] = None, filter_statement: Optional[str] = None) -> List[TrajectoryAnalysis]:
        """Analyze all trajectory files in a directory with optional filtering
        
        Args:
            directory: Directory to search for trajectory files
            pattern: Glob pattern for trajectory files
            filter_submitted: Only include trajectories with exit_status='submitted'
            filter_non_empty_patch: Only include trajectories with non-empty patches
            filter_model: Only include trajectories using specified model name
            filter_statement: Only include trajectories with problem statements containing specified text
        """
        trajectory_files = list(directory.glob(pattern))
        print(f"Found {len(trajectory_files)} trajectory files")
        
        results = []
        filtered_count = 0
        
        for file_path in trajectory_files:
            print(f"Analyzing {file_path.name}...")
            analysis = self.analyze_trajectory_file(file_path)
            if analysis:
                # Apply filters if requested
                should_include = True
                
                if filter_submitted and analysis.exit_status != 'submitted':
                    should_include = False
                    print(f"  Filtered out: exit_status='{analysis.exit_status}' (not submitted)")
                
                if filter_non_empty_patch and not self._has_meaningful_patch(analysis.resulting_patch):
                    should_include = False
                    print(f"  Filtered out: empty or minimal patch")
                
                if filter_model and filter_model not in analysis.model:
                    should_include = False
                    print(f"  Filtered out: model='{analysis.model}' (does not contain '{filter_model}')")
                
                if filter_statement and filter_statement not in analysis.problem_statement:
                    should_include = False
                    print(f"  Filtered out: problem statement does not contain '{filter_statement}'")
                
                if should_include:
                    results.append(analysis)
                else:
                    filtered_count += 1
        
        if filter_submitted or filter_non_empty_patch or filter_model or filter_statement:
            print(f"Filtering applied: kept {len(results)} trajectories, filtered out {filtered_count}")
        
        return results
    
    def export_to_json(self, results: List[TrajectoryAnalysis], output_path: Path):
        """Export results to JSON format"""
        data = [asdict(result) for result in results]
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        print(f"Exported {len(results)} analyses to {output_path}")
    
    def export_to_csv(self, results: List[TrajectoryAnalysis], output_path: Path):
        """Export summary to CSV format"""
        import csv
        
        with open(output_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            
            # Write header
            writer.writerow([
                'trajectory_id', 'mcp_context', 'success', 'success_ratio', 'exit_status', 'exit_status_type', 'exit_status_details', 
                'total_execution_time', 'num_actions', 'instance_cost', 'tokens_sent', 'tokens_received',
                'api_calls', 'swe_agent_version', 'has_patch', 'with_mcp', 'mcp_usage', 'mcp_cli_mode',
                'model', 'date'
            ])
            
            # Write data
            for result in results:
                writer.writerow([
                    result.trajectory_id,
                    result.mcp_context,
                    result.success,
                    f"{result.success_ratio:.3f}",
                    result.exit_status,
                    result.exit_status_type,
                    result.exit_status_details,
                    result.total_execution_time,
                    len(result.actions),
                    result.model_stats.instance_cost,
                    result.model_stats.tokens_sent,
                    result.model_stats.tokens_received,
                    result.model_stats.api_calls,
                    result.swe_agent_version,
                    len(result.resulting_patch or "") > 10,
                    result.with_mcp,
                    f"{result.mcp_usage:.3f}",
                    result.mcp_cli_mode,
                    result.model,
                    result.date
                ])
        
        print(f"Exported summary to {output_path}")
    
    def _extract_action_type(self, action_text: str) -> str:
        """Extract the actual action/command type from potentially complex action text"""
        if not action_text or action_text.strip() == "":
            return "empty"
        
        # Handle multi-line actions - split into lines and find the first non-comment line
        lines = action_text.split('\n')
        for line in lines:
            line = line.strip()
            if not line:  # Skip empty lines
                continue
            if line.startswith('#'):  # Skip comment lines
                continue
            
            # Found first non-comment line, extract command from it
            action_text = line
            break
        
        # Common action type patterns
        action_lower = action_text.lower().strip()
        
        # MCP actions
        if action_text.startswith('mcp_'):
            return action_text.split('_')[0] + '_' + action_text.split('_')[1] if '_' in action_text[4:] else 'mcp'
        
        # Direct command patterns
        direct_commands = ['grep', 'find', 'cat', 'ls', 'cd', 'pwd', 'head', 'tail', 'wc', 'sort', 'uniq', 'awk', 'sed', 'git']
        for cmd in direct_commands:
            if action_lower.startswith(cmd + ' ') or action_lower == cmd:
                return cmd
        
        # str_replace_editor and similar tools
        if 'str_replace_editor' in action_text:
            return 'str_replace_editor'
        if 'search_file' in action_text:
            return 'search_file'
        
        # Submit actions
        if action_lower.startswith('submit'):
            return 'submit'
        
        # Generic fallback - take first word/token
        first_token = action_text.split()[0] if action_text.split() else action_text
        # Remove special characters and take alphanumeric part
        import re
        clean_token = re.sub(r'[^\w]', '', first_token)
        return clean_token.lower() if clean_token else 'unknown'
    
    def export_to_markdown(self, results: List[TrajectoryAnalysis], output_path: Path, 
                          detailed: bool = False, include_patches: bool = True, simplified_for_split: bool = False,
                          group_by_task: bool = True):
        """Export analysis to Markdown format optimized for LLM judge analysis"""
        
        def escape_markdown(text: str) -> str:
            """Escape special markdown characters in text"""
            if not text:
                return ""
            # Escape basic markdown characters but preserve intentional formatting
            return text.replace('|', '\\|').replace('\n', '\n\n').strip()
            
        def truncate_text(text: str, max_length: int = 500, no_warning: bool = False, single_line: bool = False) -> str:
            """Truncate text for summary view"""
            if not text or len(text) <= max_length:
                return_text = text
            else:
                return_text = text[:max_length] + "..." if no_warning else text[:max_length] + "...\n*[Text truncated for summary]*"

            if return_text:
                if single_line:
                    return_text = return_text.replace("\n", "\\n")
                else:
                    return_text = return_text.replace("\\n", "")
                
            return return_text
        
        def format_patch(patch: str, max_lines: int = -1) -> str:
            """Format patch for markdown with truncation if needed"""
            if not patch or patch.strip() in ["No patch found", "No patch", "no patch"]:
                return "*No meaningful patch generated*"

            if max_lines == -1:
                return f"```diff\n{patch}\n```"

            # Split patch into blocks at each "diff --git" boundary
            lines = patch.split('\n')
            blocks: list[list[str]] = []
            current_block: list[str] = []

            for line in lines:
                if line.startswith('diff --git') and current_block:
                    blocks.append(current_block)
                    current_block = [line]
                else:
                    current_block.append(line)

            if current_block:
                blocks.append(current_block)

            # Truncate each block independently
            any_truncated = False
            result_lines: list[str] = []

            for block in blocks:
                if len(block) > max_lines:
                    result_lines.extend(block[:max_lines])
                    result_lines.append(f'# ... [block truncated – showing first {max_lines} lines]')
                    any_truncated = True
                else:
                    result_lines.extend(block)

            result_patch = '\n'.join(result_lines)
            suffix = (
                "\n\n*[One or more diff blocks truncated"
                f" – showing first {max_lines} lines per block]*"
                if any_truncated else ""
            )
            return f"```diff\n{result_patch}\n```{suffix}"
        
        with open(output_path, 'w', encoding='utf-8') as f:
            # Write header and summary
            f.write("# SWE-Agent Trajectory Analysis Report\n\n")
            f.write(f"**Generated:** {self._get_current_timestamp()}\n\n")
            f.write(f"**Total Trajectories:** {len(results)}\n\n")
            
            # Group trajectories by task if requested and we have multiple trajectories
            if group_by_task and len(results) > 1:
                self._export_grouped_analysis(f, results, detailed, include_patches, simplified_for_split)
                return
            
            # Summary statistics
            successful = sum(1 for r in results if r.success)
            submitted = sum(1 for r in results if r.exit_status.startswith('submitted'))
            manual_submissions = sum(1 for r in results if r.exit_status_type == 'manual_submission')
            auto_format_errors = sum(1 for r in results if r.exit_status_type == 'auto_format_errors')
            auto_other = sum(1 for r in results if r.exit_status_type == 'auto_other')
            with_patches = sum(1 for r in results if self._has_meaningful_patch(r.resulting_patch))
            with_mcp = sum(1 for r in results if r.with_mcp)
            used_mcp = sum(1 for r in results if r.mcp_usage > 0)
            mcp_cli_mode = sum(1 for r in results if r.mcp_cli_mode)
            
            f.write("## 📊 Executive Summary\n\n")
            f.write("| Metric | Count | Percentage |\n")
            f.write("|--------|-------|------------|\n")
            f.write(f"| Successful (submitted + ≥70% actions, no format errors) | {successful} | {successful/len(results)*100:.1f}% |\n")
            f.write(f"| Submitted trajectories | {submitted} | {submitted/len(results)*100:.1f}% |\n")
            f.write(f"| └─ Manual submissions | {manual_submissions} | {manual_submissions/len(results)*100:.1f}% |\n")
            f.write(f"| └─ Auto-submitted (format/syntax errors) | {auto_format_errors} | {auto_format_errors/len(results)*100:.1f}% |\n")
            f.write(f"| └─ Auto-submitted (other constraints) | {auto_other} | {auto_other/len(results)*100:.1f}% |\n")
            f.write(f"| With meaningful patches | {with_patches} | {with_patches/len(results)*100:.1f}% |\n")
            f.write(f"| MCP available | {with_mcp} | {with_mcp/len(results)*100:.1f}% |\n")
            f.write(f"| Actually used MCP | {used_mcp} | {used_mcp/len(results)*100:.1f}% |\n")
            f.write(f"| MCP via bash CLI wrappers | {mcp_cli_mode} | {mcp_cli_mode/len(results)*100:.1f}% |\n\n")
            
            # Add MCP CLI context explanation
            if mcp_cli_mode > 0:
                f.write("### 🔧 MCP CLI Context\n\n")
                f.write(f"**{mcp_cli_mode}** trajectories used MCP via bash CLI wrappers, which is characteristic of the Princeton SWE-agent setup. ")
                f.write("This approach provides MCP access to non-MCP-aware SWE-agent installations through command-line interfaces, but may introduce:\n")
                f.write("- Additional syntax complexity (bash escaping, JSON formatting)\n")
                f.write("- Increased execution time due to shell process overhead\n")
                f.write("- Higher potential for format/syntax errors leading to auto-submission\n")
                f.write("- Tool instability as bash wrappers are more fragile than native MCP integration\n\n")
                
                if auto_format_errors > 0:
                    f.write(f"**Note:** {auto_format_errors} trajectories auto-submitted due to format/syntax errors, ")
                    f.write("which often correlates with MCP CLI wrapper instability.\n\n")
            
            # Cost and performance summary
            total_cost = sum(r.model_stats.instance_cost for r in results)
            avg_execution_time = sum(r.total_execution_time for r in results) / len(results)
            avg_actions = sum(len(r.actions) for r in results) / len(results)
            
            f.write("## 💰 Cost & Performance Overview\n\n")
            f.write(f"- **Total Cost:** ${total_cost:.2f}\n")
            f.write(f"- **Average Cost per Trajectory:** ${total_cost/len(results):.2f}\n")
            f.write(f"- **Average Execution Time:** {avg_execution_time:.1f}s\n")
            f.write(f"- **Average Actions per Trajectory:** {avg_actions:.1f}\n\n")
            
            f.write("---\n\n")
            
            # Individual trajectory analyses
            f.write("## 📋 Individual Trajectory Analyses\n\n")
            
            for i, result in enumerate(results, 1):
                f.write(f"### {i}. Trajectory: `{result.trajectory_id}`\n\n")
                
                f.write(f"**Path:** {result.file_path}\n")
                f.write(f"**Date:** {result.date}\n\n")
                
                # Add reference to detailed split file if split mode is enabled
                if simplified_for_split:
                    # Generate the relative path to the split file
                    output_dir_name = output_path.stem  # basename of main markdown file
                    safe_trajectory_id = "".join(c for c in result.trajectory_id if c.isalnum() or c in "._-")
                    split_file_path = f"{output_dir_name}/{safe_trajectory_id}.md"
                    f.write(f"**Detailed report:** {split_file_path}\n\n")

                # Status badges using emoji
                status_emoji = "✅" if result.success else "❌"
                mcp_emoji = "🔌" if result.with_mcp else "⚫"
                patch_emoji = "📝" if self._has_meaningful_patch(result.resulting_patch) else "📄"
                cli_emoji = "🖥️" if result.mcp_cli_mode else ""
                
                # Enhanced exit status display
                exit_status_display = result.exit_status
                if result.exit_status_type == "auto_format_errors":
                    exit_status_display += " ⚠️ (format errors)"
                elif result.exit_status_type == "auto_other":
                    exit_status_display += " 🤖 (auto)"
                elif result.exit_status_type == "manual_submission":
                    exit_status_display += " ✋ (manual)"
                
                f.write(f"{status_emoji} **Status:** {exit_status_display} ")
                f.write(f"| {mcp_emoji} **MCP:** {'Available' if result.with_mcp else 'Not Available'} ")
                if result.mcp_cli_mode:
                    f.write(f"{cli_emoji} (CLI) ")
                f.write(f"| {patch_emoji} **Patch:** {'Generated' if self._has_meaningful_patch(result.resulting_patch) else 'Empty'}\n\n")
                
                # Exit status explanation for format errors
                if result.exit_status_type == "auto_format_errors":
                    f.write("⚠️ **Auto-Submission Context:** ")
                    f.write(f"{escape_markdown(result.exit_status_details)}\n\n")
                
                # Key metrics table
                f.write("#### 📈 Key Metrics\n\n")
                f.write("| Metric | Value |\n")
                f.write("|--------|-------|\n")
                f.write(f"| Model | {result.model} |\n")
                f.write(f"| Exit Status Type | {result.exit_status_type.replace('_', ' ').title()} |\n")
                f.write(f"| Success Ratio | {result.success_ratio:.1%} ({sum(1 for a in result.actions if a.success)}/{len(result.actions)} actions) |\n")
                f.write(f"| Execution Time | {result.total_execution_time:.1f} seconds |\n")
                f.write(f"| Cost | ${result.model_stats.instance_cost:.2f} |\n")
                f.write(f"| Tokens | {result.model_stats.tokens_sent:,} sent → {result.model_stats.tokens_received:,} received |\n")
                f.write(f"| MCP Usage | {result.mcp_usage:.1%} of actions |\n")
                if result.mcp_cli_mode:
                    f.write(f"| MCP Access Mode | Bash CLI Wrappers (may affect performance/syntax) |\n")
                f.write(f"| Date | {result.date.split('T')[0] if 'T' in result.date else result.date} |\n\n")
                
                # MCP Context (if applicable)
                if result.mcp_context:
                    f.write("#### 🔌 MCP Context\n\n")
                    f.write(f"> {escape_markdown(result.mcp_context)}\n\n")
                
                # Problem statement - always truncate when simplified_for_split is True
                f.write("#### 🎯 Problem Statement\n\n")
                if simplified_for_split:
                    problem_text = truncate_text(result.problem_statement, single_line=False)
                else:
                    problem_text = truncate_text(result.problem_statement, single_line = False) if not detailed else result.problem_statement.replace("\\n\\n","\n").replace("\\n","")
                f.write(f"```text\n{escape_markdown(problem_text)}\n```\n\n")
                
                # Action summary
                f.write("#### ⚡ Actions Summary\n\n")
                # if not detailed:
                    
                # Time statistics grouped by status
                successful_actions = [a for a in result.actions if a.success]
                failed_actions = [a for a in result.actions if not a.success]
                
                successful_time = sum(a.execution_time for a in successful_actions)
                failed_time = sum(a.execution_time for a in failed_actions)
                total_time = successful_time + failed_time
                
                f.write("**Execution Time by Status:**\n\n")
                f.write(f"- ✅ **Successful**: {len(successful_actions)} actions, {successful_time:.1f}s total")
                if successful_actions:
                    f.write(f" ({successful_time/len(successful_actions):.1f}s avg)")
                if total_time > 0:
                    f.write(f" ({successful_time/total_time*100:.1f}% of time)")
                f.write("\n")
                
                f.write(f"- ❌ **Failed**: {len(failed_actions)} actions, {failed_time:.1f}s total")
                if failed_actions:
                    f.write(f" ({failed_time/len(failed_actions):.1f}s avg)")
                if total_time > 0:
                    f.write(f" ({failed_time/total_time*100:.1f}% of time)")
                f.write("\n\n")
                
                # Action type distribution by status
                def get_action_type_stats(actions):
                    type_counts = {}
                    for action in actions:
                        action_type = self._extract_action_type(action.action)
                        type_counts[action_type] = type_counts.get(action_type, 0) + 1
                    return type_counts
                
                successful_types = get_action_type_stats(successful_actions)
                failed_types = get_action_type_stats(failed_actions)
                
                if successful_types:
                    f.write("**✅ Successful Action Types:**\n\n")
                    for action_type, count in sorted(successful_types.items(), key=lambda x: x[1], reverse=True):
                        f.write(f"- `{action_type}`: {count}\n")
                    f.write("\n")
                
                if failed_types:
                    f.write("**❌ Failed Action Types:**\n\n")
                    for action_type, count in sorted(failed_types.items(), key=lambda x: x[1], reverse=True):
                        f.write(f"- `{action_type}`: {count}\n")
                    f.write("\n")


                # Skip detailed actions when simplified_for_split is True
                if detailed and not simplified_for_split:
                    f.write("#### ⚡ Actions Details\n\n")
                    # Detailed action list
                    f.write("| Step | Action | Time | Status | Details |\n")
                    f.write("|------|--------|------|--------|----------|\n")
                    for action in result.actions:
                        status_icon = "✅" if action.success else "❌"
                        details = action.error if action.error else f"Output: {action.observation_length} chars"
                        f.write(f"| {action.step} | `{truncate_text(action.action, 100, no_warning=True, single_line=True)}` | {action.execution_time:.1f}s | {status_icon} | {details} |\n")
                    f.write("\n")
                
                # Results section - skip when simplified_for_split is True
                if include_patches and not simplified_for_split:
                    if self._has_meaningful_patch(result.resulting_patch):
                        f.write("#### 📝 Generated Patch\n\n")
                        f.write(format_patch(result.resulting_patch, max_lines=20 if not detailed else -1))
                        f.write("\n\n")
                    else:
                        f.write("#### 📄 No Meaningful Patch Generated\n\n")
                                
                if i < len(results):
                    f.write("---\n\n")
        
            # LLM Analysis section (placeholder for judge to fill)
            f.write("### 🤖 LLM Judge Analysis \n\n")
            f.write("**Result and metric comparison:** *[To be filled by LLM judge]*\n\n")
            f.write("**Assessment of MCP usage impact:** *[To be filled by LLM judge]*\n\n")
            f.write("**Conclusions:** *[To be filled by LLM judge]*\n")

        print(f"Exported {len(results)} trajectory analyses to {output_path}")
    
    def _get_current_timestamp(self) -> str:
        """Get current timestamp as ISO string"""
        import datetime
        return datetime.datetime.now().isoformat()
    
    def export_to_markdown_split(self, results: List[TrajectoryAnalysis], output_dir: Path,
                                detailed: bool = False, include_patches: bool = True):
        """Export each trajectory analysis to separate markdown files in specified directory"""
        import os
        
        # Create output directory if it doesn't exist
        output_dir.mkdir(parents=True, exist_ok=True)
        
        def escape_markdown(text: str) -> str:
            """Escape special markdown characters in text"""
            if not text:
                return ""
            return text.replace('|', '\\|').replace('\n', '\n\n').strip()
            
        def truncate_text(text: str, max_length: int = 500, no_warning: bool = False, single_line: bool = False) -> str:
            """Truncate text for summary view"""
            if not text or len(text) <= max_length:
                return_text = text
            else:
                return_text = text[:max_length] + "..." if no_warning else text[:max_length] + "...\n*[Text truncated for summary]*"

            if return_text:
                if single_line:
                    return_text = return_text.replace("\n", "\\n")
                else:
                    return_text = return_text.replace("\\n", "")
                
            return return_text
        
        def format_patch(patch: str, max_lines: int = -1) -> str:
            """Format patch for markdown with truncation if needed"""
            if not patch or patch.strip() in ["No patch found", "No patch", "no patch"]:
                return "*No meaningful patch generated*"

            if max_lines == -1:
                return f"```diff\n{patch}\n```"

            # Split patch into blocks at each "diff --git" boundary
            lines = patch.split('\n')
            blocks: list[list[str]] = []
            current_block: list[str] = []

            for line in lines:
                if line.startswith('diff --git') and current_block:
                    blocks.append(current_block)
                    current_block = [line]
                else:
                    current_block.append(line)

            if current_block:
                blocks.append(current_block)

            # Truncate each block independently
            any_truncated = False
            result_lines: list[str] = []

            for block in blocks:
                if len(block) > max_lines:
                    result_lines.extend(block[:max_lines])
                    result_lines.append(f'# ... [block truncated – showing first {max_lines} lines]')
                    any_truncated = True
                else:
                    result_lines.extend(block)

            result_patch = '\n'.join(result_lines)
            suffix = (
                "\n\n*[One or more diff blocks truncated"
                f" – showing first {max_lines} lines per block]*"
                if any_truncated else ""
            )
            return f"```diff\n{result_patch}\n```{suffix}"

        for result in results:
            # Create filename from trajectory ID (sanitize for filesystem)
            safe_trajectory_id = "".join(c for c in result.trajectory_id if c.isalnum() or c in "._-")
            
            # When in detailed mode, organize by task hash
            if detailed:
                # Get task grouping key and create task hash
                task_key = self._create_task_grouping_key(result)
                normalized_task, model, config = task_key
                task_hash = self._create_task_hash(normalized_task)
                
                # Create subdirectory for this task hash
                task_dir = output_dir / task_hash
                task_dir.mkdir(parents=True, exist_ok=True)
                
                output_file = task_dir / f"{safe_trajectory_id}.md"
            else:
                output_file = output_dir / f"{safe_trajectory_id}.md"
            
            with open(output_file, 'w', encoding='utf-8') as f:
                # Write individual trajectory analysis
                f.write(f"# Trajectory Analysis: `{result.trajectory_id}`\n\n")
                f.write(f"**Generated:** {self._get_current_timestamp()}\n")
                f.write(f"**Path:** {result.file_path}\n")
                f.write(f"**Date:** {result.date}\n\n")

                # Status badges using emoji
                status_emoji = "✅" if result.success else "❌"
                mcp_emoji = "🔌" if result.with_mcp else "⚫"
                patch_emoji = "📝" if self._has_meaningful_patch(result.resulting_patch) else "📄"
                
                f.write(f"{status_emoji} **Status:** {result.exit_status} ")
                f.write(f"| {mcp_emoji} **MCP:** {'Available' if result.with_mcp else 'Not Available'} ")
                f.write(f"| {patch_emoji} **Patch:** {'Generated' if self._has_meaningful_patch(result.resulting_patch) else 'Empty'}\n\n")
                
                # Key metrics table
                f.write("## 📈 Key Metrics\n\n")
                f.write("| Metric | Value |\n")
                f.write("|--------|-------|\n")
                f.write(f"| Model | {result.model} |\n")
                f.write(f"| Success Ratio | {result.success_ratio:.1%} ({sum(1 for a in result.actions if a.success)}/{len(result.actions)} actions) |\n")
                f.write(f"| Execution Time | {result.total_execution_time:.1f} seconds |\n")
                f.write(f"| Cost | ${result.model_stats.instance_cost:.2f} |\n")
                f.write(f"| Tokens | {result.model_stats.tokens_sent:,} sent → {result.model_stats.tokens_received:,} received |\n")
                f.write(f"| MCP Usage | {result.mcp_usage:.1%} of actions |\n")
                f.write(f"| Date | {result.date.split('T')[0] if 'T' in result.date else result.date} |\n\n")
                
                # MCP Context (if applicable)
                if result.mcp_context:
                    f.write("## 🔌 MCP Context\n\n")
                    f.write(f"> {escape_markdown(result.mcp_context)}\n\n")
                
                # Problem statement
                f.write("## 🎯 Problem Statement\n\n")
                problem_text = truncate_text(result.problem_statement, single_line = False) if not detailed else result.problem_statement.replace("\\n\\n","\n").replace("\\n","")
                f.write(f"```text\n{escape_markdown(problem_text)}\n```\n\n")
                
                # Action summary
                f.write("## ⚡ Actions Summary\n\n")
                
                # Time statistics grouped by status
                successful_actions = [a for a in result.actions if a.success]
                failed_actions = [a for a in result.actions if not a.success]
                
                successful_time = sum(a.execution_time for a in successful_actions)
                failed_time = sum(a.execution_time for a in failed_actions)
                total_time = successful_time + failed_time
                
                f.write("**Execution Time by Status:**\n\n")
                f.write(f"- ✅ **Successful**: {len(successful_actions)} actions, {successful_time:.1f}s total")
                if successful_actions:
                    f.write(f" ({successful_time/len(successful_actions):.1f}s avg)")
                if total_time > 0:
                    f.write(f" ({successful_time/total_time*100:.1f}% of time)")
                f.write("\n")
                
                f.write(f"- ❌ **Failed**: {len(failed_actions)} actions, {failed_time:.1f}s total")
                if failed_actions:
                    f.write(f" ({failed_time/len(failed_actions):.1f}s avg)")
                if total_time > 0:
                    f.write(f" ({failed_time/total_time*100:.1f}% of time)")
                f.write("\n\n")
                
                # Action type distribution by status
                def get_action_type_stats(actions):
                    type_counts = {}
                    for action in actions:
                        action_type = self._extract_action_type(action.action)
                        type_counts[action_type] = type_counts.get(action_type, 0) + 1
                    return type_counts
                
                successful_types = get_action_type_stats(successful_actions)
                failed_types = get_action_type_stats(failed_actions)
                
                if successful_types:
                    f.write("**✅ Successful Action Types:**\n\n")
                    for action_type, count in sorted(successful_types.items(), key=lambda x: x[1], reverse=True):
                        f.write(f"- `{action_type}`: {count}\n")
                    f.write("\n")
                
                if failed_types:
                    f.write("**❌ Failed Action Types:**\n\n")
                    for action_type, count in sorted(failed_types.items(), key=lambda x: x[1], reverse=True):
                        f.write(f"- `{action_type}`: {count}\n")
                    f.write("\n")

                if detailed:
                    f.write("## ⚡ Actions Details\n\n")
                    # Detailed action list
                    f.write("| Step | Action | Time | Status | Details |\n")
                    f.write("|------|--------|------|--------|----------|\n")
                    for action in result.actions:
                        status_icon = "✅" if action.success else "❌"
                        details = action.error if action.error else f"Output: {action.observation_length} chars"
                        f.write(f"| {action.step} | `{truncate_text(action.action, 100, no_warning=True, single_line=True)}` | {action.execution_time:.1f}s | {status_icon} | {details} |\n")
                    f.write("\n")
                
                # Results section
                if include_patches and self._has_meaningful_patch(result.resulting_patch):
                    f.write("## 📝 Generated Patch\n\n")
                    f.write(format_patch(result.resulting_patch, max_lines=20 if not detailed else -1))
                    f.write("\n\n")
                elif include_patches:
                    f.write("## 📄 No Meaningful Patch Generated\n\n")

        print(f"Exported {len(results)} individual trajectory analyses to directory: {output_dir}")
    
    def _export_grouped_analysis(self, f, results: List[TrajectoryAnalysis], detailed: bool, include_patches: bool, simplified_for_split: bool):
        """Export grouped analysis showing MCP vs non-MCP comparison for each task"""
        grouped = self.group_trajectories_by_task(results)
        
        # Overall summary statistics
        total_results = len(results)
        successful = sum(1 for r in results if r.success)
        with_mcp = sum(1 for r in results if r.with_mcp)
        used_mcp = sum(1 for r in results if r.mcp_usage > 0)
        
        f.write("## 📊 Executive Summary\n\n")
        f.write(f"- **Total Trajectories:** {total_results}\n")
        f.write(f"- **Unique Tasks:** {len(grouped)}\n")
        f.write(f"- **Overall Success Rate:** {successful/total_results*100:.1f}%\n")
        f.write(f"- **MCP Available:** {with_mcp} trajectories ({with_mcp/total_results*100:.1f}%)\n")
        f.write(f"- **Actually Used MCP:** {used_mcp} trajectories ({used_mcp/total_results*100:.1f}%)\n\n")
        
        f.write("---\n\n")
        
        # Individual task group analyses
        f.write("## 📋 Task-by-Task Analysis\n\n")
        
        for i, (task_key, task_results) in enumerate(grouped.items(), 1):
            normalized_task, model, config = task_key
            with_mcp_results = task_results["with_mcp"]
            without_mcp_results = task_results["without_mcp"]
            
            # Create short hash for this task
            task_hash = self._create_task_hash(normalized_task)
            
            f.write(f"### {i}. Task Group: {task_hash} + {model} + {config}\n\n")
            
            # Task description
            f.write("#### 🎯 Task Description\n\n")
            f.write(f"```text\n{normalized_task}...\n```\n\n")
            
            # Comparison table
            f.write("#### 📊 MCP Impact Comparison\n\n")
            
            self._write_comparison_table(f, with_mcp_results, without_mcp_results)
            
            # Always include trajectory details within each task group
            all_task_results = with_mcp_results + without_mcp_results
            if all_task_results:
                f.write(f"#### 📋 Trajectory Details\n\n")
                
                for j, result in enumerate(all_task_results, 1):
                    self._write_detailed_trajectory(f, result, j, detailed, include_patches, simplified_for_split)
            
            f.write("---\n\n")
        
        # LLM Analysis section
        f.write("## 🤖 LLM Judge Analysis\n\n")
        f.write("**Task-specific MCP impact assessment:** *[To be filled by LLM judge]*\n\n")
        f.write("**Cross-task performance patterns:** *[To be filled by LLM judge]*\n\n")
        f.write("**Conclusions and recommendations:** *[To be filled by LLM judge]*\n")
    
    def _write_comparison_table(self, f, with_mcp_results: List[TrajectoryAnalysis], without_mcp_results: List[TrajectoryAnalysis]):
        """Write comparison table for MCP vs non-MCP results"""
        def calculate_metrics(results: List[TrajectoryAnalysis]):
            if not results:
                return {
                    'count': 0, 'success_rate': 0, 'avg_success_ratio': 0, 'avg_time': 0, 
                    'avg_cost': 0, 'avg_actions': 0, 'patch_rate': 0, 'avg_mcp_usage': 0
                }
            
            return {
                'count': len(results),
                'success_rate': sum(1 for r in results if r.success) / len(results) * 100,
                'avg_success_ratio': sum(r.success_ratio for r in results) / len(results) * 100,
                'avg_time': sum(r.total_execution_time for r in results) / len(results),
                'avg_cost': sum(r.model_stats.instance_cost for r in results) / len(results),
                'avg_actions': sum(len(r.actions) for r in results) / len(results),
                'patch_rate': sum(1 for r in results if self._has_meaningful_patch(r.resulting_patch)) / len(results) * 100,
                'avg_mcp_usage': sum(r.mcp_usage for r in results) / len(results) * 100
            }
        
        mcp_metrics = calculate_metrics(with_mcp_results)
        no_mcp_metrics = calculate_metrics(without_mcp_results)
        
        f.write("| Metric | With MCP | Without MCP | Difference |\n")
        f.write("|--------|----------|-------------|------------|\n")
        f.write(f"| Trajectories | {mcp_metrics['count']} | {no_mcp_metrics['count']} | - |\n")
        
        if mcp_metrics['count'] > 0 or no_mcp_metrics['count'] > 0:
            success_diff = mcp_metrics['success_rate'] - no_mcp_metrics['success_rate']
            success_arrow = "🔺" if success_diff > 5 else "🔻" if success_diff < -5 else "➡️"
            f.write(f"| Success Rate | {mcp_metrics['success_rate']:.1f}% | {no_mcp_metrics['success_rate']:.1f}% | {success_arrow} {success_diff:+.1f}% |\n")
            
            ratio_diff = mcp_metrics['avg_success_ratio'] - no_mcp_metrics['avg_success_ratio']
            ratio_arrow = "🔺" if ratio_diff > 5 else "🔻" if ratio_diff < -5 else "➡️"
            f.write(f"| Avg Success Ratio | {mcp_metrics['avg_success_ratio']:.1f}% | {no_mcp_metrics['avg_success_ratio']:.1f}% | {ratio_arrow} {ratio_diff:+.1f}% |\n")
            
            time_diff = mcp_metrics['avg_time'] - no_mcp_metrics['avg_time']
            time_arrow = "🔻" if time_diff > 30 else "🔺" if time_diff < -30 else "➡️"
            f.write(f"| Avg Execution Time | {mcp_metrics['avg_time']:.0f}s | {no_mcp_metrics['avg_time']:.0f}s | {time_arrow} {time_diff:+.0f}s |\n")
            
            cost_diff = mcp_metrics['avg_cost'] - no_mcp_metrics['avg_cost']
            cost_arrow = "🔻" if cost_diff > 0.5 else "🔺" if cost_diff < -0.5 else "➡️"
            f.write(f"| Avg Cost | ${mcp_metrics['avg_cost']:.2f} | ${no_mcp_metrics['avg_cost']:.2f} | {cost_arrow} ${cost_diff:+.2f} |\n")
            
            actions_diff = mcp_metrics['avg_actions'] - no_mcp_metrics['avg_actions']
            actions_arrow = "🔻" if actions_diff > 10 else "🔺" if actions_diff < -10 else "➡️"
            f.write(f"| Avg Actions | {mcp_metrics['avg_actions']:.1f} | {no_mcp_metrics['avg_actions']:.1f} | {actions_arrow} {actions_diff:+.1f} |\n")
            
            patch_diff = mcp_metrics['patch_rate'] - no_mcp_metrics['patch_rate']
            patch_arrow = "🔺" if patch_diff > 10 else "🔻" if patch_diff < -10 else "➡️"
            f.write(f"| Patch Generation Rate | {mcp_metrics['patch_rate']:.1f}% | {no_mcp_metrics['patch_rate']:.1f}% | {patch_arrow} {patch_diff:+.1f}% |\n")
            
            if mcp_metrics['count'] > 0:
                f.write(f"| MCP Usage Rate | {mcp_metrics['avg_mcp_usage']:.1f}% | 0.0% | +{mcp_metrics['avg_mcp_usage']:.1f}% |\n")
        
        f.write("\n")
    
    def _write_trajectory_summary(self, f, result: TrajectoryAnalysis):
        """Write brief trajectory summary for detailed view"""
        success_emoji = "✅" if result.success else "❌"
        patch_emoji = "📝" if self._has_meaningful_patch(result.resulting_patch) else "📄"
        
        f.write(f"**{result.trajectory_id}** {success_emoji} | {patch_emoji} | ")
        f.write(f"{result.success_ratio:.0%} success | {result.total_execution_time:.0f}s | ")
        f.write(f"${result.model_stats.instance_cost:.2f}\n\n")
    
    def _write_detailed_trajectory(self, f, result: TrajectoryAnalysis, index: int, detailed: bool, include_patches: bool, simplified_for_split: bool):
        """Write detailed trajectory information within task groups"""
        f.write(f"##### {index}. Trajectory: `{result.trajectory_id}`\n\n")
        
        # Status badges using emoji
        status_emoji = "✅" if result.success else "❌"
        mcp_emoji = "🔌" if result.with_mcp else "⚫"
        patch_emoji = "📝" if self._has_meaningful_patch(result.resulting_patch) else "📄"
        cli_emoji = "🖥️" if result.mcp_cli_mode else ""
        
        # Enhanced exit status display
        exit_status_display = result.exit_status
        if result.exit_status_type == "auto_format_errors":
            exit_status_display += " ⚠️ (format errors)"
        elif result.exit_status_type == "auto_other":
            exit_status_display += " 🤖 (auto)"
        elif result.exit_status_type == "manual_submission":
            exit_status_display += " ✋ (manual)"
        
        f.write(f"{status_emoji} **Status:** {exit_status_display} ")
        f.write(f"| {mcp_emoji} **MCP:** {'Available' if result.with_mcp else 'Not Available'} ")
        if result.mcp_cli_mode:
            f.write(f"{cli_emoji} (CLI) ")
        f.write(f"| {patch_emoji} **Patch:** {'Generated' if self._has_meaningful_patch(result.resulting_patch) else 'Empty'}\n\n")
        
        # Key metrics table
        f.write("**📈 Metrics:** ")
        f.write(f"{result.success_ratio:.1%} success ({sum(1 for a in result.actions if a.success)}/{len(result.actions)} actions) | ")
        f.write(f"{result.total_execution_time:.1f}s | ${result.model_stats.instance_cost:.2f} | ")
        f.write(f"{result.mcp_usage:.1%} MCP usage\n\n")
        
        # Action summary
        f.write("**⚡ Action Summary:** ")
        successful_actions = [a for a in result.actions if a.success]
        failed_actions = [a for a in result.actions if not a.success]
        
        f.write(f"✅ {len(successful_actions)} successful, ❌ {len(failed_actions)} failed")
        if result.actions:
            f.write(f" | Avg time: {sum(a.execution_time for a in result.actions)/len(result.actions):.1f}s")
        f.write("\n\n")
        
        # Truncated patch if meaningful and includes patches
        if include_patches and self._has_meaningful_patch(result.resulting_patch):
            f.write("**📝 Patch Preview:**\n\n")
            # Use the format_patch method to show file-by-file previews
            f.write(self._format_patch_for_preview(result.resulting_patch, max_lines=8))  # 8 lines per file block
            f.write("\n")
        
        # Reference to detailed split file if split mode
        if simplified_for_split:
            safe_id = "".join(c for c in result.trajectory_id if c.isalnum() or c in "._-")
            f.write(f"\n**📄 Detailed Analysis:** See `{safe_id}.md`\n")
        
        f.write("\n")
    
    def _create_task_hash(self, normalized_task: str) -> str:
        """Create a short hash identifier for a task"""
        if not normalized_task:
            return "unknown"
        # Create MD5 hash and take first 6 characters for readability
        hash_object = hashlib.md5(normalized_task.encode())
        return hash_object.hexdigest()[:6]
    
    def _format_patch_for_preview(self, patch: str, max_lines: int = 8) -> str:
        """Format patch for preview with per-file truncation"""
        if not patch or patch.strip() in ["No patch found", "No patch", "no patch"]:
            return "*No meaningful patch generated*"

        # Split patch into blocks at each "diff --git" boundary
        lines = patch.split('\n')
        blocks: list[list[str]] = []
        current_block: list[str] = []

        for line in lines:
            if line.startswith('diff --git') and current_block:
                blocks.append(current_block)
                current_block = [line]
            else:
                current_block.append(line)

        if current_block:
            blocks.append(current_block)

        # Truncate each block independently
        any_truncated = False
        result_lines: list[str] = []

        for block in blocks:
            if len(block) > max_lines:
                result_lines.extend(block[:max_lines])
                result_lines.append(f'# ... [block truncated – showing first {max_lines} lines]')
                any_truncated = True
            else:
                result_lines.extend(block)

        result_patch = '\n'.join(result_lines)
        suffix = (
            "\n\n*[One or more diff blocks truncated"
            f" – showing first {max_lines} lines per block]*"
            if any_truncated else ""
        )
        return f"```diff\n{result_patch}\n```{suffix}"
    
    def _write_overall_mcp_analysis(self, f, grouped):
        """Write overall analysis of MCP impact across all tasks"""
        total_tasks = len(grouped)
        tasks_with_mcp_comparison = sum(1 for task_results in grouped.values() 
                                      if task_results["with_mcp"] and task_results["without_mcp"])
        
        f.write(f"- **Tasks analyzed:** {total_tasks}\n")
        f.write(f"- **Tasks with MCP comparison data:** {tasks_with_mcp_comparison}\n\n")
        
        if tasks_with_mcp_comparison > 0:
            f.write("### Cross-Task MCP Impact Patterns\n\n")
            
            # Analyze patterns across tasks
            mcp_wins = 0
            no_mcp_wins = 0
            ties = 0
            
            for task_results in grouped.values():
                if task_results["with_mcp"] and task_results["without_mcp"]:
                    mcp_success = sum(1 for r in task_results["with_mcp"] if r.success) / len(task_results["with_mcp"])
                    no_mcp_success = sum(1 for r in task_results["without_mcp"] if r.success) / len(task_results["without_mcp"])
                    
                    if mcp_success > no_mcp_success + 0.1:  # 10% threshold
                        mcp_wins += 1
                    elif no_mcp_success > mcp_success + 0.1:
                        no_mcp_wins += 1
                    else:
                        ties += 1
            
            f.write(f"- **Tasks where MCP performed better:** {mcp_wins}\n")
            f.write(f"- **Tasks where non-MCP performed better:** {no_mcp_wins}\n")
            f.write(f"- **Tasks with similar performance:** {ties}\n\n")
        else:
            f.write("*No tasks have both MCP and non-MCP trajectories for comparison.*\n\n")
    
    def print_summary(self, results: List[TrajectoryAnalysis]):
        """Print a summary of the analysis"""
        if not results:
            print("No results to summarize")
            return
        
        total_results = len(results)
        successful = sum(1 for r in results if r.success)
        submitted = sum(1 for r in results if r.exit_status.startswith('submitted'))
        
        # Exit status breakdown
        manual_submissions = sum(1 for r in results if r.exit_status_type == 'manual_submission')
        auto_format_errors = sum(1 for r in results if r.exit_status_type == 'auto_format_errors')
        auto_other = sum(1 for r in results if r.exit_status_type == 'auto_other')
        
        with_patches = sum(1 for r in results if r.resulting_patch and len(r.resulting_patch.strip()) > 10)
        
        # Calculate average success ratio
        avg_success_ratio = sum(r.success_ratio for r in results) / total_results if total_results > 0 else 0.0
        high_success_ratio = sum(1 for r in results if r.success_ratio >= 0.8)
        
        # MCP usage statistics
        with_mcp = sum(1 for r in results if r.with_mcp)
        used_mcp = sum(1 for r in results if r.mcp_usage > 0)
        mcp_cli_mode = sum(1 for r in results if r.mcp_cli_mode)
        mcp_available_and_used = sum(1 for r in results if r.with_mcp and r.mcp_usage > 0)
        avg_mcp_usage = sum(r.mcp_usage for r in results) / total_results if total_results > 0 else 0.0
        
        total_cost = sum(r.model_stats.instance_cost for r in results)
        total_tokens_sent = sum(r.model_stats.tokens_sent for r in results)
        total_tokens_received = sum(r.model_stats.tokens_received for r in results)
        total_api_calls = sum(r.model_stats.api_calls for r in results)
        
        avg_execution_time = sum(r.total_execution_time for r in results) / total_results
        avg_actions = sum(len(r.actions) for r in results) / total_results
        
        print(f"\n=== TRAJECTORY ANALYSIS SUMMARY ===")
        print(f"Total trajectories analyzed: {total_results}")
        print(f"Successful trajectories (submitted + ≥70% action success, no format errors): {successful} ({successful/total_results*100:.1f}%)")
        print(f"Submitted trajectories: {submitted} ({submitted/total_results*100:.1f}%)")
        print(f"  └─ Manual submissions: {manual_submissions} ({manual_submissions/total_results*100:.1f}%)")
        print(f"  └─ Auto-submitted (format/syntax errors): {auto_format_errors} ({auto_format_errors/total_results*100:.1f}%)")
        print(f"  └─ Auto-submitted (other constraints): {auto_other} ({auto_other/total_results*100:.1f}%)")
        print(f"Trajectories with patches: {with_patches} ({with_patches/total_results*100:.1f}%)")
        print(f"High-quality trajectories (≥80% action success): {high_success_ratio} ({high_success_ratio/total_results*100:.1f}%)")
        print(f"Average action success ratio: {avg_success_ratio*100:.1f}%")
        print(f"\nMCP Usage Analysis:")
        print(f"  Trajectories with MCP available: {with_mcp} ({with_mcp/total_results*100:.1f}%)")
        print(f"  Trajectories that used MCP: {used_mcp} ({used_mcp/total_results*100:.1f}%)")
        print(f"  MCP via bash CLI wrappers: {mcp_cli_mode} ({mcp_cli_mode/total_results*100:.1f}%)")
        print(f"  MCP available and used: {mcp_available_and_used} ({mcp_available_and_used/total_results*100:.1f}%)")
        print(f"  Average MCP usage ratio: {avg_mcp_usage:.3f} ({avg_mcp_usage*100:.1f}% of actions)")
        if used_mcp > 0:
            avg_usage_among_users = sum(r.mcp_usage for r in results if r.mcp_usage > 0) / used_mcp
            print(f"  Average MCP usage among MCP users: {avg_usage_among_users:.3f} ({avg_usage_among_users*100:.1f}% of actions)")
        
        if mcp_cli_mode > 0 and auto_format_errors > 0:
            cli_with_errors = sum(1 for r in results if r.mcp_cli_mode and r.exit_status_type == 'auto_format_errors')
            if cli_with_errors > 0:
                print(f"  MCP CLI trajectories with format errors: {cli_with_errors}/{mcp_cli_mode} ({cli_with_errors/mcp_cli_mode*100:.1f}%)")

        print(f"\nCost Analysis:")
        print(f"  Total cost: ${total_cost:.2f}")
        print(f"  Average cost per trajectory: ${total_cost/total_results:.2f}")
        print(f"  Total tokens sent: {total_tokens_sent:,}")
        print(f"  Total tokens received: {total_tokens_received:,}")
        print(f"  Total API calls: {total_api_calls:,}")
        print(f"\nPerformance Analysis:")
        print(f"  Average execution time: {avg_execution_time:.2f}s")
        print(f"  Average actions per trajectory: {avg_actions:.1f}")
        
        # Analysis note about MCP CLI mode
        if mcp_cli_mode > 0:
            print(f"\n⚠️  MCP CLI Analysis Note:")
            print(f"  {mcp_cli_mode} trajectories used MCP via bash CLI wrappers (Princeton SWE-agent setup).")
            print(f"  This may explain higher execution times and format/syntax error rates due to:")
            print(f"    - Bash escaping complexity")
            print(f"    - Shell process overhead")  
            print(f"    - Increased fragility compared to native MCP integration")


def main():
    """Main function to run the trajectory analyzer"""
    parser = argparse.ArgumentParser(description="Analyze SWE-agent trajectory files")
    parser.add_argument("directory", help="Directory containing trajectory files")
    parser.add_argument("--pattern", default="**/*.traj", help="File pattern to match (default: **/*.traj)")
    parser.add_argument("--output-json", help="Output JSON file path")
    parser.add_argument("--output-csv", help="Output CSV file path")
    parser.add_argument("--output-markdown", help="Output Markdown file path (optimized for LLM analysis)")
    parser.add_argument("--markdown-split", action="store_true", 
                       help="Create separate markdown files for each trajectory in a directory named after the output markdown file")
    parser.add_argument("--markdown-detailed", action="store_true", 
                       help="Include detailed action sequences in markdown output")
    parser.add_argument("--markdown-no-patches", action="store_true",
                       help="Exclude patches from markdown output for shorter documents")
    parser.add_argument("--group-by-task", action="store_true", 
                       default=True,
                       help="Group trajectories by normalized task statement (default: True)")
    parser.add_argument("--no-group-by-task", action="store_true", 
                       help="Disable task grouping (traditional single-list output)")
    parser.add_argument("--verbose", action="store_true", help="Verbose output")
    parser.add_argument("--filter-submitted", action="store_true", 
                       help="Only include trajectories with exit_status='submitted'")
    parser.add_argument("--filter-non-empty-patch", action="store_true",
                       help="Only include trajectories with non-empty, meaningful patches")
    parser.add_argument("--filter-model", help="Only include trajectories using specified model name")
    parser.add_argument("--filter-statement", help="Only include trajectories with problem statements containing specified text")
    
    args = parser.parse_args()
    
    # Validation: --markdown-split requires --output-markdown
    if args.markdown_split and not args.output_markdown:
        print("Error: --markdown-split requires --output-markdown to be specified")
        return 1
    
    directory = Path(args.directory)
    if not directory.exists():
        print(f"Error: Directory {directory} does not exist")
        return 1
    
    analyzer = TrajectoryAnalyzer()
    results = analyzer.analyze_directory(directory, args.pattern, 
                                        filter_submitted=args.filter_submitted,
                                        filter_non_empty_patch=args.filter_non_empty_patch,
                                        filter_model=args.filter_model,
                                        filter_statement=args.filter_statement)
    
    if not results:
        print("No trajectory files successfully analyzed")
        return 1
    
    # Print summary
    analyzer.print_summary(results)
    
    # Export results if requested
    if args.output_json:
        analyzer.export_to_json(results, Path(args.output_json))
    
    if args.output_csv:
        analyzer.export_to_csv(results, Path(args.output_csv))
    
    if args.output_markdown:
        # Handle conflicting group arguments
        group_by_task = args.group_by_task and not args.no_group_by_task
        
        analyzer.export_to_markdown(
            results, 
            Path(args.output_markdown),
            detailed=args.markdown_detailed,
            include_patches=not args.markdown_no_patches,
            simplified_for_split=args.markdown_split,
            group_by_task=group_by_task
        )
    
    if args.markdown_split:
        # Use basename of output markdown file as directory name for split files
        output_markdown_path = Path(args.output_markdown)
        split_dir_name = output_markdown_path.stem  # filename without extension
        split_output_dir = output_markdown_path.parent / split_dir_name
        
        analyzer.export_to_markdown_split(
            results,
            split_output_dir,
            detailed=args.markdown_detailed,
            include_patches=not args.markdown_no_patches
        )
    
    # Print detailed results if verbose
    if args.verbose:
        print(f"\n=== DETAILED RESULTS ===")
        for result in results[:3]:  # Show first 3 for brevity
            print(f"\nTrajectory: {result.trajectory_id}")
            print(f"Success: {result.success}")
            print(f"Exit Status: {result.exit_status}")
            print(f"Problem Statement: {result.problem_statement[:200]}...")
            print(f"Model Stats: Cost=${result.model_stats.instance_cost:.2f}, "
                  f"Tokens={result.model_stats.tokens_sent}→{result.model_stats.tokens_received}, "
                  f"API calls={result.model_stats.api_calls}")
            print(f"Actions: {len(result.actions)} steps, {result.total_execution_time:.2f}s total")
            
            if result.resulting_patch and len(result.resulting_patch) > 10:
                print(f"Patch: {len(result.resulting_patch)} characters")
    
    return 0


if __name__ == "__main__":
    exit(main())