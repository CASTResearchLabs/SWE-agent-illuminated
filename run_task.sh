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

# Add MCP server text if --with-mcp is provided
if [ "$WITH_MCP" = true ]; then
    TASK_TEXT="(current code base is available as application ${APPLICATION_NAME} via imaging-structural MCP server)
${TASK_TEXT}"
fi

# Display configuration
echo "🎯 Configuration:"
echo "  Repository: $TARGET_REPO"
echo "  Model: $MODEL"
echo "  Config: $SWE_CONFIG"
echo "  Deployment: $DEPLOYMENT"
if [ "$WITH_MCP" = true ]; then
    echo "  MCP: Enabled"
    echo "  Application Name: $APPLICATION_NAME"
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
    read -p "Clean up these directories before starting? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
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
    else
        echo "⏭️  Skipping cleanup"
        echo ""
    fi
fi

# Execute SWE-agent with parsed configuration
echo "⚡ Executing SWE-agent..."
echo ""

# Convert multiline task text to single line with \n for proper command line passing
TASK_TEXT_SINGLE_LINE=$(echo "$TASK_TEXT" | awk '{printf "%s\\n", $0}' | sed 's/\\n$//')

sweagent run \
    --config "$SWE_CONFIG" \
    --agent.model.name "$MODEL" \
    --env.repo.github_url="$TARGET_REPO" \
    --problem_statement.text="$TASK_TEXT_SINGLE_LINE" \
    --env.deployment.type="$DEPLOYMENT"

echo ""
echo "✅ Task execution completed!"