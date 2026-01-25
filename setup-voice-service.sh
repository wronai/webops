#!/bin/bash

# NLP2CMD Voice Service Setup Script
# This script sets up the voice service with Docker

set -e

echo "🚀 Setting up NLP2CMD Voice Service..."

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
mkdir -p logs uploads nginx/ssl

# Build the Docker image
echo "🔨 Building Docker image..."
docker build -f Dockerfile.voice -t nlp2cmd-voice:latest .

# Start the service
echo "🚀 Starting voice service..."
if command -v docker-compose &> /dev/null; then
    docker-compose -f docker-compose.voice.yml up -d
else
    docker compose -f docker-compose.voice.yml up -d
fi

# Wait for service to be ready
echo "⏳ Waiting for service to be ready..."
sleep 10

# Check if service is running
if curl -f http://localhost:8000/health &> /dev/null; then
    echo "✅ Voice service is running!"
    echo "🌐 Open your browser and go to: http://localhost:8000"
    echo "🎤 You can now use voice commands to control the system!"
else
    echo "❌ Service failed to start. Check logs with:"
    echo "   docker logs nlp2cmd-voice"
fi

echo ""
echo "📋 Available commands:"
echo "  📊 View logs:     docker logs -f nlp2cmd-voice"
echo "  🛑 Stop service:  docker-compose -f docker-compose.voice.yml down"
echo "  🔄 Restart:       docker-compose -f docker-compose.voice.yml restart"
echo "  🧹 Clean up:      docker-compose -f docker-compose.voice.yml down -v"
echo ""
echo "🎤 Voice Commands Examples:"
echo "  • 'list files in current directory'"
echo "  • 'show system processes'"
echo "  • 'find files larger than 100MB'"
echo "  • 'create a backup of home directory'"
echo "  • 'check disk space usage'"
