"""
Docker Voice Service - Enhanced service with voice control and shell execution
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

from ..service import NLP2CMDService, ServiceConfig
from ..generation.pipeline import RuleBasedPipeline


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
        self.pipeline = RuleBasedPipeline()
        
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
    title="NLP2CMD Voice Service",
    description="Voice-controlled command execution service",
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

# Serve static files
try:
    app.mount("/static", StaticFiles(directory="frontend"), name="static")
except Exception:
    pass  # Frontend directory might not exist

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
    <title>NLP2CMD Voice Service</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            background: white;
            padding: 30px;
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            color: #333;
            text-align: center;
            margin-bottom: 30px;
        }
        .controls {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        button {
            padding: 10px 20px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-size: 16px;
        }
        .record-btn {
            background: #e74c3c;
            color: white;
        }
        .record-btn.recording {
            background: #c0392b;
        }
        .text-input {
            flex: 1;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 5px;
            font-size: 16px;
        }
        .submit-btn {
            background: #3498db;
            color: white;
        }
        .logs {
            background: #2c3e50;
            color: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            font-family: monospace;
            font-size: 12px;
            height: 300px;
            overflow-y: auto;
            margin-top: 20px;
        }
        .result {
            background: #ecf0f1;
            padding: 15px;
            border-radius: 5px;
            margin: 20px 0;
        }
        .success {
            border-left: 4px solid #27ae60;
        }
        .error {
            border-left: 4px solid #e74c3c;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎤 NLP2CMD Voice Service</h1>
        
        <div class="controls">
            <button id="recordBtn" class="record-btn">🎤 Nagraj komendę</button>
            <input type="text" id="textInput" class="text-input" placeholder="Wpisz komendę tekstowo...">
            <button id="submitBtn" class="submit-btn">▶️ Wykonaj</button>
        </div>
        
        <div id="result" class="result" style="display: none;"></div>
        
        <div class="logs" id="logs">
            <div>🔧 NLP2CMD Voice Service - Ready</div>
            <div>📝 Możesz używać komend głosowych lub tekstowych</div>
            <div>🎤 Naciśnij "Nagraj komendę" i mów wyraźnie</div>
            <div>⌨️ Lub wpisz komendę tekstowo i kliknij "Wykonaj"</div>
        </div>
    </div>

    <script>
        let ws = null;

        // Initialize WebSocket
        function initWebSocket() {
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            ws = new WebSocket(`${protocol}//${window.location.host}/ws`);
            
            ws.onopen = function() {
                addLog('🔗 Połączono z serwerem WebSocket');
            };
            
            ws.onmessage = function(event) {
                const data = JSON.parse(event.data);
                if (data.type === 'log') {
                    addLog(data.message);
                }
            };
            
            ws.onclose = function() {
                addLog('❌ Rozłączono z serwerem WebSocket');
                // Try to reconnect after 3 seconds
                setTimeout(initWebSocket, 3000);
            };
        }

        // Add log message
        function addLog(message) {
            const logs = document.getElementById('logs');
            const logEntry = document.createElement('div');
            logEntry.textContent = message;
            logs.appendChild(logEntry);
            logs.scrollTop = logs.scrollHeight;
        }

        // Show result
        function showResult(success, data) {
            const resultDiv = document.getElementById('result');
            resultDiv.style.display = 'block';
            resultDiv.className = `result ${success ? 'success' : 'error'}`;
            
            if (success) {
                resultDiv.innerHTML = `
                    <h3>✅ Komenda wykonana</h3>
                    <p><strong>Komenda:</strong> ${data.command}</p>
                    <p><strong>Wyjaśnienie:</strong> ${data.explanation}</p>
                    <p><strong>Pewność:</strong> ${(data.confidence * 100).toFixed(1)}%</p>
                    ${data.logs ? `<p><strong>Logi:</strong></p><pre>${data.logs.join('\\n')}</pre>` : ''}
                `;
            } else {
                resultDiv.innerHTML = `
                    <h3>❌ Błąd</h3>
                    <p>${data.error}</p>
                `;
            }
        }

        // Continuous voice streaming with pause detection
        let mediaRecorder = null;
        let audioChunks = [];
        let isRecording = false;
        let silenceTimer = null;
        let audioContext = null;
        let analyser = null;
        let microphone = null;
        let javascriptNode = null;
        let isStreamActive = false;
        let speechStartTime = null;
        let isSpeaking = false;
        const SILENCE_THRESHOLD = 0.01; // Audio level threshold for silence
        const SILENCE_DURATION = 1500; // 1.5 seconds of silence to trigger command
        const MIN_SPEECH_DURATION = 500; // Minimum speech duration before pause detection

        // Start continuous voice streaming
        async function startContinuousStreaming() {
            const recordBtn = document.getElementById('recordBtn');
            
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                
                // Setup Web Audio API for real-time analysis
                audioContext = new (window.AudioContext || window.webkitAudioContext)();
                analyser = audioContext.createAnalyser();
                microphone = audioContext.createMediaStreamSource(stream);
                javascriptNode = audioContext.createScriptProcessor(2048, 1, 1);
                
                analyser.smoothingTimeConstant = 0.8;
                analyser.fftSize = 1024;
                
                microphone.connect(analyser);
                analyser.connect(javascriptNode);
                javascriptNode.connect(audioContext.destination);
                
                javascriptNode.onaudioprocess = function(event) {
                    const array = new Uint8Array(analyser.frequencyBinCount);
                    analyser.getByteFrequencyData(array);
                    
                    // Calculate average volume
                    const average = array.reduce((a, b) => a + b) / array.length;
                    const normalizedVolume = average / 255;
                    
                    // Detect speech vs silence
                    if (normalizedVolume > SILENCE_THRESHOLD) {
                        if (!isSpeaking) {
                            isSpeaking = true;
                            speechStartTime = Date.now();
                            addLog('🎤 Wykryto mowę...');
                        }
                        
                        // Reset silence timer
                        if (silenceTimer) {
                            clearTimeout(silenceTimer);
                            silenceTimer = null;
                        }
                    } else {
                        // Silence detected
                        if (isSpeaking && speechStartTime) {
                            const speechDuration = Date.now() - speechStartTime;
                            
                            if (speechDuration >= MIN_SPEECH_DURATION) {
                                // Start silence timer for command execution
                                if (!silenceTimer) {
                                    silenceTimer = setTimeout(() => {
                                        addLog('⏸️ Wykryto pauzę - uruchamiam komendę...');
                                        processCurrentAudio();
                                        resetSpeechDetection();
                                    }, SILENCE_DURATION);
                                }
                            } else {
                                // Too short, reset
                                resetSpeechDetection();
                            }
                        }
                    }
                };
                
                // Setup MediaRecorder for actual audio capture
                mediaRecorder = new MediaRecorder(stream);
                audioChunks = [];
                
                mediaRecorder.ondataavailable = event => {
                    if (event.data.size > 0) {
                        audioChunks.push(event.data);
                    }
                };
                
                mediaRecorder.start(100); // Collect data every 100ms
                isStreamActive = true;
                isRecording = true;
                
                recordBtn.textContent = '⏹️ Stop';
                recordBtn.classList.add('recording');
                addLog('🎤 Ciągłe nasłuchiwanie włączone...');
                
            } catch (error) {
                addLog(`❌ Błąd nagrywania: ${error.message}`);
            }
        }
        
        // Process collected audio when pause is detected
        async function processCurrentAudio() {
            if (audioChunks.length === 0) return;
            
            const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });
            const audioBase64 = await blobToBase64(audioBlob);
            
            addLog('🎤 Przetwarzanie komendy głosowej...');
            sendVoiceCommand(audioBase64);
            
            // Reset audio chunks for next command
            audioChunks = [];
        }
        
        // Reset speech detection state
        function resetSpeechDetection() {
            isSpeaking = false;
            speechStartTime = null;
            if (silenceTimer) {
                clearTimeout(silenceTimer);
                silenceTimer = null;
            }
        }
        
        // Stop continuous streaming
        function stopContinuousStreaming() {
            if (mediaRecorder && mediaRecorder.state !== 'inactive') {
                mediaRecorder.stop();
            }
            
            if (silenceTimer) {
                clearTimeout(silenceTimer);
                silenceTimer = null;
            }
            
            if (microphone) {
                microphone.disconnect();
            }
            
            if (javascriptNode) {
                javascriptNode.disconnect();
            }
            
            if (audioContext) {
                audioContext.close();
            }
            
            isStreamActive = false;
            isRecording = false;
            
            const recordBtn = document.getElementById('recordBtn');
            recordBtn.textContent = '🎤 Start';
            recordBtn.classList.remove('recording');
            addLog('⏹️ Nasłuchiwanie zatrzymane');
        }
        
        // Toggle continuous streaming
        async function toggleRecording() {
            if (!isRecording) {
                await startContinuousStreaming();
            } else {
                stopContinuousStreaming();
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
                
                const result = await response.json();
                showResult(result.success, result);
                
            } catch (error) {
                addLog(`❌ Błąd wysyłania komendy: ${error.message}`);
                showResult(false, { error: error.message });
            }
        }

        // Event listeners
        document.getElementById('recordBtn').addEventListener('click', toggleRecording);
        
        document.getElementById('submitBtn').addEventListener('click', () => {
            const textCommand = document.getElementById('textInput').value;
            if (textCommand.trim()) {
                addLog(`⌨️ Wykonywanie komendy: "${textCommand}"`);
                sendVoiceCommand();
            } else {
                addLog('⚠️ Wpisz komendę tekstową');
            }
        });

        document.getElementById('textInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                document.getElementById('submitBtn').click();
            }
        });

        // Initialize
        initWebSocket();
        addLog('🚀 Aplikacja gotowa do użycia');
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "service": "nlp2cmd-voice"}


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


def create_voice_app() -> FastAPI:
    """Create voice service app for uvicorn."""
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
