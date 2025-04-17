import streamlit as st
import subprocess
import os
import sys
import logging
import time
import requests
import json
import ipaddress
import tempfile
import uuid
import glob
from urllib3.exceptions import InsecureRequestWarning

# Function to get current user's unique identifier
def get_user_identifier():
    # In a real-world scenario, you might want to use a more secure method of user identification
    session_id = st.session_state.get('user_id', str(uuid.uuid4())[:8])
    if 'user_id' not in st.session_state:
        st.session_state['user_id'] = session_id
    return session_id

# Proxmox server configuration - consider moving these to environment variables or secure configuration
proxmox_ip = "10.219.82.112"
proxmox_user = "root"
proxmox_password = "Jtaclab123"

# Global boot path variables
ISOLINUX_BIN_PATH = "isolinux/isolinux.bin"
BOOT_CAT_PATH = "isolinux/boot.cat"

# Suppress insecure request warnings
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Configure logging to show in Streamlit
logging.basicConfig(level=logging.INFO, format="%(message)s")

# Set page configuration
st.set_page_config(
    page_title="OS Autoinstaller",
    page_icon="🖥️",
    layout="wide"
)

# Create a container to place the logo
col1, col2 = st.columns([1, 7])

with col1:
    # Upload logo with small size
    st.image("/Users/nbaljoshi/Project/image.png", width=120)  # Adjust width as needed

with col2:
    st.markdown(
        "<h1 style='text-align: center;'>OS Autoinstaller 🖥️</h1>",
        unsafe_allow_html=True
    )

def is_valid_ip(ip):
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False

def is_valid_subnet_mask(mask):
    try:
        if '.' in mask:  # Decimal format (e.g., 255.255.255.0)
            octets = mask.split('.')
            if len(octets) != 4:
                return False
            
            # Convert each octet to an integer and validate the range
            octet_values = []
            for octet in octets:
                if not octet.isdigit() or int(octet) < 0 or int(octet) > 255:
                    return False
                octet_values.append(int(octet))
            
            # Convert to binary representation
            binary = ''.join([bin(octet)[2:].zfill(8) for octet in octet_values])
            
            # The mask should be continuous 1s followed by 0s (e.g., 11111111.11111111.11111111.10000000)
            if '01' in binary:
                return False  # Found 1s after 0s, invalid mask
            
            return True
        
        else:  # CIDR format (e.g., /24)
            try:
                cidr = int(mask.replace('/', ''))
                return 0 <= cidr <= 32
            except ValueError:
                return False
    except Exception as e:
        logging.error(f"Error validating subnet mask: {e}")
        return False

def subnet_to_cidr(subnet_mask):
    """Convert subnet mask to CIDR notation"""
    try:
        if '/' in subnet_mask:
            # Validate the CIDR value
            cidr = int(subnet_mask.replace('/', ''))
            if cidr < 0 or cidr > 32:
                logging.error(f"Invalid CIDR value: {cidr}")
                return "/24"  # Default safe value
            return subnet_mask
        
        # Validate decimal subnet mask
        octets = subnet_mask.split('.')
        if len(octets) != 4:
            logging.error(f"Invalid subnet mask format: {subnet_mask}")
            return "/24"  # Default safe value
        
        # Convert to binary
        binary = ''.join([bin(int(x))[2:].zfill(8) for x in octets])
        cidr = binary.count('1')
        
        # Validate CIDR range
        if '01' in binary:
            logging.error(f"Invalid subnet mask {subnet_mask}, non-continuous 1s")
            return "/24"  # Default safe value
            
        return f"/{cidr}"
    except Exception as e:
        logging.error(f"Error converting subnet mask {subnet_mask}: {e}")
        return "/24"  # Default safe value

def run_remote_command(command, proxmox_ip, proxmox_user, proxmox_password):
    """Execute command on remote Proxmox server"""
    st.write(f"Running command on Proxmox: `{command}`")
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
        st.error(f"Remote command failed: {e}")
        st.error(f"Error output: {e.stderr}")
        return None

def install_local_tools():
    """Install necessary tools on local machine"""
    try:
        # Check if sshpass is installed
        result = subprocess.run(["which", "sshpass"], capture_output=True, text=True)
        if result.returncode != 0:
            st.info("Installing sshpass...")
            if sys.platform == "darwin":  # macOS
                subprocess.run(["brew", "install", "sshpass"], check=True)
            elif sys.platform.startswith("linux"):
                subprocess.run(["sudo", "apt", "install", "-y", "sshpass"], check=True)
            else:
                st.error("Unsupported OS. Please install sshpass manually.")
                return False
        return True
    except Exception as e:
        st.error(f"Failed to install tools: {e}")
        return False

