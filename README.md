# OS Autoinstaller Web Application

This is a web-based OS autoinstaller application that allows you to create custom CentOS installation ISOs and automatically install them on Dell servers using iDRAC.

## Features

- Create custom CentOS installation ISOs
- Configure network settings (DHCP or Static IP)
- Automatically mount and boot from ISO on Dell servers
- Support for CentOS 8, 9, and 10
- User-friendly web interface

## Prerequisites

- Python 3.7 or higher
- Access to a Proxmox server
- Dell server with iDRAC
- Required tools on the Proxmox server:
  - p7zip-full
  - xorriso
  - genisoimage
  - apache2

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd <repository-directory>
```

2. Install Python dependencies:
```bash
pip install -r requirements.txt
```

3. Make sure you have the required tools installed on your local machine:
- sshpass (will be installed automatically if not present)

## Configuration

1. Update the Proxmox server configuration in `server.py`:
```python

```

2. Make sure the Proxmox server has the required CentOS ISO files in `/var/www/html/`:
- CentOS-Stream-8-latest-x86_64-dvd1.iso
- CentOS-Stream-9-latest-x86_64-dvd1.iso
- CentOS-Stream-10-latest-x86_64-dvd1.iso

## Running the Application

1. Start the Flask server:
```bash
python server.py
```

2. Open your web browser and navigate to:
```
http://localhost:5000
```

## Usage

1. Enter the server details (iDRAC IP, username, and password)
2. Select the OS type and version
3. Configure network settings (DHCP or Static IP)
4. Click "Install Required Tools" to ensure all necessary tools are installed
5. Click "Create Your ISO" to start the installation process

## Security Notes

- This application requires direct access to the Proxmox server and iDRAC
- Make sure to use secure passwords and consider using environment variables for sensitive information
- The application uses SSH with password authentication - consider using SSH keys for better security

## Troubleshooting

- If the ISO creation fails, check the Proxmox server logs
- Make sure the Proxmox server has enough disk space
- Verify that the CentOS ISO files are present in the correct location
- Check the iDRAC connection and credentials

## License

This project is licensed under the MIT License - see the LICENSE file for details. 
