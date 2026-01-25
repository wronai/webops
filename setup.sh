#!/bin/bash

# WebOps Voice Service Setup Script
# Sets up voice-controlled operations service with Docker

set -e

echo "🚀 Setting up NLP2CMD WebOps Voice Service..."

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose is not installed. Please install Docker Compose first."
    exit 1
fi

# Create necessary directories
echo "📁 Creating directories..."
mkdir -p logs workspace uploads nginx/ssl monitoring/{prometheus,grafana/{dashboards,datasources}}

# Build the Docker image
echo "🔨 Building WebOps Docker image..."
docker build -f Dockerfile.standalone -t webops-voice:latest .

# Start the service
echo "🚀 Starting WebOps voice service..."
if command -v docker-compose &> /dev/null; then
    docker-compose -f docker-compose.yml up -d
else
    docker compose -f docker-compose.yml up -d
fi

# Wait for service to be ready
echo "⏳ Waiting for service to be ready..."
sleep 15

# Check if service is running
if curl -f http://localhost:8000/health &> /dev/null; then
    echo "✅ WebOps voice service is running!"
    echo "🌐 Open your browser and go to: http://localhost:8000"
    echo "🎤 You can now use voice commands for operations!"
    echo ""
    echo "📊 Available commands:"
    echo "  📊 View logs:     docker logs -f webops-voice"
    echo "  🛑 Stop service:  docker-compose -f docker-compose.yml down"
    echo "  🔄 Restart:       docker-compose -f docker-compose.yml restart"
    echo "  🧹 Clean up:      docker-compose -f docker-compose.yml down -v"
    echo ""
    echo "🎯 Operations Commands Examples:"
    echo "  • 'list files in current directory'"
    echo "  • 'show system processes sorted by memory usage'"
    echo "  • 'find files larger than 100MB in /var/log'"
    echo "  • 'check disk space usage for all partitions'"
    echo "  • 'show network connections and listening ports'"
    echo "  • 'monitor CPU usage for top 5 processes'"
    echo "  • 'list all running services and their status'"
    echo ""
    echo "🔧 Advanced Options:"
    echo "  📈 Enable monitoring: docker-compose -f webops/docker-compose.yml --profile monitoring up -d"
    echo "  🌐 Enable production: docker-compose -f webops/docker-compose.yml --profile production up -d"
else
    echo "❌ Service failed to start. Check logs with:"
    echo "   docker logs webops-voice"
fi

echo ""
echo "🎯 WebOps Voice Service Setup Complete!"
echo "📖 Documentation: webops/VOICE_SERVICE.md"