# Create a tab-based interface
tab1, tab2 = st.tabs(["1. Server Details", "2. Create Your ISO "])

# Initialize session state for server details
if 'server_details' not in st.session_state:
    st.session_state.server_details = {
        'idrac_ip': "10.219.106.203",
        'idrac_user': "root",
        'idrac_password': "Jtaclab123"
    }

with tab1:
    st.header("")
    
    # Create two columns for server settings
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Server Details")
        idrac_ip = st.text_input("Server IP Address", 
                                 value=st.session_state.server_details['idrac_ip'], 
                                 key="idrac_ip_input",placeholder="xxx.xxx.xxx.xxx")
        idrac_user = st.text_input("Server Username", 
                                   value=st.session_state.server_details['idrac_user'], 
                                   key="idrac_user_input",placeholder="username")
        idrac_password = st.text_input("Server Password", 
                                       value=st.session_state.server_details['idrac_password'], 
                                       type="password", 
                                       key="idrac_password_input",placeholder="password")
        
        # Update session state when values change
        st.session_state.server_details.update({
            'idrac_ip': idrac_ip,
            'idrac_user': idrac_user,
            'idrac_password': idrac_password
        })
    
    st.subheader("OS Selection")
    
    # New OS Type dropdown first
    os_type = st.selectbox("Operating System", options=["CentOS", "Ubuntu"], index=0, key="os_type")
    
    # OS version dropdown (changes based on OS type)
    if os_type == "CentOS":
        os_version = st.selectbox("OS Version", options=["8", "9", "10"], index=2, key="os_version")
    else:  # Ubuntu
        os_version = st.selectbox("OS Version", options=["20", "22", "24"], index=2, key="os_version")
        #st.info("Ubuntu support is coming soon! Please select CentOS for now.")
    
    st.subheader("Network Configuration")
    network_type = st.radio("Network Configuration", ["DHCP", "Static IP"], index=0)
    
    if network_type == "Static IP":
        col1, col2 = st.columns(2)
        with col1:
            ip_address = st.text_input("IP Address", placeholder="xxx.xxx.xxx.xxx")
            subnet_mask = st.text_input("Subnet Mask", placeholder="xxx.xxx.xxx.xxx")
        with col2:
            gateway = st.text_input("Gateway", placeholder="xxx.xxx.xxx.xxx")
            dns_servers = st.text_input("DNS Servers", placeholder="xxx.xxx.xxx.xxx")
        
        # Validate inputs if provided
        if ip_address and not is_valid_ip(ip_address):
            st.error("Invalid IP address format")
        if subnet_mask and not is_valid_subnet_mask(subnet_mask):
            st.error("Invalid subnet mask format")
        if gateway and not is_valid_ip(gateway):
            st.error("Invalid gateway IP format")

