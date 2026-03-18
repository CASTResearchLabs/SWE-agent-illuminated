#!/bin/bash

# Universal SWE-agent Task Runner
# Executes SWE-agent tasks from YAML configuration files
# Usage: ./run_task.sh <config.yaml>

set -e

# Check if configuration file is provided
if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    echo "Usage: $0 <config.yaml> [--with-mcp]"
    echo ""
    echo "Example configuration structure:"
    echo "  target_repo: https://github.com/owner/repo"
    echo "  model: gpt-4o"
    echo "  config: config/adaptive_engineering.yaml"
    echo "  per_instance_cost_limit: 5.0  # Optional (default: 5.0)"
    echo "  per_instance_call_limit: 100  # Optional (default: 100)"
    echo "  max_input_tokens: 1000000      # Optional (default: 1000000)"
    echo "  max_output_tokens: 128000      # Optional (default: 128000)"
    echo "  completion_kwargs:  # Optional model parameters"
    echo "    temperature: 0.5"
    echo "    max_tokens: 4096"
    echo "  task: |"
    echo "    Your multi-line task description here..."
    echo ""
    echo "Options:"
    echo "  --with-mcp    Add MCP server identification text to task"
    echo ""
    exit 1
fi

CONFIG_FILE="$1"
WITH_MCP=false

