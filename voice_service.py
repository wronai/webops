"""
WebOps Voice Service - Docker-based voice-controlled command execution
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
    import uvicorn
except ImportError:
    FastAPI = None
    HTTPException = None
    BackgroundTasks = None
    WebSocket = None
    WebSocketDisconnect = None
    HTMLResponse = None
    JSONResponse = None
    CORSMiddleware = None
    StaticFiles = None
    BaseModel = object
    Field = lambda x, **kwargs: x
    uvicorn = None

# Import NLP2CMD components
try:
    from nlp2cmd.service import NLP2CMDService, ServiceConfig
    from nlp2cmd.generation.pipeline import RuleBasedPipeline
    NLP2CMD_AVAILABLE = True
except ImportError as e:
    print(f"Warning: NLP2CMD not available: {e}")
    NLP2CMD_AVAILABLE = False
    NLP2CMDService = None
    ServiceConfig = None
    RuleBasedPipeline = None


class VoiceCommandRequest(BaseModel):
    """Voice command request model."""
    audio_data: Optional[str] = None  # Base64 encoded audio
    text_command: Optional[str] = None  # Fallback text command
    language: str = "pl"  # Language code
    execute: bool = True  # Whether to execute the command


class VoiceCommandResponse(BaseModel):
    """Voice command response model."""
    success: bool
    command: Optional[str] = None
    explanation: Optional[str] = None
    confidence: Optional[float] = None
    execution_result: Optional[Dict[str, Any]] = None
    logs: Optional[List[str]] = None
    error: Optional[str] = None


class ShellExecutor:
    """Shell command executor with logging."""
    
    def __init__(self, max_execution_time: int = 30):
        self.max_execution_time = max_execution_time
        self.logger = logging.getLogger(__name__)
        
    async def execute_command(self, command: str, working_dir: str = "/app") -> Dict[str, Any]:
        """Execute shell command and return result with logs."""
        try:
            # Create a temporary log file
            with tempfile.NamedTemporaryFile(mode='w+', suffix='.log', delete=False) as log_file:
                log_path = log_file.name
            
            # Execute command with output redirection
            process = await asyncio.create_subprocess_shell(
                f"cd {working_dir} && {command} 2>&1 | tee {log_path}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                shell=True
            )
            
            # Wait for completion with timeout
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), 
                    timeout=self.max_execution_time
                )
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return {
                    "success": False,
                    "exit_code": -1,
                    "stdout": "",
                    "stderr": "Command execution timed out",
                    "logs": ["Command execution timed out"]
                }
            
            # Read logs from file
            logs = []
            try:
                with open(log_path, 'r') as f:
                    logs = f.read().splitlines()
            except Exception:
                pass
            finally:
                # Clean up log file
                try:
                    os.unlink(log_path)
                except Exception:
                    pass
            
            return {
                "success": process.returncode == 0,
                "exit_code": process.returncode,
                "stdout": stdout.decode('utf-8') if stdout else "",
                "stderr": stderr.decode('utf-8') if stderr else "",
                "logs": logs
            }
            
        except Exception as e:
            self.logger.error(f"Error executing command: {e}")
            return {
                "success": False,
                "exit_code": -1,
                "stdout": "",
                "stderr": str(e),
                "logs": [f"Error: {str(e)}"]
            }


class VoiceServiceManager:
    """Manages voice service connections and sessions."""
    
    def __init__(self):
        self.active_connections: List[WebSocket] = []
        self.executor = ShellExecutor()
        
        # Initialize NLP2CMD pipeline if available
        if NLP2CMD_AVAILABLE and RuleBasedPipeline is not None:
            try:
                self.pipeline = RuleBasedPipeline()
                print("✅ NLP2CMD RuleBasedPipeline initialized")
            except Exception as e:
                print(f"⚠️ Failed to initialize NLP2CMD pipeline: {e}")
                self.pipeline = self._create_mock_pipeline()
        else:
            print("⚠️ Using mock pipeline (NLP2CMD not available)")
            self.pipeline = self._create_mock_pipeline()
        
    def _create_mock_pipeline(self):
        """Create mock pipeline for testing without NLP2CMD."""
        class MockPipeline:
            def process(self, query):
                class MockResult:
                    def __init__(self, query):
                        self.success = True
                        self.command = self._generate_command(query)
                        self.confidence = 0.85
                        self.errors = []
                    
                    def _generate_command(self, query):
                        query_lower = query.lower()
                        if "list files" in query_lower:
                            return "ls -la"
                        elif "show processes" in query_lower:
                            return "ps aux"
                        elif "find files" in query_lower:
                            return "find . -type f"
                        elif "disk space" in query_lower:
                            return "df -h"
                        else:
                            return f"echo 'Generated command for: {query}'"
                
                return MockResult(query)
        
        return MockPipeline()
        
    async def connect(self, websocket: WebSocket):
        """Accept WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        
    def disconnect(self, websocket: WebSocket):
        """Remove WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            
    async def broadcast_log(self, log_message: str):
        """Broadcast log message to all connected clients."""
        if self.active_connections:
            message = json.dumps({"type": "log", "message": log_message})
            await asyncio.gather(
                *[connection.send_text(message) for connection in self.active_connections],
                return_exceptions=True
            )
    
    async def process_voice_command(self, request: VoiceCommandRequest) -> VoiceCommandResponse:
        """Process voice command and return response."""
        try:
            # Get command text (either from audio transcription or fallback text)
            command_text = request.text_command
            if not command_text and request.audio_data:
                # TODO: Implement speech-to-text here
                command_text = "list files"  # Placeholder
            
            if not command_text:
                return VoiceCommandResponse(
                    success=False,
                    error="No command provided"
                )
            
            # Process command with NLP2CMD
            result = self.pipeline.process(command_text)
            
            if not result.success:
                return VoiceCommandResponse(
                    success=False,
                    error="Failed to process command",
                    explanation=result.errors[0] if result.errors else "Unknown error"
                )
            
            response_data = {
                "success": True,
                "command": result.command,
                "explanation": f"Generated by RuleBasedPipeline with confidence {result.confidence:.2f}",
                "confidence": result.confidence,
            }
            
            # Execute command if requested
            if request.execute and result.command:
                await self.broadcast_log(f"Executing: {result.command}")
                execution_result = await self.executor.execute_command(result.command)
                response_data["execution_result"] = execution_result
                response_data["logs"] = execution_result["logs"]
                
                # Broadcast logs line by line
                for log_line in execution_result["logs"]:
                    await self.broadcast_log(log_line)
            
            return VoiceCommandResponse(**response_data)
            
        except Exception as e:
            return VoiceCommandResponse(
                success=False,
                error=str(e)
            )


# Create FastAPI app
app = FastAPI(
    title="NLP2CMD WebOps Voice Service",
    description="Voice-controlled command execution service for operations",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize service manager
voice_manager = VoiceServiceManager()


@app.get("/")
async def root():
    """Root endpoint with voice interface."""
    html_content = """