with tab2:
    st.header("Create Custom ISO")
    
    if st.button("Install Required Tools"):
        with st.spinner("Installing local tools..."):
            if install_local_tools():
                st.success("Local tools installed successfully")
            else:
                st.error("Failed to install local tools")
        
        with st.spinner("Installing Proxmox tools..."):
            cmd = "apt update && apt install -y p7zip-full xorriso genisoimage apache2"
            result = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
            if result is not None:
                st.success("Proxmox tools installed successfully")
            else:
                st.error("Failed to install Proxmox tools")
    
    if st.button("Create Your ISO"):
        # Get OS type from session state
        os_type = st.session_state.get('os_type', 'CentOS')
        os_version = st.session_state.get('os_version', '10')
        
        # Check if Ubuntu was selected
        if os_type == "Ubuntu":
            st.warning("Ubuntu support is coming soon! Please select CentOS for now.")
            st.stop()
            
        # Get unique user identifier for this session
        user_id = get_user_identifier()
        
        # Validate inputs for static IP configuration
        if network_type == "Static IP":
            if not all([ip_address, subnet_mask, gateway]):
                st.error("All network fields are required for Static IP configuration")
                st.stop()
            if not all([is_valid_ip(ip_address), is_valid_subnet_mask(subnet_mask), is_valid_ip(gateway)]):
                st.error("Please fix the network configuration errors")
                st.stop()
        
        with st.spinner(f"Creating custom CentOS {os_version} ISO for user {user_id}..."):
            # Generate a unique identifier for the ISO
            unique_id = f"{user_id}-{str(uuid.uuid4())[:8]}"
            
            # Step 1: Define paths based on CentOS version with unique identifier
            working_dir = f"/root/centos{os_version}-autoinstall-ISO-{unique_id}"
            source_dir = f"{working_dir}/source-files"
            
            # Handle different ISO naming conventions for different CentOS versions
            if os_version == "10":
                iso_file = f"/var/www/html/CentOS-Stream-10-latest-x86_64-dvd1.iso"
            else:
                iso_file = f"/var/www/html/CentOS-Stream-{os_version}-latest-x86_64-dvd1.iso"
                
            crafted_iso = f"/var/www/html/user-{unique_id}-centos{os_version}.iso"
            
            # Step 2: Create directories and extract ISO
            st.info("Extracting ISO...")
            cmds = [
                f"mkdir -p {working_dir}",
                f"mkdir -p {source_dir}",
                f"cp {iso_file} {working_dir}/centos.iso",  # Copy ISO to working directory
                f"7z x {working_dir}/centos.iso -o{source_dir} -y"  # Extract from copied ISO
            ]
            for cmd in cmds:
                result = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                if result is None:
                    st.error(f"Failed to execute: {cmd}")
                    st.stop()
            
            # Step 3: Find and modify boot configurations for CentOS 10
            st.info("Configuring boot options...")
            
            if os_version == "10":
                # For CentOS 10, run the following commands to find boot config files
                cmd = f"find {source_dir} -name '*.cfg' -type f | sort"
                config_files = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                if config_files:
                    st.info(f"Found config files: {config_files}")
                
                # Find isolinux.cfg
                cmd = f"find {source_dir} -name 'isolinux.cfg' -type f | sort"
                isolinux_result = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                if isolinux_result:
                    isolinux_cfg = isolinux_result.strip().split("\n")[0]
                    st.info(f"Found isolinux.cfg at: {isolinux_cfg}")
                else:
                    st.warning("isolinux.cfg not found, searching for alternatives...")
                    cmd = f"find {source_dir} -path '*isolinux*' -name '*.cfg' -type f | sort"
                    isolinux_cfg = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                    if isolinux_cfg:
                        isolinux_cfg = isolinux_cfg.strip().split("\n")[0]
                        st.info(f"Using alternative isolinux config: {isolinux_cfg}")
                    else:
                        st.error("No isolinux configuration found. BIOS boot might not work.")
                        isolinux_cfg = f"{source_dir}/isolinux/isolinux.cfg"
                
                # Find grub.cfg
                cmd = f"find {source_dir} -path '*EFI/BOOT*' -name 'grub.cfg' -type f | sort"
                grub_result = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                if grub_result:
                    grub_cfg = grub_result.strip().split("\n")[0]
                    st.info(f"Found EFI grub.cfg at: {grub_cfg}")
                else:
                    st.warning("EFI grub.cfg not found, searching for alternatives...")
                    cmd = f"find {source_dir} -name 'grub.cfg' -type f | sort"
                    grub_result = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                    if grub_result:
                        grub_cfg = grub_result.strip().split("\n")[0]
                        st.info(f"Using alternative grub.cfg: {grub_cfg}")
                    else:
                        st.warning("No grub configuration found. EFI boot might not work.")
                        grub_cfg = f"{source_dir}/EFI/BOOT/grub.cfg"
                
                # For CentOS 10, check paths of vmlinuz and initrd.img
                cmd = f"find {source_dir} -name 'vmlinuz' -type f | sort"
                vmlinuz_path = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                if vmlinuz_path:
                    st.info(f"Found vmlinuz at: {vmlinuz_path}")
                    vmlinuz = vmlinuz_path.strip().split("\n")[0]
                    rel_vmlinuz = '/' + os.path.relpath(vmlinuz, source_dir)
                else:
                    st.warning("vmlinuz not found, using default path")
                    rel_vmlinuz = "/images/pxeboot/vmlinuz"
                
                cmd = f"find {source_dir} -name 'initrd.img' -type f | sort"
                initrd_path = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                if initrd_path:
                    st.info(f"Found initrd.img at: {initrd_path}")
                    initrd = initrd_path.strip().split("\n")[0]
                    rel_initrd = '/' + os.path.relpath(initrd, source_dir)
                else:
                    st.warning("initrd.img not found, using default path")
                    rel_initrd = "/images/pxeboot/initrd.img"
                    
                # Modified boot configuration options for CentOS 10
                isolinux_boot_option = f"""default autoinstall
timeout 5

label autoinstall
    menu label ^Autoinstall CentOS {os_version} for User {user_id}
    kernel /images/pxeboot/vmlinuz
    append initrd=/images/pxeboot/initrd.img inst.ks=cdrom:/kickstart.cfg quiet

label linux
    menu label ^Install CentOS {os_version}
    kernel /images/pxeboot/vmlinuz
    append initrd=/images/pxeboot/initrd.img
"""
                
                grub_boot_option = f"""set default=0
set timeout=5

menuentry 'Autoinstall CentOS {os_version} for User {user_id}' --class fedora --class gnu-linux --class gnu --class os {{
    linuxefi /images/pxeboot/vmlinuz inst.ks=cdrom:/kickstart.cfg quiet
    initrdefi /images/pxeboot/initrd.img
}}

menuentry 'Install CentOS {os_version}' --class fedora --class gnu-linux --class gnu --class os {{
    linuxefi /images/pxeboot/vmlinuz
    initrdefi /images/pxeboot/initrd.img
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
                    st.error(f"Failed to execute: {cmd}")
                    st.warning("Continuing despite the error...")
            
            # Step 4: Create kickstart file with network configuration
            st.info("Creating kickstart file with network configuration...")
            kickstart_path = f"{source_dir}/kickstart.cfg"
            
            # Create network configuration for kickstart
            if network_type == "DHCP":
                network_config = "network --bootproto=dhcp --device=link --activate --onboot=yes"
            else:
                # Convert subnet mask to CIDR if necessary
                cidr = subnet_to_cidr(subnet_mask)
                dns_list = dns_servers.replace(" ", "").split(",") if dns_servers else ["8.8.8.8"]
                network_config = (
                    f"network --bootproto=static --device=link --activate --onboot=yes "
                    f"--ip={ip_address} --netmask={subnet_mask} --gateway={gateway} "
                    f"--nameserver={','.join(dns_list)}"
                )
            
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
                st.error("Failed to create kickstart file")
                st.stop()
            
            # Step 5: Find necessary boot files for ISO creation
            st.info("Preparing to create bootable ISO...")
            
            if os_version == "10":
                # Try to locate isolinux.bin
                cmd = f"find {source_dir} -name 'isolinux.bin' -type f | sort"
                isolinux_bin_path = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                
                if isolinux_bin_path and isolinux_bin_path.strip():
                    isolinux_bin = isolinux_bin_path.strip().split("\n")[0]
                    isolinux_rel_path = os.path.relpath(isolinux_bin, source_dir)
                    st.info(f"Found isolinux.bin at: {isolinux_rel_path}")
                else:
                    st.warning("isolinux.bin not found, using default path")
                    isolinux_rel_path = ISOLINUX_BIN_PATH
                
                # Find EFI boot image
                cmd = f"find {source_dir} -name 'efiboot.img' -type f | sort"
                efiboot_path = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                efi_img_path = ""
                
                if efiboot_path and efiboot_path.strip():
                    efi_img = efiboot_path.strip().split("\n")[0]
                    efi_img_path = os.path.relpath(efi_img, source_dir)
                    st.info(f"Found EFI boot image at: {efi_img_path}")
                else:
                    st.warning("EFI boot image not found. UEFI boot might not work.")
                
                # Step 6: Implement repack_iso function for CentOS 10
                st.info("Creating new ISO file for CentOS 10 using repack_iso function...")
                
                # Create a temporary Python script on the Proxmox server with repack_iso function
                repack_iso_func = """
