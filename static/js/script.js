// Tab switching functionality
document.querySelectorAll('.tab-btn').forEach(button => {
    button.addEventListener('click', () => {
        // Remove active class from all buttons and contents
        document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
        
        // Add active class to clicked button and corresponding content
        button.classList.add('active');
        document.getElementById(button.dataset.tab).classList.add('active');
    });
});

// Network type radio button functionality
document.querySelectorAll('input[name="network-type"]').forEach(radio => {
    radio.addEventListener('change', () => {
        const staticIpConfig = document.getElementById('static-ip-config');
        staticIpConfig.style.display = radio.value === 'Static IP' ? 'block' : 'none';
    });
});

// OS type change handler
document.getElementById('os-type').addEventListener('change', function() {
    const osVersionSelect = document.getElementById('os-version');
    osVersionSelect.innerHTML = '';
    
    if (this.value === 'CentOS') {
        ['8', '9', '10'].forEach(version => {
            const option = document.createElement('option');
            option.value = version;
            option.textContent = version;
            osVersionSelect.appendChild(option);
        });
    } else if (this.value === 'Ubuntu') {
        ['20', '22', '24'].forEach(version => {
            const option = document.createElement('option');
            option.value = version;
            option.textContent = version;
            osVersionSelect.appendChild(option);
        });
    }
});

// IP validation function
function isValidIP(ip) {
    const ipRegex = /^(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$/;
    return ipRegex.test(ip);
}

// Subnet mask validation function
function isValidSubnetMask(mask) {
    try {
        if (mask.includes('.')) {
            const octets = mask.split('.');
            if (octets.length !== 4) return false;
            
            const binary = octets.map(octet => {
                const num = parseInt(octet);
                if (num < 0 || num > 255) return false;
                return num.toString(2).padStart(8, '0');
            }).join('');
            
            return !binary.includes('01');
        } else {
            const cidr = parseInt(mask.replace('/', ''));
            return cidr >= 0 && cidr <= 32;
        }
    } catch (e) {
        return false;
    }
}

// Install tools button handler
document.getElementById('install-tools').addEventListener('click', async () => {
    try {
        const response = await fetch('/api/install-tools', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            }
        });
        
        if (response.ok) {
            showMessage('Tools installed successfully', 'success');
        } else {
            showMessage('Failed to install tools', 'error');
        }
    } catch (error) {
        showMessage('Error installing tools: ' + error.message, 'error');
    }
});

// Create ISO button handler
document.getElementById('create-iso-btn').addEventListener('click', async () => {
    // Validate inputs
    const osType = document.getElementById('os-type').value;
    const osVersion = document.getElementById('os-version').value;
    const networkType = document.querySelector('input[name="network-type"]:checked').value;
    
    if (osType === 'Ubuntu') {
        showMessage('Ubuntu support is coming soon! Please select CentOS for now.', 'warning');
        return;
    }
    
    if (networkType === 'Static IP') {
        const ipAddress = document.getElementById('ip-address').value;
        const subnetMask = document.getElementById('subnet-mask').value;
        const gateway = document.getElementById('gateway').value;
        
        if (!ipAddress || !subnetMask || !gateway) {
            showMessage('All network fields are required for Static IP configuration', 'error');
            return;
        }
        
        if (!isValidIP(ipAddress) || !isValidSubnetMask(subnetMask) || !isValidIP(gateway)) {
            showMessage('Please fix the network configuration errors', 'error');
            return;
        }
    }
    
    // Show progress container
    const progressContainer = document.getElementById('progress-container');
    const progressBar = progressContainer.querySelector('.progress-bar');
    const statusText = document.getElementById('status-text');
    progressContainer.style.display = 'block';
    
    try {
        // Start the ISO creation process
        const response = await fetch('/api/create-iso', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                osType,
                osVersion,
                networkType,
                ipAddress: document.getElementById('ip-address').value,
                subnetMask: document.getElementById('subnet-mask').value,
                gateway: document.getElementById('gateway').value,
                dnsServers: document.getElementById('dns-servers').value,
                idracIp: document.getElementById('idrac-ip').value,
                idracUser: document.getElementById('idrac-user').value,
                idracPassword: document.getElementById('idrac-password').value
            })
        });
        
        if (response.ok) {
            const data = await response.json();
            showMessage('ISO created successfully', 'success');
            
            // Update progress
            progressBar.style.width = '100%';
            statusText.textContent = 'ISO creation complete';
        } else {
            throw new Error('Failed to create ISO');
        }
    } catch (error) {
        showMessage('Error creating ISO: ' + error.message, 'error');
        progressBar.style.width = '0%';
        statusText.textContent = 'Failed to create ISO';
    }
});

// Helper function to show messages
function showMessage(message, type) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `${type}-message`;
    messageDiv.textContent = message;
    
    const container = document.querySelector('.container');
    container.insertBefore(messageDiv, container.firstChild);
    
    // Remove message after 5 seconds
    setTimeout(() => {
        messageDiv.remove();
    }, 5000);
}

// Initialize the page
document.addEventListener('DOMContentLoaded', () => {
    // Set up event listeners for input validation
    document.getElementById('ip-address').addEventListener('input', function() {
        if (this.value && !isValidIP(this.value)) {
            this.classList.add('is-invalid');
        } else {
            this.classList.remove('is-invalid');
        }
    });
    
    document.getElementById('subnet-mask').addEventListener('input', function() {
        if (this.value && !isValidSubnetMask(this.value)) {
            this.classList.add('is-invalid');
        } else {
            this.classList.remove('is-invalid');
        }
    });
    
    document.getElementById('gateway').addEventListener('input', function() {
        if (this.value && !isValidIP(this.value)) {
            this.classList.add('is-invalid');
        } else {
            this.classList.remove('is-invalid');
        }
    });
}); 