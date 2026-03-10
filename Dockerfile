FROM python:3.12

# Set the working directory
WORKDIR /app

RUN apt-get update && apt-get install -y \
    vim

# Install Docker CLI using the official Docker installation script
RUN curl -fsSL https://get.docker.com -o get-docker.sh && \
    sh get-docker.sh && \
    rm get-docker.sh

# Copy the application code
# Do this last to take advantage of the docker layer mechanism
COPY . /app

# Make doc_task.sh executable
RUN chmod +x /app/doc_task.sh

# Accept build argument for API key
ARG IMAGING_X_API_KEY=N/A

# Replace placeholder in config file with actual API key
RUN sed -i "s/<your Imaging API key here>/${IMAGING_X_API_KEY}/g" /app/config/default_with_mcp.yaml

# Install Python dependencies
RUN pip install -e '.'

CMD ["bash"]