def repack_iso(source_dir, crafted_iso, user_id):
    import subprocess
    import os
    import logging
    
    # Define paths
    ISOLINUX_BIN_PATH = "isolinux/isolinux.bin"
    BOOT_CAT_PATH = "isolinux/boot.cat"
    
    # Check if isolinux.bin exists at the expected path
    isolinux_bin = os.path.join(source_dir, ISOLINUX_BIN_PATH)
    
    print(f"Creating ISO from {source_dir} to {crafted_iso}")
    print(f"Checking for isolinux.bin at {isolinux_bin}")
    
    # Build the command
    if not os.path.exists(isolinux_bin):
        print(f"Warning: {isolinux_bin} not found. Using simpler ISO creation method.")
        cmd = [
            "mkisofs", "-o", crafted_iso,
            "-J", "-R", "-V", f"CentOS10-USER-{user_id}",
            source_dir
        ]
    else:
        # Use full boot options if isolinux.bin exists
        print(f"Found isolinux.bin at {isolinux_bin}, using full boot options")
        cmd = [
            "mkisofs", "-o", crafted_iso,
            "-b", ISOLINUX_BIN_PATH,
            "-c", BOOT_CAT_PATH,
            "-no-emul-boot", "-boot-load-size", "4", "-boot-info-table",
            "-J", "-R", "-V", f"CentOS10-USER-{user_id}",
            source_dir
        ]
    
    print(f"Running command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"ISO creation successful: {crafted_iso}")
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        print(f"ISO creation failed: {e.stderr}")
        return False, e.stderr
"""
                
                # Create a temporary script on the Proxmox server
                script_path = f"{working_dir}/repack_iso.py"
                cmd = f"cat > {script_path} << 'EOF'\n{repack_iso_func}\nEOF"
                run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                
                # Run the function to create the ISO
                cmd = f"cd {working_dir} && python3 -c \"import sys; sys.path.append('.'); from repack_iso import repack_iso; success, output = repack_iso('{source_dir}', '{crafted_iso}', '{user_id}'); print('Success: ' + str(success)); print(output)\""
                result = run_remote_command(cmd, proxmox_ip, proxmox_user, proxmox_password)
                
                if result is None or "Success: False" in result:
                    st.warning("ISO creation using repack_iso failed, trying alternative method...")
                    
                    # Try with xorriso as a fallback
                    xorriso_cmd = f"""cd {source_dir} && \
                    xorriso -as mkisofs \
                    -V 'CentOS10-USER-{user_id}' \
                    -o {crafted_iso} \
                    -b isolinux/isolinux.bin \
                    -c isolinux/boot.cat \
                    -no-emul-boot \
                    -boot-load-size 4 \
                    -boot-info-table \
                    -R -J ."""
                    
                    result = run_remote_command(xorriso_cmd, proxmox_ip, proxmox_user, proxmox_password)
                    
                    if result is None:
                        st.warning("xorriso method failed, trying simplest method...")
                        
                        # Simplest method as last resort
                        simple_cmd = f"""cd {working_dir} && \
                        mkisofs -o {crafted_iso} \
                        -R -J -V "CentOS10-USER-{user_id}" \
                        {source_dir}"""
                        
                        result = run_remote_command(simple_cmd, proxmox_ip, proxmox_user, proxmox_password)
                        
                        if result is None:
                            st.error("All ISO creation methods failed for CentOS 10")
                            st.stop()
            else:
                # Standard ISO creation for CentOS 8/9
                st.info("Creating new ISO file for CentOS 8/9...")
                repack_cmd = f"""cd {working_dir} && \
                mkisofs -o {crafted_iso} \
                -b {ISOLINUX_BIN_PATH} \
                -c {BOOT_CAT_PATH} \
                -no-emul-boot -boot-load-size 4 -boot-info-table \
                -J -R -V "CentOS{os_version}-USER-{user_id}" \
                {source_dir}"""
                
                result = run_remote_command(repack_cmd, proxmox_ip, proxmox_user, proxmox_password)
                
                if result is None:
                    st.error(f"Failed to create ISO for CentOS {os_version}")
                    st.stop()
            
            # Verify ISO creation
            verify_cmd = f"test -f {crafted_iso} && echo 'success' || echo 'failure'"
            result = run_remote_command(verify_cmd, proxmox_ip, proxmox_user, proxmox_password)
            
            if result == "success":
                st.success(f"Custom CentOS {os_version} ISO created successfully for User {user_id} at {crafted_iso}")
            else:
                st.error("Failed to verify ISO creation")
                st.stop()

            # Immediately proceed with mounting
            iso_url = f"http://{proxmox_ip}/{os.path.basename(crafted_iso)}"
            
            with st.spinner("Connecting to Dell iDRAC and mounting ISO..."):
                # Create progress indicators
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                # Step 1: Create iDRAC session
                status_text.text("Creating iDRAC session...")
                progress_bar.progress(10)
                
                session_url = f"https://{idrac_ip}/redfish/v1/SessionService/Sessions"
                headers = {'Content-Type': 'application/json'}
                payload = {"UserName": idrac_user, "Password": idrac_password}
                
                try:
                    session = requests.post(session_url, json=payload, headers=headers, verify=False)
                    
                    if session.status_code != 201:
                        st.error(f"Authentication Failed: {session.text}")
                        st.stop()
                    
                    token = session.headers['X-Auth-Token']
                    session_uri = session.headers['Location']
                    if session_uri.startswith("/"):
                        session_uri = f"https://{idrac_ip}{session_uri}"
                    
                    headers['X-Auth-Token'] = token
                    status_text.text("✅ Authenticated Successfully.")
                    progress_bar.progress(30)
                    
                    # Step 2: Check ISO status
                    status_text.text("Checking Virtual Media status...")
                    vm_status_url = f"https://{idrac_ip}/redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/CD"
                    response = requests.get(vm_status_url, headers=headers, verify=False)
                    
                    if response.status_code == 200:
                        vm_info = response.json()
                        current_image = vm_info.get('Image', None)
                        if current_image == iso_url:
                            status_text.text("✅ ISO is already mounted.")
                        else:
                            # Step 3: Mount ISO
                            status_text.text("Mounting ISO...")
                            vm_insert_url = f"https://{idrac_ip}/redfish/v1/Managers/iDRAC.Embedded.1/VirtualMedia/CD/Actions/VirtualMedia.InsertMedia"
                            iso_payload = {
                                "Image": iso_url,
                                "Inserted": True,
                                "WriteProtected": True
                            }
                            
                            response = requests.post(vm_insert_url, json=iso_payload, headers=headers, verify=False)
                            
                            if response.status_code not in [200, 204]:
                                st.error(f"Failed to Mount ISO: {response.text}")
                                st.stop()
                            
                            status_text.text("✅ ISO Mounted Successfully.")
                    
                    progress_bar.progress(50)
                    
                  
                    
                    # Step 4: Set boot device to Virtual CD/DVD
                    status_text.text("Setting boot device...")
                    attributes_url = f"https://{idrac_ip}/redfish/v1/Managers/iDRAC.Embedded.1/Attributes/"
                    boot_payload = {
                        "Attributes": {
                            "ServerBoot.1.FirstBootDevice": "VCD-DVD"
                        }
                    }
                    
                    response = requests.patch(attributes_url, json=boot_payload, headers=headers, verify=False)
                    
                    if response.status_code not in [200, 204]:
                        st.error(f"Failed to set first boot device: {response.text}")
                        st.stop()
                    
                    status_text.text("✅ First Boot Device set to Virtual CD/DVD.")
                    progress_bar.progress(70)
                    
                    # Step 5: Enable boot once
                    status_text.text("Enabling one-time boot...")
                    boot_once_payload = {
                        "Attributes": {
                            "VirtualMedia.1.BootOnce": "Enabled"
                        }
                    }
                    
                    response = requests.patch(attributes_url, json=boot_once_payload, headers=headers, verify=False)
                    
                    if response.status_code not in [200, 204]:
                        st.error(f"Failed to enable one-time boot: {response.text}")
                        st.stop()
                    
                    status_text.text("✅ One-Time Boot enabled for Virtual Media.")
                    progress_bar.progress(90)
                    
                    # Step 6: Reboot server
                    status_text.text("Rebooting server...")
                    reset_url = f"https://{idrac_ip}/redfish/v1/Systems/System.Embedded.1/Actions/ComputerSystem.Reset"
                    reboot_payload = {"ResetType": "ForceRestart"}
                    
                    response = requests.post(reset_url, json=reboot_payload, headers=headers, verify=False)
                    
                    if response.status_code not in [200, 204]:
                        st.error(f"Failed to reboot server: {response.text}")
                        st.stop()
                    
                    # Step 7: Close session
                    close_response = requests.delete(session_uri, headers=headers, verify=False)
                    
                    # Step 8: Clean up temporary files on Proxmox (optional, you might want to keep the ISO for a while)
                    status_text.text("Cleaning up temporary files...")
                    cleanup_cmd = f"rm -rf {working_dir}"
                    run_remote_command(cleanup_cmd, proxmox_ip, proxmox_user, proxmox_password)
                    
                    progress_bar.progress(100)
                    status_text.text("✅ Server is rebooting and will install CentOS automatically.")
                    st.success(f"CentOS {os_version} installation process started successfully on Dell server {idrac_ip}")
                    
                except Exception as e:
                    st.error(f"Error during iDRAC operations: {str(e)}")

# Add footer
st.markdown("---")
st.markdown("OS Auto-Installation Tool © 2025")