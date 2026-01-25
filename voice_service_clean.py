"""
WebOps Voice Service - Clean version with separated files
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
    from fastapi import FastAPI, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect, Request
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
    Request = None
    HTMLResponse = None
    JSONResponse = None
    CORSMiddleware = None
    StaticFiles = None
    Jinja2Templates = None
    BaseModel = object
    Field = lambda x, **kwargs: x
    uvicorn = None

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
    """Shell command executor with timeout and logging."""
    
    def __init__(self, max_execution_time: int = 30):
        self.max_execution_time = max_execution_time
    
    async def execute_command(self, command: str) -> Dict[str, Any]:
        """Execute shell command with timeout and logging."""
        try:
            # Create temporary file for output
            with tempfile.NamedTemporaryFile(mode='w+', delete=True, suffix='.log') as temp_file:
                # Execute command with timeout
                process = await asyncio.create_subprocess_shell(
                    command,
                    stdout=temp_file,
                    stderr=temp_file,
                    timeout=self.max_execution_time
                )
                stdout, stderr = await process.communicate()
                
                return {
                    "success": process.returncode == 0,
                    "exit_code": process.returncode,
                    "stdout": stdout.strip() if stdout else "",
                    "stderr": stderr.strip() if stderr else "",
                    "logs": [line.strip() for line in temp_file.read_text().split('\n') if line.strip()],
                    "execution_time": 0  # Would need to track this
                }
        except asyncio.TimeoutError:
            return {
                "success": False,
                "exit_code": 124,
                "stdout": "",
                "stderr": "Command execution timed out",
                "logs": ["Command execution timed out"],
                "execution_time": self.max_execution_time
            }
        except Exception as e:
            return {
                "success": False,
                "exit_code": 1,
                "stdout": "",
                "stderr": str(e),
                "logs": [f"Error executing command: {e}"],
                "execution_time": 0
            }


class VoiceServiceManager:
    """Manages voice command processing and WebSocket connections."""
    
    def __init__(self):
        """Initialize the voice service manager."""
        # Always initialize NLP2CMD pipeline directly
        self.pipeline = self._create_nlp2cmd_pipeline()
        self.nlp2cmd_service = None
        self.active_connections: List[WebSocket] = []
        self.executor = ShellExecutor()
        print("✅ Using direct NLP2CMD CLI pipeline")
        
    def _create_nlp2cmd_pipeline(self):
        """Create direct NLP2CMD pipeline using subprocess."""
        class NLP2CMDPipeline:
            def process(self, query):
                import subprocess
                import os
                import json
                
                try:
                    # Set environment for NLP2CMD
                    env = os.environ.copy()
                    env['NLP2CMD_KEYWORD_DETECTOR_CONFIG'] = '/app/nlp2cmd-repo/data/keyword_intent_detector_config.json'
                    env['NLP2CMD_PATTERNS_FILE'] = '/app/nlp2cmd-repo/data/patterns.json'
                    
                    # Run nlp2cmd CLI
                    result = subprocess.run([
                        'nlp2cmd', query
                    ], capture_output=True, text=True, env=env, timeout=30)
                    
                    if result.returncode == 0:
                        # Parse the output to extract command
                        output_lines = result.stdout.strip().split('\n')
                        command = ""
                        yaml_data = {}
                        
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
                        
                        # Fallback to YAML
                        if not command:
                            for line in output_lines:
                                if 'generated_command:' in line:
                                    command = line.split(':', 1)[1].strip().strip('"')
                                    break
                        
                        class NLP2CMDResult:
                            def __init__(self, cmd):
                                self.success = True
                                self.command = cmd
                                self.confidence = 1.0
                                self.errors = []
                                self.explanation = f"NLP2CMD generated: {cmd}"
                                self.status = yaml_data.get('status', 'success')
                                self.warnings = yaml_data.get('warnings', [])
                                self.suggestions = yaml_data.get('suggestions', [])
                        
                        return NLP2CMDResult(command)
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
        """Connect a new WebSocket client."""
        self.active_connections.append(websocket)
        try:
            while True:
                # Keep connection alive
                await websocket.receive_text()
        except WebSocketDisconnect:
            self.active_connections.remove(websocket)
        except Exception as e:
            print(f"WebSocket error: {e}")
    
    async def broadcast_log(self, message: str):
        """Broadcast log message to all connected clients."""
        if self.active_connections:
            await asyncio.gather(
                *[connection.send_text(json.dumps({"type": "log", "message": message})) for connection in self.active_connections],
                return_exceptions=True
            )
    
    async def process_voice_command(self, request: VoiceCommandRequest) -> VoiceCommandResponse:
        """Process voice command and return response."""
        import sys
        print(f"🐛 BACKEND DEBUG: Voice command request received", file=sys.stderr, flush=True)
        print(f"🐛 BACKEND DEBUG: Request text: {request.text_command}", file=sys.stderr, flush=True)
        print(f"🐛 BACKEND DEBUG: Has audio data: {bool(request.audio_data)}", file=sys.stderr, flush=True)
        print(f"🐛 BACKEND DEBUG: Language: {request.language}", file=sys.stderr, flush=True)
        print(f"🐛 BACKEND DEBUG: Execute flag: {request.execute}", file=sys.stderr, flush=True)
        
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
                        print(f"DEBUG: Audio too small ({len(audio_bytes)} bytes, using fallback", file=sys.stderr, flush=True)
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
            import sys
            print(f"DEBUG: About to process command: {command_text}", file=sys.stderr, flush=True)
            print(f"DEBUG: Audio data present: {bool(request.audio_data)}", file=sys.stderr, flush=True)
            print(f"DEBUG: Language: {request.language}", file=sys.stderr, flush=True)
            print(f"DEBUG: Execute flag: {request.execute}", file=sys.stderr, flush=True)
            
            # Force direct subprocess call to bypass any caching
            import subprocess
            import os
            env = os.environ.copy()
            env['NLP2CMD_KEYWORD_DETECTOR_CONFIG'] = '/app/nlp2cmd-repo/data/keyword_intent_detector_config.json'
            env['NLP2CMD_PATTERNS_FILE'] = '/app/nlp2cmd-repo/data/patterns.json'
            
            print(f"DEBUG: Starting NLP2CMD subprocess...", file=sys.stderr, flush=True)
            result = subprocess.run(['nlp2cmd', command_text], capture_output=True, text=True, env=env, timeout=30)
            print(f"DEBUG: Raw NLP2CMD result: {result.returncode}", file=sys.stderr, flush=True)
            print(f"DEBUG: Raw NLP2CMD stdout length: {len(result.stdout)}", file=sys.stderr, flush=True)
            print(f"DEBUG: Raw NLP2CMD stderr: {result.stderr}", file=sys.stderr, flush=True)
            
            # Parse output directly here
            if result.returncode == 0:
                output_lines = result.stdout.strip().split('\n')
                command = ""
                yaml_data = {}
                
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
                
                # Fallback to YAML
                if not command:
                    for line in output_lines:
                        if 'generated_command:' in line:
                            command = line.split(':', 1)[1].strip().strip('"')
                            break
                
                print(f"DEBUG: Extracted command: '{command}'", file=sys.stderr, flush=True)
                print(f"DEBUG: YAML data keys: {list(yaml_data.keys())}", file=sys.stderr, flush=True)
                
                # Create mock result
                class MockResult:
                    def __init__(self, cmd):
                        self.success = True
                        self.command = cmd
                        self.confidence = 1.0
                        self.errors = []
                        self.explanation = f"NLP2CMD generated: {cmd}"
                        self.status = yaml_data.get('status', 'success')
                        self.warnings = yaml_data.get('warnings', [])
                        self.suggestions = yaml_data.get('suggestions', [])
                
                pipeline_result = MockResult(command)
                print(f"DEBUG: Pipeline result created - command: {pipeline_result.command}", file=sys.stderr, flush=True)
            else:
                class MockResult:
                    def __init__(self):
                        self.success = False
                        self.command = ""
                        self.confidence = 0.0
                        self.errors = ["NLP2CMD failed"]
                        self.explanation = "NLP2CMD processing failed"
                
                pipeline_result = MockResult()
            
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
async def root(request: Request):
    """Root endpoint with voice interface."""
    return templates.TemplateResponse("index.html", {"request": request})


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
        pass
    except Exception as e:
        print(f"WebSocket error: {e}")


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
