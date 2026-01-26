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
    from fastapi.templating import Jinja2Templates
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
    Jinja2Templates = None

# Import NLP2CMD components
try:
    from nlp2cmd.service import NLP2CMDService, ServiceConfig
    from nlp2cmd.generation.pipeline import RuleBasedPipeline
    NLP2CMD_AVAILABLE = True
    print("✅ NLP2CMD package imported successfully")
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
        
    async def execute_command(self, command: str, working_dir: str = None) -> Dict[str, Any]:
        """Execute shell command and return result with logs."""
        try:
            # Use current working directory if none specified
            if working_dir is None:
                working_dir = os.getcwd()
            
            # Ensure the working directory exists
            if not os.path.exists(working_dir):
                working_dir = os.getcwd()
            
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
        
        # Always initialize NLP2CMD pipeline directly
        self.pipeline = self._create_nlp2cmd_pipeline()
        self.nlp2cmd_service = None
        print("✅ NLP2CMD pipeline initialized")
        
    def _create_nlp2cmd_pipeline(self):
        """Create NLP2CMD pipeline."""
        if NLP2CMD_AVAILABLE and RuleBasedPipeline is not None:
            try:
                return RuleBasedPipeline()
            except Exception as e:
                print(
                    f"⚠️ Failed to init in-process RuleBasedPipeline ({e}); falling back to subprocess CLI",
                    file=sys.stderr,
                    flush=True,
                )

        # Fallback: subprocess CLI
        class NLP2CMDPipeline:
            def process(self, query):
                import subprocess
                import os
                import json
                import sys
                
                print(f"DEBUG: Processing query: {query}", file=sys.stderr, flush=True)
                
                try:
                    # Set environment for NLP2CMD
                    env = os.environ.copy()
                    env['NLP2CMD_KEYWORD_DETECTOR_CONFIG'] = '/app/nlp2cmd-repo/data/keyword_intent_detector_config.json'
                    env['NLP2CMD_PATTERNS_FILE'] = '/app/nlp2cmd-repo/data/patterns.json'
                    
                    # Run nlp2cmd CLI
                    result = subprocess.run([
                        'nlp2cmd', query
                    ], capture_output=True, text=True, env=env, timeout=30)
                    
                    print(f"DEBUG: NLP2CMD return code: {result.returncode}", flush=True)
                    
                    if result.returncode == 0:
                        # Parse the output to extract command
                        output_lines = result.stdout.strip().split('\n')
                        command = ""
                        yaml_data = {}
                        
                        # Debug: print the raw output
                        print(f"DEBUG: NLP2CMD output: {result.stdout}", flush=True)
                        
                        # Extract command (line after ```bash)
                        bash_block_started = False
                        for line in output_lines:
                            line = line.strip()
                            if line == '```bash':
                                bash_block_started = True
                                continue
                            elif line == '```' and bash_block_started:
                                break
                            elif bash_block_started and line:
                                command = line
                                break
                        
                        # If no command found in bash block, try to extract from yaml
                        if not command:
                            for line in output_lines:
                                line = line.strip()
                                if line.startswith('generated_command:'):
                                    command = line.replace('generated_command:', '').strip().strip('"')
                                    break
                        
                        # Parse YAML data
                        yaml_start = False
                        yaml_lines = []
                        for line in output_lines:
                            line = line.strip()
                            if line == '```yaml':
                                yaml_start = True
                                continue
                            elif line == '```' and yaml_start:
                                break
                            elif yaml_start:
                                yaml_lines.append(line)
                        
                        if yaml_lines:
                            try:
                                yaml_text = '\n'.join(yaml_lines)
                                # Simple YAML parsing for key values
                                for line in yaml_text.split('\n'):
                                    if ':' in line and not line.startswith(' '):
                                        key, value = line.split(':', 1)
                                        yaml_data[key.strip()] = value.strip()
                            except:
                                pass
                        
                        # If no command found in backticks, try to extract from yaml
                        if not command and 'generated_command' in yaml_data:
                            command = yaml_data['generated_command'].strip().strip('"')
                        
                        # Debug: print parsed values
                        print(f"DEBUG: Parsed command: '{command}'", flush=True)
                        print(f"DEBUG: Parsed yaml: {yaml_data}", flush=True)
                        
                        class NLP2CMDResult:
                            def __init__(self, command, yaml_data):
                                self.success = True
                                self.command = command
                                self.confidence = float(yaml_data.get('confidence', '0.9'))
                                self.errors = []
                                self.explanation = f"NLP2CMD generated: {command}"
                                self.status = yaml_data.get('status', 'success')
                                self.warnings = yaml_data.get('warnings', [])
                                self.suggestions = yaml_data.get('suggestions', [])
                        
                        return NLP2CMDResult(command, yaml_data)
                    else:
                        # Error case
                        class NLP2CMDResult:
                            def __init__(self, error):
                                self.success = False
                                self.command = ""
                                self.confidence = 0.0
                                self.errors = [error]
                                self.explanation = f"NLP2CMD error: {error}"
                        
                        return NLP2CMDResult(result.stderr)
                        
                except subprocess.TimeoutExpired:
                    class NLP2CMDResult:
                        def __init__(self):
                            self.success = False
                            self.command = ""
                            self.confidence = 0.0
                            self.errors = ["NLP2CMD timeout"]
                            self.explanation = "NLP2CMD processing timed out"
                    
                    return NLP2CMDResult()
                except Exception as e:
                    class NLP2CMDResult:
                        def __init__(self, error):
                            self.success = False
                            self.command = ""
                            self.confidence = 0.0
                            self.errors = [str(error)]
                            self.explanation = f"NLP2CMD error: {str(error)}"
                    
                    return NLP2CMDResult(str(e))
        
        return NLP2CMDPipeline()
        
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
                # Simple speech-to-text simulation for demo
                # In production, integrate with real STT service
                import base64
                try:
                    # Decode base64 audio (simplified check)
                    audio_bytes = base64.b64decode(request.audio_data)
                    print(f"DEBUG: Audio data decoded, size: {len(audio_bytes)} bytes", file=sys.stderr, flush=True)
                    if len(audio_bytes) > 1000:  # Has actual audio data
                        # For demo, map common audio patterns to commands
                        command_text = "list files"  # Default fallback
                        print(f"DEBUG: Audio detected - using default command: {command_text}", file=sys.stderr, flush=True)
                        await self.broadcast_log("🎤 Audio detected - using default command for demo")
                    else:
                        command_text = "list files"
                        print(f"DEBUG: Audio too small ({len(audio_bytes)} bytes), using fallback", file=sys.stderr, flush=True)
                except Exception as e:
                    command_text = "list files"
                    print(f"DEBUG: Audio decode error: {e}, using fallback", file=sys.stderr, flush=True)
            else:
                print(f"DEBUG: Using text command: {command_text}", file=sys.stderr, flush=True)
            
            if not command_text:
                return VoiceCommandResponse(
                    success=False,
                    error="No command provided"
                )
            
            # Process command with NLP2CMD pipeline
            print(f"DEBUG: About to process command: {command_text}", file=sys.stderr, flush=True)
            print(f"DEBUG: Audio data present: {bool(request.audio_data)}", file=sys.stderr, flush=True)
            print(f"DEBUG: Language: {request.language}", file=sys.stderr, flush=True)
            print(f"DEBUG: Execute flag: {request.execute}", file=sys.stderr, flush=True)

            pipeline_result = self.pipeline.process(command_text)
            
            print(f"DEBUG: Final pipeline result: {pipeline_result.command}", file=sys.stderr, flush=True)
            
            if not pipeline_result.success:
                print(f"DEBUG: Pipeline failed - errors: {pipeline_result.errors}", file=sys.stderr, flush=True)
                return VoiceCommandResponse(
                    success=False,
                    error="Failed to process command",
                    explanation=pipeline_result.errors[0] if pipeline_result.errors else "Unknown error"
                )
            
            print(f"DEBUG: About to execute command: {pipeline_result.command}", file=sys.stderr, flush=True)
            print(f"DEBUG: Execute flag: {request.execute}", file=sys.stderr, flush=True)
            
            result = {
                "success": True,
                "command": pipeline_result.command,
                "explanation": f"Generated by RuleBasedPipeline with confidence {pipeline_result.confidence:.2f}",
                "confidence": pipeline_result.confidence,
            }
            
            # Execute command if requested
            if request.execute and pipeline_result.command:
                print(f"DEBUG: Executing command: {pipeline_result.command}", file=sys.stderr, flush=True)
                await self.broadcast_log(f"Executing: {pipeline_result.command}")
                execution_result = await self.executor.execute_command(pipeline_result.command)
                print(f"DEBUG: Execution result: {execution_result}", file=sys.stderr, flush=True)
                print(f"DEBUG: Execution success: {execution_result.get('success')}", file=sys.stderr, flush=True)
                print(f"DEBUG: Execution exit code: {execution_result.get('exit_code')}", file=sys.stderr, flush=True)
                result["execution_result"] = execution_result
                result["logs"] = execution_result["logs"]
                
                # Broadcast logs line by line
                for log_line in execution_result.get("logs", []):
                    await self.broadcast_log(log_line)
            else:
                print(f"DEBUG: Skipping execution - execute={request.execute}, command='{pipeline_result.command}'", file=sys.stderr, flush=True)
            
            return VoiceCommandResponse(**result)
            
        except Exception as e:
            return VoiceCommandResponse(
                success=False,
                error=str(e)
            )
    
    async def _process_with_mock_pipeline(self, text: str, language: str, execute: bool) -> Dict[str, Any]:
        """Process command using mock pipeline."""
        # Use mock pipeline
        result = self.pipeline.process(text)
        
        if result.success and execute:
            # Execute the command
            await self.broadcast_log(f"Executing: {result.command}")
            execution_result = await self.executor.execute_command(result.command)
            
            return {
                "success": True,
                "command": result.command,
                "explanation": result.explanation,
                "confidence": result.confidence,
                "execution_result": execution_result,
                "logs": execution_result.get("logs", []),
            }
        else:
            return {
                "success": result.success,
                "command": result.command,
                "explanation": result.explanation,
                "confidence": result.confidence,
                "execution_result": None,
                "logs": result.errors if hasattr(result, 'errors') else [],
            }

    async def _process_with_nlp2cmd_service(self, text: str, language: str, execute: bool) -> Dict[str, Any]:
        """Process command using NLP2CMD service."""
        try:
            # Use the pipeline directly from the service
            pipeline = self.nlp2cmd_service.pipeline
            if pipeline is None:
                # Fallback to mock
                return await self._process_with_mock_pipeline(text, language, execute)
            
            # Process query using pipeline
            result = pipeline.process(text)
            
            if result.success and execute:
                # Execute the command
                await self.broadcast_log(f"Executing: {result.command}")
                execution_result = await self.executor.execute_command(result.command)
                
                response_data = {
                    "success": True,
                    "command": result.command,
                    "explanation": result.explanation or f"Generated command: {result.command}",
                    "confidence": getattr(result, 'confidence', 0.85),
                    "execution_result": execution_result,
                    "logs": execution_result.get("logs", []),
                }
                
                # Broadcast logs line by line
                for log_line in execution_result.get("logs", []):
                    await self.broadcast_log(log_line)
                    
                return response_data
            else:
                return {
                    "success": result.success,
                    "command": result.command,
                    "explanation": result.explanation or f"Generated command: {result.command}",
                    "confidence": getattr(result, 'confidence', 0.85),
                    "execution_result": None,
                    "logs": result.errors if hasattr(result, 'errors') else [],
                }
                
        except Exception as e:
            return {
                "success": False,
                "command": text,
                "explanation": f"NLP2CMD service error: {str(e)}",
                "confidence": 0.0,
                "execution_result": None,
                "logs": [f"Service error: {str(e)}"],
                "error": str(e)
            }


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

