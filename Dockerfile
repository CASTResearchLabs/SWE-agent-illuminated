FROM python:3.12

# Set the working directory
WORKDIR /app

RUN apt-get update && apt-get install -y \
    vim \
    curl \
    wget

# Install yq v4 (latest) from GitHub releases
# ARG GITHUB_TOKEN

# RUN YQ_VERSION=$(curl -s -H "Authorization: Bearer ${GITHUB_TOKEN}" https://api.github.com/repos/mikefarah/yq/releases/latest | grep -Po '"tag_name": "\K[^"]*') && \
#     wget https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 -O /usr/bin/yq && \
#     chmod +x /usr/bin/yq
RUN wget https://github.com/mikefarah/yq/releases/download/v4.52.4/yq_linux_amd64 -O /usr/bin/yq && \
    chmod +x /usr/bin/yq

# Install Docker CLI using the official Docker installation script
RUN curl -fsSL https://get.docker.com -o get-docker.sh && \
    sh get-docker.sh && \
    rm get-docker.sh

# Copy the application code
# Do this last to take advantage of the docker layer mechanism
COPY . /app

# Make task run scripts executable
RUN chmod +x /app/run_task.sh

# Accept build arguments for API key and MCP URL
ARG IMAGING_X_API_KEY=N/A
ARG IMAGING_MCP_URL=http://172.31.237.125:8282/mcp

# Replace placeholders in config file with actual values
RUN sed -i "s/<your Imaging API key here>/${IMAGING_X_API_KEY}/g" /app/config/adaptive_engineering.yaml && \
    sed -i "s|<your Imaging MCP URL here>|${IMAGING_MCP_URL}|g" /app/config/adaptive_engineering.yaml

# Install Python dependencies
RUN pip install -e '.'

CMD ["bash"]