"""
Docker Integration Tests for WebOps Voice Service
"""

import pytest
import asyncio
import subprocess
import time
import requests
from pathlib import Path


class TestDockerIntegration:
    """Test Docker integration for WebOps voice service."""
    
    @pytest.fixture(scope="class")
    def docker_service(self):
        """Start Docker service for testing."""
        # Build and start service
        subprocess.run(["docker", "build", "-f", "Dockerfile.standalone", "-t", "webops-voice:test", "."], 
                      cwd="/home/tom/github/wronai/nlp2cmd/webops", check=True)
        
        container_id = subprocess.run(
            ["docker", "run", "-d", "--name", "webops-voice-test", 
             "-p", "8001:8000", "webops-voice:test"],
            capture_output=True, text=True, check=True
        ).stdout.strip()
        
        # Wait for service to be ready
        max_attempts = 30
        for i in range(max_attempts):
            try:
                response = requests.get("http://localhost:8001/health", timeout=5)
                if response.status_code == 200:
                    break
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
        
        yield container_id
        
        # Cleanup
        subprocess.run(["docker", "stop", "webops-voice-test"], check=False)
        subprocess.run(["docker", "rm", "webops-voice-test"], check=False)
    
    def test_docker_health_check(self, docker_service):
        """Test Docker service health check."""
        response = requests.get("http://localhost:8001/health")
        assert response.status_code == 200
        
        data = response.json()
        assert data["status"] == "healthy"
        assert data["service"] == "nlp2cmd-webops-voice"
    
    def test_docker_web_interface(self, docker_service):
        """Test web interface in Docker."""
        response = requests.get("http://localhost:8001/")
        assert response.status_code == 200
        assert "WebOps Voice Service" in response.text
        assert "operations" in response.text.lower()
    
    def test_docker_voice_command(self, docker_service):
        """Test voice command processing in Docker."""
        command_data = {
            "text_command": "echo 'Docker test'",
            "language": "pl",
            "execute": True
        }
        
        response = requests.post("http://localhost:8001/voice-command", json=command_data)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert data["command"] is not None
        assert data["execution_result"] is not None
        assert "Docker test" in data["execution_result"]["stdout"]
    
    def test_docker_operations_commands(self, docker_service):
        """Test operations-specific commands in Docker."""
        operations_commands = [
            "list files in current directory",
            "show system processes",
            "check disk space usage"
        ]
        
        for command in operations_commands:
            command_data = {
                "text_command": command,
                "language": "pl",
                "execute": True
            }
            
            response = requests.post("http://localhost:8001/voice-command", json=command_data)
            assert response.status_code == 200
            
            data = response.json()
            assert data["success"] is True
            assert data["execution_result"] is not None
            assert data["logs"] is not None
    
    def test_docker_shell_execution(self, docker_service):
        """Test shell command execution in Docker container."""
        # Test various shell operations
        shell_commands = [
            ("pwd", "current directory"),
            ("whoami", "current user"),
            ("date", "current date"),
            ("uname -a", "system information")
        ]
        
        for command, description in shell_commands:
            command_data = {
                "text_command": command,
                "language": "pl",
                "execute": True
            }
            
            response = requests.post("http://localhost:8001/voice-command", json=command_data)
            assert response.status_code == 200
            
            data = response.json()
            assert data["success"] is True
            assert data["execution_result"]["exit_code"] == 0
            print(f"✅ {description}: {command}")
    
    def test_docker_file_operations(self, docker_service):
        """Test file operations in Docker."""
        # Create test file
        create_command = {
            "text_command": "echo 'Docker test file' > /tmp/test.txt",
            "language": "pl",
            "execute": True
        }
        
        response = requests.post("http://localhost:8001/voice-command", json=create_command)
        assert response.status_code == 200
        assert response.json()["success"] is True
        
        # Read test file
        read_command = {
            "text_command": "cat /tmp/test.txt",
            "language": "pl",
            "execute": True
        }
        
        response = requests.post("http://localhost:8001/voice-command", json=read_command)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "Docker test file" in data["execution_result"]["stdout"]
        
        # Clean up
        cleanup_command = {
            "text_command": "rm /tmp/test.txt",
            "language": "pl",
            "execute": True
        }
        
        response = requests.post("http://localhost:8001/voice-command", json=cleanup_command)
        assert response.status_code == 200
    
    def test_docker_error_handling(self, docker_service):
        """Test error handling in Docker."""
        # Test invalid command
        error_command = {
            "text_command": "invalid_command_that_does_not_exist",
            "language": "pl",
            "execute": True
        }
        
        response = requests.post("http://localhost:8001/voice-command", json=error_command)
        assert response.status_code == 200
        
        data = response.json()
        # Should handle gracefully either with success (fallback) or proper error
        assert "success" in data
    
    def test_docker_concurrent_requests(self, docker_service):
        """Test concurrent requests in Docker."""
        import threading
        
        results = []
        errors = []
        
        def make_request():
            try:
                command_data = {
                    "text_command": "echo 'concurrent test'",
                    "language": "pl",
                    "execute": True
                }
                
                response = requests.post("http://localhost:8001/voice-command", json=command_data, timeout=10)
                results.append(response.status_code)
            except Exception as e:
                errors.append(str(e))
        
        # Make 5 concurrent requests
        threads = []
        for _ in range(5):
            thread = threading.Thread(target=make_request)
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        assert len(errors) == 0
        assert len(results) == 5
        assert all(status == 200 for status in results)
    
    def test_docker_resource_limits(self, docker_service):
        """Test resource limits in Docker."""
        # Test memory usage
        memory_command = {
            "text_command": "free -h",
            "language": "pl",
            "execute": True
        }
        
        response = requests.post("http://localhost:8001/voice-command", json=memory_command)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "Mem:" in data["execution_result"]["stdout"]
        
        # Test disk usage
        disk_command = {
            "text_command": "df -h",
            "language": "pl",
            "execute": True
        }
        
        response = requests.post("http://localhost:8001/voice-command", json=disk_command)
        assert response.status_code == 200
        
        data = response.json()
        assert data["success"] is True
        assert "Filesystem" in data["execution_result"]["stdout"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
