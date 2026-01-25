"""
Voice Service Tests
"""

import pytest
import asyncio
import json
from fastapi.testclient import TestClient
from unittest.mock import Mock, patch

try:
    from nlp2cmd.service.docker_app import app, VoiceServiceManager, VoiceCommandRequest
except ImportError:
    pytest.skip("Voice service dependencies not available", allow_module_level=True)


@pytest.fixture
def client():
    """Test client for voice service."""
    return TestClient(app)


@pytest.fixture
def voice_manager():
    """Voice service manager fixture."""
    return VoiceServiceManager()


class TestVoiceService:
    """Test voice service functionality."""
    
    def test_root_endpoint(self, client):
        """Test root endpoint returns HTML interface."""
        response = client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert "NLP2CMD Voice Service" in response.text
    
    def test_health_check(self, client):
        """Test health check endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "nlp2cmd-voice"
    
    def test_voice_command_text_only(self, client):
        """Test voice command with text input."""
        request_data = {
            "text_command": "list files",
            "language": "pl",
            "execute": False  # Don't actually execute in tests
        }
        
        with patch.object(VoiceServiceManager, 'process_voice_command') as mock_process:
            mock_process.return_value = asyncio.Future()
            mock_process.return_value.set_result({
                "success": True,
                "command": "ls -la",
                "explanation": "Generated command",
                "confidence": 0.95
            })
            
            response = client.post("/voice-command", json=request_data)
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["command"] == "ls -la"
    
    def test_voice_command_with_audio(self, client):
        """Test voice command with audio data."""
        request_data = {
            "audio_data": "base64-audio-data-placeholder",
            "language": "pl",
            "execute": False
        }
        
        with patch.object(VoiceServiceManager, 'process_voice_command') as mock_process:
            mock_process.return_value = asyncio.Future()
            mock_process.return_value.set_result({
                "success": True,
                "command": "echo test",
                "explanation": "Generated command",
                "confidence": 0.85
            })
            
            response = client.post("/voice-command", json=request_data)
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
    
    def test_voice_command_no_input(self, client):
        """Test voice command with no input."""
        request_data = {
            "language": "pl",
            "execute": False
        }
        
        response = client.post("/voice-command", json=request_data)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is False
        assert "No command provided" in data["error"]
    
    def test_voice_command_invalid_request(self, client):
        """Test voice command with invalid request."""
        request_data = {
            "text_command": "",  # Empty command
            "language": "invalid-lang",
            "execute": False
        }
        
        response = client.post("/voice-command", json=request_data)
        # Should handle gracefully
        assert response.status_code in [200, 422]


class TestVoiceServiceManager:
    """Test voice service manager."""
    
    @pytest.mark.asyncio
    async def test_process_text_command(self, voice_manager):
        """Test processing text command."""
        request = VoiceCommandRequest(
            text_command="list files",
            language="pl",
            execute=False
        )
        
        response = await voice_manager.process_voice_command(request)
        
        assert response.success is True
        assert response.command is not None
        assert "ls" in response.command.lower()
    
    @pytest.mark.asyncio
    async def test_process_command_with_execution(self, voice_manager):
        """Test processing command with execution."""
        request = VoiceCommandRequest(
            text_command="echo test",
            language="pl", 
            execute=True
        )
        
        response = await voice_manager.process_voice_command(request)
        
        assert response.success is True
        assert response.execution_result is not None
        assert response.logs is not None
    
    @pytest.mark.asyncio
    async def test_process_invalid_command(self, voice_manager):
        """Test processing invalid command."""
        request = VoiceCommandRequest(
            text_command="",  # Empty command
            language="pl",
            execute=False
        )
        
        response = await voice_manager.process_voice_command(request)
        
        assert response.success is False
        assert response.error is not None


class TestShellExecutor:
    """Test shell command executor."""
    
    @pytest.mark.asyncio
    async def test_simple_command(self):
        """Test simple command execution."""
        from nlp2cmd.service.docker_app import ShellExecutor
        
        executor = ShellExecutor()
        result = await executor.execute_command("echo 'test'")
        
        assert result["success"] is True
        assert result["exit_code"] == 0
        assert "test" in result["stdout"]
        assert len(result["logs"]) > 0
    
    @pytest.mark.asyncio
    async def test_command_with_error(self):
        """Test command that produces error."""
        from nlp2cmd.service.docker_app import ShellExecutor
        
        executor = ShellExecutor()
        result = await executor.execute_command("exit 1")
        
        assert result["success"] is False
        assert result["exit_code"] == 1
    
    @pytest.mark.asyncio
    async def test_command_timeout(self):
        """Test command timeout handling."""
        from nlp2cmd.service.docker_app import ShellExecutor
        
        executor = ShellExecutor(max_execution_time=1)
        result = await executor.execute_command("sleep 5")
        
        assert result["success"] is False
        assert "timed out" in result["stderr"].lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