# Check for --with-mcp argument
if [ $# -eq 2 ] && [ "$2" = "--with-mcp" ]; then
    WITH_MCP=true
elif [ $# -eq 2 ]; then
    echo "Error: Invalid argument '$2'. Use --with-mcp or no second argument"
    exit 1
fi

# Check if configuration file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Configuration file '$CONFIG_FILE' not found"
    exit 1
fi

# Check if yq is available for YAML parsing
if ! command -v yq &> /dev/null; then
    echo "Error: 'yq' command not found. Please install yq for YAML parsing:"
    echo "  # On Ubuntu/Debian:"
    echo "  sudo snap install yq"
    echo "  # On macOS:"
    echo "  brew install yq"
    echo "  # Or download from: https://github.com/mikefarah/yq/releases"
    exit 1
fi

# Parse YAML configuration
echo "📋 Parsing configuration from: $CONFIG_FILE"

TARGET_REPO=$(yq eval '.target_repo' "$CONFIG_FILE")
MODEL=$(yq eval '.model // "gpt-4o"' "$CONFIG_FILE")
SWE_CONFIG=$(yq eval '.config // "config/adaptive_engineering.yaml"' "$CONFIG_FILE")
TASK_TEXT=$(yq eval '.task' "$CONFIG_FILE")
DEPLOYMENT=$(yq eval '.deployment // "local"' "$CONFIG_FILE")
APPLICATION_NAME=$(yq eval '.application_name // ""' "$CONFIG_FILE")
COMPLETION_KWARGS=$(yq eval '.completion_kwargs // null' "$CONFIG_FILE")
PER_INSTANCE_COST_LIMIT=$(yq eval '.per_instance_cost_limit // 5.0' "$CONFIG_FILE")
PER_INSTANCE_CALL_LIMIT=$(yq eval '.per_instance_call_limit // 100' "$CONFIG_FILE")
MAX_INPUT_TOKENS=$(yq eval '.max_input_tokens // 1000000' "$CONFIG_FILE")
MAX_OUTPUT_TOKENS=$(yq eval '.max_output_tokens // 128000' "$CONFIG_FILE")

# Validate required fields
if [ "$TARGET_REPO" = "null" ] || [ -z "$TARGET_REPO" ]; then
    echo "Error: 'target_repo' is required in configuration file"
    exit 1
fi

if [ "$TASK_TEXT" = "null" ] || [ -z "$TASK_TEXT" ]; then
    echo "Error: 'task' is required in configuration file"
    exit 1
fi

if [ "$WITH_MCP" = true ] && ([ "$APPLICATION_NAME" = "null" ] || [ -z "$APPLICATION_NAME" ]); then
    echo "Error: 'application_name' is required in configuration file when --with-mcp is used"
    exit 1
fi

# Handle completion_kwargs for Gemini models
COMPLETION_KWARGS_ARG=""
if [ "$COMPLETION_KWARGS" != "null" ] && [ -n "$COMPLETION_KWARGS" ]; then
    # Use provided completion_kwargs 
    COMPLETION_KWARGS_JSON=$(echo "$COMPLETION_KWARGS" | yq eval -o=json '.')
    COMPLETION_KWARGS_ARG="--agent.model.completion_kwargs=$COMPLETION_KWARGS_JSON"
    echo "🔧 Using custom completion_kwargs for non-Gemini model"
fi

# Store original task text before MCP modification
ORIGINAL_TASK_TEXT="$TASK_TEXT"

# Add MCP server text if --with-mcp is provided
MCP_CONTEXT=""
if [ "$WITH_MCP" = true ]; then
    MCP_CONTEXT="(current code base is available as application ${APPLICATION_NAME} via imaging-structural MCP server)"
    TASK_TEXT="${MCP_CONTEXT}
${TASK_TEXT}"
fi

# Display configuration
echo "🎯 Configuration:"
echo "  Repository: $TARGET_REPO"
echo "  Model: $MODEL"
echo "  Config: $SWE_CONFIG"
echo "  Deployment: $DEPLOYMENT"
echo "  Per-instance cost limit: $PER_INSTANCE_COST_LIMIT"
echo "  Per-instance call limit: $PER_INSTANCE_CALL_LIMIT"
echo "  Max input tokens: $MAX_INPUT_TOKENS"
echo "  Max output tokens: $MAX_OUTPUT_TOKENS"
if [ "$WITH_MCP" = true ]; then
    echo "  MCP: Enabled"
    echo "  Application Name: $APPLICATION_NAME"
fi
if [ -n "$COMPLETION_KWARGS_ARG" ]; then
    echo "  Completion kwargs: $(echo "$COMPLETION_KWARGS_ARG" | sed 's/--agent.model.completion_kwargs=//')"
fi
echo ""
echo "📝 Task:"
echo "$TASK_TEXT" | sed 's/^/  /'
echo ""

# Confirm execution
read -p "🚀 Execute this SWE-agent task? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled by user"
    exit 0
fi

# Extract owner and repo from target_repo URL for cleanup
REPO_OWNER_REPO=$(echo "$TARGET_REPO" | sed 's|.*github.com/||' | sed 's|\.git$||')
REPO_OWNER=$(echo "$REPO_OWNER_REPO" | cut -d'/' -f1)
REPO_NAME=$(echo "$REPO_OWNER_REPO" | cut -d'/' -f2)
REPO_DIR="/${REPO_OWNER}__${REPO_NAME}"

# Check for directories to clean up
CLEANUP_NEEDED=false
CLEANUP_DIRS=""

if [ -d "/root/tools" ] && [ "$(ls -A /root/tools/ 2>/dev/null)" ]; then
    CLEANUP_NEEDED=true
    CLEANUP_DIRS="$CLEANUP_DIRS\n  • /root/tools/* subdirectories"
fi

if [ -d "$REPO_DIR" ]; then
    CLEANUP_NEEDED=true
    CLEANUP_DIRS="$CLEANUP_DIRS\n  • $REPO_DIR"
fi

# Perform cleanup if needed
if [ "$CLEANUP_NEEDED" = true ]; then
    echo "🧹 The following directories from previous runs were found:"
    echo -e "$CLEANUP_DIRS"
    echo ""
    read -p "Clean up these directories before starting? (Y/n): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Nn]$ ]]; then
        echo "⏭️  Skipping cleanup"
        echo ""
    else
        echo "🗑️  Cleaning up..."
        
        # Clean /root/tools/* subdirectories
        if [ -d "/root/tools" ]; then
            find /root/tools -mindepth 1 -maxdepth 1 -type d -exec rm -rf {} \; 2>/dev/null || true
            echo "  ✓ Cleaned /root/tools/* subdirectories"
        fi
        
        # Clean repo directory
        if [ -d "$REPO_DIR" ]; then
            rm -rf "$REPO_DIR" 2>/dev/null || true
            echo "  ✓ Removed $REPO_DIR"
        fi
        
        echo "✅ Cleanup completed"
        echo ""
    fi
fi

# Execute SWE-agent with parsed configuration
echo "⚡ Executing SWE-agent..."
echo ""

# Convert multiline task text to single line with \n for proper command line passing
TASK_TEXT_SINGLE_LINE=$(echo "$TASK_TEXT" | awk '{printf "%s\\n", $0}' | sed 's/\\n$//')

# Build sweagent command with optional completion_kwargs
CMD=(sweagent run \
    --config "$SWE_CONFIG" \
    --agent.model.name "$MODEL" \
    --agent.model.per_instance_cost_limit="$PER_INSTANCE_COST_LIMIT" \
    --agent.model.per_instance_call_limit="$PER_INSTANCE_CALL_LIMIT" \
    --agent.model.max_input_tokens="$MAX_INPUT_TOKENS" \
    --agent.model.max_output_tokens="$MAX_OUTPUT_TOKENS" \
    --env.repo.github_url="$TARGET_REPO" \
    --problem_statement.text="$TASK_TEXT_SINGLE_LINE" \
    --env.deployment.type="$DEPLOYMENT")

# Add completion_kwargs if present
if [ -n "$COMPLETION_KWARGS_ARG" ]; then
    CMD+=("$COMPLETION_KWARGS_ARG")
fi

# Display the final command for debugging
echo "🔧 Final command to be executed:"
echo ""
printf "  %s" "${CMD[0]}"
for arg in "${CMD[@]:1}"; do
    if [[ "$arg" == --* ]]; then
        printf " \\\\\n    %s" "$arg"
    else
        printf " \"%s\"" "$arg"
    fi
done
echo ""
echo ""

# Final confirmation with command visible
read -p "🚀 Execute the above command? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled by user"
    exit 0
fi

# Execute the command
echo "⚡ Starting execution..."
"${CMD[@]}"

echo ""
echo "✅ Task execution completed!"