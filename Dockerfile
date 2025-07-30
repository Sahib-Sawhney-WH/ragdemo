# Use Python 3.11 slim image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
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
COPY rag_api_service/requirements.txt rag_api_service/

# Install Python dependencies (both main and Flask API requirements)
RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir -r rag_api_service/requirements.txt

# Install Playwright and browsers
RUN playwright install chromium
RUN playwright install-deps chromium

# Copy all application files
COPY . .

# Create necessary directories
RUN mkdir -p /app/logs /app/data
RUN mkdir -p /app/rag_api_service/src/database

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV FLASK_APP=rag_api_service/src/main.py
ENV FLASK_ENV=production

# Create a simple startup script
RUN echo '#!/bin/bash\ncd /app\npython rag_api_service/src/main.py' > /app/start.sh
RUN chmod +x /app/start.sh

# Expose port
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

# Use the startup script
CMD ["/app/start.sh"]