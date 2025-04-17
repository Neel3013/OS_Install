// Add debug logging
console.log('main.js loaded');

// DOM Elements
const isoForm = document.getElementById('isoCreationForm');
const installToolsBtn = document.getElementById('installToolsBtn');
const createIsoBtn = document.getElementById('createIsoBtn');
const spinnerContainer = document.getElementById('spinner-container');
const logContainer = document.getElementById('logContainer');
const logsElement = document.getElementById('logs');

// Initialize event listeners
document.addEventListener('DOMContentLoaded', () => {
    // Form submission
    isoForm.addEventListener('submit', (e) => {
        e.preventDefault();
        createISO();
    });

    // Install tools button
    installToolsBtn.addEventListener('click', () => {
        installTools();
    });
});

// Install required tools
function installTools() {
    showSpinner();
    showLogs();
    appendLog('Installing required tools...', 'info');

    fetch('/api/install-tools', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.error) {
            appendLog(data.error, 'error');
        } else {
            appendLog('Tools installed successfully!', 'success');
        }
    })
    .catch(error => {
        appendLog(`Error: ${error.message}`, 'error');
    })
    .finally(() => {
        hideSpinner();
    });
}

// Create ISO image
function createISO() {
    // Validate form
    if (!isoForm.checkValidity()) {
        isoForm.reportValidity();
        return;
    }

    // Show UI indicators
    showSpinner();
    showLogs();
    clearLogs();
    
    // Disable buttons while processing
    disableButtons(true);
    
    // Get form data
    const formData = {
        osType: document.getElementById('osType').value,
        osVersion: document.getElementById('osVersion').value,
        idracIp: document.getElementById('idracIp').value,
        idracUser: document.getElementById('idracUser').value,
        idracPassword: document.getElementById('idracPassword').value,
        ipAddress: document.getElementById('ipAddress').value,
        subnetMask: document.getElementById('subnetMask').value,
        gateway: document.getElementById('gateway').value,
        dnsServers: document.getElementById('dnsServers').value
    };

    // Log start of process
    appendLog('Starting ISO creation process...', 'info');
    
    // Make POST request to create the ISO
    fetch('/api/create-iso', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify(formData)
    })
    .then(response => {
        if (!response.ok) {
            if (response.status === 409) {
                throw new Error('Another ISO creation process is already running');
            } else {
                return response.json().then(data => {
                    throw new Error(data.error || 'Error creating ISO');
                });
            }
        }
        
        // Stream is starting, continue reading the response
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        
        function processStream() {
            return reader.read().then(({ done, value }) => {
                if (done) {
                    appendLog('Stream completed', 'info');
                    disableButtons(false);
                    hideSpinner();
                    return;
                }
                
                const chunk = decoder.decode(value, { stream: true });
                const lines = chunk.split('\n\n');
                
                for (const line of lines) {
                    if (line.startsWith('data: ')) {
                        try {
                            const jsonData = JSON.parse(line.substring(6));
                            if (jsonData.type && jsonData.message) {
                                appendLog(jsonData.message, jsonData.type);
                                
                                // Check for completion
                                if (jsonData.type === 'success' && jsonData.message.includes('reboot')) {
                                    appendLog('ISO creation and server setup completed successfully!', 'success');
                                    disableButtons(false);
                                    hideSpinner();
                                }
                            }
                        } catch (e) {
                            // For non-JSON data
                            if (line.includes('ERROR')) {
                                appendLog('Error occurred during ISO creation', 'error');
                                disableButtons(false);
                                hideSpinner();
                            } else if (line.includes('COMPLETE')) {
                                appendLog('ISO creation completed successfully!', 'success');
                                disableButtons(false);
                                hideSpinner();
                            }
                        }
                    }
                }
                
                // Continue reading
                return processStream();
            });
        }
        
        // Start processing the stream
        return processStream();
    })
    .catch(error => {
        appendLog(`Error: ${error.message}`, 'error');
        disableButtons(false);
        hideSpinner();
    });
}

// Handle log messages from SSE
function handleEventMessage(data) {
    // Handle different message types based on data structure
    try {
        const jsonData = JSON.parse(data);
        if (jsonData.type && jsonData.message) {
            appendLog(jsonData.message, jsonData.type);
            
            // Check for completion
            if (jsonData.type === 'success' && jsonData.message.includes('reboot')) {
                appendLog('ISO creation and server setup completed successfully!', 'success');
                disableButtons(false);
                hideSpinner();
            }
        }
    } catch (error) {
        // Handle non-JSON messages
        if (data.includes('ERROR')) {
            appendLog('An error occurred during ISO creation', 'error');
            disableButtons(false);
            hideSpinner();
        } else if (data.includes('COMPLETE')) {
            appendLog('ISO created successfully!', 'success');
            disableButtons(false);
            hideSpinner();
        } else {
            appendLog(data, 'info');
        }
    }
}

// Helper functions
function showSpinner() {
    spinnerContainer.classList.remove('hidden');
}

function hideSpinner() {
    spinnerContainer.classList.add('hidden');
}

function showLogs() {
    logContainer.classList.remove('hidden');
}

function clearLogs() {
    logsElement.innerHTML = '';
}

function appendLog(message, type = 'info') {
    const logEntry = document.createElement('div');
    logEntry.className = `log-entry log-${type}`;
    
    // Format timestamp
    const now = new Date();
    const timestamp = now.toLocaleTimeString();
    
    logEntry.textContent = `[${timestamp}] ${message}`;
    logsElement.appendChild(logEntry);
    
    // Auto-scroll to bottom
    logContainer.scrollTop = logContainer.scrollHeight;
}

function disableButtons(disabled) {
    createIsoBtn.disabled = disabled;
    installToolsBtn.disabled = disabled;
}

// Remove duplicate CSS since it's already in style.css
const oldStyle = document.querySelector('style:not([id])');
if (oldStyle) {
    oldStyle.remove();
} 