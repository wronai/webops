/**
 * WebOps Voice Service - Frontend JavaScript
 * Voice-controlled command execution with continuous streaming
 */

// Global variables
let ws = null;
let commandCount = 0;
let successCount = 0;
let totalTime = 0;

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

// DEBUG: Log script initialization
console.log('🐛 DEBUG: Script initializing...');
addLog('🐛 DEBUG: JavaScript script starting...');

// DEBUG: Log variable declarations
console.log('🐛 DEBUG: Declaring global variables...');

console.log('🐛 DEBUG: Audio variables declared successfully');
addLog('🐛 DEBUG: Audio streaming variables initialized');

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
    
    ws.onerror = function(error) {
        console.error('WebSocket error:', error);
        addLog('❌ WebSocket connection error');
    };
    
    ws.onclose = function() {
        addLog('🔌 WebSocket connection closed');
        updateStatus(false);
        // Try to reconnect after 3 seconds
        setTimeout(initWebSocket, 3000);
    };
}

// Update status indicator
function updateStatus(isOnline) {
    const statusElement = document.querySelector('.status-indicator');
    if (statusElement) {
        statusElement.className = `status-indicator status-${isOnline ? 'online' : 'offline'}`;
    }
}

// Add log message to logs panel
function addLog(message) {
    const logsPanel = document.getElementById('logs');
    if (logsPanel) {
        const logEntry = document.createElement('div');
        logEntry.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
        logsPanel.appendChild(logEntry);
        logsPanel.scrollTop = logsPanel.scrollHeight;
    }
}

// Show command result
function showResult(success, data) {
    const resultDiv = document.getElementById('result');
    if (!resultDiv) return;
    
    resultDiv.style.display = 'block';
    
    if (success) {
        resultDiv.innerHTML = `
            <h3>✅ Command Executed Successfully</h3>
            <div><strong>Command:</strong></div>
            <div class="command-display">${data.command || 'No command generated'}</div>
            <p><strong>Confidence:</strong> ${data.confidence ? (data.confidence * 100).toFixed(1) + '%' : 'N/A'}</p>
            <p><strong>Explanation:</strong> ${data.explanation || 'No explanation provided'}</p>
            ${data.execution_result ? `
                <p><strong>Exit Code:</strong> ${data.execution_result.exit_code || 'N/A'}</p>
                ${data.execution_result.stdout ? `<p><strong>Output:</strong></p><pre>${data.execution_result.stdout}</pre>` : ''}
                ${data.execution_result.stderr ? `<p><strong>Error:</strong></p><pre>${data.execution_result.stderr}</pre>` : ''}
            ` : ''}
        `;
    } else {
        resultDiv.innerHTML = `
            <h3>❌ Error</h3>
            <p>${data.error || 'Unknown error occurred'}</p>
        `;
    }
}

// Update metrics
function updateMetrics(success, responseTime) {
    commandCount++;
    if (success) {
        successCount++;
    }
    totalTime += responseTime;
    
    const commandCountEl = document.getElementById('commandCount');
    const successRateEl = document.getElementById('successRate');
    const avgTimeEl = document.getElementById('avgTime');
    
    if (commandCountEl) commandCountEl.textContent = commandCount;
    if (successRateEl) successRateEl.textContent = Math.round((successCount / commandCount) * 100) + '%';
    if (avgTimeEl) avgTimeEl.textContent = Math.round(totalTime / commandCount) + 'ms';
}

// Set command from examples
function setCommand(command) {
    const textInput = document.getElementById('textInput');
    if (textInput) {
        textInput.value = command;
        addLog(`📝 Command set: "${command}"`);
    }
}

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
        addLog(`❌ Błąd wysyłania komendy: ${error.message}`);
        showResult(false, { error: error.message });
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    console.log('🐛 DEBUG: DOM loaded, initializing...');
    
    // Initialize WebSocket
    initWebSocket();
    
    // Add event listeners
    const recordBtn = document.getElementById('recordBtn');
    const submitBtn = document.getElementById('submitBtn');
    const textInput = document.getElementById('textInput');
    
    if (recordBtn) {
        recordBtn.addEventListener('click', toggleRecording);
    }
    
    if (submitBtn) {
        submitBtn.addEventListener('click', () => {
            const textCommand = textInput ? textInput.value : '';
            if (textCommand.trim()) {
                addLog(`⌨️ Wykonywanie komendy: "${textCommand}"`);
                sendVoiceCommand();
            } else {
                addLog('⚠️ Wpisz komendę tekstową');
            }
        });
    }
    
    if (textInput) {
        textInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                submitBtn.click();
            }
        });
    }
    
    addLog('🚀 WebOps Voice Service initialized');
    console.log('🐛 DEBUG: Initialization complete');
});
