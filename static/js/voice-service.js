/**
 * WebOps Voice Service - Frontend JavaScript
 * Voice-controlled command execution with continuous streaming
 */

// Global variables
let ws = null;
let commandCount = 0;
let successCount = 0;
let totalTime = 0;
let commandHistory = []; // Store executed commands

// Voice feedback settings
let voiceFeedbackEnabled = true;
let voiceFeedbackVolume = 0.7;

// Command suggestions settings
let commandSuggestionsEnabled = true;
let currentSuggestions = [];
let selectedSuggestionIndex = -1;

// Common command patterns for autocomplete
const commonCommandPatterns = [
    'list files', 'show directory contents', 'show current directory',
    'show running processes', 'show system processes', 'check disk space',
    'list containers', 'find files larger than', 'show network connections',
    'display system info', 'show memory usage', 'check cpu usage',
    'list users', 'show logged in users', 'display environment variables',
    'show mounted filesystems', 'check system load', 'show kernel version',
    'list installed packages', 'show service status', 'check port usage'
];

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
    
    // Determine actual success based on exit code if execution_result exists
    const actualSuccess = data.execution_result ? data.execution_result.exit_code === 0 : success;
    
    if (actualSuccess) {
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
        // Provide better error messages for common exit codes
        let errorMessage = data.error || 'Unknown error occurred';
        let errorTitle = '❌ Command Execution Failed';
        
        if (data.execution_result) {
            const exitCode = data.execution_result.exit_code;
            switch (exitCode) {
                case 127:
                    errorMessage = 'Command not found. The generated command is not available in the current environment.';
                    break;
                case 1:
                    errorMessage = data.execution_result.stderr || 'Command failed with exit code 1 (general error).';
                    break;
                case 2:
                    errorMessage = 'Command failed with exit code 2 (misuse of shell builtins).';
                    break;
                case 126:
                    errorMessage = 'Command found but not executable (permission denied).';
                    break;
                case 124:
                    errorMessage = 'Command execution timed out.';
                    break;
                default:
                    if (exitCode > 128) {
                        errorMessage = `Command terminated by signal ${exitCode - 128}.`;
                    } else {
                        errorMessage = `Command failed with exit code ${exitCode}.`;
                    }
            }
        }
        
        resultDiv.innerHTML = `
            <h3>${errorTitle}</h3>
            <div><strong>Command:</strong></div>
            <div class="command-display">${data.command || 'No command generated'}</div>
            <p><strong>Confidence:</strong> ${data.confidence ? (data.confidence * 100).toFixed(1) + '%' : 'N/A'}</p>
            <p><strong>Explanation:</strong> ${data.explanation || 'No explanation provided'}</p>
            ${data.execution_result ? `
                <p><strong>Exit Code:</strong> ${data.execution_result.exit_code || 'N/A'}</p>
                ${data.execution_result.stdout ? `<p><strong>Output:</strong></p><pre>${data.execution_result.stdout}</pre>` : ''}
                ${data.execution_result.stderr ? `<p><strong>Error:</strong></p><pre>${data.execution_result.stderr}</pre>` : ''}
            ` : ''}
            <p><strong>Error Details:</strong></p>
            <div class="error-message">${errorMessage}</div>
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

// Add command to history
function addCommandToHistory(textCommand, result) {
    const historyEntry = {
        textCommand: textCommand,
        generatedCommand: result.command,
        confidence: result.confidence,
        success: result.success,
        timestamp: new Date(),
        executionResult: result.execution_result
    };
    
    // Add to beginning of history (most recent first)
    commandHistory.unshift(historyEntry);
    
    // Limit history to last 50 commands
    if (commandHistory.length > 50) {
        commandHistory.pop();
    }
    
    // Update history display
    updateCommandHistoryDisplay();
    
    // Provide voice feedback
    provideVoiceFeedback(result.success, result.command);
}

// Provide voice feedback for command results
function provideVoiceFeedback(success, command) {
    if (!voiceFeedbackEnabled || !('speechSynthesis' in window)) {
        return;
    }
    
    const utterance = new SpeechSynthesisUtterance();
    utterance.volume = voiceFeedbackVolume;
    utterance.rate = 1.0;
    utterance.pitch = 1.0;
    
    if (success) {
        utterance.text = `Command executed successfully: ${command || 'command completed'}`;
        utterance.lang = 'en-US'; // English for success messages
    } else {
        utterance.text = 'Command execution failed';
        utterance.lang = 'en-US'; // English for error messages
    }
    
    // Add some personality with voice selection
    const voices = speechSynthesis.getVoices();
    if (voices.length > 0) {
        // Try to find a pleasant voice
        const preferredVoice = voices.find(voice => 
            voice.name.includes('Google') || 
            voice.name.includes('Microsoft') || 
            voice.lang.startsWith('en')
        );
        if (preferredVoice) {
            utterance.voice = preferredVoice;
        }
    }
    
    speechSynthesis.speak(utterance);
}

// Toggle voice feedback
function toggleVoiceFeedback() {
    voiceFeedbackEnabled = !voiceFeedbackEnabled;
    const status = voiceFeedbackEnabled ? 'enabled' : 'disabled';
    addLog(`🔊 Voice feedback ${status}`);
    
    // Provide immediate feedback
    if (voiceFeedbackEnabled) {
        const testUtterance = new SpeechSynthesisUtterance('Voice feedback enabled');
        testUtterance.volume = voiceFeedbackVolume;
        speechSynthesis.speak(testUtterance);
    }
}

// Generate command suggestions based on input
function generateSuggestions(input) {
    if (!commandSuggestionsEnabled || input.length < 2) {
        return [];
    }
    
    const inputLower = input.toLowerCase();
    const suggestions = [];
    
    // Add suggestions from command history (recent commands first)
    commandHistory.forEach(entry => {
        if (entry.textCommand.toLowerCase().includes(inputLower) && 
            !suggestions.includes(entry.textCommand)) {
            suggestions.push(entry.textCommand);
        }
    });
    
    // Add suggestions from common patterns
    commonCommandPatterns.forEach(pattern => {
        if (pattern.toLowerCase().includes(inputLower) && 
            !suggestions.includes(pattern)) {
            suggestions.push(pattern);
        }
    });
    
    return suggestions.slice(0, 5); // Limit to 5 suggestions
}

// Display command suggestions
function displaySuggestions(suggestions) {
    const existingDropdown = document.querySelector('.suggestions-dropdown');
    if (existingDropdown) {
        existingDropdown.remove();
    }
    
    if (suggestions.length === 0) {
        selectedSuggestionIndex = -1;
        return;
    }
    
    const textInput = document.getElementById('textInput');
    const dropdown = document.createElement('div');
    dropdown.className = 'suggestions-dropdown';
    
    suggestions.forEach((suggestion, index) => {
        const item = document.createElement('div');
        item.className = 'suggestion-item';
        item.textContent = suggestion;
        item.onclick = () => selectSuggestion(suggestion);
        item.onmouseenter = () => highlightSuggestion(index);
        dropdown.appendChild(item);
    });
    
    textInput.parentNode.appendChild(dropdown);
    selectedSuggestionIndex = -1;
}

// Hide suggestions dropdown
function hideSuggestions() {
    const dropdown = document.querySelector('.suggestions-dropdown');
    if (dropdown) {
        dropdown.remove();
    }
    selectedSuggestionIndex = -1;
}

// Select a suggestion
function selectSuggestion(suggestion) {
    const textInput = document.getElementById('textInput');
    textInput.value = suggestion;
    hideSuggestions();
    addLog(`💡 Selected suggestion: "${suggestion}"`);
}

// Highlight suggestion for keyboard navigation
function highlightSuggestion(index) {
    const items = document.querySelectorAll('.suggestion-item');
    items.forEach((item, i) => {
        if (i === index) {
            item.classList.add('highlighted');
            selectedSuggestionIndex = index;
        } else {
            item.classList.remove('highlighted');
        }
    });
}

// Handle keyboard navigation for suggestions
function handleSuggestionKeys(event) {
    const suggestions = document.querySelectorAll('.suggestion-item');
    if (suggestions.length === 0) return;
    
    switch (event.key) {
        case 'ArrowDown':
            event.preventDefault();
            selectedSuggestionIndex = Math.min(selectedSuggestionIndex + 1, suggestions.length - 1);
            highlightSuggestion(selectedSuggestionIndex);
            break;
        case 'ArrowUp':
            event.preventDefault();
            selectedSuggestionIndex = Math.max(selectedSuggestionIndex - 1, -1);
            highlightSuggestion(selectedSuggestionIndex);
            break;
        case 'Enter':
            if (selectedSuggestionIndex >= 0) {
                event.preventDefault();
                const selectedSuggestion = suggestions[selectedSuggestionIndex].textContent;
                selectSuggestion(selectedSuggestion);
            }
            break;
        case 'Escape':
            hideSuggestions();
            break;
    }
}

// Handle input changes for suggestions
function handleInputChange() {
    const textInput = document.getElementById('textInput');
    const input = textInput.value.trim();
    
    if (input.length >= 2 && commandSuggestionsEnabled) {
        currentSuggestions = generateSuggestions(input);
        displaySuggestions(currentSuggestions);
    } else {
        hideSuggestions();
    }
}

// Update command history display
function updateCommandHistoryDisplay() {
    const historyContainer = document.getElementById('commandHistory');
    if (!historyContainer) return;
    
    if (commandHistory.length === 0) {
        historyContainer.innerHTML = '<div class="history-item">No commands executed yet</div>';
        return;
    }
    
    historyContainer.innerHTML = commandHistory.map((entry, index) => {
        const timeString = entry.timestamp.toLocaleTimeString();
        const confidencePercent = entry.confidence ? (entry.confidence * 100).toFixed(1) : 'N/A';
        const statusIcon = entry.success ? '✅' : '❌';
        
        return `
            <div class="history-item" onclick="reuseCommand(${index})">
                <div class="history-command">${entry.textCommand}</div>
                <div class="history-details">
                    <span class="history-time">${timeString}</span>
                    <span class="history-confidence">📊 ${confidencePercent}%</span>
                    <span class="history-status">${statusIcon}</span>
                </div>
                ${entry.generatedCommand ? `<div class="history-generated">🔧 ${entry.generatedCommand}</div>` : ''}
            </div>
        `;
    }).join('');
}

// Reuse command from history
function reuseCommand(index) {
    if (index >= 0 && index < commandHistory.length) {
        const entry = commandHistory[index];
        const textInput = document.getElementById('textInput');
        if (textInput) {
            textInput.value = entry.textCommand;
            addLog(`📝 Reused command from history: "${entry.textCommand}"`);
        }
    }
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
        
        // Add command to history
        addCommandToHistory(textCommand, result);
        
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
        
        // Add suggestion event listeners
        textInput.addEventListener('input', handleInputChange);
        textInput.addEventListener('keydown', handleSuggestionKeys);
        textInput.addEventListener('blur', () => {
            // Delay hiding suggestions to allow clicks on them
            setTimeout(hideSuggestions, 150);
        });
        textInput.addEventListener('focus', handleInputChange);
    }
    
    addLog('🚀 WebOps Voice Service initialized');
    console.log('🐛 DEBUG: Initialization complete');
});
