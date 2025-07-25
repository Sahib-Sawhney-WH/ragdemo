# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libwayland-client0 \
    libx11-6 \
    libx11-xcb1 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libxss1 \
    libxtst6 \
    lsb-release \
    xdg-utils \
    libu2f-udev \
    libvulkan1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright and browsers
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy the application code
COPY . .

# Copy RAG system files to the container
COPY exponenthr_scraper.py .
COPY content_discovery.py .
COPY change_detection.py .
COPY azure_search_integration.py .
COPY synchronization_service.py .
COPY rag_orchestrator.py .

# Copy Flask API service
COPY rag_api_service/ ./rag_api_service/

# Create necessary directories
RUN mkdir -p /app/logs /app/data

# Set environment variables
ENV PYTHONPATH=/app
ENV FLASK_APP=rag_api_service/src/main.py
ENV FLASK_ENV=production
ENV PYTHONUNBUFFERED=1

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

# Create startup script
RUN echo '#!/bin/bash\n\
set -e\n\
\n\
echo "Starting ExponentHR RAG Solution..."\n\
\n\
# Wait for dependencies to be ready\n\
sleep 10\n\
\n\
# Start the Flask application\n\
cd /app/rag_api_service\n\
python src/main.py\n\
' > /app/start.sh && chmod +x /app/start.sh

# Run the application
CMD ["/app/start.sh"]

