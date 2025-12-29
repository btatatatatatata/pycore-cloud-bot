# RUN 'important.sh' BEFORE RUNNING THE BOT!!!!
# =========================================== BOT CODE STARTS HERE ===========================================
import discord
from discord.ext import commands
from discord import ui, app_commands
import os
import random
import string
import json
import random
import subprocess
from dotenv import load_dotenv
import asyncio
import datetime
import docker
import time
import logging
import traceback
import aiohttp
import socket
import re
import psutil
import platform
import shutil
from typing import Optional, Literal
import sqlite3
import pickle
import base64
import threading
from discord.ext import tasks
#from flask import Flask, render_template, request, jsonify, session
#from flask_socketio import SocketIO, emit
import docker
import paramiko
import os
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('PycroeCloud_bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('[PYCROE.HOST]')

# Load environment variables
load_dotenv()

# Bot configuration
TOKEN = os.getenv('DISCORD_TOKEN')
ADMIN_IDS = {int(id_) for id_ in os.getenv('ADMIN_IDS', '1279500219154956419').split(',') if id_.strip()}
ADMIN_ROLE_ID = int(os.getenv('ADMIN_ROLE_ID', '1453779290297598161'))
WATERMARK = "PYCROE VPS Service"
WELCOME_MESSAGE = "Welcome To Pycroe Host! Get Started With Us!"
MAX_VPS_PER_USER = int(os.getenv('MAX_VPS_PER_USER', '3'))
DEFAULT_OS_IMAGE = os.getenv('DEFAULT_OS_IMAGE', 'ubuntu:22.04')
DOCKER_NETWORK = os.getenv('DOCKER_NETWORK', 'bridge')
MAX_CONTAINERS = int(os.getenv('MAX_CONTAINERS', '100'))
DB_FILE = 'PycroeCloud.db'
BACKUP_FILE = 'PycroeCloud_backup.pkl'

# Known miner process names/patterns
MINER_PATTERNS = [
    'xmrig', 'ethminer', 'cgminer', 'sgminer', 'bfgminer',
    'minerd', 'cpuminer', 'cryptonight', 'stratum', 'pool'
]

# Dockerfile template for custom images
DOCKERFILE_TEMPLATE = """
FROM {base_image}

# Prevent prompts
ENV DEBIAN_FRONTEND=noninteractive

# Install systemd, sudo, SSH, Docker and other essential packages
RUN apt-get update && \\
    apt-get install -y systemd systemd-sysv dbus sudo \\
                       curl gnupg2 apt-transport-https ca-certificates \\
                       software-properties-common \\
                       docker.io openssh-server tmate && \\
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Root password
RUN echo "root:{root_password}" | chpasswd

# Create user and set password
RUN useradd -m -s /bin/bash {username} && \\
    echo "{username}:{user_password}" | chpasswd && \\
    usermod -aG sudo {username}

# Enable SSH login
RUN mkdir /var/run/sshd && \\
    sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin yes/' /etc/ssh/sshd_config && \\
    sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config
RUN sudo add-apt-repository ppa:zhangsongcui3371/fastfetch
RUN sudo apt update
RUN sudo apt install fastfetch

# Enable services on boot
RUN systemctl enable ssh && \\
    systemctl enable docker

# Pycroe Host customization
RUN echo '{welcome_message}' > /etc/motd && \\
    echo 'echo "{welcome_message}"' >> /home/{username}/.bashrc && \\
    echo '{watermark}' > /etc/machine-info && \\
    echo 'PycroeCloud-{vps_id}' > /etc/hostname

# Install additional useful packages
RUN apt-get update && \\
    apt-get install -y neofetch htop nano vim wget git tmux net-tools dnsutils iputils-ping && \\
    apt-get clean && \\
    rm -rf /var/lib/apt/lists/*

# Fix systemd inside container
STOPSIGNAL SIGRTMIN+3

# Boot into systemd (like a VM)
CMD ["/sbin/init"]
"""

class Database:
    """Handles all data persistence using SQLite3"""
    def __init__(self, db_file):
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self._create_tables()
        self._initialize_settings()

    def _create_tables(self):
        """Create necessary tables"""
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS vps_instances (
                token TEXT PRIMARY KEY,
                vps_id TEXT UNIQUE,
                container_id TEXT,
                memory INTEGER,
                cpu INTEGER,
                disk INTEGER,
                username TEXT,
                password TEXT,
                root_password TEXT,
                created_by TEXT,
                created_at TEXT,
                tmate_session TEXT,
                watermark TEXT,
                os_image TEXT,
                restart_count INTEGER DEFAULT 0,
                last_restart TEXT,
                status TEXT DEFAULT 'running',
                use_custom_image BOOLEAN DEFAULT 1
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS usage_stats (
                key TEXT PRIMARY KEY,
                value INTEGER DEFAULT 0
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id TEXT PRIMARY KEY
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS admin_users (
                user_id TEXT PRIMARY KEY
            )
        ''')
        
        self.conn.commit()

    def _initialize_settings(self):
        """Initialize default settings"""
        defaults = {
            'max_containers': str(MAX_CONTAINERS),
            'max_vps_per_user': str(MAX_VPS_PER_USER)
        }
        for key, value in defaults.items():
            self.cursor.execute('INSERT OR IGNORE INTO system_settings (key, value) VALUES (?, ?)', (key, value))
        
        # Load admin users from database
        self.cursor.execute('SELECT user_id FROM admin_users')
        for row in self.cursor.fetchall():
            ADMIN_IDS.add(int(row[0]))
            
        self.conn.commit()

    def get_setting(self, key, default=None):
        self.cursor.execute('SELECT value FROM system_settings WHERE key = ?', (key,))
        result = self.cursor.fetchone()
        return int(result[0]) if result else default

    def set_setting(self, key, value):
        self.cursor.execute('INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)', (key, str(value)))
        self.conn.commit()

    def get_stat(self, key, default=0):
        self.cursor.execute('SELECT value FROM usage_stats WHERE key = ?', (key,))
        result = self.cursor.fetchone()
        return result[0] if result else default

    def increment_stat(self, key, amount=1):
        current = self.get_stat(key)
        self.cursor.execute('INSERT OR REPLACE INTO usage_stats (key, value) VALUES (?, ?)', (key, current + amount))
        self.conn.commit()

    def get_vps_by_id(self, vps_id):
        self.cursor.execute('SELECT * FROM vps_instances WHERE vps_id = ?', (vps_id,))
        row = self.cursor.fetchone()
        if not row:
            return None, None
        columns = [desc[0] for desc in self.cursor.description]
        vps = dict(zip(columns, row))
        return vps['token'], vps

    def get_vps_by_token(self, token):
        self.cursor.execute('SELECT * FROM vps_instances WHERE token = ?', (token,))
        row = self.cursor.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in self.cursor.description]
        return dict(zip(columns, row))

    def get_user_vps_count(self, user_id):
        self.cursor.execute('SELECT COUNT(*) FROM vps_instances WHERE created_by = ?', (str(user_id),))
        return self.cursor.fetchone()[0]

    def get_user_vps(self, user_id):
        self.cursor.execute('SELECT * FROM vps_instances WHERE created_by = ?', (str(user_id),))
        columns = [desc[0] for desc in self.cursor.description]
        return [dict(zip(columns, row)) for row in self.cursor.fetchall()]

    def get_all_vps(self):
        self.cursor.execute('SELECT * FROM vps_instances')
        columns = [desc[0] for desc in self.cursor.description]
        return {row[0]: dict(zip(columns, row)) for row in self.cursor.fetchall()}

    def add_vps(self, vps_data):
        columns = ', '.join(vps_data.keys())
        placeholders = ', '.join('?' for _ in vps_data)
        self.cursor.execute(f'INSERT INTO vps_instances ({columns}) VALUES ({placeholders})', tuple(vps_data.values()))
        self.conn.commit()
        self.increment_stat('total_vps_created')

    def remove_vps(self, token):
        self.cursor.execute('DELETE FROM vps_instances WHERE token = ?', (token,))
        self.conn.commit()
        return self.cursor.rowcount > 0

    def update_vps(self, token, updates):
        set_clause = ', '.join(f'{k} = ?' for k in updates)
        values = list(updates.values()) + [token]
        self.cursor.execute(f'UPDATE vps_instances SET {set_clause} WHERE token = ?', values)
        self.conn.commit()
        return self.cursor.rowcount > 0

    def is_user_banned(self, user_id):
        self.cursor.execute('SELECT 1 FROM banned_users WHERE user_id = ?', (str(user_id),))
        return self.cursor.fetchone() is not None

    def ban_user(self, user_id):
        self.cursor.execute('INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)', (str(user_id),))
        self.conn.commit()

    def unban_user(self, user_id):
        self.cursor.execute('DELETE FROM banned_users WHERE user_id = ?', (str(user_id),))
        self.conn.commit()

    def get_banned_users(self):
        self.cursor.execute('SELECT user_id FROM banned_users')
        return [row[0] for row in self.cursor.fetchall()]

    def add_admin(self, user_id):
        self.cursor.execute('INSERT OR IGNORE INTO admin_users (user_id) VALUES (?)', (str(user_id),))
        self.conn.commit()
        ADMIN_IDS.add(int(user_id))

    def remove_admin(self, user_id):
        self.cursor.execute('DELETE FROM admin_users WHERE user_id = ?', (str(user_id),))
        self.conn.commit()
        if int(user_id) in ADMIN_IDS:
            ADMIN_IDS.remove(int(user_id))

    def get_admins(self):
        self.cursor.execute('SELECT user_id FROM admin_users')
        return [row[0] for row in self.cursor.fetchall()]

    def backup_data(self):
        """Backup all data to a file"""
        data = {
            'vps_instances': self.get_all_vps(),
            'usage_stats': {},
            'system_settings': {},
            'banned_users': self.get_banned_users(),
            'admin_users': self.get_admins()
        }
        
        # Get usage stats
        self.cursor.execute('SELECT * FROM usage_stats')
        for row in self.cursor.fetchall():
            data['usage_stats'][row[0]] = row[1]
            
        # Get system settings
        self.cursor.execute('SELECT * FROM system_settings')
        for row in self.cursor.fetchall():
            data['system_settings'][row[0]] = row[1]
            
        with open(BACKUP_FILE, 'wb') as f:
            pickle.dump(data, f)
            
        return True

    def restore_data(self):
        """Restore data from backup file"""
        if not os.path.exists(BACKUP_FILE):
            return False
            
        try:
            with open(BACKUP_FILE, 'rb') as f:
                data = pickle.load(f)
                
            # Clear all tables
            self.cursor.execute('DELETE FROM vps_instances')
            self.cursor.execute('DELETE FROM usage_stats')
            self.cursor.execute('DELETE FROM system_settings')
            self.cursor.execute('DELETE FROM banned_users')
            self.cursor.execute('DELETE FROM admin_users')
            
            # Restore VPS instances
            for token, vps in data['vps_instances'].items():
                columns = ', '.join(vps.keys())
                placeholders = ', '.join('?' for _ in vps)
                self.cursor.execute(f'INSERT INTO vps_instances ({columns}) VALUES ({placeholders})', tuple(vps.values()))
            
            # Restore usage stats
            for key, value in data['usage_stats'].items():
                self.cursor.execute('INSERT INTO usage_stats (key, value) VALUES (?, ?)', (key, value))
                
            # Restore system settings
            for key, value in data['system_settings'].items():
                self.cursor.execute('INSERT INTO system_settings (key, value) VALUES (?, ?)', (key, value))
                
            # Restore banned users
            for user_id in data['banned_users']:
                self.cursor.execute('INSERT INTO banned_users (user_id) VALUES (?)', (user_id,))
                
            # Restore admin users
            for user_id in data['admin_users']:
                self.cursor.execute('INSERT INTO admin_users (user_id) VALUES (?)', (user_id,))
                ADMIN_IDS.add(int(user_id))
                
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error restoring data: {e}")
            return False

    def close(self):
        self.conn.close()

# Initialize bot with command prefix '/'
class PycroeCloudBot(commands.Bot):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.db = Database(DB_FILE)
        self.session = None
        self.docker_client = None
        self.system_stats = {
            'cpu_usage': 0,
            'memory_usage': 0,
            'disk_usage': 0,
            'network_io': (0, 0),
            'last_updated': 0
        }
        self.my_persistent_views = {}

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        try:
            self.docker_client = docker.from_env()
            logger.info("Docker client initialized successfully")
            self.loop.create_task(self.update_system_stats())
            self.loop.create_task(self.anti_miner_monitor())
            # Reconnect to existing containers
            await self.reconnect_containers()
            # Restore persistent views
            await self.restore_persistent_views()
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            self.docker_client = None

    async def reconnect_containers(self):
        """Reconnect to existing containers on startup"""
        if not self.docker_client:
            return
            
        for token, vps in list(self.db.get_all_vps().items()):
            if vps['status'] == 'running':
                try:
                    container = self.docker_client.containers.get(vps['container_id'])
                    if container.status != 'running':
                        container.start()
                    logger.info(f"Reconnected and started container for VPS {vps['vps_id']}")
                except docker.errors.NotFound:
                    logger.warning(f"Container {vps['container_id']} not found, removing from data")
                    self.db.remove_vps(token)
                except Exception as e:
                    logger.error(f"Error reconnecting container {vps['vps_id']}: {e}")

    async def restore_persistent_views(self):
        """Restore persistent views after restart"""
        # This would be implemented to restore any persistent UI components
        pass

    async def anti_miner_monitor(self):
        """Periodically check for mining activities"""
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                for token, vps in self.db.get_all_vps().items():
                    if vps['status'] != 'running':
                        continue
                    try:
                        container = self.docker_client.containers.get(vps['container_id'])
                        if container.status != 'running':
                            continue
                        
                        # Check processes
                        exec_result = container.exec_run("ps aux")
                        output = exec_result.output.decode().lower()
                        
                        for pattern in MINER_PATTERNS:
                            if pattern in output:
                                logger.warning(f"Mining detected in VPS {vps['vps_id']}, suspending...")
                                container.stop()
                                self.db.update_vps(token, {'status': 'suspended'})
                                # Notify owner
                                try:
                                    owner = await self.fetch_user(int(vps['created_by']))
                                    await owner.send(f"⚠️ Your VPS {vps['vps_id']} has been suspended due to detected mining activity. Contact admin to unsuspend.")
                                except:
                                    pass
                                break
                    except Exception as e:
                        logger.error(f"Error checking VPS {vps['vps_id']} for mining: {e}")
            except Exception as e:
                logger.error(f"Error in anti_miner_monitor: {e}")
            await asyncio.sleep(300)  # Check every 5 minutes

    async def update_system_stats(self):
        """Update system statistics periodically"""
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                # CPU usage
                cpu_percent = psutil.cpu_percent(interval=1)
                
                # Memory usage
                mem = psutil.virtual_memory()
                
                # Disk usage
                disk = psutil.disk_usage('/')
                
                # Network IO
                net_io = psutil.net_io_counters()
                
                self.system_stats = {
                    'cpu_usage': cpu_percent,
                    'memory_usage': mem.percent,
                    'memory_used': mem.used / (1024 ** 3),  # GB
                    'memory_total': mem.total / (1024 ** 3),  # GB
                    'disk_usage': disk.percent,
                    'disk_used': disk.used / (1024 ** 3),  # GB
                    'disk_total': disk.total / (1024 ** 3),  # GB
                    'network_sent': net_io.bytes_sent / (1024 ** 2),  # MB
                    'network_recv': net_io.bytes_recv / (1024 ** 2),  # MB
                    'last_updated': time.time()
                }
            except Exception as e:
                logger.error(f"Error updating system stats: {e}")
            await asyncio.sleep(30)

    async def close(self):
        await super().close()
        if self.session:
            await self.session.close()
        if self.docker_client:
            self.docker_client.close()
        self.db.close()

def generate_token():
    """Generate a random token for VPS access"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=24))

def generate_vps_id():
    """Generate a unique VPS ID"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=10))

def generate_ssh_password():
    """Generate a random SSH password"""
    chars = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choices(chars, k=16))

def has_admin_role(ctx):
    """Check if user has admin role or is in ADMIN_IDS"""
    if isinstance(ctx, discord.Interaction):
        user_id = ctx.user.id
        roles = ctx.user.roles
    else:
        user_id = ctx.author.id
        roles = ctx.author.roles
    
    if user_id in ADMIN_IDS:
        return True
    
    return any(role.id == ADMIN_ROLE_ID for role in roles)

async def capture_ssh_session_line(process):
    """Capture the SSH session line from tmate output"""
    try:
        while True:
            output = await process.stdout.readline()
            if not output:
                break
            output = output.decode('utf-8').strip()
            if "ssh session:" in output:
                return output.split("ssh session:")[1].strip()
        return None
    except Exception as e:
        logger.error(f"Error capturing SSH session: {e}")
        return None

async def run_docker_command(container_id, command, timeout=120):
    """Run a Docker command asynchronously with timeout"""
    try:
        process = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            if process.returncode != 0:
                raise Exception(f"Command failed: {stderr.decode()}")
            return True, stdout.decode()
        except asyncio.TimeoutError:
            process.kill()
            raise Exception(f"Command timed out after {timeout} seconds")
    except Exception as e:
        logger.error(f"Error running Docker command: {e}")
        return False, str(e)

async def kill_apt_processes(container_id):
    """Kill any running apt processes"""
    try:
        success, _ = await run_docker_command(container_id, ["bash", "-c", "killall apt apt-get dpkg || true"])
        await asyncio.sleep(2)
        success, _ = await run_docker_command(container_id, ["bash", "-c", "rm -f /var/lib/apt/lists/lock /var/cache/apt/archives/lock /var/lib/dpkg/lock*"])
        await asyncio.sleep(2)
        return success
    except Exception as e:
        logger.error(f"Error killing apt processes: {e}")
        return False

async def wait_for_apt_lock(container_id, status_msg):
    """Wait for apt lock to be released"""
    max_attempts = 5
    for attempt in range(max_attempts):
        try:
            await kill_apt_processes(container_id)
            
            process = await asyncio.create_subprocess_exec(
                "docker", "exec", container_id, "bash", "-c", "lsof /var/lib/dpkg/lock-frontend",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                return True
                
            if isinstance(status_msg, discord.Interaction):
                await status_msg.followup.send(f"🔄 Waiting for package manager to be ready... (Attempt {attempt + 1}/{max_attempts})", ephemeral=True)
            else:
                await status_msg.edit(content=f"🔄 Waiting for package manager to be ready... (Attempt {attempt + 1}/{max_attempts})")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Error checking apt lock: {e}")
            await asyncio.sleep(5)
    
    return False

async def build_custom_image(vps_id, username, root_password, user_password, base_image=DEFAULT_OS_IMAGE):
    """Build a custom Docker image using our template"""
    try:
        # Create a temporary directory for the Dockerfile
        temp_dir = f"temp_dockerfiles/{vps_id}"
        os.makedirs(temp_dir, exist_ok=True)
        
        # Generate Dockerfile content
        dockerfile_content = DOCKERFILE_TEMPLATE.format(
            base_image=base_image,
            root_password=root_password,
            username=username,
            user_password=user_password,
            welcome_message=WELCOME_MESSAGE,
            watermark=WATERMARK,
            vps_id=vps_id
        )
        
        # Write Dockerfile
        dockerfile_path = os.path.join(temp_dir, "Dockerfile")
        with open(dockerfile_path, 'w') as f:
            f.write(dockerfile_content)
        
        # Build the image
        image_tag = f"PycroeCloud/{vps_id.lower()}:latest"
        build_process = await asyncio.create_subprocess_exec(
            "docker", "build", "-t", image_tag, temp_dir,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await build_process.communicate()
        
        if build_process.returncode != 0:
            raise Exception(f"Failed to build image: {stderr.decode()}")
        
        return image_tag
    except Exception as e:
        logger.error(f"Error building custom image: {e}")
        raise
    finally:
        # Clean up temporary directory
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
        except Exception as e:
            logger.error(f"Error cleaning up temp directory: {e}")

async def setup_container(container_id, status_msg, memory, username, vps_id=None, use_custom_image=False):
    """Enhanced container setup with Pycroe Host customization"""
    try:
        # Ensure container is running
        if isinstance(status_msg, discord.Interaction):
            await status_msg.followup.send("🔍 Checking container status...", ephemeral=True)
        else:
            await status_msg.edit(content="🔍 Checking container status...")
            
        container = bot.docker_client.containers.get(container_id)
        if container.status != "running":
            if isinstance(status_msg, discord.Interaction):
                await status_msg.followup.send("🚀 Starting container...", ephemeral=True)
            else:
                await status_msg.edit(content="🚀 Starting container...")
            container.start()
            await asyncio.sleep(5)

        # Generate SSH password
        ssh_password = generate_ssh_password()
        
        # Install tmate and other required packages
        if not use_custom_image:
            if isinstance(status_msg, discord.Interaction):
                await status_msg.followup.send("📦 Installing required packages...", ephemeral=True)
            else:
                await status_msg.edit(content="📦 Installing required packages...")
                
            # Update package list
            success, output = await run_docker_command(container_id, ["apt-get", "update"])
            if not success:
                raise Exception(f"Failed to update package list: {output}")

            # Install packages
            packages = [
                "tmate", "neofetch", "screen", "wget", "curl", "htop", "nano", "vim", 
                "openssh-server", "sudo", "ufw", "git", "docker.io", "systemd", "systemd-sysv"
            ]
            success, output = await run_docker_command(container_id, ["apt-get", "install", "-y"] + packages)
            if not success:
                raise Exception(f"Failed to install packages: {output}")

        # Setup SSH
        if isinstance(status_msg, discord.Interaction):
            await status_msg.followup.send("🔐 Configuring SSH access...", ephemeral=True)
        else:
            await status_msg.edit(content="🔐 Configuring SSH access...")
            
        # Create user and set password (if not using custom image)
        if not use_custom_image:
            user_setup_commands = [
                f"useradd -m -s /bin/bash {username}",
                f"echo '{username}:{ssh_password}' | chpasswd",
                f"usermod -aG sudo {username}",
                "sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin no/' /etc/ssh/sshd_config",
                "sed -i 's/#PasswordAuthentication yes/PasswordAuthentication yes/' /etc/ssh/sshd_config",
                "service ssh restart"
            ]
            
            for cmd in user_setup_commands:
                success, output = await run_docker_command(container_id, ["bash", "-c", cmd])
                if not success:
                    raise Exception(f"Failed to setup user: {output}")

        # Set Pycroe Host customization
        if isinstance(status_msg, discord.Interaction):
            await status_msg.followup.send("🎨 Setting up Pycroe HOST customization...", ephemeral=True)
        else:
            await status_msg.edit(content="🎨 Setting up Pycroe HOST customization...")
            
        # Create welcome message file
        welcome_cmd = f"echo '{WELCOME_MESSAGE}' > /etc/motd && echo 'echo \"{WELCOME_MESSAGE}\"' >> /home/{username}/.bashrc"
        success, output = await run_docker_command(container_id, ["bash", "-c", welcome_cmd])
        if not success:
            logger.warning(f"Could not set welcome message: {output}")

        # Set hostname and watermark
        if not vps_id:
            vps_id = generate_vps_id()
        hostname_cmd = f"echo 'PycroeCloud-{vps_id}' > /etc/hostname && hostname PycroeCloud-{vps_id}"
        success, output = await run_docker_command(container_id, ["bash", "-c", hostname_cmd])
        if not success:
            raise Exception(f"Failed to set hostname: {output}")

        # Set memory limit in cgroup
        if isinstance(status_msg, discord.Interaction):
            await status_msg.followup.send("⚙️ Setting resource limits...", ephemeral=True)
        else:
            await status_msg.edit(content="⚙️ Setting resource limits...")
            
        memory_bytes = memory * 1024 * 1024 * 1024
        success, output = await run_docker_command(container_id, ["bash", "-c", f"echo {memory_bytes} > /sys/fs/cgroup/memory.max"])
        if not success:
            logger.warning(f"Could not set memory limit in cgroup: {output}")

        # Set watermark in machine info
        success, output = await run_docker_command(container_id, ["bash", "-c", f"echo '{WATERMARK}' > /etc/machine-info"])
        if not success:
            logger.warning(f"Could not set machine info: {output}")

        # Basic security setup
        security_commands = [
            "ufw allow ssh",
            "ufw --force enable",
            "apt-get -y autoremove",
            "apt-get clean",
            f"chown -R {username}:{username} /home/{username}",
            f"chmod 700 /home/{username}"
        ]
        
        for cmd in security_commands:
            success, output = await run_docker_command(container_id, ["bash", "-c", cmd])
            if not success:
                logger.warning(f"Security setup command failed: {cmd} - {output}")

        if isinstance(status_msg, discord.Interaction):
            await status_msg.followup.send("✅ Pycroe HOST VPS setup completed successfully!", ephemeral=True)
        else:
            await status_msg.edit(content="✅ Pycroe HOST VPS setup completed successfully!")
            
        return True, ssh_password, vps_id
    except Exception as e:
        error_msg = f"Setup failed: {str(e)}"
        logger.error(error_msg)
        if isinstance(status_msg, discord.Interaction):
            await status_msg.followup.send(f"❌ {error_msg}", ephemeral=True)
        else:
            await status_msg.edit(content=f"❌ {error_msg}")
        return False, None, None

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = PycroeCloudBot(command_prefix='/', intents=intents, help_command=None)
DB_PATH = "PycroeCloud.db"

def get_running_instances_count() -> int:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # عدّ الـ instances اللي status = 'running'
    cursor.execute("SELECT COUNT(*) FROM vps_instances WHERE status = 'running'")
    count = cursor.fetchone()[0]

    conn.close()
    return count


@tasks.loop(seconds=15)  # تغييره حسب رغبتك
async def rotate_status(bot: discord.Client):
    count = get_running_instances_count()

    statuses = [
        f"🚀 Managing {count} Cloud Instances — Ready to Scale Anytime ☁️⚡",
        f"🧠 Running {count} Instances, Infinite Potential 💻🔥",
        f"☁️ {count} Active Instances | Infrastructure Standing By 🛡️🚀",
        f"⚙️ Managing {count} Cloud Nodes — Systems Online & Waiting 💡🖥️",
        f"🌐 {count} Cloud Instances Deployed | VPS Engine Idle but Powerful 💪⚡"
    ]

    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=random.choice(statuses)
        )
    )
@bot.event
async def on_ready():
    logger.info(f'{bot.user} has connected to Discord!')
    
    # Auto-start VPS containers based on status
    if bot.docker_client:
        for token, vps in bot.db.get_all_vps().items():
            if vps['status'] == 'running':
                try:
                    container = bot.docker_client.containers.get(vps["container_id"])
                    if container.status != "running":
                        container.start()
                        logger.info(f"Started container for VPS {vps['vps_id']}")
                except docker.errors.NotFound:
                    logger.warning(f"Container {vps['container_id']} not found")
                except Exception as e:
                    logger.error(f"Error starting container: {e}")
    
   # try:
       # await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Pycroe HOST VPS"))
       # synced_commands = await bot.tree.sync()
       # logger.info(f"Synced {len(synced_commands)} slash commands")
  #  exc#ept Exception as e:
       # logger.error(f"Error syncing slash commands: {e}")

    if not rotate_status.is_running():
        rotate_status.start(bot)

    # بعدين اعمل sync للأوامر لو محتاج
    try:
        synced_commands = await bot.tree.sync()
        logger.info(f"Synced {len(synced_commands)} slash commands completed successfully!")
    except Exception as e:
        logger.error(f"Error syncing slash commands: {e}")

POLL_INTERVAL = 5  # seconds between polls (tweakable)
STATUS_TIMEOUT = 60 * 60 * 3  # 3 hours max per live session (safety)

def _shorten(s: str, limit: int = 1000) -> str:
    if not s:
        return ""
    return s if len(s) <= limit else s[:limit-1] + "…"

async def _gather_container_info(container):
    """
    Return dict with keys: status, running, restarts, started_at, mem_cgroup_gb (optional), last_logs (str)
    This helper runs blocking docker SDK calls in executor to avoid blocking event loop.
    """
    loop = asyncio.get_running_loop()
    info = {}
    try:
        def _sync():
            container.reload()
            st = container.status
            attrs = container.attrs
            restarts = attrs.get("RestartCount", 0)
            started_at = attrs.get("State", {}).get("StartedAt")
            return st, restarts, started_at
        st, restarts, started_at = await loop.run_in_executor(None, _sync)
        info['status'] = st
        info['restarts'] = restarts
        info['started_at'] = started_at
        info['running'] = (st == "running")
    except Exception:
        info['status'] = "unknown"
        info['restarts'] = None
        info['started_at'] = None
        info['running'] = False

    # try read cgroup memory.max (cgroup v2) inside container
    try:
        rc, out = container.exec_run(
            "bash -lc 'cat /sys/fs/cgroup/memory.max 2>/dev/null || echo max'",
            stdout=True, stderr=True
        )
        v2_val = out.decode('utf-8', errors='ignore').strip()
        if v2_val.isdigit() and v2_val != "0":
            info['mem_cgroup_gb'] = round(int(v2_val) / (1024 ** 3))
        else:
            info['mem_cgroup_gb'] = None
    except Exception:
        info['mem_cgroup_gb'] = None

    # last logs - get last 12 lines
    try:
        def _logs_sync():
            return container.logs(tail=12).decode('utf-8', errors='ignore')
        last_logs = await loop.run_in_executor(None, _logs_sync)
        info['last_logs'] = last_logs.strip()
    except Exception:
        info['last_logs'] = ""

    return info

async def _status_worker(bot, ctx, vps_id: str, message, requester_id: int):
    """
    Background task that polls and updates the message embed.
    Cancelling this task should stop updates.
    """
    start_time = datetime.datetime.utcnow()
    try:
        while True:
            # safety timeout
            if (datetime.datetime.utcnow() - start_time).total_seconds() > STATUS_TIMEOUT:
                try:
                    await message.edit(content="Live status session timed out (automatic stop).")
                except Exception:
                    pass
                break

            # get vps from DB
            vps = bot.db.get_vps_by_id(vps_id)
            if not vps:
                # VPS removed -> notify and stop
                try:
                    await message.edit(content=f"VPS `{vps_id}` not found. Stopping live status.")
                except Exception:
                    pass
                break

            container_id = vps.get("container_id")
            container_obj = None
            container_status = "unknown"
            human_limit_gb = vps.get("memory")

            # try to access docker container
            try:
                if not getattr(bot, "docker_client", None):
                    bot.docker_client = docker.from_env()
                container_obj = bot.docker_client.containers.get(container_id)
            except Exception as e:
                container_status = f"container access error: {_shorten(str(e), 200)}"
            else:
                # gather details
                info = await _gather_container_info(container_obj)
                container_status = info.get("status", "unknown")
                human_limit_gb = info.get("mem_cgroup_gb") or vps.get("memory")

            # Build embed content (or plain content if you prefer)
            embed = discord.Embed(
                title=f"Live VPS Status — {vps_id}",
                timestamp=datetime.datetime.utcnow(),
                color=discord.Color.blurple()
            )
            embed.add_field(name="Owner", value=f"<@{vps.get('created_by')}>", inline=True)
            embed.add_field(name="Status", value=container_status, inline=True)
            embed.add_field(name="Memory (configured)", value=f"{vps.get('memory')} GB", inline=True)
            embed.add_field(name="Memory (enforced)", value=(f"{human_limit_gb} GB" if human_limit_gb else "N/A"), inline=True)
            embed.add_field(name="CPU", value=f"{vps.get('cpu')} cores", inline=True)
            embed.add_field(name="Disk", value=f"{vps.get('disk')} GB", inline=True)
            embed.add_field(name="Usage", value=f"Restarts: {vps.get('restart_count', 0)}", inline=True)
            embed.add_field(name="SSHX Link", value=f"```{_shorten(vps.get('sshx_link','-'),300)}```", inline=False)

            # add a simple log section
            last_logs = ""
            if container_obj:
                last_logs = (await _gather_container_info(container_obj)).get('last_logs') or ""
            if not last_logs:
                last_logs = vps.get('last_logs', '') or "(no logs available)"
            embed.add_field(name="Recent logs (tail)", value=f"```{_shorten(last_logs, 900)}```", inline=False)

            # small footer
            embed.set_footer(text=f"Live updates every {POLL_INTERVAL}s — started at {start_time.isoformat()}Z")

            # edit message
            try:
                await message.edit(content=None, embed=embed)
            except Exception:
                # If embed edit fails, try to replace with simple text
                text = textwrap.dedent(f"""
                Live VPS Status — {vps_id}
                Owner: <@{vps.get('created_by')}>
                Status: {container_status}
                Memory (configured): {vps.get('memory')} GB
                Memory (enforced): {human_limit_gb if human_limit_gb else 'N/A'} GB
                CPU: {vps.get('cpu')} cores
                Disk: {vps.get('disk')} GB
                Restarts: {vps.get('restart_count', 0)}
                SSHX Link: {_shorten(vps.get('sshx_link','-'), 400)}

                Recent logs:
                {_shorten(last_logs, 1000)}

                (updates every {POLL_INTERVAL}s)
                """)
                try:
                    await message.edit(content=text, embed=None)
                except Exception:
                    # give up this round
                    pass

            # wait
            await asyncio.sleep(POLL_INTERVAL)

    except asyncio.CancelledError:
        # graceful cancellation (user asked to stop)
        try:
            await message.edit(content="Live status session stopped by user.")
        except Exception:
            pass
        raise
    except Exception as e:
        # unexpected error: report and stop
        try:
            await message.edit(content=f"Live status worker stopped due to error: {_shorten(str(e),300)}")
        except Exception:
            pass
        logger.exception("deploy_status worker error")
    finally:
        # cleanup references in bot
        bot.vps_status_tasks.pop(vps_id, None)
        bot.vps_status_messages.pop(vps_id, None)

# The main command: supports subcommands: start / stop / status (immediate snapshot)
@bot.hybrid_command(
    name="deploy_status",
    description="Manage live status monitoring for a VPS (start|stop|snapshot). Owner or admins only."
)
@app_commands.describe(
    action="start | stop | snapshot",
    vps_id="VPS ID (e.g. PycroeCloud-abc123)"
)
async def deploy_status(ctx, action: str, vps_id: str):
    """
    action:
      - start: begin live updating message (owner or admin can start)
      - stop: stop live updates (owner or admin)
      - snapshot: show a single immediate snapshot (anyone allowed who is owner or admin)
    """
    # Basic permissions: owner or admin
    try:
        vps = bot.db.get_vps_by_id(vps_id)
    except Exception:
        vps = None

    if not vps:
        await ctx.send("VPS not found. Check the VPS ID.", ephemeral=True)
        return

    caller_id = getattr(ctx.author, "id", None)
    is_owner = str(caller_id) == str(vps.get("created_by"))
    is_admin = has_admin_role(ctx)

    if not (is_owner or is_admin):
        await ctx.send("Only the VPS owner or an admin can manage live status for this VPS.", ephemeral=True)
        return

    action = action.lower().strip()
    if action not in ("start", "stop", "snapshot"):
        await ctx.send("Invalid action. Use `start`, `stop`, or `snapshot`.", ephemeral=True)
        return

    # Initialize storage dicts if missing
    if not hasattr(bot, "vps_status_tasks"):
        bot.vps_status_tasks = {}
    if not hasattr(bot, "vps_status_messages"):
        bot.vps_status_messages = {}

    # STOP
    if action == "stop":
        task = bot.vps_status_tasks.get(vps_id)
        if not task:
            await ctx.send("No active live status session found for this VPS.", ephemeral=True)
            return
        task.cancel()
        # task's finally will cleanup dict entries
        await ctx.send("Stopping live status session...", ephemeral=True)
        return

    # SNAPSHOT (one-time)
    if action == "snapshot":
        # build immediate snapshot (reuse worker helper for single-shot)
        container_id = vps.get("container_id")
        container_obj = None
        try:
            if not getattr(bot, "docker_client", None):
                bot.docker_client = docker.from_env()
            container_obj = bot.docker_client.containers.get(container_id)
        except Exception:
            container_obj = None

        info = {}
        if container_obj:
            info = await _gather_container_info(container_obj)
        embed = discord.Embed(title=f"VPS Snapshot — {vps_id}", timestamp=datetime.datetime.utcnow())
        embed.add_field(name="Owner", value=f"<@{vps.get('created_by')}>", inline=True)
        embed.add_field(name="Status", value=info.get("status", "unknown"), inline=True)
        embed.add_field(name="Memory (configured)", value=f"{vps.get('memory')} GB", inline=True)
        embed.add_field(name="Memory (enforced)", value=(f"{info.get('mem_cgroup_gb')} GB" if info.get('mem_cgroup_gb') else "N/A"), inline=True)
        embed.add_field(name="Logs (tail)", value=f"```{_shorten(info.get('last_logs','(no logs)'))}```", inline=False)
        await ctx.send(embed=embed, ephemeral=True)
        return

    # START
    if action == "start":
        # if already running -> tell the caller
        if vps_id in bot.vps_status_tasks:
            await ctx.send("Live status session already running for this VPS. Use `deploy_status stop <vps_id>` then restart if you want a fresh session.", ephemeral=True)
            return

        # create message to edit later
        starter = await ctx.send(f"Starting live status for `{vps_id}` — preparing...", ephemeral=False)
        # store message reference
        bot.vps_status_messages[vps_id] = starter

        # spawn worker task
        task = bot.loop.create_task(_status_worker(bot, ctx, vps_id, starter, requester_id=caller_id))
        bot.vps_status_tasks[vps_id] = task

        await ctx.send("Live status session started. The message above will be updated periodically. Use `deploy_status stop <vps_id>` to stop it.", ephemeral=True)
        return
@bot.hybrid_command(name='ping', description='Ping the bot latency')
async def ping(ctx):
    """Ping the bot latency"""
    try:
        latency = bot.latency * 1000  # Convert to milliseconds
        await ctx.send(f"Pong Latency: {latency:.2f} ms")
    except Exception as e:
        logger.error(f"Error in ping command: {e}")
        await ctx.send("An error occurred while processing your request.")
@bot.hybrid_command(name='help', description='Show all available commands')
async def show_commands(ctx):
    """Show all available commands"""
    try:
        embed = discord.Embed(title="🤖 Pycroe HOST VPS Bot Commands", color=discord.Color.blue())
        
        # User commands
        embed.add_field(name="User Commands", value="""
`/deploy` - Create a new VPS (Admin only)
`/connect_vps <token>` - Connect to your VPS
`/list` - List all your VPS instances
`/ping` - Check bot latency
`/help` - Show this help message
`/manage_vps <vps_id>` - Manage your VPS
`/transfer_vps <vps_id> <user>` - Transfer VPS ownership
`/vps_stats <vps_id>` - Show VPS resource usage
`/change_ssh_password <vps_id>` - Change SSH password
`/vps_shell <vps_id>` - Get shell access to your VPS
`/vps_console <vps_id>` - Get direct console access to your VPS
`/vps_usage` - Show your VPS usage statistics
""", inline=False)
        
        # Admin commands
        if has_admin_role(ctx):
            embed.add_field(name="Admin Commands", value="""
`/list_all` - List all VPS instances
`/delete_vps <vps_id>` - Delete a VPS
`/admin_stats` - Show system statistics
`/cleanup_vps` - Cleanup inactive VPS instances
`/add_admin <user>` - Add a new admin
`/remove_admin <user>` - Remove an admin (Owner only)
`/list_admins` - List all admin users
`/system_info` - Show detailed system information
`/container_limit <max>` - Set maximum container limit
`/global_stats` - Show global usage statistics
`/migrate_vps <vps_id>` - Migrate VPS to another host
`/emergency_stop <vps_id>` - Force stop a problematic VPS
`/emergency_remove <vps_id>` - Force remove a problematic VPS
`/suspend_vps <vps_id>` - Suspend a VPS
`/unsuspend_vps <vps_id>` - Unsuspend a VPS
`/edit_vps <vps_id> <memory> <cpu> <disk>` - Edit VPS specifications
`/ban_user <user>` - Ban a user from creating VPS
`/unban_user <user>` - Unban a user
`/list_banned` - List banned users
`/backup_data` - Backup all data
`/restore_data` - Restore from backup
`/reinstall_bot` - Reinstall the bot (Owner only)
""", inline=False)
        
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in show_commands: {e}")
        await ctx.send("❌ An error occurred while processing your request.")

@bot.hybrid_command(name='add_admin', description='Add a new admin (Admin only)')
@app_commands.describe(
    user="User to make admin"
)
async def add_admin(ctx, user: discord.User):
    """Add a new admin user"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return
    
    bot.db.add_admin(user.id)
    await ctx.send(f"✅ {user.mention} has been added as an admin!")

@bot.hybrid_command(name='remove_admin', description='Remove an admin (Owner only)')
@app_commands.describe(
    user="User to remove from admin"
)
async def remove_admin(ctx, user: discord.User):
    """Remove an admin user (Owner only)"""
    if ctx.author.id != 1210291131301101618:  # Only the owner can remove admins
        await ctx.send("❌ Only the owner can remove admins!", ephemeral=True)
        return
    
    bot.db.remove_admin(user.id)
    await ctx.send(f"✅ {user.mention} has been removed from admins!")

@bot.hybrid_command(name='list_admins', description='List all admin users')
async def list_admins(ctx):
    """List all admin users"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return
    
    embed = discord.Embed(title="Admin Users", color=discord.Color.blue())
    
    # List user IDs in ADMIN_IDS
    admin_list = []
    for admin_id in ADMIN_IDS:
        try:
            user = await bot.fetch_user(admin_id)
            admin_list.append(f"{user.name} ({user.id})")
        except:
            admin_list.append(f"Unknown User ({admin_id})")
    
    # List users with admin role
    if ctx.guild:
        admin_role = ctx.guild.get_role(ADMIN_ROLE_ID)
        if admin_role:
            role_admins = [f"{member.name} ({member.id})" for member in admin_role.members]
            admin_list.extend(role_admins)
    
    if not admin_list:
        embed.description = "No admins found"
    else:
        embed.description = "\n".join(sorted(set(admin_list)))  # Remove duplicates
    
    await ctx.send(embed=embed, ephemeral=True)

@bot.hybrid_command(name='deploy', description='Create a new VPS (Admin only)')
@app_commands.describe(
    memory="Memory in GB",
    cpu="CPU cores",
    disk="Disk space in GB",
    owner="User who will own the VPS",
    os_image="OS image to use (ubuntu/debian/arch), default is Ubuntu 22.04 LTS",
    use_custom_image="Use custom Pycroe HOST image (recommended)",
    reason="Optional reason for this deployment"
)
async def create_vps_command(
    ctx,
    memory: int,
    cpu: int,
    disk: int,
    owner: discord.Member,
    os_image: str = DEFAULT_OS_IMAGE,
    use_custom_image: bool = True,
    reason: Optional[str] = None
):
    """Create a new VPS with specified parameters (Admin only) — improved: no-swap, cgroup assert, better UX"""
    # ---------- Helpers (محلية للوظيفة بحيث تفضل في ملف واحد) ----------
    async def _assert_no_swap(container, expected_gb: int) -> bool:
        """تحقّق إن memory.max = expected و memory.swap.max = 0 (cgroup v2)"""
        try:
            rc1, out1 = container.exec_run(
                "bash -lc 'cat /sys/fs/cgroup/memory.max 2>/dev/null || echo max'"
            )
            rc2, out2 = container.exec_run(
                "bash -lc 'cat /sys/fs/cgroup/memory.swap.max 2>/dev/null || echo none'"
            )
            mem_val = out1.decode().strip()
            swap_val = out2.decode().strip()
            ok_mem = mem_val.isdigit() and abs(int(mem_val) - expected_gb*(1024**3)) <= (1*1024**3)
            ok_swap = swap_val == "0"
            return ok_mem and ok_swap
        except Exception:
            return False

    async def _get_tmate(container_id: str, tries: int = 2) -> Optional[str]:
        """التقاط سطر tmate (ssh session) مع محاولتين"""
        for _ in range(tries):
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", container_id, "tmate", "-F",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            line = await capture_ssh_session_line(proc)
            if line:
                return line
        return None

    # ----------------- البداية الفعلية للأمر -----------------
    try:
        # صلاحيات
        if not has_admin_role(ctx):
            await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
            return
        if bot.db.is_user_banned(owner.id):
            await ctx.send("❌ This user is banned from creating VPS!", ephemeral=True); return
        if not ctx.guild:
            await ctx.send("❌ This command can only be used in a server!", ephemeral=True); return

        # Docker جاهز
        try:
            if not bot.docker_client:
                bot.docker_client = docker.from_env()
            bot.docker_client.ping()
        except Exception:
            await ctx.send(
                "❌ Docker is not available. run ```\n"
                "sudo apt update\nsudo apt install -y docker.io\n"
                "sudo systemctl enable --now docker\nsudo systemctl status docker --no-pager\n```",
                ephemeral=True
            )
            return

        # Validate
        if not (1 <= memory <= 512):
            await ctx.send("❌ Memory must be between 1GB and 512GB", ephemeral=True); return
        if not (1 <= cpu <= 32):
            await ctx.send("❌ CPU cores must be between 1 and 32", ephemeral=True); return
        if not (10 <= disk <= 1000):
            await ctx.send("❌ Disk space must be between 10GB and 1000GB", ephemeral=True); return

        # حدود السيستم/المستخدم
        containers = bot.docker_client.containers.list(all=True)
        if len(containers) >= bot.db.get_setting('max_containers', MAX_CONTAINERS):
            await ctx.send(
                f"❌ Maximum container limit reached ({bot.db.get_setting('max_containers')}). "
                f"Please delete some VPS instances first.", ephemeral=True
            )
            return
        if bot.db.get_user_vps_count(owner.id) >= bot.db.get_setting('max_vps_per_user', MAX_VPS_PER_USER):
            await ctx.send(
                f"❌ {owner.mention} already has the maximum number of VPS instances "
                f"({bot.db.get_setting('max_vps_per_user')})", ephemeral=True
            )
            return

        status_msg = await ctx.send("🚀 Creating Pycroe HOST VPS instance... This may take a few minutes.")

        # ثوابت الإنشاء
        mem_str = f"{memory}g"  # هنستخدمها لـ mem_limit/memswap_limit
        vps_id = generate_vps_id()
        username = owner.name.lower().replace(" ", "_")[:20]
        root_password = generate_ssh_password()
        user_password = generate_ssh_password()
        token = generate_token()

        # الشبكة
        try:
            nets = subprocess.run(
                ["docker","network","ls","--format","{{.Name}}"],
                capture_output=True, text=True
            ).stdout.splitlines()
            if DOCKER_NETWORK not in nets:
                subprocess.run(["docker","network","create", DOCKER_NETWORK], check=False)
        except Exception:
            pass

        # عامل تشغيل موحّد (No-Swap + OOM Kill شغال)
        def _run_container(image: str, custom: bool):
            common = dict(
                detach=True,
                privileged=True,
                hostname=f"PycroeCloud-{vps_id}",
                mem_limit=mem_str,
                memswap_limit=mem_str,
                mem_swappiness=0,
                oom_kill_disable=False,
                cpu_period=100000,
                cpu_quota=int(cpu * 100000),
                cap_add=["ALL"],
                network=DOCKER_NETWORK,
                volumes={
                    f'PycroeCloud-{vps_id}': {'bind': '/data', 'mode': 'rw'},
                    '/var/lib/lxcfs/proc/meminfo': {'bind': '/proc/meminfo', 'mode': 'ro'},
                    '/var/lib/lxcfs/proc/cpuinfo': {'bind': '/proc/cpuinfo', 'mode': 'ro'},
                    '/var/lib/lxcfs/proc/stat': {'bind': '/proc/stat', 'mode': 'ro'},
                    '/var/lib/lxcfs/proc/uptime': {'bind': '/proc/uptime', 'mode': 'ro'},
                },
                restart_policy={"Name": "always"},
                name=f"PycroeCloud-{vps_id}",
            )
            if custom:
                return bot.docker_client.containers.run(image, **common)
            else:
                return bot.docker_client.containers.run(
                    image,
                    command="bash -lc 'while true; do sleep 3600; done'",
                    tty=True,
                    **common
                )

        # Build/Run
        try:
            if use_custom_image:
                await status_msg.edit(content="🔨 Building custom Docker image...")
                image_tag = await build_custom_image(
                    vps_id, username, root_password, user_password, os_image
                )
                await status_msg.edit(content="⚙️ Initializing container...")
                container = _run_container(image_tag, custom=True)
            else:
                await status_msg.edit(content="⚙️ Initializing container...")
                try:
                    container = _run_container(os_image, custom=False)
                except docker.errors.ImageNotFound:
                    await status_msg.edit(
                        content=f"❌ OS image {os_image} not found. Using default {DEFAULT_OS_IMAGE}"
                    )
                    container = _run_container(DEFAULT_OS_IMAGE, custom=False)
                    os_image = DEFAULT_OS_IMAGE
        except Exception as e:
            await status_msg.edit(content=f"❌ Failed to start container: {e}")
            return

        # تأكيد عدم وجود Swap + تطبيق RAM limit
        enforced_ok = await _assert_no_swap(container, memory)
        if not enforced_ok:
            try:
                container.stop(); container.remove()
            except Exception:
                pass
            await status_msg.edit(
                content=("❌ Memory/Swap limits weren’t enforced on this container.\n"
                         "تأكّد إن الـ host مُفعّل cgroups v2 (واضح إنه مفعّل عندك)، "
                         "وإننا بنشغّل بـ mem_limit=memswap_limit و mem_swappiness=0 (اتعملت)، "
                         "لو فضلت المشكلة جرّب `docker update --memory {0}g --memory-swap {0}g --memory-swappiness 0 <cid>` ثم أعد المحاولة."
                         ).format(memory)
            )
            return

        # Setup داخل الكونتينر
        await status_msg.edit(content="🔧 Container created. Setting up Pycroe Host environment...")
        await asyncio.sleep(1)

        setup_success, ssh_password, _ = await setup_container(
            container.id, status_msg, memory, username, vps_id=vps_id, use_custom_image=use_custom_image
        )
        if not setup_success:
            try:
                container.stop(); container.remove()
            except Exception:
                pass
            await status_msg.edit(content="❌ Failed to setup container.")
            return

        # تأكيد cgroup memory (عرض فقط)
        human_limit_gb = None
        try:
            exit_code, output = container.exec_run(
                "bash -lc 'cat /sys/fs/cgroup/memory.max 2>/dev/null || echo max'",
                stdout=True, stderr=True
            )
            v2_val = output.decode('utf-8', errors='ignore').strip()
            if v2_val.isdigit() and v2_val != "0":
                human_limit_gb = round(int(v2_val) / (1024 ** 3))
        except Exception:
            pass

        # tmate
        await status_msg.edit(content="🔐 Starting SSH/tmate session...")
        ssh_session_line = await _get_tmate(container.id, tries=2)
        if not ssh_session_line:
            try:
                container.stop(); container.remove()
            except Exception:
                pass
            await status_msg.edit(content="❌ Failed to get tmate session")
            return

        # حفظ في DB
        vps_data = {
            "token": token,
            "vps_id": vps_id,
            "container_id": container.id,
            "memory": memory,
            "cpu": cpu,
            "disk": disk,
            "username": username,
            "password": ssh_password,
            "root_password": root_password if use_custom_image else None,
            "created_by": str(owner.id),
            "created_at": str(datetime.datetime.now()),
            "tmate_session": ssh_session_line,
            "watermark": WATERMARK,
            "os_image": os_image,
            "restart_count": 0,
            "last_restart": None,
            "status": "running",
            "use_custom_image": use_custom_image
        }
        bot.db.add_vps(vps_data)

        # إخطار + Embed
        try:
            embed = discord.Embed(title="🎉 Pycroe Host VPS Creation Successful", color=discord.Color.green())
       #     embed.add_field(name=f"Admin Deployed:") #embed.image.url = "https://i.imgur.com/fJTPMM9.png" 
            embed.add_field(name="🆔 VPS ID", value=vps_id, inline=True)
            embed.add_field(name="💾 Memory", value=f"{memory}GB", inline=True)
            if human_limit_gb:
                embed.add_field(name="🧰 Enforced Limit", value=f"{human_limit_gb}GB (cgroup)", inline=True)
            embed.add_field(name="⚡ CPU", value=f"{cpu} cores", inline=True)
            embed.add_field(name="💿 Disk", value=f"{disk}GB", inline=True)
            if reason:
                embed.add_field(name="📝 Reason", value=reason[:1024], inline=False)
            embed.add_field(name="👤 Username", value=username, inline=True)
            embed.add_field(name="🔑 User Password", value=f"||{ssh_password}||", inline=False)
            if use_custom_image:
                embed.add_field(name="🔑 Root Password", value=f"||{root_password}||", inline=False)
       
            embed.add_field(name="🔒 Tmate Session", value=f"```{ssh_session_line}```", inline=False)
      #      embed.add_field(name="🔌 Direct SSH", value=f"```ssh {username}@<server-ip>```", inline=False)
            embed.add_field(
                name="ℹ️ Note",
                value=("This is a Pycroe Host VPS instance. You can install and configure additional packages as needed."),
                inline=False
            )
            embed.add_field(
                name="🧰 Auto-Installed Packages",
                value=(
                    "Includes:\n"
                    "• `tmate` & `tmux`\n"
                    "• `OpenSSH` + `sudo`\n"
                    "• `Python 3`\n\n"
        #            "⚠️ **Important:** Using Docker *inside* this instance will result in your VPS being "
        #           "**suspended and permanently deleted**.\n"
                ),
                inline=False
            )

            await owner.send(embed=embed)
            await status_msg.edit(
                content=f"✅ Pycroe HOST VPS creation successful! VPS has been created for {owner.mention}. Check your DMs for connection details."
            )
        except discord.Forbidden:
            await status_msg.edit(
                content=f"❌ I couldn't send a DM to {owner.mention}. Please ask them to enable DMs from server members."
            )

    except Exception as e:
        logger.error(f"deploy error: {e}")
        await ctx.send(f"❌ An error occurred while creating the VPS: {e}")
        try:
            if 'container' in locals():
                try:
                    container.stop(); container.remove()
                except Exception:
                    pass
        except Exception:
            pass
@bot.hybrid_command(name='sshx_deploy', description='Create a new VPS (Admin only)')
@app_commands.describe(
    memory="Memory in GB",
    cpu="CPU cores",
    disk="Disk space in GB",
    owner="User who will own the VPS",
    os_image="OS image to use (ubuntu/debian/arch), default is Ubuntu 22.04 LTS",
    use_custom_image="Use custom Pycroe HOST image (recommended)",
    reason="Optional reason for this deployment"
)
async def sshx_deploy(
    ctx,
    memory: int,
    cpu: int,
    disk: int,
    owner: discord.Member,
    os_image: str = DEFAULT_OS_IMAGE,
    use_custom_image: bool = True,
    reason: Optional[str] = None
):
    """Create a new VPS with specified parameters (Admin only).
    This command sets up the container and installs sshx inside it, then returns the sshx output as SSHX LINK.
    Note: this command will NOT provide direct SSH credentials in chat/DM."""
    async def _assert_no_swap(container, expected_gb: int) -> bool:
        try:
            rc1, out1 = container.exec_run(
                "bash -lc 'cat /sys/fs/cgroup/memory.max 2>/dev/null || echo max'"
            )
            rc2, out2 = container.exec_run(
                "bash -lc 'cat /sys/fs/cgroup/memory.swap.max 2>/dev/null || echo none'"
            )
            mem_val = out1.decode().strip()
            swap_val = out2.decode().strip()
            ok_mem = mem_val.isdigit() and abs(int(mem_val) - expected_gb*(1024**3)) <= (1*1024**3)
            ok_swap = swap_val == "0"
            return ok_mem and ok_swap
        except Exception:
            return False

    async def _get_tmate(container_id: str, tries: int = 2) -> Optional[str]:
        for _ in range(tries):
            proc = await asyncio.create_subprocess_exec(
                "docker", "exec", container_id, "tmate", "-F",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            line = await capture_ssh_session_line(proc)
            if line:
                return line
        return None

    try:
        # Permissions & context checks
        if not has_admin_role(ctx):
            await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
            return
        if bot.db.is_user_banned(owner.id):
            await ctx.send("❌ This user is banned from creating VPS!", ephemeral=True); return
        if not ctx.guild:
            await ctx.send("❌ This command can only be used in a server!", ephemeral=True); return

        # Docker availability
        try:
            if not bot.docker_client:
                bot.docker_client = docker.from_env()
            bot.docker_client.ping()
        except Exception:
            await ctx.send(
                "❌ Docker is not available. run ```\n"
                "sudo apt update\nsudo apt install -y docker.io\n"
                "sudo systemctl enable --now docker\nsudo systemctl status docker --no-pager\n```",
                ephemeral=True
            )
            return

        # Validate resources
        if not (1 <= memory <= 512):
            await ctx.send("❌ Memory must be between 1GB and 512GB", ephemeral=True); return
        if not (1 <= cpu <= 32):
            await ctx.send("❌ CPU cores must be between 1 and 32", ephemeral=True); return
        if not (10 <= disk <= 1000):
            await ctx.send("❌ Disk space must be between 10GB and 1000GB", ephemeral=True); return

        # Limits
        containers = bot.docker_client.containers.list(all=True)
        if len(containers) >= bot.db.get_setting('max_containers', MAX_CONTAINERS):
            await ctx.send(
                f"❌ Maximum container limit reached ({bot.db.get_setting('max_containers')}). "
                f"Please delete some VPS instances first.", ephemeral=True
            )
            return
        if bot.db.get_user_vps_count(owner.id) >= bot.db.get_setting('max_vps_per_user', MAX_VPS_PER_USER):
            await ctx.send(
                f"❌ {owner.mention} already has the maximum number of VPS instances "
                f"({bot.db.get_setting('max_vps_per_user')})", ephemeral=True
            )
            return

        status_msg = await ctx.send("🚀 Creating Pycroe HOST VPS instance... This may take a few minutes.")

        # Creation constants
        mem_str = f"{memory}g"
        vps_id = generate_vps_id()
        username = owner.name.lower().replace(" ", "_")[:20]
        root_password = generate_ssh_password()
        user_password = generate_ssh_password()
        token = generate_token()

        # Ensure docker network
        try:
            nets = subprocess.run(
                ["docker","network","ls","--format","{{.Name}}"],
                capture_output=True, text=True
            ).stdout.splitlines()
            if DOCKER_NETWORK not in nets:
                subprocess.run(["docker","network","create", DOCKER_NETWORK], check=False)
        except Exception:
            pass

        # Container runner
        def _run_container(image: str, custom: bool):
            common = dict(
                detach=True,
                privileged=True,
                hostname=f"PycroeCloud-{vps_id}",
                mem_limit=mem_str,
                memswap_limit=mem_str,
                mem_swappiness=0,
                oom_kill_disable=False,
                cpu_period=100000,
                cpu_quota=int(cpu * 100000),
                cap_add=["ALL"],
                network=DOCKER_NETWORK,
                volumes={
                    f'PycroeCloud-{vps_id}': {'bind': '/data', 'mode': 'rw'},
                    '/var/lib/lxcfs/proc/meminfo': {'bind': '/proc/meminfo', 'mode': 'ro'},
                    '/var/lib/lxcfs/proc/cpuinfo': {'bind': '/proc/cpuinfo', 'mode': 'ro'},
                    '/var/lib/lxcfs/proc/stat': {'bind': '/proc/stat', 'mode': 'ro'},
                    '/var/lib/lxcfs/proc/uptime': {'bind': '/proc/uptime', 'mode': 'ro'},
                },
                restart_policy={"Name": "always"},
                name=f"PycroeCloud-{vps_id}",
            )
            if custom:
                return bot.docker_client.containers.run(image, **common)
            else:
                return bot.docker_client.containers.run(
                    image,
                    command="bash -lc 'while true; do sleep 3600; done'",
                    tty=True,
                    **common
                )

        # Build or run image
        try:
            if use_custom_image:
                await status_msg.edit(content="🔨 Building custom Docker image...")
                image_tag = await build_custom_image(
                    vps_id, username, root_password, user_password, os_image
                )
                await status_msg.edit(content="⚙️ Initializing container...")
                container = _run_container(image_tag, custom=True)
            else:
                await status_msg.edit(content="⚙️ Initializing container...")
                try:
                    container = _run_container(os_image, custom=False)
                except docker.errors.ImageNotFound:
                    await status_msg.edit(
                        content=f"❌ OS image {os_image} not found. Using default {DEFAULT_OS_IMAGE}"
                    )
                    container = _run_container(DEFAULT_OS_IMAGE, custom=False)
                    os_image = DEFAULT_OS_IMAGE
        except Exception as e:
            await status_msg.edit(content=f"❌ Failed to start container: {e}")
            return

        # Verify cgroup memory/swap enforcement
        enforced_ok = await _assert_no_swap(container, memory)
        if not enforced_ok:
            try:
                container.stop(); container.remove()
            except Exception:
                pass
            await status_msg.edit(
                content=("❌ Memory/Swap limits weren’t enforced on this container.\n"
                         "Ensure host uses cgroups v2 and docker is configured with memory limits.")
            )
            return

        # Setup inside the container (your existing helper)
        await status_msg.edit(content="🔧 Container created. Setting up Pycroe Host environment...")
        await asyncio.sleep(1)
        setup_success, ssh_password, _ = await setup_container(
            container.id, status_msg, memory, username, vps_id=vps_id, use_custom_image=use_custom_image
        )
        if not setup_success:
            try:
                container.stop(); container.remove()
            except Exception:
                pass
            await status_msg.edit(content="❌ Failed to setup container.")
            return

        # (Optional) read human readable cgroup limit for display
        human_limit_gb = None
        try:
            exit_code, output = container.exec_run(
                "bash -lc 'cat /sys/fs/cgroup/memory.max 2>/dev/null || echo max'",
                stdout=True, stderr=True
            )
            v2_val = output.decode('utf-8', errors='ignore').strip()
            if v2_val.isdigit() and v2_val != "0":
                human_limit_gb = round(int(v2_val) / (1024 ** 3))
        except Exception:
            pass

        # Start tmate (for support) - keep this behavior if you rely on it
        await status_msg.edit(content="🔐 Starting tmate session for support...")
        ssh_session_line = await _get_tmate(container.id, tries=2)
        if not ssh_session_line:
            # not fatal for sshx flow, but many flows expect tmate; we will warn and continue
            ssh_session_line = None

        # Install sshx installer and run sshx inside the container, capture output
        await status_msg.edit(content="🔗 Installing sshx inside the container and capturing SSHX LINK...")
        sshx_output = None
        try:
            # Run the install script (silent); do not fail the whole process if this part fails
            _, install_out = container.exec_run("bash -lc 'curl -sSf https://sshx.io/get | sh'") 
            # After install, attempt to run `sshx` with no args to get its default output (or a URL)
            rc, run_out = container.exec_run("bash -lc 'sshx 2>&1 || true'")
            sshx_output = run_out.decode('utf-8', errors='ignore').strip()
            # Heuristic: if the output is long, try to find a URL-looking substring (sshx.io/ or https://)
            if sshx_output:
                import re
                m = re.search(r'(https?://\S+|sshx\.io/\S+)', sshx_output)
                if m:
                    sshx_output = m.group(0)
        except Exception:
            sshx_output = None

        if not sshx_output:
            sshx_output = "SSHX LINK not available (installation or runtime of sshx failed inside the container)."

        # Save VPS to DB with sshx link (no direct ssh credentials in chat)
        vps_data = {
            "token": token,
            "vps_id": vps_id,
            "container_id": container.id,
            "memory": memory,
            "cpu": cpu,
            "disk": disk,
            "username": username,
            "password": ssh_password,
            "root_password": root_password if use_custom_image else None,
            "created_by": str(owner.id),
            "created_at": str(datetime.datetime.now()),
            "tmate_session": ssh_session_line,
            "sshx_link": sshx_output,
            "watermark": WATERMARK,
            "os_image": os_image,
            "restart_count": 0,
            "last_restart": None,
            "status": "running",
            "use_custom_image": use_custom_image
        }
        bot.db.add_vps(vps_data)

        # Notify owner (DM) and edit status message
        try:
            embed = discord.Embed(title="🎉 Pycroe Host VPS Creation Successful", color=discord.Color.green())
            embed.set_thumbnail(url="https://i.imgur.com/fJTPMM9.png")
            embed.add_field(name="VPS ID", value=vps_id, inline=True)
            embed.add_field(name="Memory", value=f"{memory}GB", inline=True)
            if human_limit_gb:
                embed.add_field(name="Enforced Limit", value=f"{human_limit_gb}GB (cgroup)", inline=True)
            embed.add_field(name="CPU", value=f"{cpu} cores", inline=True)
            embed.add_field(name="Disk", value=f"{disk}GB", inline=True)
            if reason:
                embed.add_field(name="Reason", value=reason[:1024], inline=False)
            embed.add_field(name="Username", value=username, inline=True)
            # Do NOT provide direct SSH password in the embed or public chat.
            if use_custom_image:
                # Root password is kept in DB but not shown directly in chat. If you must reveal it, consider DM + encryption.
                embed.add_field(name="Root Password", value="(stored securely)", inline=False)
            embed.add_field(name="SSHX LINK", value=f"```{sshx_output}```", inline=False)
            if ssh_session_line:
                embed.add_field(name="Support Session (tmate)", value=f"```{ssh_session_line}```", inline=False)
            embed.add_field(
                name="Note",
                value=("This is a Pycroe Host VPS instance. The SSHX LINK is how you can connect via sshx.io. "
                       "Direct SSH credentials are not displayed here. Using Docker inside the VPS may lead to suspension."),
                inline=False
            )
            embed.add_field(
                name="Auto-Installed Packages",
                value="Includes: tmate, tmux, OpenSSH, sudo, Python 3",
                inline=False
            )

            await owner.send(embed=embed)
            await status_msg.edit(
                content=f"✅ Pycroe HOST VPS creation successful! VPS has been created for {owner.mention}. Check your DMs for the SSHX LINK and details."
            )
        except discord.Forbidden:
            await status_msg.edit(
                content=f"❌ I couldn't send a DM to {owner.mention}. Please ask them to enable DMs from server members."
            )

    except Exception as e:
        logger.error(f"sshx_deploy error: {e}")
        await ctx.send(f"❌ An error occurred while creating the VPS: {e}")
        try:
            if 'container' in locals():
                try:
                    container.stop(); container.remove()
                except Exception:
                    pass
        except Exception:
            pass
@bot.hybrid_command(
    name="sshx_link",
    description="Regenerate SSHX link for your VPS and close the old SSHX session (owner only)"
)
@app_commands.describe(
    vps_identifier="VPS ID or existing SSHX link"
)
async def sshx_link(ctx, vps_identifier: str):
    """
    Owner-only command.
    Provide the VPS ID (e.g. PycroeCloud-abc123) or the existing SSHX link stored for the VPS.
    This command will: verify ownership, ensure container is running, stop old sshx processes,
    reinstall/run sshx and capture the new link, save it to DB, and DM the owner the result.
    """
    # quick helpers
    def find_vps_by_identifier(identifier: str):
        # Implement according to your DB schema. Example tries ID first then link.
        v = bot.db.get_vps_by_id(identifier)
        if v:
            return v
        v = bot.db.get_vps_by_sshx_link(identifier)
        return v

    try:
        # Ensure guild context
        if not ctx.guild:
            await ctx.send("This command can only be used in a server.", ephemeral=True)
            return

        # Lookup VPS
        vps = find_vps_by_identifier(vps_identifier)
        if not vps:
            await ctx.send("VPS not found (check ID or SSHX link).", ephemeral=True)
            return

        # Check ownership
        caller_id = getattr(ctx.author, "id", None)
        if str(caller_id) != str(vps.get("created_by")):
            await ctx.send("You are not the owner of this VPS. Only the owner can run this command.", ephemeral=True)
            return

        # Get container
        container_id = vps.get("container_id")
        if not container_id:
            await ctx.send("VPS record is missing container id. Contact an admin.", ephemeral=True)
            return

        # Ensure docker client ready
        try:
            if not bot.docker_client:
                bot.docker_client = docker.from_env()
            bot.docker_client.ping()
        except Exception:
            await ctx.send("Docker is not available on the host. Ask an admin to check the host.", ephemeral=True)
            return

        # Fetch container object
        try:
            container = bot.docker_client.containers.get(container_id)
        except docker.errors.NotFound:
            await ctx.send("The container for this VPS was not found. It may have been removed.", ephemeral=True)
            return
        except Exception as e:
            await ctx.send(f"Failed to access the container: {e}", ephemeral=True)
            return

        # Is container running?
        if container.status != "running":
            await ctx.send("VPS container is not running. Starting it now...", ephemeral=True)
            try:
                container.start()
                # refresh status
                container.reload()
            except Exception as e:
                await ctx.send(f"Failed to start the container: {e}", ephemeral=True)
                return

        # Inform user we're working (ephemeral)
        working_msg = await ctx.send("Regenerating SSHX link... this may take up to a minute.", ephemeral=True)

        # 1) Try to stop any previous sshx processes inside the container
        try:
            # pkill may not exist -> try both pkill and killall, fallback to ps+awk
            cmds = [
                "bash -lc 'pkill -f sshx || true'",
                "bash -lc 'killall sshx || true'",
                # fallback: find sshx PIDs and kill
                "bash -lc \"ps -ef | grep sshx | grep -v grep | awk '{print $2}' | xargs -r kill -9 || true\""
            ]
            for c in cmds:
                container.exec_run(c, stdout=False, stderr=False)
        except Exception:
            # Non-fatal - continue
            pass

        # 2) (Re)install sshx inside the container (safe to run even if already installed)
        sshx_install_cmd = "bash -lc 'curl -sSf https://sshx.io/get | sh'"
        try:
            exit_code, install_out = container.exec_run(sshx_install_cmd, demux=True, stdout=True, stderr=True)
            # we do not require successful install to be exit_code == 0 because script may behave differently
        except Exception as e:
            # continue but record error for logs
            logger.warning(f"sshx install exec failed for container {container_id}: {e}")

        # 3) Run sshx to obtain the link - try reasonable invocations and parse output
        sshx_output = None
        try:
            # First try simple run (non-interactive)
            rc, out = container.exec_run("bash -lc 'sshx 2>&1 || true'", stdout=True, stderr=True, demux=False, stream=False)
            raw = (out or b"").decode("utf-8", errors="ignore").strip()
            if raw:
                # heuristic search for URL-like substring
                import re
                m = re.search(r'(https?://\S+|sshx\.io/\S+)', raw)
                if m:
                    sshx_output = m.group(0)
                else:
                    # if raw is short and looks like a token/shortlink, use it entirely
                    if len(raw) < 300:
                        sshx_output = raw
            # If not found, attempt a more explicit command (if sshx supports an output flag)
            if not sshx_output:
                # Example fallback: try `sshx create --print` (if your sshx supports it) - adapt if needed
                rc2, out2 = container.exec_run("bash -lc 'sshx create --print 2>&1 || true'", stdout=True, stderr=True)
                raw2 = (out2 or b"").decode("utf-8", errors="ignore").strip()
                m2 = re.search(r'(https?://\S+|sshx\.io/\S+)', raw2)
                if m2:
                    sshx_output = m2.group(0)
                elif raw2 and len(raw2) < 300:
                    sshx_output = raw2
        except Exception as e:
            logger.warning(f"Failed to run sshx inside container {container_id}: {e}")

        if not sshx_output:
            # final fallback: keep a clear message but still update DB with 'not available'
            sshx_output = "SSHX LINK not available (sshx failed or produced no parsable output)."

        # 4) Update DB record
        try:
            vps['sshx_link'] = sshx_output
            vps['last_sshx_updated'] = str(datetime.datetime.now())
            bot.db.update_vps(vps.get("vps_id"), vps)  # adapt to your DB API
        except Exception:
            logger.exception("Failed to update VPS record with sshx link")

        # 5) Notify owner by DM (detailed) and reply ephemeral (short)
        owner_member = ctx.author
        try:
            embed = discord.Embed(title="SSHX Link Regenerated", color=discord.Color.blurple())
            embed.add_field(name="VPS ID", value=vps.get("vps_id"), inline=True)
            embed.add_field(name="Container", value=container_id, inline=True)
            embed.add_field(name="Status", value=container.status, inline=True)
            embed.add_field(name="SSHX LINK", value=f"```{sshx_output}```", inline=False)
            embed.add_field(name="Note", value="Old SSHX sessions inside the container were terminated before generating the new link.", inline=False)
            await owner_member.send(embed=embed)
            await working_msg.edit(content="✅ SSHX link regenerated and sent to your DMs.", ephemeral=True)
        except discord.Forbidden:
            # Can't DM - send ephemeral with the link (still allowed) or error
            try:
                await ctx.send(f"Could not DM you. Here is the SSHX LINK:\n```{sshx_output}```", ephemeral=True)
            except Exception:
                await ctx.send("Could not DM you and couldn't post the SSHX link here either. Ask an admin.", ephemeral=True)

    except Exception as e:
        logger.exception("sshx_link command failed")
        await ctx.send(f"An error occurred while regenerating SSHX link: {e}", ephemeral=True)

@bot.hybrid_command(name='list', description='List all your VPS instances')
async def list_vps(ctx):
    """List all VPS instances owned by the user"""
    try:
        user_vps = bot.db.get_user_vps(ctx.author.id)
        
        if not user_vps:
            await ctx.send("❌ You don't have any VPS instances.", ephemeral=True)
            return

        embed = discord.Embed(title="Your Pycroe HOST VPS Instances", color=discord.Color.blue())
        
        for vps in user_vps:
            try:
                # Handle missing container ID gracefully
                container = bot.docker_client.containers.get(vps["container_id"]) if vps["container_id"] else None
                status = vps['status'].capitalize() if vps.get('status') else "Unknown"
            except Exception as e:
                status = "Not Found"
                logger.error(f"Error fetching container {vps['container_id']}: {e}")

            # Adding fields safely to prevent missing keys causing errors
            embed.add_field(
                name=f"VPS ID : {vps['vps_id']}",
                value=f"""
Status: {status}
Memory: {vps.get('memory', 'Unknown')}GB
CPU: {vps.get('cpu', 'Unknown')} cores
Disk Allocated: {vps.get('disk', 'Unknown')}GB
Username: {vps.get('username', 'Unknown')}
OS: {vps.get('os_image', DEFAULT_OS_IMAGE)}
Created: {vps.get('created_at', 'Unknown')}
Restarts: {vps.get('restart_count', 0)}
""",
                inline=False
            )
        
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in list_vps: {e}")
        await ctx.send(f"❌ Error listing VPS instances: {str(e)}")

@bot.hybrid_command(name='list_all', description='List all VPS instances (Admin only)')
async def admin_list_vps(ctx):
    """List all VPS instances (Admin only)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    try:
        all_vps = bot.db.get_all_vps()
        if not all_vps:
            await ctx.send("No VPS instances found.", ephemeral=True)
            return

        embed = discord.Embed(title="All Pycroe Host VPS Instances", color=discord.Color.blue())
        valid_vps_count = 0
        
        for token, vps in all_vps.items():
            try:
                # Fetch username of the owner with error handling
                user = await bot.fetch_user(int(vps.get("created_by", "0")))
                username = user.name if user else "Unknown User"
            except Exception as e:
                username = "Unknown User"
                logger.error(f"Error fetching user {vps.get('created_by')}: {e}")

            try:
                # Handle missing container ID gracefully
                container = bot.docker_client.containers.get(vps.get("container_id", "")) if vps.get("container_id") else None
                container_status = container.status if container else "Not Found"
            except Exception as e:
                container_status = "Not Found"
                logger.error(f"Error fetching container {vps.get('container_id')}: {e}")

            # Get status and other info with error fallback
            status = vps.get('status', "Unknown").capitalize()

            vps_info = f"""
Owner: {username}
Status: {status} (Container: {container_status})
Memory: {vps.get('memory', 'Unknown')}GB
CPU: {vps.get('cpu', 'Unknown')} cores
Disk: {vps.get('disk', 'Unknown')}GB
Username: {vps.get('username', 'Unknown')}
OS: {vps.get('os_image', DEFAULT_OS_IMAGE)}
Created: {vps.get('created_at', 'Unknown')}
Restarts: {vps.get('restart_count', 0)}
"""

            embed.add_field(
                name=f"VPS {vps.get('vps_id', 'Unknown')}",
                value=vps_info,
                inline=False
            )
            valid_vps_count += 1

        if valid_vps_count == 0:
            await ctx.send("No valid VPS instances found.", ephemeral=True)
            return

        embed.set_footer(text=f"Total VPS instances: {valid_vps_count}")
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in admin_list_vps: {e}")
        await ctx.send(f"❌ Error listing VPS instances: {str(e)}")

@bot.hybrid_command(name='delete_vps', description='Delete a VPS instance completely (Admin only)')
@app_commands.describe(
    vps_id="ID of the VPS to delete"
)
async def delete_vps(ctx, vps_id: str):
    """Forcefully and cleanly delete a VPS (container, volume, image, DB record)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    try:
        token, vps = bot.db.get_vps_by_id(vps_id)
        if not vps:
            await ctx.send("❌ VPS not found!", ephemeral=True)
            return

        await ctx.send(f"🧹 Deleting Pycroe Host VPS `{vps_id}`... Please wait ⏳", ephemeral=True)

        container_id = vps.get("container_id")
        image_name = f"PycroeCloud/{vps_id.lower()}:latest"
        volume_name = f"PycroeCloud-{vps_id}"
        removed = {"container": False, "image": False, "volume": False}

        # ---- Remove Docker container
        try:
            container = bot.docker_client.containers.get(container_id)
            container.stop(timeout=10)
            container.remove(force=True)
            removed["container"] = True
            logger.info(f"[DELETE] Container {container_id} removed for VPS {vps_id}")
        except docker.errors.NotFound:
            logger.warning(f"[DELETE] Container {container_id} already gone for VPS {vps_id}")
            removed["container"] = True
        except Exception as e:
            logger.error(f"Error removing container: {e}")

        # ---- Remove Docker image if custom
        try:
            if vps.get("use_custom_image"):
                img = bot.docker_client.images.get(image_name)
                bot.docker_client.images.remove(image=img.id, force=True, noprune=False)
                removed["image"] = True
                logger.info(f"[DELETE] Image {image_name} removed for VPS {vps_id}")
        except docker.errors.ImageNotFound:
            removed["image"] = True
        except Exception as e:
            logger.error(f"Error removing image {image_name}: {e}")

        # ---- Remove associated Docker volume
        try:
            volume = bot.docker_client.volumes.get(volume_name)
            volume.remove(force=True)
            removed["volume"] = True
            logger.info(f"[DELETE] Volume {volume_name} removed for VPS {vps_id}")
        except docker.errors.NotFound:
            removed["volume"] = True
        except Exception as e:
            logger.error(f"Error removing volume {volume_name}: {e}")

        # ---- Remove leftover files (backups, temp Dockerfile dirs)
        try:
            paths = [
                f"temp_dockerfiles/{vps_id}",
                f"migrations/{vps_id}",
                f"PycroeCloud_backup_{vps_id}.pkl",
                f"/var/lib/docker/volumes/{volume_name}",
            ]
            for path in paths:
                if os.path.exists(path):
                    if os.path.isdir(path):
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        os.remove(path)
            logger.info(f"[DELETE] Residual files cleaned for VPS {vps_id}")
        except Exception as e:
            logger.error(f"Error cleaning residual files: {e}")

        # ---- Remove DB record
        try:
            bot.db.remove_vps(token)
            logger.info(f"[DELETE] VPS {vps_id} removed from DB")
        except Exception as e:
            logger.error(f"Error removing VPS record: {e}")

        # ---- Final confirmation
        embed = discord.Embed(title=f"🧹 Pycroe Host VPS {vps_id} Deleted", color=discord.Color.red())
        embed.add_field(name="Container Removed", value="✅" if removed["container"] else "⚠️ Failed", inline=True)
        embed.add_field(name="Image Removed", value="✅" if removed["image"] else "⚠️ Failed", inline=True)
        embed.add_field(name="Volume Removed", value="✅" if removed["volume"] else "⚠️ Failed", inline=True)
        embed.add_field(name="Database Entry", value="✅ Removed", inline=True)
        embed.add_field(
            name="Owner",
            value=f"<@{vps['created_by']}> ({vps['created_by']})",
            inline=False,
        )
        embed.set_footer(text=f"Deleted by {ctx.author} • {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        await ctx.send(embed=embed)

        # ---- Notify VPS owner
        try:
            owner = await bot.fetch_user(int(vps["created_by"]))
            await owner.send(f"⚠️ Your VPS `{vps_id}` has been **deleted by an admin ({ctx.author})**.")
        except Exception:
            pass

    except Exception as e:
        logger.error(f"Error in delete_vps: {e}")
        await ctx.send(f"❌ Error deleting VPS: {e}", ephemeral=True)

@bot.hybrid_command(name='connect_vps', description='Connect to a VPS using the provided token')
@app_commands.describe(
    token="Access token for the VPS"
)
async def connect_vps(ctx, token: str):
    """Connect to a VPS using the provided token"""
    vps = bot.db.get_vps_by_token(token)
    if not vps:
        await ctx.send("❌ Invalid token!", ephemeral=True)
        return
        
    if str(ctx.author.id) != vps["created_by"] and not has_admin_role(ctx):
        await ctx.send("❌ You don't have permission to access this VPS!", ephemeral=True)
        return

    try:
        try:
            container = bot.docker_client.containers.get(vps["container_id"])
            if container.status != "running":
                container.start()
                await asyncio.sleep(5)
        except:
            await ctx.send("❌ VPS instance not found or is no longer available.", ephemeral=True)
            return

        exec_cmd = await asyncio.create_subprocess_exec(
            "docker", "exec", vps["container_id"], "tmate", "-F",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        ssh_session_line = await capture_ssh_session_line(exec_cmd)
        if not ssh_session_line:
            raise Exception("Failed to get tmate session")

        bot.db.update_vps(token, {"tmate_session": ssh_session_line})
        
        embed = discord.Embed(title="Pycroe Host VPS Connection Details", color=discord.Color.blue())
        embed.add_field(name="Username", value=vps["username"], inline=True)
        embed.add_field(name="SSH Password", value=f"||{vps.get('password', 'Not set')}||", inline=True)
        embed.add_field(name="Tmate Session", value=f"```{ssh_session_line}```", inline=False)
        embed.add_field(name="Connection Instructions", value="""
1. Copy the Tmate session command
2. Open your terminal
3. Paste and run the command
4. You will be connected to your Pycroe Host VPS

Or use direct SSH:
```ssh {username}@<server-ip>```
""".format(username=vps["username"]), inline=False)
        
        await ctx.author.send(embed=embed)
        await ctx.send("✅ Connection details sent to your DMs! Use the Tmate command to connect to your Pycroe Host VPS.", ephemeral=True)
        
    except discord.Forbidden:
        await ctx.send("❌ I couldn't send you a DM. Please enable DMs from server members.", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in connect_vps: {e}")
        await ctx.send(f"❌ An error occurred while connecting to the VPS: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='vps_stats', description='Show resource usage for a VPS')
@app_commands.describe(
    vps_id="ID of the VPS to check"
)
async def vps_stats(ctx, vps_id: str):
    """Show resource usage for a VPS"""
    try:
        token, vps = bot.db.get_vps_by_id(vps_id)
        if not vps or (vps["created_by"] != str(ctx.author.id) and not has_admin_role(ctx)):
            await ctx.send("❌ VPS not found or you don't have access to it!", ephemeral=True)
            return

        try:
            container = bot.docker_client.containers.get(vps["container_id"])
            if container.status != "running":
                await ctx.send("❌ VPS is not running!", ephemeral=True)
                return

            # Get memory stats
            mem_process = await asyncio.create_subprocess_exec(
                "docker", "exec", vps["container_id"], "free", "-m",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await mem_process.communicate()
            
            if mem_process.returncode != 0:
                raise Exception(f"Failed to get memory info: {stderr.decode()}")

            # Get CPU stats
            cpu_process = await asyncio.create_subprocess_exec(
                "docker", "exec", vps["container_id"], "top", "-bn1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            cpu_stdout, cpu_stderr = await cpu_process.communicate()

            # Get disk stats
            disk_process = await asyncio.create_subprocess_exec(
                "docker", "exec", vps["container_id"], "df", "-h",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            disk_stdout, disk_stderr = await disk_process.communicate()

            embed = discord.Embed(title=f"Resource Usage for VPS {vps_id}", color=discord.Color.blue())
            embed.add_field(name="Memory Info", value=f"```{stdout.decode()}```", inline=False)
            
            if disk_process.returncode == 0:
                embed.add_field(name="Disk Info", value=f"```{disk_stdout.decode()}```", inline=False)
            
            embed.add_field(name="Configured Limits", value=f"""
Memory: {vps['memory']}GB
CPU: {vps['cpu']} cores
Disk Allocated: {vps['disk']}GB
""", inline=True)
            
            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Error checking VPS stats: {str(e)}", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in vps_stats: {e}")
        await ctx.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='change_ssh_password', description='Change the SSH password for a VPS')
@app_commands.describe(
    vps_id="ID of the VPS to update"
)
async def change_ssh_password(ctx, vps_id: str):
    """Change the SSH password for a VPS"""
    try:
        token, vps = bot.db.get_vps_by_id(vps_id)
        if not vps or vps["created_by"] != str(ctx.author.id):
            await ctx.send("❌ VPS not found or you don't have access to it!", ephemeral=True)
            return

        try:
            container = bot.docker_client.containers.get(vps["container_id"])
            if container.status != "running":
                await ctx.send("❌ VPS is not running!", ephemeral=True)
                return

            new_password = generate_ssh_password()
            
            process = await asyncio.create_subprocess_exec(
                "docker", "exec", vps["container_id"], "bash", "-c", f"echo '{vps['username']}:{new_password}' | chpasswd",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                raise Exception(f"Failed to change password: {stderr.decode()}")

            bot.db.update_vps(token, {'password': new_password})
            
            embed = discord.Embed(title=f"SSH Password Updated for VPS {vps_id}", color=discord.Color.green())
            embed.add_field(name="Username", value=vps['username'], inline=True)
            embed.add_field(name="New Password", value=f"||{new_password}||", inline=False)
            
            await ctx.author.send(embed=embed)
            await ctx.send("✅ SSH password updated successfully! Check your DMs for the new password.", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Error changing SSH password: {str(e)}", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in change_ssh_password: {e}")
        await ctx.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='admin_stats', description='Show system statistics (Admin only)')
async def admin_stats(ctx):
    """Show system statistics (Admin only)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    try:
        # Get Docker stats
        containers = bot.docker_client.containers.list(all=True) if bot.docker_client else []
        
        # Get system stats
        stats = bot.system_stats
        
        embed = discord.Embed(title="Pycroe Host System Statistics", color=discord.Color.blue())
        embed.add_field(name="VPS Instances", value=f"Total: {len(bot.db.get_all_vps())}\nRunning: {len([c for c in containers if c.status == 'running'])}", inline=True)
        embed.add_field(name="Docker Containers", value=f"Total: {len(containers)}\nRunning: {len([c for c in containers if c.status == 'running'])}", inline=True)
        embed.add_field(name="CPU Usage", value=f"{stats['cpu_usage']}%", inline=True)
        embed.add_field(name="Memory Usage", value=f"{stats['memory_usage']}% ({stats['memory_used']:.2f}GB / {stats['memory_total']:.2f}GB)", inline=True)
        embed.add_field(name="Disk Usage", value=f"{stats['disk_usage']}% ({stats['disk_used']:.2f}GB / {stats['disk_total']:.2f}GB)", inline=True)
        embed.add_field(name="Network", value=f"Sent: {stats['network_sent']:.2f}MB\nRecv: {stats['network_recv']:.2f}MB", inline=True)
        embed.add_field(name="Container Limit", value=f"{len(containers)}/{bot.db.get_setting('max_containers')}", inline=True)
        embed.add_field(name="Last Updated", value=f"<t:{int(stats['last_updated'])}:R>", inline=True)
        
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in admin_stats: {e}")
        await ctx.send(f"❌ Error getting system stats: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='system_info', description='Show detailed system information (Admin only)')
async def system_info(ctx):
    """Show detailed system information (Admin only)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    try:
        # System information
        uname = platform.uname()
        boot_time = datetime.datetime.fromtimestamp(psutil.boot_time())
        
        # CPU information
        cpu_info = f"""
System: {uname.system}
Node Name: {uname.node}
Release: {uname.release}
Version: {uname.version}
Machine: {uname.machine}
Processor: {uname.processor}
Physical cores: {psutil.cpu_count(logical=False)}
Total cores: {psutil.cpu_count(logical=True)}
CPU Usage: {psutil.cpu_percent()}%
"""
        
        # Memory Information
        svmem = psutil.virtual_memory()
        mem_info = f"""
Total: {svmem.total / (1024**3):.2f}GB
Available: {svmem.available / (1024**3):.2f}GB
Used: {svmem.used / (1024**3):.2f}GB
Percentage: {svmem.percent}%
"""
        
        # Disk Information
        partitions = psutil.disk_partitions()
        disk_info = ""
        for partition in partitions:
            try:
                partition_usage = psutil.disk_usage(partition.mountpoint)
                disk_info += f"""
Device: {partition.device}
  Mountpoint: {partition.mountpoint}
  File system type: {partition.fstype}
  Total Size: {partition_usage.total / (1024**3):.2f}GB
  Used: {partition_usage.used / (1024**3):.2f}GB
  Free: {partition_usage.free / (1024**3):.2f}GB
  Percentage: {partition_usage.percent}%
"""
            except PermissionError:
                continue
        
        # Network information
        net_io = psutil.net_io_counters()
        net_info = f"""
Bytes Sent: {net_io.bytes_sent / (1024**2):.2f}MB
Bytes Received: {net_io.bytes_recv / (1024**2):.2f}MB
"""
        
        embed = discord.Embed(title="Detailed System Information", color=discord.Color.blue())
        embed.add_field(name="System", value=f"Boot Time: {boot_time}", inline=False)
        embed.add_field(name="CPU Info", value=f"```{cpu_info}```", inline=False)
        embed.add_field(name="Memory Info", value=f"```{mem_info}```", inline=False)
        embed.add_field(name="Disk Info", value=f"```{disk_info}```", inline=False)
        embed.add_field(name="Network Info", value=f"```{net_info}```", inline=False)
        
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in system_info: {e}")
        await ctx.send(f"❌ Error getting system info: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='container_limit', description='Set maximum container limit (Owner only)')
@app_commands.describe(
    max_limit="New maximum container limit"
)
async def set_container_limit(ctx, max_limit: int):
    """Set maximum container limit (Owner only)"""
    if ctx.author.id != 1210291131301101618:  # Only the owner can set limit
        await ctx.send("❌ Only the owner can set container limit!", ephemeral=True)
        return
    
    if max_limit < 1 or max_limit > 1000:
        await ctx.send("❌ Container limit must be between 1 and 1000", ephemeral=True)
        return
    
    bot.db.set_setting('max_containers', max_limit)
    await ctx.send(f"✅ Maximum container limit set to {max_limit}", ephemeral=True)

@bot.hybrid_command(name='cleanup_vps', description='Cleanup inactive VPS instances (Admin only)')
async def cleanup_vps(ctx):
    """Cleanup inactive VPS instances (Admin only)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    try:
        cleanup_count = 0
        
        for token, vps in list(bot.db.get_all_vps().items()):
            try:
                container = bot.docker_client.containers.get(vps['container_id'])
                if container.status != 'running':
                    container.stop()
                    container.remove()
                    bot.db.remove_vps(token)
                    cleanup_count += 1
            except docker.errors.NotFound:
                bot.db.remove_vps(token)
                cleanup_count += 1
            except Exception as e:
                logger.error(f"Error cleaning up VPS {vps['vps_id']}: {e}")
                continue
        
        if cleanup_count > 0:
            await ctx.send(f"✅ Cleaned up {cleanup_count} inactive VPS instances!")
        else:
            await ctx.send("ℹ️ No inactive VPS instances found to clean up.")
    except Exception as e:
        logger.error(f"Error in cleanup_vps: {e}")
        await ctx.send(f"❌ Error during cleanup: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='vps_shell', description='Get shell access to your VPS')
@app_commands.describe(
    vps_id="ID of the VPS to access"
)
async def vps_shell(ctx, vps_id: str):
    """Get shell access to your VPS"""
    try:
        token, vps = bot.db.get_vps_by_id(vps_id)
        if not vps or (vps["created_by"] != str(ctx.author.id) and not has_admin_role(ctx)):
            await ctx.send("❌ VPS not found or you don't have access to it!", ephemeral=True)
            return

        try:
            container = bot.docker_client.containers.get(vps["container_id"])
            if container.status != "running":
                await ctx.send("❌ VPS is not running!", ephemeral=True)
                return

            await ctx.send(f"✅ Shell access to VPS {vps_id}:\n"
                          f"```docker exec -it {vps['container_id']} bash```\n"
                          f"Username: {vps['username']}\n"
                          f"Password: ||{vps.get('password', 'Not set')}||", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Error accessing VPS shell: {str(e)}", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in vps_shell: {e}")
        await ctx.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='vps_console', description='Get direct console access to your VPS')
@app_commands.describe(
    vps_id="ID of the VPS to access"
)
async def vps_console(ctx, vps_id: str):
    """Get direct console access to your VPS"""
    try:
        token, vps = bot.db.get_vps_by_id(vps_id)
        if not vps or (vps["created_by"] != str(ctx.author.id) and not has_admin_role(ctx)):
            await ctx.send("❌ VPS not found or you don't have access to it!", ephemeral=True)
            return

        try:
            container = bot.docker_client.containers.get(vps["container_id"])
            if container.status != "running":
                await ctx.send("❌ VPS is not running!", ephemeral=True)
                return

            await ctx.send(f"✅ Console access to VPS {vps_id}:\n"
                          f"```docker attach {vps['container_id']}```\n"
                          f"Note: To detach from the console without stopping the container, use Ctrl+P followed by Ctrl+Q", 
                          ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Error accessing VPS console: {str(e)}", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in vps_console: {e}")
        await ctx.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='vps_usage', description='Show your VPS usage statistics')
async def vps_usage(ctx):
    """Show your VPS usage statistics"""
    try:
        user_vps = bot.db.get_user_vps(ctx.author.id)
        
        total_memory = sum(vps['memory'] for vps in user_vps)
        total_cpu = sum(vps['cpu'] for vps in user_vps)
        total_disk = sum(vps['disk'] for vps in user_vps)
        total_restarts = sum(vps.get('restart_count', 0) for vps in user_vps)
        
        embed = discord.Embed(title="Your Pycroe Host VPS Usage", color=discord.Color.blue())
        embed.add_field(name="Total VPS Instances", value=len(user_vps), inline=True)
        embed.add_field(name="Total Memory Allocated", value=f"{total_memory}GB", inline=True)
        embed.add_field(name="Total CPU Cores Allocated", value=total_cpu, inline=True)
        embed.add_field(name="Total Disk Allocated", value=f"{total_disk}GB", inline=True)
        embed.add_field(name="Total Restarts", value=total_restarts, inline=True)
        
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in vps_usage: {e}")
        await ctx.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='global_stats', description='Show global usage statistics (Admin only)')
async def global_stats(ctx):
    """Show global usage statistics (Admin only)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    try:
        all_vps = bot.db.get_all_vps()
        total_memory = sum(vps['memory'] for vps in all_vps.values())
        total_cpu = sum(vps['cpu'] for vps in all_vps.values())
        total_disk = sum(vps['disk'] for vps in all_vps.values())
        total_restarts = sum(vps.get('restart_count', 0) for vps in all_vps.values())
        
        embed = discord.Embed(title="Pycroe Host Global Usage Statistics", color=discord.Color.blue())
        embed.add_field(name="Total VPS Created", value=bot.db.get_stat('total_vps_created'), inline=True)
        embed.add_field(name="Total Restarts", value=bot.db.get_stat('total_restarts'), inline=True)
        embed.add_field(name="Current VPS Instances", value=len(all_vps), inline=True)
        embed.add_field(name="Total Memory Allocated", value=f"{total_memory}GB", inline=True)
        embed.add_field(name="Total CPU Cores Allocated", value=total_cpu, inline=True)
        embed.add_field(name="Total Disk Allocated", value=f"{total_disk}GB", inline=True)
        embed.add_field(name="Total Restarts", value=total_restarts, inline=True)
        
        await ctx.send(embed=embed)
    except Exception as e:
        logger.error(f"Error in global_stats: {e}")
        await ctx.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='migrate_vps', description='Migrate a VPS to another host (Admin only)')
@app_commands.describe(
    vps_id="ID of the VPS to migrate"
)
async def migrate_vps(ctx, vps_id: str):
    """Migrate a VPS to another host (Admin only)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    try:
        token, vps = bot.db.get_vps_by_id(vps_id)
        if not vps:
            await ctx.send("❌ VPS not found!", ephemeral=True)
            return

        status_msg = await ctx.send(f"🔄 Preparing to migrate VPS {vps_id}...")
        
        # Create a snapshot
        backup_id = generate_vps_id()[:8]
        backup_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        backup_dir = f"migrations/{vps_id}"
        os.makedirs(backup_dir, exist_ok=True)
        backup_file = f"{backup_dir}/{backup_id}.tar"
        
        await status_msg.edit(content=f"🔄 Creating snapshot {backup_id} for migration...")
        
        process = await asyncio.create_subprocess_exec(
            "docker", "export", "-o", backup_file, vps["container_id"],
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"Snapshot failed: {stderr.decode()}")
        
        await status_msg.edit(content=f"✅ Snapshot {backup_id} created successfully. Please download this file and import it on the new host: {backup_file}")
        
    except Exception as e:
        logger.error(f"Error in migrate_vps: {e}")
        await ctx.send(f"❌ Error during migration: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='emergency_stop', description='Force stop a problematic VPS (Admin only)')
@app_commands.describe(
    vps_id="ID of the VPS to stop"
)
async def emergency_stop(ctx, vps_id: str):
    """Force stop a problematic VPS (Admin only)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    try:
        token, vps = bot.db.get_vps_by_id(vps_id)
        if not vps:
            await ctx.send("❌ VPS not found!", ephemeral=True)
            return

        try:
            container = bot.docker_client.containers.get(vps["container_id"])
            if container.status != "running":
                await ctx.send("VPS is already stopped!", ephemeral=True)
                return
            
            await ctx.send("⚠️ Attempting to force stop the VPS... This may take a moment.", ephemeral=True)
            
            # Try normal stop first
            try:
                container.stop(timeout=10)
                bot.db.update_vps(token, {'status': 'stopped'})
                await ctx.send("✅ VPS stopped successfully!", ephemeral=True)
                return
            except:
                pass
            
            # If normal stop failed, try killing the container
            try:
                subprocess.run(["docker", "kill", vps["container_id"]], check=True)
                bot.db.update_vps(token, {'status': 'stopped'})
                await ctx.send("✅ VPS killed forcefully!", ephemeral=True)
            except subprocess.CalledProcessError as e:
                raise Exception(f"Failed to kill container: {e}")
            
        except Exception as e:
            await ctx.send(f"❌ Error stopping VPS: {str(e)}", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in emergency_stop: {e}")
        await ctx.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='emergency_remove', description='Force remove a problematic VPS (Admin only)')
@app_commands.describe(
    vps_id="ID of the VPS to remove"
)
async def emergency_remove(ctx, vps_id: str):
    """Force remove a problematic VPS (Admin only)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    try:
        token, vps = bot.db.get_vps_by_id(vps_id)
        if not vps:
            await ctx.send("❌ VPS not found!", ephemeral=True)
            return

        try:
            # First try to stop the container normally
            try:
                container = bot.docker_client.containers.get(vps["container_id"])
                container.stop()
            except:
                pass
            
            # Then try to remove it forcefully
            try:
                subprocess.run(["docker", "rm", "-f", vps["container_id"]], check=True)
            except subprocess.CalledProcessError as e:
                raise Exception(f"Failed to remove container: {e}")
            
            # Remove from data
            bot.db.remove_vps(token)
            
            await ctx.send("✅ VPS removed forcefully!", ephemeral=True)
        except Exception as e:
            await ctx.send(f"❌ Error removing VPS: {str(e)}", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in emergency_remove: {e}")
        await ctx.send(f"❌ Error: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='suspend_vps', description='Suspend a VPS (Admin only)')
@app_commands.describe(
    vps_id="ID of the VPS to suspend"
)
async def suspend_vps(ctx, vps_id: str):
    """Suspend a VPS (Admin only)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    try:
        token, vps = bot.db.get_vps_by_id(vps_id)
        if not vps:
            await ctx.send("❌ VPS not found!", ephemeral=True)
            return

        if vps['status'] == 'suspended':
            await ctx.send("❌ VPS is already suspended!", ephemeral=True)
            return

        try:
            container = bot.docker_client.containers.get(vps["container_id"])
            container.stop()
        except Exception as e:
            logger.error(f"Error stopping container for suspend: {e}")

        bot.db.update_vps(token, {'status': 'suspended'})
        await ctx.send(f"✅ VPS {vps_id} has been suspended!")

        # Notify owner
        try:
            owner = await bot.fetch_user(int(vps['created_by']))
            await owner.send(f"⚠️ Your VPS (ID : {vps_id}) has been suspended by an admin. Contact support for details.")
        except:
            pass

    except Exception as e:
        logger.error(f"Error in suspend_vps: {e}")
        await ctx.send(f"❌ Error suspending VPS: {str(e)}")

@bot.hybrid_command(name='unsuspend_vps', description='Unsuspend a VPS (Admin only)')
@app_commands.describe(
    vps_id="ID of the VPS to unsuspend"
)
async def unsuspend_vps(ctx, vps_id: str):
    """Unsuspend a VPS (Admin only)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    try:
        token, vps = bot.db.get_vps_by_id(vps_id)
        if not vps:
            await ctx.send("❌ VPS not found!", ephemeral=True)
            return

        if vps['status'] != 'suspended':
            await ctx.send("❌ VPS is not suspended!", ephemeral=True)
            return

        try:
            container = bot.docker_client.containers.get(vps["container_id"])
            container.start()
        except Exception as e:
            logger.error(f"Error starting container for unsuspend: {e}")
            await ctx.send(f"❌ Error starting container: {str(e)}")
            return

        bot.db.update_vps(token, {'status': 'running'})
        await ctx.send(f"✅ VPS (ID : {vps_id}) has been unsuspended!")

        # Notify owner
        try:
            owner = await bot.fetch_user(int(vps['created_by']))
            await owner.send(f"✅ Your VPS (ID : {vps_id}) has been unsuspended by an admin.")
        except:
            pass

    except Exception as e:
        logger.error(f"Error in unsuspend_vps: {e}")
        await ctx.send(f"❌ Error unsuspending VPS: {str(e)}")
def _load_admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_IDS", "")
    return {int(x) for x in raw.replace(" ", "").split(",") if x}

ADMIN_IDS = _load_admin_ids()

def has_admin_id(ctx: commands.Context) -> bool:
    return ctx.author and ctx.author.id in ADMIN_IDS

@bot.hybrid_command(name='say', description='make a bot say message (Admin only)')
@app_commands.describe(
    message="message the bot will send after a short delay"
)
async def say(ctx: commands.Context, *, message: str):
    """Say a message via the bot (Admin only)"""

    if not has_admin_id(ctx):
        # ephemeral يعمل فقط عند الاستدعاء كسلاش
        if getattr(ctx, "interaction", None):
            await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        else:
            await ctx.send("❌ You must be an admin to use this command!")
        return

    try:
        # رسالة تأكيد (ephemeral لو Slash)
        if getattr(ctx, "interaction", None):
            await ctx.interaction.response.send_message("✔ Done ✔", ephemeral=True)
        else:
            await ctx.send("✔ Done ✔")

        # انتظر ثانية ثم أرسل الرسالة المطلوبة في نفس القناة
        await asyncio.sleep(1)
        await ctx.channel.send(message)

    except Exception as e:
        logger.error(f"Error in say command: {e}")
        # لو كان Slash ولم نرد بعد:
        if getattr(ctx, "interaction", None) and not ctx.interaction.response.is_done():
            await ctx.interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
        else:
            await ctx.send(f"❌ Error: {e}")
@bot.hybrid_command(name='edit_vps', description='Edit VPS specifications (Admin only)')
@app_commands.describe(
    vps_id="ID of the VPS to edit",
    memory="New memory in GB (optional)",
    cpu="New CPU cores (optional)",
    disk="New disk space in GB (optional)"
)
async def edit_vps(ctx, vps_id: str, memory: Optional[int] = None, cpu: Optional[int] = None, disk: Optional[int] = None):
    """Edit VPS specifications (Admin only)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    if memory is None and cpu is None and disk is None:
        await ctx.send("❌ At least one specification to edit must be provided!", ephemeral=True)
        return

    try:
        token, vps = bot.db.get_vps_by_id(vps_id)
        if not vps:
            await ctx.send("❌ VPS not found!", ephemeral=True)
            return

        updates = {}
        if memory is not None:
            if memory < 1 or memory > 512:
                await ctx.send("❌ Memory must be between 1GB and 512GB", ephemeral=True)
                return
            updates['memory'] = memory
        if cpu is not None:
            if cpu < 1 or cpu > 32:
                await ctx.send("❌ CPU cores must be between 1 and 32", ephemeral=True)
                return
            updates['cpu'] = cpu
        if disk is not None:
            if disk < 10 or disk > 1000:
                await ctx.send("❌ Disk space must be between 10GB and 1000GB", ephemeral=True)
                return
            updates['disk'] = disk

        # Restart container with new limits
        try:
            container = bot.docker_client.containers.get(vps["container_id"])
            container.stop()
            container.remove()

            memory_bytes = (memory or vps['memory']) * 1024 * 1024 * 1024
            cpu_quota = int((cpu or vps['cpu']) * 100000)

            new_container = bot.docker_client.containers.run(
                vps['os_image'],
                detach=True,
                privileged=True,
                hostname=f"PycroeCloud-{vps_id}",
                mem_limit=memory_bytes,
                cpu_period=100000,
                cpu_quota=cpu_quota,
                cap_add=["ALL"],
                command="tail -f /dev/null",
                tty=True,
                network=DOCKER_NETWORK,
                volumes={
                    f'PycroeCloud-{vps_id}': {'bind': '/data', 'mode': 'rw'}
                },
                restart_policy={"Name": "always"}
            )

            updates['container_id'] = new_container.id
            await asyncio.sleep(5)
            setup_success, _, _ = await setup_container(
                new_container.id, 
                ctx, 
                memory or vps['memory'], 
                vps['username'], 
                vps_id=vps_id,
                use_custom_image=vps['use_custom_image']
            )
            if not setup_success:
                raise Exception("Failed to setup new container")
        except Exception as e:
            await ctx.send(f"❌ Error updating container: {str(e)}")
            return

        bot.db.update_vps(token, updates)
        await ctx.send(f"✅ VPS {vps_id} specifications updated successfully!")

    except Exception as e:
        logger.error(f"Error in edit_vps: {e}")
        await ctx.send(f"❌ Error editing VPS: {str(e)}")

@bot.hybrid_command(name='ban_user', description='Ban a user from creating VPS (Admin only)')
@app_commands.describe(
    user="User to ban"
)
async def ban_user(ctx, user: discord.User):
    """Ban a user from creating VPS (Admin only)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    bot.db.ban_user(user.id)
    await ctx.send(f"✅ {user.mention} has been banned from creating VPS!")

@bot.hybrid_command(name='unban_user', description='Unban a user (Admin only)')
@app_commands.describe(
    user="User to unban"
)
async def unban_user(ctx, user: discord.User):
    """Unban a user (Admin only)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    bot.db.unban_user(user.id)
    await ctx.send(f"✅ {user.mention} has been unbanned!")

@bot.hybrid_command(name='list_banned', description='List banned users (Admin only)')
async def list_banned(ctx):
    """List banned users (Admin only)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    banned = bot.db.get_banned_users()
    if not banned:
        await ctx.send("No banned users.", ephemeral=True)
        return

    embed = discord.Embed(title="Banned Users", color=discord.Color.red())
    banned_list = []
    for user_id in banned:
        try:
            user = await bot.fetch_user(int(user_id))
            banned_list.append(f"{user.name} ({user_id})")
        except:
            banned_list.append(f"Unknown ({user_id})")
    embed.description = "\n".join(banned_list)
    await ctx.send(embed=embed, ephemeral=True)

@bot.hybrid_command(name='backup_data', description='Backup all bot data (Admin only)')
async def backup_data(ctx):
    """Backup all bot data (Admin only)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    try:
        if bot.db.backup_data():
            await ctx.send("✅ Data backup completed successfully!", ephemeral=True)
        else:
            await ctx.send("❌ Failed to backup data!", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in backup_data: {e}")
        await ctx.send(f"❌ Error backing up data: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='restore_data', description='Restore from backup (Admin only)')
async def restore_data(ctx):
    """Restore from backup (Admin only)"""
    if not has_admin_role(ctx):
        await ctx.send("❌ You must be an admin to use this command!", ephemeral=True)
        return

    try:
        if bot.db.restore_data():
            await ctx.send("✅ Data restore completed successfully!", ephemeral=True)
        else:
            await ctx.send("❌ Failed to restore data!", ephemeral=True)
    except Exception as e:
        logger.error(f"Error in restore_data: {e}")
        await ctx.send(f"❌ Error restoring data: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='reinstall_bot', description='Reinstall the bot (Owner only)')
async def reinstall_bot(ctx):
    """Reinstall the bot (Owner only)"""
    if ctx.author.id != 1210291131301101618:  # Only the owner can reinstall
        await ctx.send("❌ Only the owner can reinstall the bot!", ephemeral=True)
        return

    try:
        await ctx.send("🔄 Reinstalling Pycroe Host bot... This may take a few minutes.")
        
        # Create Dockerfile for bot reinstallation
        dockerfile_content = f"""
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    docker.io \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy bot code
COPY . .

# Start the bot
CMD ["python", "bot.py"]
"""
        
        with open("Dockerfile.bot", "w") as f:
            f.write(dockerfile_content)
        
        # Build and run the bot in a container
        process = await asyncio.create_subprocess_exec(
            "docker", "build", "-t", "PycroeCloud-bot", "-f", "Dockerfile.bot", ".",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            raise Exception(f"Failed to build bot image: {stderr.decode()}")
        
        await ctx.send("✅ Bot reinstalled successfully! Restarting...")
        
        # Restart the bot
        os._exit(0)
        
    except Exception as e:
        logger.error(f"Error in reinstall_bot: {e}")
        await ctx.send(f"❌ Error reinstalling bot: {str(e)}", ephemeral=True)

class VPSManagementView(ui.View):
    def __init__(self, vps_id, container_id):
        super().__init__(timeout=300)
        self.vps_id = vps_id
        self.container_id = container_id
        self.original_message = None

    async def handle_missing_container(self, interaction: discord.Interaction):
        token, _ = bot.db.get_vps_by_id(self.vps_id)
        if token:
            bot.db.remove_vps(token)
        
        embed = discord.Embed(title=f"Pycroe Host VPS Management - {self.vps_id}", color=discord.Color.red())
        embed.add_field(name="Status", value="🔴 Container Not Found", inline=True)
        embed.add_field(name="Note", value="This VPS instance is no longer available. Please create a new one.", inline=False)
        
        for item in self.children:
            item.disabled = True
        
        await interaction.message.edit(embed=embed, view=self)
        await interaction.response.send_message("❌ This VPS instance is no longer available. Please create a new one.", ephemeral=True)

    @discord.ui.button(label="Start VPS", style=discord.ButtonStyle.green)
    async def start_vps(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
            
            try:
                container = bot.docker_client.containers.get(self.container_id)
            except docker.errors.NotFound:
                await self.handle_missing_container(interaction)
                return
            
            token, vps = bot.db.get_vps_by_id(self.vps_id)
            if vps['status'] == 'suspended':
                await interaction.followup.send("❌ This VPS is suspended. Contact admin to unsuspend.", ephemeral=True)
                return

            if container.status == "running":
                await interaction.followup.send("VPS is already running!", ephemeral=True)
                return
            
            container.start()
            await asyncio.sleep(5)
            
            if token:
                bot.db.update_vps(token, {'status': 'running'})
            
            embed = discord.Embed(title=f"Pycroe Host VPS Management - {self.vps_id}", color=discord.Color.green())
            embed.add_field(name="Status", value="🟢 Running", inline=True)
            
            if vps:
                embed.add_field(name="Memory", value=f"{vps['memory']}GB", inline=True)
                embed.add_field(name="CPU", value=f"{vps['cpu']} cores", inline=True)
                embed.add_field(name="Disk", value=f"{vps['disk']}GB", inline=True)
                embed.add_field(name="Username", value=vps['username'], inline=True)
                embed.add_field(name="Created", value=vps['created_at'], inline=True)
            
            await interaction.message.edit(embed=embed)
            await interaction.followup.send("✅ Pycroe Host VPS started successfully!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error starting VPS: {str(e)}", ephemeral=True)

    @discord.ui.button(label="Stop VPS", style=discord.ButtonStyle.red)
    async def stop_vps(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
            
            try:
                container = bot.docker_client.containers.get(self.container_id)
            except docker.errors.NotFound:
                await self.handle_missing_container(interaction)
                return
            
            if container.status != "running":
                await interaction.followup.send("VPS is already stopped!", ephemeral=True)
                return
            
            container.stop()
            
            token, vps = bot.db.get_vps_by_id(self.vps_id)
            if token:
                bot.db.update_vps(token, {'status': 'stopped'})
            
            embed = discord.Embed(title=f"Pycroe Host VPS Management - {self.vps_id}", color=discord.Color.orange())
            embed.add_field(name="Status", value="🔴 Stopped", inline=True)
            
            if vps:
                embed.add_field(name="Memory", value=f"{vps['memory']}GB", inline=True)
                embed.add_field(name="CPU", value=f"{vps['cpu']} cores", inline=True)
                embed.add_field(name="Disk", value=f"{vps['disk']}GB", inline=True)
                embed.add_field(name="Username", value=vps['username'], inline=True)
                embed.add_field(name="Created", value=vps['created_at'], inline=True)
            
            await interaction.message.edit(embed=embed)
            await interaction.followup.send("✅ Pycroe Host VPS stopped successfully!", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error stopping VPS: {str(e)}", ephemeral=True)

    @discord.ui.button(label="Restart VPS", style=discord.ButtonStyle.blurple)
    async def restart_vps(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            await interaction.response.defer(ephemeral=True)
            
            try:
                container = bot.docker_client.containers.get(self.container_id)
            except docker.errors.NotFound:
                await self.handle_missing_container(interaction)
                return
            
            token, vps = bot.db.get_vps_by_id(self.vps_id)
            if vps['status'] == 'suspended':
                await interaction.followup.send("❌ This VPS is suspended. Contact admin to unsuspend.", ephemeral=True)
                return

            container.restart()
            await asyncio.sleep(5)
            
            # Update restart count in VPS data
            if token:
                updates = {
                    'restart_count': vps.get('restart_count', 0) + 1,
                    'last_restart': str(datetime.datetime.now()),
                    'status': 'running'
                }
                bot.db.update_vps(token, updates)
                
                bot.db.increment_stat('total_restarts')
                
                # Get new SSH session
                try:
                    exec_cmd = await asyncio.create_subprocess_exec(
                        "docker", "exec", self.container_id, "tmate", "-F",
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )

                    ssh_session_line = await capture_ssh_session_line(exec_cmd)
                    if ssh_session_line:
                        bot.db.update_vps(token, {'tmate_session': ssh_session_line})
                        
                        # Send new SSH details to owner
                        try:
                            owner = await bot.fetch_user(int(vps["created_by"]))
                            embed = discord.Embed(title=f"Pycroe Host VPS Restarted - {self.vps_id}", color=discord.Color.blue())
                            embed.add_field(name="New SSH Session", value=f"```{ssh_session_line}```", inline=False)
                            await owner.send(embed=embed)
                        except:
                            pass
                except:
                    pass
            
            embed = discord.Embed(title=f"Pycroe Host VPS Management - {self.vps_id}", color=discord.Color.green())
            embed.add_field(name="Status", value="🟢 Running", inline=True)
            
            if vps:
                embed.add_field(name="Memory", value=f"{vps['memory']}GB", inline=True)
                embed.add_field(name="CPU", value=f"{vps['cpu']} cores", inline=True)
                embed.add_field(name="Disk", value=f"{vps['disk']}GB", inline=True)
                embed.add_field(name="Username", value=vps['username'], inline=True)
                embed.add_field(name="Created", value=vps['created_at'], inline=True)
                embed.add_field(name="Restart Count", value=vps.get('restart_count', 0) + 1, inline=True)
            
            await interaction.message.edit(embed=embed, view=VPSManagementView(self.vps_id, container.id))
            await interaction.followup.send("✅ Pycroe HOST VPS restarted successfully! New SSH details sent to owner.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Error restarting VPS: {str(e)}", ephemeral=True)

    @discord.ui.button(label="Reinstall OS", style=discord.ButtonStyle.grey)
    async def reinstall_os(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            try:
                container = bot.docker_client.containers.get(self.container_id)
            except docker.errors.NotFound:
                await self.handle_missing_container(interaction)
                return
            
            view = OSSelectionView(self.vps_id, self.container_id, interaction.message)
            await interaction.response.send_message("Select new OS:", view=view, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Error: {str(e)}", ephemeral=True)

    @discord.ui.button(label="Transfer VPS", style=discord.ButtonStyle.grey)
    async def transfer_vps(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = TransferVPSModal(self.vps_id)
        await interaction.response.send_modal(modal)

class OSSelectionView(ui.View):
    def __init__(self, vps_id, container_id, original_message):
        super().__init__(timeout=300)
        self.vps_id = vps_id
        self.container_id = container_id
        self.original_message = original_message
        
        self.add_os_button("Ubuntu 22.04", "arindamvm/unvm")
        self.add_os_button("Debian 12", "debian:12")
        self.add_os_button("Arch Linux", "archlinux:latest")
        self.add_os_button("Alpine", "alpine:latest")
        self.add_os_button("CentOS 7", "centos:7")
        self.add_os_button("Fedora 38", "fedora:38")

    def add_os_button(self, label: str, image: str):
        button = discord.ui.Button(label=label, style=discord.ButtonStyle.grey)
        
        async def os_callback(interaction: discord.Interaction):
            await self.reinstall_os(interaction, image)
        
        button.callback = os_callback
        self.add_item(button)

    async def reinstall_os(self, interaction: discord.Interaction, image: str):
        try:
            token, vps = bot.db.get_vps_by_id(self.vps_id)
            if not vps:
                await interaction.response.send_message("❌ VPS not found!", ephemeral=True)
                return

            await interaction.response.defer(ephemeral=True)

            try:
                old_container = bot.docker_client.containers.get(self.container_id)
                old_container.stop()
                old_container.remove()
            except Exception as e:
                logger.error(f"Error removing old container: {e}")

            status_msg = await interaction.followup.send("🔄 Reinstalling Pycroe Host VPS... This may take a few minutes.", ephemeral=True)
            
            memory_bytes = vps['memory'] * 1024 * 1024 * 1024

            try:
                container = bot.docker_client.containers.run(
                    image,
                    detach=True,
                    privileged=True,
                    hostname=f"PycroeCloud-{self.vps_id}",
                    mem_limit=memory_bytes,
                    cpu_period=100000,
                    cpu_quota=int(vps['cpu'] * 100000),
                    cap_add=["ALL"],
                    command="tail -f /dev/null",
                    tty=True,
                    network=DOCKER_NETWORK,
                    volumes={
                        f'PycroeCloud-{self.vps_id}': {'bind': '/data', 'mode': 'rw'}
                    }
                )
            except docker.errors.ImageNotFound:
                await status_msg.edit(content=f"❌ OS image {image} not found. Using default {DEFAULT_OS_IMAGE}")
                container = bot.docker_client.containers.run(
                    DEFAULT_OS_IMAGE,
                    detach=True,
                    privileged=True,
                    hostname=f"PycroeCloud-{self.vps_id}",
                    mem_limit=memory_bytes,
                    cpu_period=100000,
                    cpu_quota=int(vps['cpu'] * 100000),
                    cap_add=["ALL"],
                    command="tail -f /dev/null",
                    tty=True,
                    network=DOCKER_NETWORK,
                    volumes={
                        f'PycroeCloud-{self.vps_id}': {'bind': '/data', 'mode': 'rw'}
                    }
                )
                image = DEFAULT_OS_IMAGE

            bot.db.update_vps(token, {
                'container_id': container.id,
                'os_image': image
            })

            try:
                setup_success, ssh_password, _ = await setup_container(
                    container.id, 
                    status_msg, 
                    vps['memory'], 
                    vps['username'], 
                    vps_id=self.vps_id
                )
                if not setup_success:
                    raise Exception("Failed to setup container")
                
                bot.db.update_vps(token, {'password': ssh_password})
            except Exception as e:
                await status_msg.edit(content=f"❌ Container setup failed: {str(e)}")
                return

            try:
                exec_cmd = await asyncio.create_subprocess_exec(
                    "docker", "exec", container.id, "tmate", "-F",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                ssh_session_line = await capture_ssh_session_line(exec_cmd)
                if ssh_session_line:
                    bot.db.update_vps(token, {'tmate_session': ssh_session_line})
                    
                    # Send new SSH details to owner
                    try:
                        owner = await bot.fetch_user(int(vps["created_by"]))
                        embed = discord.Embed(title=f"Pycroe Host VPS Reinstalled - {self.vps_id}", color=discord.Color.blue())
                        embed.add_field(name="New OS", value=image, inline=True)
                        embed.add_field(name="New SSH Session", value=f"```{ssh_session_line}```", inline=False)
                        embed.add_field(name="New SSH Password", value=f"||{ssh_password}||", inline=False)
                        await owner.send(embed=embed)
                    except:
                        pass
            except Exception as e:
                logger.error(f"Warning: Failed to start tmate session: {e}")

            await status_msg.edit(content="✅ Pycroe Host VPS reinstalled successfully!")
            
            try:
                embed = discord.Embed(title=f"Pycroe Host VPS Management - {self.vps_id}", color=discord.Color.green())
                embed.add_field(name="Status", value="🟢 Running", inline=True)
                embed.add_field(name="Memory", value=f"{vps['memory']}GB", inline=True)
                embed.add_field(name="CPU", value=f"{vps['cpu']} cores", inline=True)
                embed.add_field(name="Disk", value=f"{vps['disk']}GB", inline=True)
                embed.add_field(name="Username", value=vps['username'], inline=True)
                embed.add_field(name="Created", value=vps['created_at'], inline=True)
                embed.add_field(name="OS", value=image, inline=True)
                
                await self.original_message.edit(embed=embed, view=VPSManagementView(self.vps_id, container.id))
            except Exception as e:
                logger.error(f"Warning: Failed to update original message: {e}")

        except Exception as e:
            try:
                await interaction.followup.send(f"❌ Error reinstalling VPS: {str(e)}", ephemeral=True)
            except:
                try:
                    channel = interaction.channel
                    await channel.send(f"❌ Error reinstalling Pycroe Host VPS {self.vps_id}: {str(e)}")
                except:
                    logger.error(f"Failed to send error message: {e}")

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self.original_message.edit(view=self)
        except:
            pass

class TransferVPSModal(ui.Modal, title='Transfer VPS'):
    def __init__(self, vps_id: str):
        super().__init__()
        self.vps_id = vps_id
        self.new_owner = ui.TextInput(
            label='New Owner',
            placeholder='Enter user ID or @mention',
            required=True
        )
        self.add_item(self.new_owner)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            new_owner_input = self.new_owner.value.strip()
            
            # Extract user ID from mention if provided
            if new_owner_input.startswith('<@') and new_owner_input.endswith('>'):
                new_owner_id = new_owner_input[2:-1]
                if new_owner_id.startswith('!'):  # Handle nickname mentions
                    new_owner_id = new_owner_id[1:]
            else:
                # Validate it's a numeric ID
                if not new_owner_input.isdigit():
                    await interaction.response.send_message("❌ Please provide a valid user ID or @mention", ephemeral=True)
                    return
                new_owner_id = new_owner_input

            token, vps = bot.db.get_vps_by_id(self.vps_id)
            if not vps or vps["created_by"] != str(interaction.user.id):
                await interaction.response.send_message("❌ VPS not found or you don't have permission to transfer it!", ephemeral=True)
                return

            try:
                old_owner = await bot.fetch_user(int(vps["created_by"]))
                old_owner_name = old_owner.name
            except:
                old_owner_name = "Unknown User"

            try:
                new_owner = await bot.fetch_user(int(new_owner_id))
                new_owner_name = new_owner.name
                
                # Check if new owner is banned
                if bot.db.is_user_banned(new_owner.id):
                    await interaction.response.send_message(f"❌ {new_owner.mention} is banned!", ephemeral=True)
                    return

                # Check if new owner already has max VPS
                if bot.db.get_user_vps_count(new_owner.id) >= bot.db.get_setting('max_vps_per_user'):
                    await interaction.response.send_message(f"❌ {new_owner.mention} already has the maximum number of VPS instances ({bot.db.get_setting('max_vps_per_user')})", ephemeral=True)
                    return
            except:
                await interaction.response.send_message("❌ Invalid user ID or mention!", ephemeral=True)
                return

            bot.db.update_vps(token, {"created_by": str(new_owner.id)})

            await interaction.response.send_message(f"✅ Pycroe HOST VPS {self.vps_id} has been transferred from {old_owner_name} to {new_owner_name}!", ephemeral=True)
            
            try:
                embed = discord.Embed(title="Pycroe Host VPS Transferred to You", color=discord.Color.green())
                embed.add_field(name="VPS ID", value=self.vps_id, inline=True)
                embed.add_field(name="Previous Owner", value=old_owner_name, inline=True)
                embed.add_field(name="Memory", value=f"{vps['memory']}GB", inline=True)
                embed.add_field(name="CPU", value=f"{vps['cpu']} cores", inline=True)
                embed.add_field(name="Disk", value=f"{vps['disk']}GB", inline=True)
                embed.add_field(name="Username", value=vps['username'], inline=True)
                embed.add_field(name="Access Token", value=token, inline=False)
                embed.add_field(name="SSH Password", value=f"||{vps.get('password', 'Not set')}||", inline=False)
                await new_owner.send(embed=embed)
            except:
                await interaction.followup.send("Note: Could not send DM to the new owner.", ephemeral=True)

        except Exception as e:
            logger.error(f"Error in TransferVPSModal: {e}")
            await interaction.response.send_message(f"❌ Error transferring VPS: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='manage_vps', description='Manage a VPS instance')
@app_commands.describe(
    vps_id="ID of the VPS to manage"
)
async def manage_vps(ctx, vps_id: str):
    """Manage a VPS instance"""
    try:
        token, vps = bot.db.get_vps_by_id(vps_id)
        if not vps or (vps["created_by"] != str(ctx.author.id) and not has_admin_role(ctx)):
            await ctx.send("❌ VPS not found or you don't have access to it!", ephemeral=True)
            return

        try:
            container = bot.docker_client.containers.get(vps["container_id"])
            container_status = container.status.capitalize()
        except:
            container_status = "Not Found"

        status = vps['status'].capitalize()

        embed = discord.Embed(title=f"Pycroe Host VPS Management - {vps_id}", color=discord.Color.blue())
        embed.add_field(name="Status", value=f"{status} (Container: {container_status})", inline=True)
        embed.add_field(name="Memory", value=f"{vps['memory']}GB", inline=True)
        embed.add_field(name="CPU", value=f"{vps['cpu']} cores", inline=True)
        embed.add_field(name="Disk Allocated", value=f"{vps['disk']}GB", inline=True)
        embed.add_field(name="Username", value=vps['username'], inline=True)
        embed.add_field(name="Created", value=vps['created_at'], inline=True)
        embed.add_field(name="OS", value=vps.get('os_image', DEFAULT_OS_IMAGE), inline=True)
        embed.add_field(name="Restart Count", value=vps.get('restart_count', 0), inline=True)

        view = VPSManagementView(vps_id, vps["container_id"])
        
        message = await ctx.send(embed=embed, view=view)
        view.original_message = message
    except Exception as e:
        logger.error(f"Error in manage_vps: {e}")
        await ctx.send(f"❌ Error managing VPS: {str(e)}", ephemeral=True)

@bot.hybrid_command(name='transfer_vps', description='Transfer a VPS to another user')
@app_commands.describe(
    vps_id="ID of the VPS to transfer",
    new_owner="User to transfer the VPS to"
)
async def transfer_vps_command(ctx, vps_id: str, new_owner: discord.Member):
    """Transfer a VPS to another user"""
    try:
        token, vps = bot.db.get_vps_by_id(vps_id)
        if not vps or vps["created_by"] != str(ctx.author.id):
            await ctx.send("❌ VPS not found or you don't have permission to transfer it!", ephemeral=True)
            return

        if bot.db.is_user_banned(new_owner.id):
            await ctx.send("❌ This user is banned!", ephemeral=True)
            return

        # Check if new owner already has max VPS
        if bot.db.get_user_vps_count(new_owner.id) >= bot.db.get_setting('max_vps_per_user'):
            await ctx.send(f"❌ {new_owner.mention} already has the maximum number of VPS instances ({bot.db.get_setting('max_vps_per_user')})", ephemeral=True)
            return

        bot.db.update_vps(token, {"created_by": str(new_owner.id)})

        await ctx.send(f"✅ Pycroe Host VPS {vps_id} has been transferred from {ctx.author.name} to {new_owner.name}!")

        try:
            embed = discord.Embed(title="Pycroe Host VPS Transferred to You", color=discord.Color.green())
            embed.add_field(name="VPS ID", value=vps_id, inline=True)
            embed.add_field(name="Previous Owner", value=ctx.author.name, inline=True)
            embed.add_field(name="Memory", value=f"{vps['memory']}GB", inline=True)
            embed.add_field(name="CPU", value=f"{vps['cpu']} cores", inline=True)
            embed.add_field(name="Disk", value=f"{vps['disk']}GB", inline=True)
            embed.add_field(name="Username", value=vps['username'], inline=True)
            embed.add_field(name="Access Token", value=token, inline=False)
            embed.add_field(name="SSH Password", value=f"||{vps.get('password', 'Not set')}||", inline=False)
            await new_owner.send(embed=embed)
        except:
            await ctx.send("Note: Could not send DM to the new owner.", ephemeral=True)

    except Exception as e:
        logger.error(f"Error in transfer_vps_command: {e}")
        await ctx.send(f"❌ Error transferring VPS: {str(e)}", ephemeral=True)

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CheckFailure):
        await ctx.send("❌ You don't have permission to use this command!", ephemeral=True)
    elif isinstance(error, commands.CommandNotFound):
        await ctx.send("❌ Command not found! Use `/help` to see available commands.", ephemeral=True)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Missing required argument: {error.param.name}", ephemeral=True)
    else:
        logger.error(f"Command error: {error}")
        await ctx.send(f"❌ An error occurred: {str(error)}", ephemeral=True)

if __name__ == "__main__":
    try:
        os.makedirs("temp_dockerfiles", exist_ok=True)
        os.makedirs("migrations", exist_ok=True)
        
        bot.run(TOKEN)
    except Exception as e:
        logger.error(f"Bot crashed: {e}")
        traceback.print_exc()
# =========================================== BOT CODE ENDS HERE ===========================================