# Mount static files
if StaticFiles:
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup templates
templates = Jinja2Templates(directory="templates") if Jinja2Templates else None

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
                <input type="text" id="textInput" class="text-input" placeholder="Enter command or start continuous voice...">
                <button id="recordBtn" class="record-btn">🎤 Start Voice</button>
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
                <div>🎤 Continuous voice streaming enabled</div>
                <div>⏸️ Pause detection for automatic command execution</div>
                <div>📊 Real-time execution logs displayed below</div>
                <div>🛡️ All commands executed in isolated environment</div>
                <div>🐛 DEBUG MODE - Enhanced logging enabled</div>
                <div>📝 Check browser console for JavaScript errors</div>
            </div>
            
            <div class="examples">
                <h4>🎯 Quick Examples (click to use):</h4>
                <div class="example-item" onclick="setCommand('list files')">list files</div>
                <div class="example-item" onclick="setCommand('show current directory contents')">show current directory contents</div>
                <div class="example-item" onclick="setCommand('show running processes')">show running processes</div>
                <div class="example-item" onclick="setCommand('show system processes')">show system processes</div>
                <div class="example-item" onclick="setCommand('check disk space')">check disk space</div>
                <div class="example-item" onclick="setCommand('list containers')">list containers</div>
                <div class="example-item" onclick="setCommand('find files larger than 100MB')">find files larger than 100MB</div>
                <div class="example-item" onclick="setCommand('show network connections')">show network connections</div>
            </div>
        </div>
    </div>

    <script>
        let ws = null;
        let commandCount = 0;
        let successCount = 0;
        let totalTime = 0;

        // DEBUG: Log script initialization
        console.log('🐛 DEBUG: Script initializing...');
        addLog('🐛 DEBUG: JavaScript script starting...');

        // DEBUG: Log variable declarations
        console.log('🐛 DEBUG: Declaring global variables...');
        
        // DEBUG: Check for existing variables
        if (typeof mediaRecorder !== 'undefined') {
            console.error('🐛 ERROR: mediaRecorder already declared!');
            addLog('🐛 ERROR: mediaRecorder already declared!');
        }
        if (typeof audioChunks !== 'undefined') {
            console.error('🐛 ERROR: audioChunks already declared!');
            addLog('🐛 ERROR: audioChunks already declared!');
        }

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

        // Continuous voice streaming with pause detection
        console.log('🐛 DEBUG: Declaring audio variables...');
        addLog('🐛 DEBUG: Setting up audio streaming variables...');
        
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
        
        console.log('🐛 DEBUG: Audio variables declared successfully');
        addLog('🐛 DEBUG: Audio streaming variables initialized');

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
            console.log('🐛 DEBUG: toggleRecording called, isRecording:', isRecording);
            addLog(`🐛 DEBUG: toggleRecording - Current state: ${isRecording ? 'recording' : 'stopped'}`);
            
            if (!isRecording) {
                console.log('🐛 DEBUG: Starting continuous streaming...');
                await startContinuousStreaming();
            } else {
                console.log('🐛 DEBUG: Stopping continuous streaming...');
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
            const startTime = Date.now();
            
            addLog(`🚀 Sending command - Text: "${textCommand || 'none'}", Audio: ${audioData ? 'yes' : 'no'}`);
            
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
                
                addLog(`📥 Response received in ${responseTime}ms - Success: ${result.success}`);
                addLog(`🔧 Generated command: "${result.command || 'none'}"`);
                addLog(`📊 Confidence: ${result.confidence || 'N/A'}`);
                
                if (result.execution_result) {
                    addLog(`⚡ Execution exit code: ${result.execution_result.exit_code || 'N/A'}`);
                    if (result.execution_result.stdout) {
                        addLog(`📤 Output: ${result.execution_result.stdout.trim()}`);
                    }
                    if (result.execution_result.stderr) {
                        addLog(`❌ Error: ${result.execution_result.stderr.trim()}`);
                    }
                }
                
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
    import sys
    print(f"🐛 BACKEND DEBUG: Voice command request received", file=sys.stderr, flush=True)
    print(f"🐛 BACKEND DEBUG: Request text: {request.text_command}", file=sys.stderr, flush=True)
    print(f"🐛 BACKEND DEBUG: Has audio data: {bool(request.audio_data)}", file=sys.stderr, flush=True)
    print(f"🐛 BACKEND DEBUG: Language: {request.language}", file=sys.stderr, flush=True)
    print(f"🐛 BACKEND DEBUG: Execute flag: {request.execute}", file=sys.stderr, flush=True)
    
    result = await voice_manager.process_voice_command(request)
    print(f"🐛 BACKEND DEBUG: Voice command processed, success: {result.success}", file=sys.stderr, flush=True)
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
        port=8001,
        log_level="info"
    )
