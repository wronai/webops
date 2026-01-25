"""
Load testing script for NLP2CMD Voice Service
"""

from locust import HttpUser, task, between
import json
import base64


class VoiceServiceUser(HttpUser):
    """Simulated user for voice service load testing."""
    
    wait_time = between(1, 3)
    
    def on_start(self):
        """Called when a simulated user starts."""
        self.client.get("/health")
    
    @task(3)
    def get_voice_interface(self):
        """Get the voice interface page."""
        self.client.get("/")
    
    @task(5)
    def send_text_command(self):
        """Send a text command."""
        commands = [
            "list files in current directory",
            "show system processes", 
            "find files larger than 100MB",
            "check disk space usage",
            "show network connections",
            "list running services",
            "display system information",
            "find recently modified files"
        ]
        
        command = self.environment.parsed_options.command or commands[
            int(self.client.request_id) % len(commands)
        ]
        
        payload = {
            "text_command": command,
            "language": "pl",
            "execute": False  # Don't execute during load testing
        }
        
        with self.client.post(
            "/voice-command",
            json=payload,
            catch_response=True
        ) as response:
            if response.status_code == 200:
                data = response.json()
                if not data.get("success", False):
                    print(f"Command failed: {command} - {data.get('error', 'Unknown error')}")
    
    @task(1)
    def send_voice_command(self):
        """Send a voice command (simulated with audio data)."""
        # Simulate audio data (base64 encoded)
        fake_audio = base64.b64encode(b"fake_audio_data").decode()
        
        payload = {
            "audio_data": fake_audio,
            "language": "pl",
            "execute": False
        }
        
        self.client.post("/voice-command", json=payload)
    
    @task(1)
    def send_complex_command(self):
        """Send a more complex command."""
        complex_commands = [
            "find all python files larger than 1MB and modified in last 7 days",
            "show top 10 processes consuming most memory and sort by CPU usage",
            "create a backup of home directory excluding node_modules and .git folders",
            "monitor disk usage and alert if any partition is over 80% full"
        ]
        
        command = complex_commands[int(self.client.request_id) % len(complex_commands)]
        
        payload = {
            "text_command": command,
            "language": "pl",
            "execute": False
        }
        
        self.client.post("/voice-command", json=payload)


class WebsiteUser(HttpUser):
    """Simulated web user browsing the interface."""
    
    wait_time = between(2, 5)
    
    @task
    def index_page(self):
        """Browse the main page."""
        self.client.get("/")
    
    @task
    def health_check(self):
        """Check service health."""
        self.client.get("/health")


if __name__ == "__main__":
    # Run with: locust -f load_test.py --host=http://localhost:8000
    pass