<!DOCTYPE html>
<html lang="pl">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NLP2CMD WebOps Voice Service</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            color: #333;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        header {
            text-align: center;
            color: white;
            margin-bottom: 30px;
        }
        
        h1 {
            font-size: 2.5em;
            margin-bottom: 10px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        
        .subtitle {
            font-size: 1.2em;
            opacity: 0.9;
        }
        
        .main-panel {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0 20px 40px rgba(0,0,0,0.1);
            backdrop-filter: blur(10px);
        }
        
        .controls {
            display: grid;
            grid-template-columns: 1fr auto auto;
            gap: 15px;
            margin-bottom: 30px;
            align-items: center;
        }
        
        .text-input {
            padding: 15px;
            border: 2px solid #e1e8ed;
            border-radius: 10px;
            font-size: 16px;
            transition: all 0.3s ease;
        }
        
        .text-input:focus {
            outline: none;
            border-color: #667eea;
            box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
        }
        
        button {
            padding: 15px 25px;
            border: none;
            border-radius: 10px;
            cursor: pointer;
            font-size: 16px;
            font-weight: 600;
            transition: all 0.3s ease;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        
        .record-btn {
            background: linear-gradient(135deg, #e74c3c, #c0392b);
            color: white;
        }
        
        .record-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(231, 76, 60, 0.3);
        }
        
        .record-btn.recording {
            background: linear-gradient(135deg, #c0392b, #a93226);
            animation: pulse 1.5s infinite;
        }
        
        @keyframes pulse {
            0% { box-shadow: 0 0 0 0 rgba(231, 76, 60, 0.7); }
            70% { box-shadow: 0 0 0 10px rgba(231, 76, 60, 0); }
            100% { box-shadow: 0 0 0 0 rgba(231, 76, 60, 0); }
        }
        
        .submit-btn {
            background: linear-gradient(135deg, #3498db, #2980b9);
            color: white;
        }
        
        .submit-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 5px 15px rgba(52, 152, 219, 0.3);
        }
        
        .result-panel {
            background: #f8f9fa;
            border-radius: 15px;
            padding: 20px;
            margin: 20px 0;
            border-left: 5px solid #28a745;
            display: none;
        }
        
        .result-panel.error {
            border-left-color: #dc3545;
        }
        
        .result-panel h3 {
            margin-bottom: 15px;
            color: #333;
        }
        
        .command-display {
            background: #2c3e50;
            color: #ecf0f1;
            padding: 15px;
            border-radius: 8px;
            font-family: 'Courier New', monospace;
            font-size: 14px;
            margin: 10px 0;
            overflow-x: auto;
        }
        
        .logs-panel {
            background: #1a1a1a;
            color: #00ff00;
            border-radius: 15px;
            padding: 20px;
            font-family: 'Courier New', monospace;
            font-size: 13px;
            height: 400px;
            overflow-y: auto;
            margin-top: 20px;
            border: 2px solid #333;
        }
        
        .status-indicator {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            margin-right: 8px;
        }
        
        .status-online {
            background: #28a745;
            animation: blink 2s infinite;
        }
        
        @keyframes blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
        }
        
        .examples {
            background: rgba(255, 255, 255, 0.1);
            border-radius: 10px;
            padding: 15px;
            margin-top: 20px;
        }
        
        .examples h4 {
            color: white;
            margin-bottom: 10px;
        }
        
        .example-item {
            background: rgba(255, 255, 255, 0.2);
            padding: 8px 12px;
            border-radius: 5px;
            margin: 5px 0;
            font-size: 14px;
            cursor: pointer;
            transition: background 0.3s ease;
        }
        
        .example-item:hover {
            background: rgba(255, 255, 255, 0.3);
        }
        
        .metrics {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin: 20px 0;
        }
        
        .metric-card {
            background: rgba(255, 255, 255, 0.1);
            padding: 15px;
            border-radius: 10px;
            text-align: center;
            color: white;
        }
        
        .metric-value {
            font-size: 2em;
            font-weight: bold;
            margin-bottom: 5px;
        }
        
        .metric-label {
            font-size: 0.9em;
            opacity: 0.8;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎤 NLP2CMD WebOps Voice Service</h1>
            <p class="subtitle">Voice-controlled command execution for operations teams</p>
        </header>
        
        <div class="main-panel">
            <div class="controls">
                <input type="text" id="textInput" class="text-input" placeholder="Enter command or use voice...">
                <button id="recordBtn" class="record-btn">🎤 Record</button>
                <button id="submitBtn" class="submit-btn">▶ Execute</button>
            </div>
            
            <div class="metrics">
                <div class="metric-card">
                    <div class="metric-value" id="commandCount">0</div>
                    <div class="metric-label">Commands Executed</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value" id="successRate">100%</div>
                    <div class="metric-label">Success Rate</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value" id="avgTime">0ms</div>
                    <div class="metric-label">Avg Response Time</div>
                </div>
                <div class="metric-card">
                    <div class="metric-value"><span class="status-indicator status-online"></span>Online</div>
                    <div class="metric-label">Service Status</div>
                </div>
            </div>
            
            <div id="result" class="result-panel"></div>
            
            <div class="logs-panel" id="logs">
                <div>🔧 WebOps Voice Service - Ready</div>
                <div>🎤 Voice commands enabled for operations automation</div>
                <div>⌨️ Text input available for precise commands</div>
                <div>📊 Real-time execution logs displayed below</div>
                <div>🛡️ All commands executed in isolated environment</div>
            </div>
            
            <div class="examples">
                <h4>🎯 Quick Examples (click to use):</h4>
                <div class="example-item" onclick="setCommand('list files in current directory')">list files in current directory</div>
                <div class="example-item" onclick="setCommand('show system processes sorted by memory usage')">show system processes sorted by memory usage</div>
                <div class="example-item" onclick="setCommand('find files larger than 100MB in /var/log')">find files larger than 100MB in /var/log</div>
                <div class="example-item" onclick="setCommand('check disk space usage for all partitions')">check disk space usage for all partitions</div>
                <div class="example-item" onclick="setCommand('show network connections and listening ports')">show network connections and listening ports</div>
                <div class="example-item" onclick="setCommand('monitor CPU usage for top 5 processes')">monitor CPU usage for top 5 processes</div>
                <div class="example-item" onclick="setCommand('list all running services and their status')">list all running services and their status</div>
            </div>
        </div>
    </div>

    <script>
        let ws = null;
        let mediaRecorder = null;
        let audioChunks = [];
        let isRecording = false;
        let commandCount = 0;
        let successCount = 0;
        let totalTime = 0;

        // Initialize WebSocket
        function initWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
            
            ws.onopen = function() {
                addLog('🔗 Connected to WebSocket server');
                updateStatus(true);
            };
            
            ws.onmessage = function(event) {
                const data = JSON.parse(event.data);
                if (data.type === 'log') {
                    addLog(data.message);
                }
            };
            
            ws.onclose = function() {
                addLog('❌ Disconnected from WebSocket server');
                updateStatus(false);
                // Try to reconnect after 3 seconds
                setTimeout(initWebSocket, 3000);
            };
            
            ws.onerror = function(error) {
                addLog('❌ WebSocket error: ' + error);
                updateStatus(false);
            };
        }

        // Add log message
        function addLog(message) {
            const logs = document.getElementById('logs');
            const logEntry = document.createElement('div');
            logEntry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
            logs.appendChild(logEntry);
            logs.scrollTop = logs.scrollHeight;
        }

        // Update status indicator
        function updateStatus(isOnline) {
            const indicator = document.querySelector('.status-indicator');
            if (isOnline) {
                indicator.classList.add('status-online');
            } else {
                indicator.classList.remove('status-online');
            }
        }

        // Update metrics
        function updateMetrics(success, responseTime) {
            commandCount++;
            if (success) successCount++;
            totalTime += responseTime;
            
            document.getElementById('commandCount').textContent = commandCount;
            document.getElementById('successRate').textContent = 
                Math.round((successCount / commandCount) * 100) + '%';
            document.getElementById('avgTime').textContent = 
                Math.round(totalTime / commandCount) + 'ms';
        }

        // Show result
        function showResult(success, data) {
            const resultDiv = document.getElementById('result');
            resultDiv.style.display = 'block';
            resultDiv.className = `result-panel ${success ? '' : 'error'}`;
            
            if (success) {
                resultDiv.innerHTML = `
                    <h3>✅ Command Executed Successfully</h3>
                    <div><strong>Command:</strong></div>
                    <div class="command-display">${data.command}</div>
                    <p><strong>Confidence:</strong> ${(data.confidence * 100).toFixed(1)}%</p>
                    <p><strong>Explanation:</strong> ${data.explanation}</p>
                    ${data.execution_result ? `
                        <p><strong>Exit Code:</strong> ${data.execution_result.exit_code}</p>
                        ${data.execution_result.stdout ? `
                            <p><strong>Output:</strong></p>
                            <div class="command-display">${data.execution_result.stdout}</div>
                        ` : ''}
                        ${data.execution_result.stderr ? `
                            <p><strong>Errors:</strong></p>
                            <div class="command-display">${data.execution_result.stderr}</div>
                        ` : ''}
                    ` : ''}
                `;
            } else {
                resultDiv.innerHTML = `
                    <h3>❌ Command Failed</h3>
                    <p><strong>Error:</strong> ${data.error}</p>
                `;
            }
        }

        // Set command from examples
        function setCommand(command) {
            document.getElementById('textInput').value = command;
            addLog(`📝 Command set: "${command}"`);
        }

        // Record audio
        async function toggleRecording() {
            const recordBtn = document.getElementById('recordBtn');
            
            if (!isRecording) {
                try {
                    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                    mediaRecorder = new MediaRecorder(stream);
                    audioChunks = [];
                    
                    mediaRecorder.ondataavailable = event => {
                        audioChunks.push(event.data);
                    };
                    
                    mediaRecorder.onstop = async () => {
                        const audioBlob = new Blob(audioChunks, { type: 'audio/wav' });
                        const audioBase64 = await blobToBase64(audioBlob);
                        
                        addLog('🎤 Processing audio recording...');
                        sendVoiceCommand(audioBase64);
                        
                        // Stop all tracks
                        stream.getTracks().forEach(track => track.stop());
                    };
                    
                    mediaRecorder.start();
                    isRecording = true;
                    recordBtn.textContent = '⏹ Stop';
                    recordBtn.classList.add('recording');
                    addLog('🎤 Recording... Speak clearly');
                    
                } catch (error) {
                    addLog(`❌ Recording error: ${error.message}`);
                }
            } else {
                mediaRecorder.stop();
                isRecording = false;
                recordBtn.textContent = '🎤 Record';
                recordBtn.classList.remove('recording');
                addLog('⏹ Recording stopped');
            }
        }

        // Convert blob to base64
        function blobToBase64(blob) {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(reader.result.split(',')[1]);
                reader.onerror = error => reject(error);
                reader.readAsDataURL(blob);
            });
        }

        // Send voice command
        async function sendVoiceCommand(audioData = null) {
            const textCommand = document.getElementById('textInput').value;
            const startTime = Date.now();
            
            try {
                const response = await fetch('/voice-command', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        audio_data: audioData,
                        text_command: textCommand || null,
                        language: 'pl',
                        execute: true
                    })
                });
                
                const responseTime = Date.now() - startTime;
                const result = await response.json();
                
                showResult(result.success, result);
                updateMetrics(result.success, responseTime);
                
                if (result.success) {
                    addLog(`✅ Command completed in ${responseTime}ms`);
                } else {
                    addLog(`❌ Command failed: ${result.error}`);
                }
                
            } catch (error) {
                addLog(`❌ Request error: ${error.message}`);
                showResult(false, { error: error.message });
                updateMetrics(false, Date.now() - startTime);
            }
        }

        // Event listeners
        document.getElementById('recordBtn').addEventListener('click', toggleRecording);
        
        document.getElementById('submitBtn').addEventListener('click', () => {
            const textCommand = document.getElementById('textInput').value;
            if (textCommand.trim()) {
                addLog(`⌨️ Executing command: "${textCommand}"`);
                sendVoiceCommand();
            } else {
                addLog('⚠️ Please enter a command');
            }
        });

        document.getElementById('textInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                document.getElementById('submitBtn').click();
            }
        });

        // Initialize
        initWebSocket();
        addLog('🚀 WebOps Voice Service ready for operations');
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy", 
        "service": "nlp2cmd-webops-voice",
        "version": "1.0.0"
    }


@app.post("/voice-command")
async def process_voice_command(request: VoiceCommandRequest):
    """Process voice command and execute shell command."""
    result = await voice_manager.process_voice_command(request)
    return result


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time log streaming."""
    await voice_manager.connect(websocket)
    try:
        while True:
            # Keep connection alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        voice_manager.disconnect(websocket)


def create_webops_voice_app() -> FastAPI:
    """Create WebOps voice service app for uvicorn."""
    return app


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Run the service
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info"
    )
