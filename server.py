import logging
import io
import time
import json
import sys
import os
import subprocess
import requests
import ipaddress
from urllib3.exceptions import InsecureRequestWarning
from flask import Flask, request, jsonify, Response, stream_with_context, send_from_directory
from flask_cors import CORS
import uuid
import tempfile
import glob
import threading

# Configure logging first
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Create a StringIO object to capture logs
log_stream = io.StringIO()
stream_handler = logging.StreamHandler(log_stream)
stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logger.addHandler(stream_handler)

# Suppress insecure request warnings
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Initialize Flask app with proper static folder configuration
app = Flask(__name__, 
    static_folder='static',
    static_url_path='/static'
)
CORS(app)

# Proxmox server configuration
proxmox_ip = "10.219.82.112"
proxmox_user = "root"
proxmox_password = "Jtaclab123"

# Global boot path variables
ISOLINUX_BIN_PATH = "isolinux/isolinux.bin"
BOOT_CAT_PATH = "isolinux/boot.cat"

# Process lock to prevent duplicate ISO creation
iso_creation_lock = threading.Lock()
active_processes = {}

def run_remote_command(command, proxmox_ip, proxmox_user, proxmox_password):
    """Execute command on remote Proxmox server"""
    try:
        cmd = [
            "sshpass", "-p", proxmox_password,
            "ssh", "-o", "StrictHostKeyChecking=no",
            f"{proxmox_user}@{proxmox_ip}",
            command
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        logger.error(f"Remote command failed: {e}")
        logger.error(f"Error output: {e.stderr}")
        return None

def install_local_tools():
    """Install necessary tools on local machine"""
    try:
        # Check if sshpass is installed
        result = subprocess.run(["which", "sshpass"], capture_output=True, text=True)
        if result.returncode != 0:
            logger.info("Installing sshpass...")
            if sys.platform == "darwin":  # macOS
                subprocess.run(["brew", "install", "sshpass"], check=True)
            elif sys.platform.startswith("linux"):
                subprocess.run(["sudo", "apt", "install", "-y", "sshpass"], check=True)
            else:
                logger.error("Unsupported OS. Please install sshpass manually.")
                return False
        return True
    except Exception as e:
        logger.error(f"Failed to install tools: {e}")
        return False

def subnet_to_cidr(subnet_mask):
    """Convert subnet mask to CIDR notation"""
    try:
        if '/' in subnet_mask:
            cidr = int(subnet_mask.replace('/', ''))
            if cidr < 0 or cidr > 32:
                return "/24"
            return subnet_mask
        
        octets = subnet_mask.split('.')
        if len(octets) != 4:
            return "/24"
        
        binary = ''.join([bin(int(x))[2:].zfill(8) for x in octets])
        cidr = binary.count('1')
        
        if '01' in binary:
            return "/24"
            
        return f"/{cidr}"
    except Exception as e:
        logger.error(f"Error converting subnet mask {subnet_mask}: {e}")
        return "/24"

@app.route('/')
def index():
    """Serve the main page"""
    try:
        return send_from_directory('templates', 'index.html')
    except Exception as e:
        logger.error(f"Error serving index.html: {e}")
        return jsonify({"error": "Failed to load page"}), 500

@app.route('/favicon.ico')
def favicon():
    """Serve the favicon"""
    try:
        return send_from_directory('static/img', 'favicon.ico', mimetype='image/vnd.microsoft.icon')
    except Exception as e:
        logger.warning(f"Favicon not found: {e}")
        return '', 404  # Return empty response with 404 status

@app.route('/api/install-tools', methods=['POST'])
def install_tools():
    try:
        logger.info("Installing tools on Proxmox server...")
        
        # Run command on Proxmox server to install required tools
        cmd = "apt update && apt install -y p7zip-full xorriso genisoimage apache2"
        result = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
        
        if result is None:
            logger.error("Failed to install tools on Proxmox server")
            return jsonify({'error': 'Failed to install tools on Proxmox server'}), 500
        
        # Install local tools if needed
        logger.info("Installing local tools...")
        try:
            # Check if sshpass is installed
            subprocess.run(["which", "sshpass"], capture_output=True, text=True, check=True)
            logger.info("sshpass is already installed")
        except subprocess.CalledProcessError:
            logger.info("Installing sshpass...")
            if sys.platform == "darwin":  # macOS
                subprocess.run(["brew", "install", "sshpass"], check=True)
            elif sys.platform.startswith("linux"):
                subprocess.run(["sudo", "apt", "install", "-y", "sshpass"], check=True)
            else:
                return jsonify({'error': 'Unsupported OS. Please install sshpass manually.'}), 500
        
        return jsonify({'success': True, 'message': 'Tools installed successfully'})
    except Exception as e:
        logger.error(f"Error installing tools: {str(e)}")
        return jsonify({'error': f'Error installing tools: {str(e)}'}), 500

@app.route('/api/create-iso', methods=['POST'])
def create_iso():
    try:
        data = request.get_json()
        if not data:
            logger.error("No data provided")
            return jsonify({'error': 'No data provided'}), 400

        # Extract and validate required fields
        required_fields = {
            'osType': data.get('osType'),
            'osVersion': data.get('osVersion'),
            'idracIp': data.get('idracIp'),
            'idracUser': data.get('idracUser'),
            'idracPassword': data.get('idracPassword'),
            'ipAddress': data.get('ipAddress'),
            'subnetMask': data.get('subnetMask'),
            'gateway': data.get('gateway'),
            'dnsServers': data.get('dnsServers')
        }

        # Check for missing required fields
        missing_fields = [field for field, value in required_fields.items() if not value]
        if missing_fields:
            error_msg = f"Missing required fields: {', '.join(missing_fields)}"
            logger.error(error_msg)
            return jsonify({'error': error_msg}), 400

        # Generate a unique process ID based on the request data
        process_id = f"{data['osType']}_{data['osVersion']}_{data['idracIp']}"
        
        # Check if this exact process is already running
        if process_id in active_processes:
            logger.warning(f"Process already running for {process_id}")
            return jsonify({'error': 'An ISO creation process is already running for this configuration'}), 409
            
        # Acquire lock to prevent race conditions
        if not iso_creation_lock.acquire(blocking=False):
            logger.warning("Another ISO creation process is already in progress")
            return jsonify({'error': 'Another ISO creation process is already in progress'}), 409

        try:
            # Mark this process as active
            active_processes[process_id] = True
            
            # Clear previous logs
            log_stream.truncate(0)
            log_stream.seek(0)

            # Generate unique identifier for this session
            user_id = str(uuid.uuid4())[:8]

            # Define paths outside the generator to ensure they're only created once
            os_type = data['osType']
            os_version = data['osVersion']
            working_dir = f"/root/centos{os_version}-autoinstall-ISO-{user_id}"
            source_dir = f"{working_dir}/source-files"
            
            # Handle different ISO naming conventions
            if os_version == "10":
                iso_file = f"/var/www/html/CentOS-Stream-10-latest-x86_64-dvd1.iso"
            else:
                iso_file = f"/var/www/html/CentOS-Stream-{os_version}-latest-x86_64-dvd1.iso"
            
            crafted_iso = f"/var/www/html/user-{user_id}-centos{os_version}.iso"

            def generate():
                try:
                    # Log the start of the process
                    yield f"data: {json.dumps({'type': 'info', 'message': 'Starting ISO creation process'})}\n\n"
                    yield f"data: {json.dumps({'type': 'info', 'message': f'Creating ISO for {os_type} {os_version}'})}\n\n"
                    
                    # Step 2: Create directories and extract ISO
                    yield f"data: {json.dumps({'type': 'info', 'message': 'Creating directories and extracting ISO...'})}\n\n"
                    
                    cmds = [
                        f"mkdir -p {working_dir}",
                        f"mkdir -p {source_dir}",
                        f"cp {iso_file} {working_dir}/centos.iso",
                        f"7z x {working_dir}/centos.iso -o{source_dir} -y"
                    ]
                    
                    for cmd in cmds:
                        result = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                        if result is None:
                            error_msg = f"Failed to execute: {cmd}"
                            yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
                            yield f"data: ERROR\n\n"
                            return
                        yield f"data: {json.dumps({'type': 'info', 'message': f'Executed: {cmd}'})}\n\n"

                    # Step 3: Find and modify boot configurations
                    logger.info("Configuring boot options...")
                    yield f"data: {json.dumps({'type': 'info', 'message': 'Configuring boot options...'})}\n\n"

                    if os_version == "10":
                        # For CentOS 10, find boot config files
                        cmd = f"find {source_dir} -name '*.cfg' -type f | sort"
                        config_files = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                        if config_files:
                            logger.info(f"Found config files: {config_files}")
                            yield f"data: {json.dumps({'type': 'info', 'message': f'Found config files: {config_files}'})}\n\n"
                        
                        # Find isolinux.cfg
                        cmd = f"find {source_dir} -name 'isolinux.cfg' -type f | sort"
                        isolinux_result = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                        if isolinux_result:
                            isolinux_cfg = isolinux_result.strip().split("\n")[0]
                            logger.info(f"Found isolinux.cfg at: {isolinux_cfg}")
                            yield f"data: Found isolinux.cfg at: {isolinux_cfg}\n\n"
                        else:
                            logger.warning("isolinux.cfg not found, searching for alternatives...")
                            yield f"data: {json.dumps({'type': 'info', 'message': 'isolinux.cfg not found, searching for alternatives...'})}\n\n"
                            cmd = f"find {source_dir} -path '*isolinux*' -name '*.cfg' -type f | sort"
                            isolinux_cfg = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                            if isolinux_cfg:
                                isolinux_cfg = isolinux_cfg.strip().split("\n")[0]
                                logger.info(f"Using alternative isolinux config: {isolinux_cfg}")
                                yield f"data: {json.dumps({'type': 'info', 'message': f'Using alternative isolinux config: {isolinux_cfg}'})}\n\n"
                            else:
                                logger.warning("No isolinux configuration found. Creating isolinux directory structure...")
                                yield f"data: {json.dumps({'type': 'info', 'message': 'No isolinux configuration found. Creating isolinux directory structure...'})}\n\n"
                                
                                # Create isolinux directories
                                isolinux_dir = f"{source_dir}/isolinux"
                                cmds = [
                                    f"mkdir -p {isolinux_dir}",
                                    f"find {source_dir} -name '*.bin' -type f -exec cp {{}} {isolinux_dir}/isolinux.bin \\;",
                                    f"find {source_dir} -name 'isolinux.bin' -type f -exec cp {{}} {isolinux_dir}/isolinux.bin \\;",
                                    f"touch {isolinux_dir}/boot.cat"
                                ]
                                
                                for cmd in cmds:
                                    result = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                                    if result is None:
                                        logger.warning(f"Failed to execute: {cmd}")
                                        yield f"data: {json.dumps({'type': 'warning', 'message': f'Failed to execute: {cmd}'})}\n\n"
                                    else:
                                        logger.info(f"Executed: {cmd}")
                                        yield f"data: {json.dumps({'type': 'info', 'message': f'Executed: {cmd}'})}\n\n"
                                
                                isolinux_cfg = f"{isolinux_dir}/isolinux.cfg"
                                logger.info(f"Using created isolinux.cfg at: {isolinux_cfg}")
                                yield f"data: {json.dumps({'type': 'info', 'message': f'Using created isolinux.cfg at: {isolinux_cfg}'})}\n\n"

                        # Find grub.cfg
                        cmd = f"find {source_dir} -path '*EFI/BOOT*' -name 'grub.cfg' -type f | sort"
                        grub_result = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                        if grub_result:
                            grub_cfg = grub_result.strip().split("\n")[0]
                            logger.info(f"Found EFI grub.cfg at: {grub_cfg}")
                            yield f"data: Found EFI grub.cfg at: {grub_cfg}\n\n"
                        else:
                            logger.warning("EFI grub.cfg not found, searching for alternatives...")
                            yield f"data: EFI grub.cfg not found, searching for alternatives...\n\n"
                            cmd = f"find {source_dir} -name 'grub.cfg' -type f | sort"
                            grub_result = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                            if grub_result:
                                grub_cfg = grub_result.strip().split("\n")[0]
                                logger.info(f"Using alternative grub.cfg: {grub_cfg}")
                                yield f"data: Using alternative grub.cfg: {grub_cfg}\n\n"
                            else:
                                logger.warning("No grub configuration found. EFI boot might not work.")
                                yield f"data: No grub configuration found. EFI boot might not work.\n\n"
                                grub_cfg = f"{source_dir}/EFI/BOOT/grub.cfg"

                        # For CentOS 10, check paths of vmlinuz and initrd.img
                        cmd = f"find {source_dir} -name 'vmlinuz' -type f | sort"
                        vmlinuz_path = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                        if vmlinuz_path:
                            logger.info(f"Found vmlinuz at: {vmlinuz_path}")
                            vmlinuz = vmlinuz_path.strip().split("\n")[0]
                            rel_vmlinuz = '/' + os.path.relpath(vmlinuz, source_dir)
                        else:
                            logger.warning("vmlinuz not found, using default path")
                            rel_vmlinuz = "/images/pxeboot/vmlinuz"

                        cmd = f"find {source_dir} -name 'initrd.img' -type f | sort"
                        initrd_path = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                        if initrd_path:
                            logger.info(f"Found initrd.img at: {initrd_path}")
                            initrd = initrd_path.strip().split("\n")[0]
                            rel_initrd = '/' + os.path.relpath(initrd, source_dir)
                        else:
                            logger.warning("initrd.img not found, using default path")
                            rel_initrd = "/images/pxeboot/initrd.img"

                        # Modified boot configuration options for CentOS 10
                        isolinux_boot_option = f"""default autoinstall
timeout 5

label autoinstall
    menu label ^Autoinstall CentOS {os_version} for User {user_id}
    kernel {rel_vmlinuz}
    append initrd={rel_initrd} inst.ks=cdrom:/kickstart.cfg quiet

label linux
    menu label ^Install CentOS {os_version}
    kernel {rel_vmlinuz}
    append initrd={rel_initrd}
"""

                        grub_boot_option = f"""set default=0
set timeout=5

menuentry 'Autoinstall CentOS {os_version} for User {user_id}' --class fedora --class gnu-linux --class gnu --class os {{
    linuxefi {rel_vmlinuz} inst.ks=cdrom:/kickstart.cfg quiet
    initrdefi {rel_initrd}
}}

menuentry 'Install CentOS {os_version}' --class fedora --class gnu-linux --class gnu --class os {{
    linuxefi {rel_vmlinuz}
    initrdefi {rel_initrd}
}}
"""
                    else:
                        # For CentOS 8/9, use the standard paths
                        isolinux_cfg = f"{source_dir}/isolinux/isolinux.cfg"
                        grub_cfg = f"{source_dir}/EFI/BOOT/grub.cfg"
                        
                        isolinux_boot_option = f"""default autoinstall
timeout 5

label autoinstall
    menu label ^Autoinstall CentOS {os_version} for User {user_id}
    kernel vmlinuz
    append initrd=initrd.img inst.ks=cdrom:/kickstart.cfg inst.text inst.cmdline quiet

label linux
    menu label ^Install CentOS {os_version}
    kernel vmlinuz
    append initrd=initrd.img
"""

                        grub_boot_option = f"""set default=0
set timeout=5

menuentry 'Autoinstall CentOS {os_version} for User {user_id}' --class fedora --class gnu-linux --class gnu --class os {{
    linuxefi /images/pxeboot/vmlinuz inst.ks=cdrom:/kickstart.cfg inst.text inst.cmdline quiet
    initrdefi /images/pxeboot/initrd.img
}}

menuentry 'Install CentOS {os_version}' --class fedora --class gnu-linux --class gnu --class os {{
    linuxefi /images/pxeboot/vmlinuz
    initrdefi /images/pxeboot/initrd.img
}}
"""

                    # Write boot configuration files
                    cmds = [
                        f"mkdir -p $(dirname {isolinux_cfg})",
                        f"cat > {isolinux_cfg} << 'EOL'\n{isolinux_boot_option}\nEOL",
                        f"mkdir -p $(dirname {grub_cfg})",
                        f"cat > {grub_cfg} << 'EOL'\n{grub_boot_option}\nEOL"
                    ]

                    for cmd in cmds:
                        result = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                        if result is None:
                            logger.warning(f"Failed to execute: {cmd}")
                            yield f"data: Warning: Failed to execute: {cmd}\n\n"
                            logger.warning("Continuing despite the error...")
                            yield f"data: Warning: Continuing despite the error...\n\n"
                        else:
                            logger.info(f"Executed: {cmd}")
                            yield f"data: Executed: {cmd}\n\n"

                    # Step 4: Create kickstart file
                    logger.info("Creating kickstart file...")
                    yield f"data: Creating kickstart file...\n\n"

                    kickstart_path = f"{source_dir}/kickstart.cfg"
                    
                    # Check if all network configuration fields are provided
                    if data.get('ipAddress') and data.get('subnetMask') and data.get('gateway'):
                        # Static IP configuration
                        cidr = subnet_to_cidr(data['subnetMask'])
                        dns_list = data['dnsServers'].replace(" ", "").split(",") if data['dnsServers'] else ["8.8.8.8"]
                        network_config = (
                            f"network --bootproto=static --device=link --activate --onboot=yes "
                            f"--ip={data['ipAddress']} --netmask={data['subnetMask']} --gateway={data['gateway']} "
                            f"--nameserver={','.join(dns_list)}"
                        )
                    else:
                        # DHCP configuration
                        network_config = "network --bootproto=dhcp --device=link --activate --onboot=yes"

                    # Create appropriate kickstart content for CentOS version
                    if os_version == "10":
                        kickstart_content = f"""# CentOS {os_version} Kickstart File for User {user_id}
# System language
lang en_US.UTF-8
# Keyboard layouts
keyboard us
# Enable network interface and set it up
{network_config}
# Root password
rootpw --plaintext centos123
# Create user
user --name=centos --password=centos123 --groups=wheel
# System timezone
timezone America/New_York --utc
# System bootloader configuration
bootloader --location=mbr --append="crashkernel=auto"
# Clear the Master Boot Record
zerombr
# Partition clearing information
clearpart --all --initlabel
# Disk partitioning information
autopart
# System services
services --enabled="chronyd"
# System firewall
firewall --disabled
# SELinux configuration
selinux --disabled

%packages
@^minimal-environment
chrony
wget
vim
net-tools
%end

%post
echo "Installation complete for User {user_id}"
%end

reboot
"""
                    else:
                        # CentOS 8/9 kickstart
                        kickstart_content = f"""# CentOS {os_version} Kickstart File for User {user_id}
text
lang en_US.UTF-8
keyboard us
timezone America/New_York --utc
rootpw --plaintext centos123
user --name=centos --password=centos123
bootloader --location=mbr
zerombr
clearpart --all --initlabel
autopart

# Network configuration
{network_config}

services --enabled=sshd,NetworkManager
firewall --disabled
selinux --disabled

%packages
@^minimal-environment
wget
vim
net-tools
NetworkManager
%end

%post --log=/root/kickstart-post.log
# Modify repositories for CentOS 8
if [ "{os_version}" == "8" ]; then
    sed -i '/mirrorlist=/s/^/#/' /etc/yum.repos.d/CentOS-Stream-*.repo
    sed -i '/baseurl=/s/^#//' /etc/yum.repos.d/CentOS-Stream-*.repo
    sed -i 's|^baseurl=.*|baseurl=http://vault.centos.org/$contentdir/$releasever/BaseOS/$basearch/os/|' /etc/yum.repos.d/CentOS-Stream-BaseOS.repo
    sed -i 's|^baseurl=.*|baseurl=http://vault.centos.org/$contentdir/$releasever/AppStream/$basearch/os/|' /etc/yum.repos.d/CentOS-Stream-AppStream.repo
    sed -i 's|^baseurl=.*|baseurl=http://vault.centos.org/$contentdir/$releasever/BaseOS/$basearch/os/|' /etc/yum.repos.d/CentOS-Stream-Extras.repo
    sed -i 's|^baseurl=.*|baseurl=http://vault.centos.org/$contentdir/$releasever/BaseOS/$basearch/os/|' /etc/yum.repos.d/CentOS-Stream-Extras-common.repo
fi
echo "Repository configuration complete for User {user_id}"
%end

reboot
"""

                    cmd = f"cat > {kickstart_path} << 'EOL'\n{kickstart_content}\nEOL"
                    result = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                    if result is None:
                        error_msg = "Failed to create kickstart file"
                        logger.error(error_msg)
                        yield f"data: {error_msg}\n\n"
                        yield f"data: ERROR\n\n"
                        return

                    # Step 5: Create ISO
                    logger.info("Creating bootable ISO...")
                    yield f"data: {json.dumps({'type': 'info', 'message': 'Creating bootable ISO...'})}\n\n"

                    if os_version == "10":
                        # Check if isolinux.bin exists
                        check_isolinux_bin = f"test -f {source_dir}/isolinux/isolinux.bin && echo 'exists' || echo 'missing'"
                        isolinux_bin_status = run_remote_command(check_isolinux_bin, proxmox_ip, proxmox_user, proxmox_password)
                        
                        if isolinux_bin_status == "missing":
                            logger.warning("isolinux.bin is missing, attempting to find it elsewhere...")
                            yield f"data: {json.dumps({'type': 'warning', 'message': 'isolinux.bin is missing, attempting to find it elsewhere...'})}\n\n"
                            
                            # Find any .bin files and copy to isolinux directory
                            find_bins = f"find {source_dir} -name '*.bin' -type f | head -1"
                            bin_file = run_remote_command(find_bins, proxmox_ip, proxmox_user, proxmox_password)
                            if bin_file:
                                create_bin = f"cp {bin_file} {source_dir}/isolinux/isolinux.bin"
                                run_remote_command(create_bin, proxmox_ip, proxmox_user, proxmox_password)
                                yield f"data: {json.dumps({'type': 'info', 'message': f'Copied {bin_file} to isolinux/isolinux.bin'})}\n\n"
                        
                        # Try multiple methods for CentOS 10
                        repack_cmd = f"""cd {source_dir} && \
                        xorriso -as mkisofs \
                        -V 'CentOS10-USER-{user_id}' \
                        -o {crafted_iso} \
                        -b isolinux/isolinux.bin \
                        -c isolinux/boot.cat \
                        -no-emul-boot \
                        -boot-load-size 4 \
                        -boot-info-table \
                        -eltorito-alt-boot \
                        -e EFI/BOOT/BOOTX64.EFI \
                        -no-emul-boot \
                        -isohybrid-gpt-basdat \
                        -R -J ."""
                    
                        result = run_remote_command(repack_cmd, proxmox_ip, proxmox_user, proxmox_password)
                        if result is None:
                            logger.warning("ISO creation using xorriso hybrid method failed, trying standard method...")
                            yield f"data: {json.dumps({'type': 'warning', 'message': 'ISO creation using xorriso hybrid method failed, trying standard method...'})}\n\n"
                    
                            # Try standard method as fallback
                            standard_cmd = f"""cd {source_dir} && \
                            mkisofs -o {crafted_iso} \
                            -b isolinux/isolinux.bin \
                            -c isolinux/boot.cat \
                            -no-emul-boot -boot-load-size 4 -boot-info-table \
                            -J -R -V "CentOS10-USER-{user_id}" ."""
                            
                            result = run_remote_command(standard_cmd, proxmox_ip, proxmox_user, proxmox_password)
                            
                            if result is None:
                                logger.warning("Standard method failed, trying simplest method...")
                                yield f"data: {json.dumps({'type': 'warning', 'message': 'Standard method failed, trying simplest method...'})}\n\n"
                                
                                # Simplest method as last resort
                                simple_cmd = f"""cd {working_dir} && \
                                mkisofs -o {crafted_iso} \
                                -R -J -V "CentOS10-USER-{user_id}" \
                                {source_dir}"""
                                
                                result = run_remote_command(simple_cmd, proxmox_ip, proxmox_user, proxmox_password)
                                
                                if result is None:
                                    error_msg = "All ISO creation methods failed for CentOS 10"
                                    logger.error(error_msg)
                                    yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
                                    yield f"data: ERROR\n\n"
                                    return
                    else:
                        # Standard ISO creation for CentOS 8/9
                        repack_cmd = f"""cd {working_dir} && \
                        mkisofs -o {crafted_iso} \
                        -b {ISOLINUX_BIN_PATH} \
                        -c {BOOT_CAT_PATH} \
                        -no-emul-boot -boot-load-size 4 -boot-info-table \
                        -J -R -V "CentOS{os_version}-USER-{user_id}" \
                        {source_dir}"""
                        
                        result = run_remote_command(repack_cmd, proxmox_ip, proxmox_user, proxmox_password)
                        
                        if result is None:
                            error_msg = f"Failed to create ISO for CentOS {os_version}"
                            logger.error(error_msg)
                            yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
                            yield f"data: ERROR\n\n"
                            return

                    # Verify ISO creation
                    verify_cmd = f"test -f {crafted_iso} && echo 'success' || echo 'failure'"
                    result = run_remote_command(verify_cmd, proxmox_ip, proxmox_user, proxmox_password)

                    if result == "success":
                        success_msg = f"Custom CentOS {os_version} ISO created successfully at {crafted_iso}"
                        logger.info(success_msg)
                        yield f"data: {json.dumps({'type': 'success', 'message': success_msg})}\n\n"
                        yield f"data: COMPLETE\n\n"
                    else:
                        error_msg = "Failed to verify ISO creation"
                        logger.error(error_msg)
                        yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
                        yield f"data: ERROR\n\n"
                        return

                    # Mount ISO to iDRAC
                    iso_path = crafted_iso  # Use the same path where the ISO was created
                    
                    # Check if ISO exists on Proxmox server
                    verify_cmd = f"test -f {iso_path} && echo 'exists' || echo 'missing'"
                    result = run_remote_command(verify_cmd, proxmox_ip, proxmox_user, proxmox_password)
                    if result != "exists":
                        error_msg = f"Custom ISO not found on Proxmox server: {iso_path}"
                        logger.error(error_msg)
                        yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
                        return
                    
                    # Verify ISO is accessible via HTTP
                    iso_url = f"http://{proxmox_ip}/{os.path.basename(iso_path)}"
                    response = requests.head(iso_url)
                    if response.status_code != 200:
                        error_msg = f"ISO not accessible at {iso_url}"
                        logger.error(error_msg)
                        yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
                        return
                    
                    # Create iDRAC session
                    logger.info("Creating iDRAC session...")
                    yield f"data: {json.dumps({'type': 'info', 'message': 'Creating iDRAC session...'})}\n\n"
                    
                    session_url = f"https://{data['idracIp']}/redfish/v1/SessionService/Sessions"
                    headers = {'Content-Type': 'application/json'}
                    payload = {"UserName": data['idracUser'], "Password": data['idracPassword']}
                    
                    try:
                        session = requests.post(session_url, json=payload, headers=headers, verify=False)
                        if session.status_code != 201:
                            error_msg = f"Authentication Failed: {session.text}"
                            logger.error(error_msg)
                            yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
                            return
                        
                        token = session.headers['X-Auth-Token']
                        session_uri = session.headers['Location']
                        if session_uri.startswith("/"):
                            session_uri = f"https://{data['idracIp']}{session_uri}"
                        
                        headers['X-Auth-Token'] = token
                        logger.info("Authenticated successfully")
                        yield f"data: {json.dumps({'type': 'info', 'message': 'Authenticated successfully'})}\n\n"
                        
                        # Check Virtual Media status
                        logger.info("Checking Virtual Media status...")
                        yield f"data: {json.dumps({'type': 'info', 'message': 'Checking Virtual Media status...'})}\n\n"
                        
                        vm_status_url = f"https://{data['idracIp']}/redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/CD"
                        response = requests.get(vm_status_url, headers=headers, verify=False)
                        
                        if response.status_code == 200:
                            vm_info = response.json()
                            current_image = vm_info.get('Image', None)
                            if current_image == iso_url:
                                logger.info("ISO is already mounted")
                                yield f"data: {json.dumps({'type': 'info', 'message': 'ISO is already mounted'})}\n\n"
                            else:
                                # Mount ISO
                                logger.info("Mounting ISO...")
                                yield f"data: {json.dumps({'type': 'info', 'message': 'Mounting ISO...'})}\n\n"
                                
                                vm_insert_url = f"https://{data['idracIp']}/redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/CD/Actions/VirtualMedia.InsertMedia"
                                iso_payload = {
                                    "Image": iso_url,
                                    "Inserted": True,
                                    "WriteProtected": True
                                }
                                
                                response = requests.post(vm_insert_url, json=iso_payload, headers=headers, verify=False)
                                if response.status_code not in [200, 204]:
                                    error_msg = f"Failed to Mount ISO: {response.text}"
                                    logger.error(error_msg)
                                    yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
                                    return
                                
                                logger.info("ISO mounted successfully")
                                yield f"data: {json.dumps({'type': 'info', 'message': 'ISO mounted successfully'})}\n\n"
                        
                        # Set boot device to Virtual CD/DVD
                        logger.info("Setting boot device...")
                        yield f"data: {json.dumps({'type': 'info', 'message': 'Setting boot device...'})}\n\n"
                        
                        attributes_url = f"https://{data['idracIp']}/redfish/v1/Managers/iDRAC.Embedded.1/Attributes/"
                        boot_payload = {
                            "Attributes": {
                                "ServerBoot.1.FirstBootDevice": "VCD-DVD"
                            }
                        }
                        
                        response = requests.patch(attributes_url, json=boot_payload, headers=headers, verify=False)
                        if response.status_code not in [200, 204]:
                            error_msg = f"Failed to set first boot device: {response.text}"
                            logger.error(error_msg)
                            yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
                            return
                        
                        logger.info("First boot device set to Virtual CD/DVD")
                        yield f"data: {json.dumps({'type': 'info', 'message': 'First boot device set to Virtual CD/DVD'})}\n\n"
                        
                        # Enable boot once
                        logger.info("Enabling one-time boot...")
                        yield f"data: {json.dumps({'type': 'info', 'message': 'Enabling one-time boot...'})}\n\n"
                        
                        boot_once_payload = {
                            "Attributes": {
                                "VirtualMedia.1.BootOnce": "Enabled"
                            }
                        }
                        
                        response = requests.patch(attributes_url, json=boot_once_payload, headers=headers, verify=False)
                        if response.status_code not in [200, 204]:
                            error_msg = f"Failed to enable one-time boot: {response.text}"
                            logger.error(error_msg)
                            yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
                            return
                        
                        logger.info("One-time boot enabled for Virtual Media")
                        yield f"data: {json.dumps({'type': 'info', 'message': 'One-time boot enabled for Virtual Media'})}\n\n"
                        
                        # Reboot server
                        logger.info("Rebooting server...")
                        yield f"data: {json.dumps({'type': 'info', 'message': 'Rebooting server...'})}\n\n"
                        
                        reset_url = f"https://{data['idracIp']}/redfish/v1/Systems/System.Embedded.1/Actions/ComputerSystem.Reset"
                        reboot_payload = {"ResetType": "ForceRestart"}
                        
                        response = requests.post(reset_url, json=reboot_payload, headers=headers, verify=False)
                        if response.status_code not in [200, 204]:
                            error_msg = f"Failed to reboot server: {response.text}"
                            logger.error(error_msg)
                            yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
                            return
                        
                        # Close session
                        close_response = requests.delete(session_uri, headers=headers, verify=False)
                        
                        logger.info("Server is rebooting and will install CentOS automatically")
                        yield f"data: {json.dumps({'type': 'success', 'message': 'Server is rebooting and will install CentOS automatically'})}\n\n"
                        
                    except Exception as e:
                        error_msg = f"Error during iDRAC operations: {str(e)}"
                        logger.error(error_msg)
                        yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
                        return

                except Exception as e:
                    error_msg = f"Error during ISO creation: {str(e)}"
                    logger.error(error_msg)
                    yield f"data: {json.dumps({'type': 'error', 'message': error_msg})}\n\n"
                    yield f"data: ERROR\n\n"
                finally:
                    # Clean up resources
                    if process_id in active_processes:
                        del active_processes[process_id]
                    # Release the lock
                    iso_creation_lock.release()
                    logger.info(f"Process {process_id} completed and resources released")

            return Response(stream_with_context(generate()), mimetype='text/event-stream')

        except Exception as e:
            logger.error(f"Error in create-iso endpoint: {str(e)}")
            # Make sure to clean up in case of error
            if process_id in active_processes:
                del active_processes[process_id]
            # Release the lock
            iso_creation_lock.release()
            return jsonify({'error': str(e)}), 500

    except Exception as e:
        logger.error(f"Error in create-iso endpoint: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/health')
def health_check():
    """Health check endpoint to verify server is running"""
    return jsonify({"status": "healthy", "timestamp": time.time()})

@app.route('/stream-logs')
def stream_logs():
    """Stream logs to the client"""
    try:
        return Response(
            stream_with_context(generate_logs()),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive'
            }
        )
    except Exception as e:
        logger.error(f"Failed to initialize log streaming: {e}")
        return jsonify({"error": "Failed to initialize log streaming"}), 500

def generate_logs():
    """Generator function for streaming logs"""
    try:
        log_stream.seek(0)
        while True:
            # Read any new log entries
            new_logs = log_stream.read()
            if new_logs:
                yield f"data: {json.dumps({'log': new_logs})}\n\n"
            time.sleep(0.1)  # Small delay to prevent CPU overuse
    except GeneratorExit:
        logger.info("Client disconnected from log stream")
    except Exception as e:
        logger.error(f"Error in log streaming: {e}")
        yield f"data: {json.dumps({'error': str(e)})}\n\n"

if __name__ == '__main__':
    try:
        # Attempt to start server with retries
        max_retries = 3
        current_port = 5001
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Starting server on port {current_port}, attempt {attempt + 1}/{max_retries}")
                app.run(debug=True, port=current_port, host='127.0.0.1')
                break
            except OSError as e:
                if "Address already in use" in str(e):
                    logger.warning(f"Port {current_port} is in use, trying port {current_port + 1}")
                    current_port += 1
                else:
                    raise
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        sys.exit(1) 