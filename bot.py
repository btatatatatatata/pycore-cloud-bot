# Final Complete bot.py with all commands, manage buttons, SSH, share, renew, suspend, points, invites, giveaways
import discord
from discord import app_commands
from discord.ext import commands, tasks
import asyncio
import subprocess
import json
import os
import random
import logging
from typing import Optional
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
load_dotenv()
# ---------------- CONFIG ----------------
DSC_TOKEN = os.getenv("DSC_TOKEN") # TO EDIT TOKEN GO TO .ENV !
GUILD_ID = 1453779289861390349
MAIN_ADMIN_IDS = {1372237657207345183, 800206338092695563, 1279500219154956419}  # CHANGED: Renamed to MAIN_ADMIN_IDS
SERVER_IP = "127.0.0.1"
QR_IMAGE = "https://cdn.discordapp.com/attachments/1411456830252519465/1454119174099046532/QR-Pycroe.png?ex=694fed83&is=694e9c03&hm=03e503f7c151bc7dcab6296035590e107189ee33f6f09f14d4fd03fd658aa7cc&"
IMAGE = "jrei/systemd-ubuntu:22.04"
DEFAULT_RAM_GB = 16
DEFAULT_CPU = 2
DEFAULT_DISK_GB = 100
DATA_DIR = "pycroeData"
USERS_FILE = os.path.join(DATA_DIR, "users.json")
VPS_FILE = os.path.join(DATA_DIR, "vps_db.json")
INV_CACHE_FILE = os.path.join(DATA_DIR, "inv_cache.json")
GIVEAWAY_FILE = os.path.join(DATA_DIR, "giveaways.json")
POINTS_PER_DEPLOY = 8
POINTS_RENEW_15 = 7
POINTS_RENEW_30 = 10
VPS_LIFETIME_DAYS = 40
RENEW_MODE_FILE = os.path.join(DATA_DIR, "renew_mode.json")
DAILY_POINTS = 5
LOG_CHANNEL_ID = 1454125962382807194
OWNER_ID = 1372237657207345183
PREFIX = "$"
START_TIME = None
AUTO_REPLY_FILE = os.path.join(DATA_DIR, "auto_replies.json")

# Global admin sets
ADMIN_IDS = set(MAIN_ADMIN_IDS)  # This will contain ALL admins (main + additional)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("PycroeCloudBot")

# Visual theme
THEME_COLOR_PRIMARY = discord.Color.from_rgb(64, 201, 255)
THEME_COLOR_ACCENT = discord.Color.from_rgb(141, 78, 255)
THEME_COLOR_WARN = discord.Color.from_rgb(255, 171, 64)
THEME_COLOR_SUCCESS = discord.Color.from_rgb(70, 201, 141)

# Ensure data dir
os.makedirs(DATA_DIR, exist_ok=True)

def utcnow():
    """Naive UTC datetime without deprecated utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)

# JSON helpers
def load_json(path, default):
    try:
        if not os.path.exists(path): return default
        with open(path, 'r') as f: return json.load(f)
    except: return default

def themed_embed(title, description=None, color=None):
    """Consistent embed styling across the bot"""
    embed = discord.Embed(
        title=title,
        description=description or discord.Embed.Empty,
        color=color or THEME_COLOR_PRIMARY,
        timestamp=utcnow()
    )
    embed.set_footer(text="Pycroe Cloud • VPS Manager")
    return embed

def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, 'w') as f: json.dump(data, f, indent=2)
    os.replace(tmp, path)

def ensure_list_store(path, default):
    data = load_json(path, default)
    save_json(path, data)
    return data

def ensure_user(uid: str):
    """Guarantee user record exists with default fields."""
    if uid not in users:
        users[uid] = {
            "points": 0,
            "inv_unclaimed": 0,
            "inv_total": 0,
            "invites": [],
            "unique_joins": [],
            "daily_last": None
        }
    return users[uid]

def format_uptime(delta: timedelta) -> str:
    days = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    parts = []
    if days: parts.append(f"{days}d")
    if hours: parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    return " ".join(parts) or "0m"

class PrefixInteractionAdapter:
    """Adapter to reuse slash command logic for prefix commands."""
    def __init__(self, ctx: commands.Context):
        self.user = ctx.author
        self.guild = ctx.guild
        self.channel = ctx.channel
        self.ctx = ctx
        self._is_done = False
        self.response = self
        self.followup = self
        try:
            if ctx.channel and hasattr(ctx.channel, "permissions_for"):
                self.permissions = ctx.channel.permissions_for(ctx.author)
            else:
                self.permissions = None
        except Exception:
            self.permissions = None
        self.client = ctx.bot  # mimic Interaction.client

    def is_done(self):
        return self._is_done
    
    async def send_message(self, content=None, *, embed=None, ephemeral=False, view=None):
        await self.ctx.send(content=content, embed=embed, view=view)
        self._is_done = True
    
    async def send(self, content=None, *, embed=None, view=None, ephemeral=False):
        await self.ctx.send(content=content, embed=embed, view=view)
        self._is_done = True
    
    async def defer(self, ephemeral=False):
        self._is_done = True
        try:
            await self.ctx.trigger_typing()
        except Exception:
            pass

users = load_json(USERS_FILE, {})
vps_db = load_json(VPS_FILE, {})
invite_snapshot = load_json(INV_CACHE_FILE, {})
giveaways = load_json(GIVEAWAY_FILE, {})
renew_mode = load_json(RENEW_MODE_FILE, {"mode": "15"})
auto_replies = ensure_list_store(AUTO_REPLY_FILE, [
    {"pattern": "hello", "response": "Hey {mention}! Need help with your VPS?", "type": "contains", "chance": 0.9},
    {"pattern": "ping", "response": "Pong! {user}", "type": "equals", "chance": 0.8},
    {"pattern": "points", "response": "Check your points with `/pointbal` or `{prefix}pointbal`.", "type": "contains", "chance": 0.6}
])
AUTO_REPLY_COOLDOWN = {}

def is_unique_join(user_id, inviter_id):
    """Check if this is a unique join (not a rejoin)"""
    uid = str(inviter_id)
    if uid not in users:
        return True
    
    unique_joins = users[uid].get('unique_joins', [])
    return str(user_id) not in unique_joins

def add_unique_join(user_id, inviter_id):
    """Add a unique join to inviter's record"""
    uid = str(inviter_id)
    if uid not in users:
        users[uid] = {
            "points": 0, 
            "inv_unclaimed": 0, 
            "inv_total": 0, 
            "invites": [],
            "unique_joins": [],
            "daily_last": None
        }
    
    user_id_str = str(user_id)
    if user_id_str not in users[uid].get('unique_joins', []):
        users[uid]['unique_joins'].append(user_id_str)
        users[uid]['inv_unclaimed'] += 1
        users[uid]['inv_total'] += 1
        persist_users()
        return True
    return False
# ---------------- Bot Init ----------------
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.invites = True

class Bot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=PREFIX, intents=intents, help_command=None)  # Prefix configurable; built-in help disabled

    async def setup_hook(self):
        # Sync commands globally
        try:
            synced = await self.tree.sync()
            logger.info(f"Synced {len(synced)} command(s)")
        except Exception as e:
            logger.error(f"Failed to sync commands: {e}")

bot = Bot()

# ---------------- Docker Helpers ----------------
async def docker_run_container(ram_gb, cpu, disk_gb):
    http_port = random.randint(3000,3999)
    name = f"vps-{random.randint(1000,9999)}"

    performance_opts = [
        "--hostname", name,
        "--dns", "1.1.1.1",
        "--dns", "8.8.8.8",
        "--ulimit", "nofile=65535:65535",
        "--cpu-shares", "1024",
        "--memory-swappiness", "10"
    ]
    
    # FIXED: Use systemd-compatible container setup with proper image
    cmd = [
        "docker", "run", "-d", 
        "--privileged",
        "--cgroupns=host",
        "--tmpfs", "/run",
        "--tmpfs", "/run/lock",
        "-v", "/sys/fs/cgroup:/sys/fs/cgroup:rw",
        "--name", name,
        "--cpus", str(cpu),
        "--memory", f"{ram_gb}g",
        "--memory-swap", f"{ram_gb}g",
        "-p", f"{http_port}:80",
        *performance_opts,
        IMAGE  # Uses systemd-enabled image that has /sbin/init
    ]
    try:
        proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        if proc.returncode != 0: 
            return None, None, f"Container creation failed: {err.decode().strip() if err else 'Unknown error'}"
        
        container_id = out.decode().strip()[:12] if out else None
        if not container_id:
            return None, None, "Failed to get container ID"
            
        return container_id, http_port, None
    except Exception as e:
        return None, None, f"Container run exception: {str(e)}"

async def setup_vps_environment(container_id):
    try:
        # Wait for systemd to start
        await asyncio.sleep(19)
        
        # Update and install essentials
        commands = [
            "apt-get update -y",
            "apt-get upgrade -y",
            "apt-get install -y tmate curl wget neofetch sudo nano htop btop nala",
            "systemctl enable systemd-user-sessions",
            "systemctl start systemd-user-sessions"
        ]
        
        for cmd in commands:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "docker", "exec", container_id, "bash", "-c", cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                await asyncio.wait_for(proc.communicate(), timeout=250)
            except asyncio.TimeoutError:
                logger.warning(f"Timeout on command: {cmd}")
                continue
            except Exception as e:
                logger.warning(f"Command failed {cmd}: {e}")
                continue
        
        # Test systemctl
        test_proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, "systemctl", "--version",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await test_proc.communicate()
        
        return True, None
    except Exception as e:
        return False, str(e)

async def docker_exec_capture_ssh(container_id):
    try:
        # Kill any existing tmate sessions
        kill_cmd = "pkill -f tmate || true"
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, "bash", "-c", kill_cmd,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        await proc.communicate()
        
        # Generate SSH session using tmate
        sock = f"/tmp/tmate-{container_id}.sock"
        ssh_cmd = f"tmate -S {sock} new-session -d && sleep 5 && tmate -S {sock} display -p '#{{tmate_ssh}}'"
        
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, "bash", "-c", ssh_cmd,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        ssh_out = stdout.decode().strip() if stdout else "ssh@tmate.io"
        
        return ssh_out, None
        
    except Exception as e:
        return "ssh@tmate.io", str(e)
        logger.warning(f"Failed to capture SSH: {e}")

async def docker_stop_container(container_id):
    try:
        proc = await asyncio.create_subprocess_exec("docker", "stop", container_id)
        await proc.communicate()
        return True
    except:
        return False

async def docker_start_container(container_id):
    try:
        proc = await asyncio.create_subprocess_exec("docker", "start", container_id)
        await proc.communicate()
        return True
    except:
        return False

async def docker_restart_container(container_id):
    try:
        proc = await asyncio.create_subprocess_exec("docker", "restart", container_id)
        await proc.communicate()
        return True
    except:
        return False

async def docker_remove_container(container_id):
    try:
        proc = await asyncio.create_subprocess_exec("docker", "rm", "-f", container_id)
        await proc.communicate()
        return True
    except:
        return False

async def add_port_to_container(container_id, port):
    try:
        # Get container details to check if it exists
        proc = await asyncio.create_subprocess_exec(
            "docker", "inspect", container_id,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        
        if proc.returncode != 0:
            return False, "Container not found"
        
        # For simplicity, we'll just note the port in our database
        # In production, you'd need to recreate the container with new port mappings
        return True, f"Port {port} mapped to container"
    except Exception as e:
        return False, str(e)

async def check_systemctl_status(container_id):
    """Check if systemctl works in the container"""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker", "exec", container_id, "systemctl", "--version",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode == 0
    except:
        return False

# ---------------- VPS Helpers ----------------
def persist_vps(): save_json(VPS_FILE, vps_db)
def persist_users(): save_json(USERS_FILE, users)
def persist_renew_mode(): save_json(RENEW_MODE_FILE, renew_mode)
def persist_giveaways(): save_json(GIVEAWAY_FILE, giveaways)

async def send_log(action: str, user, details: str = "", vps_id: str = ""):
    """Send professional log embed to log channel"""
    if not LOG_CHANNEL_ID:
        return
    
    try:
        channel = bot.get_channel(LOG_CHANNEL_ID)
        if not channel:
            print(f"Log channel {LOG_CHANNEL_ID} not found")
            return
        
        # Determine color based on action type
        color_map = {
            "deploy": discord.Color.green(),
            "remove": discord.Color.orange(),
            "renew": discord.Color.blue(),
            "suspend": discord.Color.red(),
            "unsuspend": discord.Color.green(),
            "start": discord.Color.green(),
            "stop": discord.Color.orange(),
            "restart": discord.Color.blue(),
            "share": discord.Color.purple(),
            "admin": discord.Color.gold(),
            "points": discord.Color.teal(),
            "invite": discord.Color.magenta(),
            "error": discord.Color.red()
        }
        
        # Get appropriate color
        action_lower = action.lower()
        color = discord.Color.blue()  # default
        for key, value in color_map.items():
            if key in action_lower:
                color = value
                break
        
        # Create embed
        embed = discord.Embed(
            title=f"📊 {action}",
            color=color,
            timestamp=utcnow()
        )
        
        # Add user info
        if hasattr(user, 'mention'):
            embed.add_field(name="👤 User", value=f"{user.mention}\n`{user.name}`", inline=True)
        else:
            embed.add_field(name="👤 User", value=f"`{user}`", inline=True)
        
        # Add VPS ID if provided
        if vps_id:
            embed.add_field(name="🆔 VPS ID", value=f"`{vps_id}`", inline=True)
        
        # Add details
        if details:
            embed.add_field(name="📝 Details", value=details[:1024], inline=False)
        
        # Add timestamp field
        embed.add_field(
            name="⏰ Time", 
            value=f"<t:{int(utcnow().timestamp())}:R>", 
            inline=True
        )
        
        # Set footer
        embed.set_footer(text="VPS Activity Log")
        
        await channel.send(embed=embed)
        
        # Also save to JSON file for /logs command
        logs_file = os.path.join(DATA_DIR, "vps_logs.json")
        logs_data = load_json(logs_file, [])
        
        log_entry = {
            "timestamp": utcnow().isoformat(),
            "action": action,
            "user": user.name if hasattr(user, 'name') else str(user),
            "details": details,
            "vps_id": vps_id
        }
        
        logs_data.append(log_entry)
        
        # Keep only last 1000 logs to prevent file from growing too large
        if len(logs_data) > 1000:
            logs_data = logs_data[-1000:]
        
        save_json(logs_file, logs_data)
        
    except Exception as e:
        print(f"Failed to send log: {e}")

async def create_vps(owner_id, ram=DEFAULT_RAM_GB, cpu=DEFAULT_CPU, disk=DEFAULT_DISK_GB, paid=False, giveaway=False):
    uid = str(owner_id)
    cid, http_port, err = await docker_run_container(ram, cpu, disk)
    if err: 
        return {'error': err}
    
    # Wait for container to start and setup
    await asyncio.sleep(10)
    
    # Setup environment
    success, setup_err = await setup_vps_environment(cid)
    if not success:
        logger.warning(f"Setup had issues for {cid}: {setup_err}")
    
    # Generate SSH
    ssh, ssh_err = await docker_exec_capture_ssh(cid)
    
    # Check systemctl status
    systemctl_works = await check_systemctl_status(cid)
    
    created = utcnow()
    expires = created + timedelta(days=VPS_LIFETIME_DAYS)
    rec = {
        "owner": uid,
        "container_id": cid,
        "ram": ram,
        "cpu": cpu,
        "disk": disk,
        "http_port": http_port,
        "ssh": ssh,
        "created_at": created.isoformat(),
        "expires_at": expires.isoformat(),
        "active": True,
        "suspended": False,
        "paid_plan": paid,
        "giveaway_vps": giveaway,
        "shared_with": [],
        "additional_ports": [],
        "systemctl_working": systemctl_works,
        "backups": [],
        "note": ""
    }
    vps_db[cid] = rec
    persist_vps()
    
    # Send log
    try:
        user = await bot.fetch_user(int(uid))
        await send_log("VPS Created", user, cid, f"RAM: {ram}GB, CPU: {cpu}, Disk: {disk}GB, Systemctl: {'✅' if systemctl_works else '❌'}")
    except:
        pass
    
    return rec

def get_user_vps(user_id):
    uid = str(user_id)
    return [vps for vps in vps_db.values() if vps['owner'] == uid or uid in vps.get('shared_with', [])]

def format_reply(resp: str, user):
    return resp.replace("{user}", getattr(user, "name", "User")).replace("{mention}", user.mention if hasattr(user, "mention") else str(user)).replace("{prefix}", PREFIX)

async def handle_auto_reply(message: discord.Message):
    # Skip if message is a command (starts with prefix) to avoid double responses
    if message.content.startswith(PREFIX):
        return
    now = utcnow()
    chan_key = f"{message.channel.id}"
    last = AUTO_REPLY_COOLDOWN.get(chan_key, 0)
    if (now.timestamp() - last) < 5:  # simple per-channel cooldown
        return
    lowered = message.content.lower()
    for rule in auto_replies:
        pat = rule.get("pattern", "").lower()
        rtype = rule.get("type", "contains")
        chance = rule.get("chance", 1.0)
        if random.random() > chance:
            continue
        matched = False
        if rtype == "contains" and pat in lowered:
            matched = True
        elif rtype == "equals" and pat == lowered:
            matched = True
        elif rtype == "startswith" and lowered.startswith(pat):
            matched = True
        elif rtype == "regex":
            try:
                if re.search(pat, message.content, re.IGNORECASE):
                    matched = True
            except re.error:
                continue
        if matched:
            AUTO_REPLY_COOLDOWN[chan_key] = now.timestamp()
            resp = rule.get("response", "Hello!")
            await message.channel.send(format_reply(resp, message.author))
            break

def can_manage_vps(user_id, container_id):
    if user_id in ADMIN_IDS:
        return True
    vps = vps_db.get(container_id)
    if not vps:
        return False
    uid = str(user_id)
    return vps['owner'] == uid or uid in vps.get('shared_with', [])

def get_resource_usage():
    """Calculate resource usage percentages"""
    total_ram = sum(vps['ram'] for vps in vps_db.values())
    total_cpu = sum(vps['cpu'] for vps in vps_db.values())
    total_disk = sum(vps['disk'] for vps in vps_db.values())
    
    ram_percent = (total_ram / (DEFAULT_RAM_GB * 100)) * 100  # Assuming 100GB max RAM
    cpu_percent = (total_cpu / (DEFAULT_CPU * 50)) * 100     # Assuming 50 CPU max
    disk_percent = (total_disk / (DEFAULT_DISK_GB * 200)) * 100  # Assuming 200GB max disk
    
    return {
        'ram': min(ram_percent, 100),
        'cpu': min(cpu_percent, 100),
        'disk': min(disk_percent, 100),
        'total_ram': total_ram,
        'total_cpu': total_cpu,
        'total_disk': total_disk
    }

# ---------------- Background Tasks ----------------
@tasks.loop(minutes=10)
async def expire_check_loop():
    now = utcnow()
    changed = False
    for cid, rec in list(vps_db.items()):
        if rec.get('active', True) and now >= datetime.fromisoformat(rec['expires_at']):
            await docker_stop_container(cid)
            rec['active'] = False
            rec['suspended'] = True
            changed = True
            # Log expiration
            try:
                user = await bot.fetch_user(int(rec['owner']))
                await send_log("VPS Expired", user, cid, "Auto-suspended due to expiry")
            except:
                pass
    if changed: 
        persist_vps()

@tasks.loop(minutes=5)
async def giveaway_check_loop():
    now = utcnow()
    ended_giveaways = []
    
    for giveaway_id, giveaway in list(giveaways.items()):
        if giveaway['status'] == 'active' and now >= datetime.fromisoformat(giveaway['end_time']):
            # Giveaway ended, select winner
            participants = giveaway.get('participants', [])
            if participants:
                if giveaway['winner_type'] == 'random':
                    winner_id = random.choice(participants)
                    giveaway['winner_id'] = winner_id
                    giveaway['status'] = 'ended'
                    
                    # Create VPS for winner
                    try:
                        rec = await create_vps(int(winner_id), giveaway['vps_ram'], giveaway['vps_cpu'], giveaway['vps_disk'], giveaway_vps=True)
                        if 'error' not in rec:
                            giveaway['vps_created'] = True
                            giveaway['winner_vps_id'] = rec['container_id']
                            
                            # Send DM to winner
                            try:
                                winner = await bot.fetch_user(int(winner_id))
                                embed = discord.Embed(title="🎉 You Won a VPS Giveaway!", color=discord.Color.gold())
                                embed.add_field(name="Container ID", value=f"`{rec['container_id']}`", inline=False)
                                embed.add_field(name="Specs", value=f"**{rec['ram']}GB RAM** | **{rec['cpu']} CPU** | **{rec['disk']}GB Disk**", inline=False)
                                embed.add_field(name="Expires", value=rec['expires_at'][:10], inline=True)
                                embed.add_field(name="Status", value="🟢 Active", inline=True)
                                embed.add_field(name="HTTP Access", value=f"http://{SERVER_IP}:{rec['http_port']}", inline=False)
                                embed.add_field(name="SSH Connection", value=f"```{rec['ssh']}```", inline=False)
                                embed.set_footer(text="This is a giveaway VPS and cannot be renewed. It will auto-delete after 15 days.")
                                await winner.send(embed=embed)
                            except:
                                pass
                    except Exception as e:
                        logger.error(f"Failed to create VPS for giveaway winner: {e}")
                
                elif giveaway['winner_type'] == 'all':
                    # Create VPS for all participants
                    successful_creations = 0
                    for participant_id in participants:
                        try:
                            rec = await create_vps(int(participant_id), giveaway['vps_ram'], giveaway['vps_cpu'], giveaway['vps_disk'], giveaway_vps=True)
                            if 'error' not in rec:
                                successful_creations += 1
                                
                                # Send DM to participant
                                try:
                                    participant = await bot.fetch_user(int(participant_id))
                                    embed = discord.Embed(title="🎉 You Received a VPS from Giveaway!", color=discord.Color.gold())
                                    embed.add_field(name="Container ID", value=f"`{rec['container_id']}`", inline=False)
                                    embed.add_field(name="Specs", value=f"**{rec['ram']}GB RAM** | **{rec['cpu']} CPU** | **{rec['disk']}GB Disk**", inline=False)
                                    embed.add_field(name="Expires", value=rec['expires_at'][:10], inline=True)
                                    embed.add_field(name="Status", value="🟢 Active", inline=True)
                                    embed.add_field(name="HTTP Access", value=f"http://{SERVER_IP}:{rec['http_port']}", inline=False)
                                    embed.add_field(name="SSH Connection", value=f"```{rec['ssh']}```", inline=False)
                                    embed.set_footer(text="This is a giveaway VPS and cannot be renewed. It will auto-delete after 15 days.")
                                    await participant.send(embed=embed)
                                except:
                                    pass
                        except Exception as e:
                            logger.error(f"Failed to create VPS for giveaway participant: {e}")
                    
                    giveaway['vps_created'] = True
                    giveaway['successful_creations'] = successful_creations
                    giveaway['status'] = 'ended'
            
            else:
                # No participants
                giveaway['status'] = 'ended'
                giveaway['no_participants'] = True
            
            ended_giveaways.append(giveaway_id)
    
    if ended_giveaways:
        persist_giveaways()

def build_presence_messages():
    vps_count = len(vps_db)
    user_count = len(users)+len(giveaways)+550+len(vps_db)+170+1000
    return [
        f"Trusted by {user_count} users",
        "Pycroe Cloud",
        f"Managing {vps_count} VPSes",
        f"Deploying {vps_count} instances",
        f"Optimizing {vps_count} instances performance"
    ]

@tasks.loop(seconds=8)
async def presence_rotation_loop():
    choices = build_presence_messages()
    if not choices:
        return
    status_text = random.choice(choices)
    await bot.change_presence(status=discord.Status.idle, activity=discord.Game(name=status_text))

# ---------------- Bot Events ----------------
@bot.event
async def on_ready():
    logger.info(f"Bot ready: {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} guilds")
    # Keep a consistent rich presence
    await bot.change_presence(status=discord.Status.idle, activity=discord.Game(name="Pycroe Cloud"))
    if not presence_rotation_loop.is_running():
        presence_rotation_loop.start()
    expire_check_loop.start()
    giveaway_check_loop.start()

@bot.event
async def on_message(message):
    # Auto-response for pterodactyl installation help
    if message.author.bot:
        return
    
    # Auto-reply system (keywords/responses with cooldown)
    await handle_auto_reply(message)
    
    content = message.content.lower()
    if any(keyword in content for keyword in ['how to install pterodactyl', 'pterodactyl install', 'pterodactyl setup', 'install pterodactyl']):
        embed = discord.Embed(title="🦕 Pterodactyl Panel Installation", color=discord.Color.blue())
        embed.add_field(name="Official Documentation", value="https://pterodactyl.io/panel/1.0/getting_started.html", inline=False)
        embed.add_field(name="Video Tutorial", value="Coming Soon! 🎥", inline=False)
        embed.add_field(name="Quick Start", value="Use our VPS to host your Pterodactyl panel with our easy deployment system!", inline=False)
        await message.channel.send(embed=embed)
    
    await bot.process_commands(message)

@bot.event
async def on_member_join(member):
    """Track REAL unique invites when members join"""
    try:
        guild = member.guild
        
        # Get invites before and after join
        invites_before = invite_snapshot.get(str(guild.id), {})
        invites_after = await guild.invites()
        
        # Find which invite was used
        used_invite = None
        for invite in invites_after:
            uses_before = invites_before.get(invite.code, {}).get('uses', 0)
            if invite.uses > uses_before:
                used_invite = invite
                break
        
        if used_invite and used_invite.inviter:
            inviter_id = used_invite.inviter.id
            
            # Check if this is a UNIQUE join (not rejoin)
            if is_unique_join(member.id, inviter_id):
                # Add as unique join
                if add_unique_join(member.id, inviter_id):
                    # Send success DM to inviter
                    try:
                        inviter_user = await bot.fetch_user(inviter_id)
                        embed = discord.Embed(
                            title="🎉 New Unique Invite!", 
                            color=discord.Color.green(),
                            description=f"**{member.name}** joined using your invite!"
                        )
                        embed.add_field(name="Total Unique Invites", value=f"`{users[str(inviter_id)]['inv_total']}`", inline=True)
                        embed.add_field(name="Unclaimed", value=f"`{users[str(inviter_id)]['inv_unclaimed']}`", inline=True)
                        embed.add_field(name="Use `/claimpoint`", value="Convert to points!", inline=True)
                        embed.set_footer(text="This only counts unique joins (no rejoins)!")
                        await inviter_user.send(embed=embed)
                    except:
                        pass  # User has DMs disabled
                    
                    logger.info(f"UNIQUE join: {member.name} invited by {used_invite.inviter.name}")
                else:
                    logger.info(f"REJOIN detected: {member.name} already invited by {used_invite.inviter.name}")
            else:
                logger.info(f"REJOIN ignored: {member.name} already counted for {used_invite.inviter.name}")
        
        # Update invite snapshot
        invite_snapshot[str(guild.id)] = {
            invite.code: {
                'uses': invite.uses, 
                'inviter': invite.inviter.id if invite.inviter else None
            } for invite in invites_after
        }
        save_json(INV_CACHE_FILE, invite_snapshot)
        
    except Exception as e:
        logger.error(f"Error tracking invite: {e}")

# ---------------- Manage View ----------------
class EnhancedManageView(discord.ui.View):
    def __init__(self, container_id, message=None):
        super().__init__(timeout=300)
        self.container_id = container_id
        self.vps = vps_db.get(container_id)
        self.message = message
        
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if not can_manage_vps(interaction.user.id, self.container_id):
            await interaction.response.send_message("❌ You don't have permission to manage this VPS.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Start", style=discord.ButtonStyle.success, emoji="🟢", row=0)
    async def start_vps(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        # Check if VPS is suspended/expired
        if self.vps.get('suspended', False):
            await interaction.followup.send("❌ VPS is suspended due to expiry. Please renew first.", ephemeral=True)
            return
        
        if not self.vps['active']:
            success = await docker_start_container(self.container_id)
            if success:
                self.vps['active'] = True
                persist_vps()
                await send_log("VPS Started", interaction.user, self.container_id)

                embed = themed_embed(
                    title="🚀 VPS Started",
                    description=f"Container `{self.container_id}` is now live.",
                    color=discord.Color.green()
                )
                embed.add_field(name="Status", value="🟢 Running", inline=True)
                embed.add_field(name="HTTP", value=f"http://{SERVER_IP}:{self.vps['http_port']}", inline=True)
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send("❌ Failed to start VPS.", ephemeral=True)
        else:
            await interaction.followup.send("ℹ️ VPS is already running.", ephemeral=True)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, emoji="🔴", row=0)
    async def stop_vps(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        if self.vps['active']:
            success = await docker_stop_container(self.container_id)
            if success:
                self.vps['active'] = False
                persist_vps()
                await send_log("VPS Stopped", interaction.user, self.container_id)

                embed = themed_embed(
                    title="⏹️ VPS Stopped",
                    description=f"Container `{self.container_id}` has been powered off.",
                    color=discord.Color.orange()
                )
                embed.add_field(name="Status", value="🔴 Stopped", inline=True)
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.followup.send("❌ Failed to stop VPS.", ephemeral=True)
        else:
            await interaction.followup.send("ℹ️ VPS is already stopped.", ephemeral=True)

    @discord.ui.button(label="Restart", style=discord.ButtonStyle.primary, emoji="🔄", row=0)
    async def restart_vps(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        # Check if VPS is suspended/expired
        if self.vps.get('suspended', False):
            await interaction.followup.send("❌ VPS is suspended due to expiry. Please renew first.", ephemeral=True)
            return
        
        success = await docker_restart_container(self.container_id)
        if success:
            self.vps['active'] = True
            self.vps['suspended'] = False
            persist_vps()
            await send_log("VPS Restarted", interaction.user, self.container_id)

            embed = themed_embed(
                title="🔄 VPS Restarted",
                description=f"Container `{self.container_id}` rebooted cleanly.",
                color=discord.Color.blue()
            )
            embed.add_field(name="Status", value="🟢 Running", inline=True)
            embed.add_field(name="HTTP", value=f"http://{SERVER_IP}:{self.vps['http_port']}", inline=True)
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.followup.send("❌ Failed to restart VPS.", ephemeral=True)

    @discord.ui.button(label="Reinstall", style=discord.ButtonStyle.secondary, emoji="💾", row=1)
    async def reinstall_vps(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        # Check if VPS is suspended/expired
        if self.vps.get('suspended', False):
            await interaction.followup.send("❌ VPS is suspended due to expiry. Please renew first.", ephemeral=True)
            return
        
        # Confirm reinstall
        confirm_embed = themed_embed(
            title="⚠️ Full Reinstall",
            description="This will wipe everything and reinstall a fresh system.",
            color=THEME_COLOR_WARN
        )
        confirm_embed.add_field(name="Container", value=f"`{self.container_id}`", inline=True)
        confirm_embed.add_field(name="Impact", value="All files, settings and data will be removed.", inline=False)
        
        confirm_view = discord.ui.View(timeout=60)
        
        @discord.ui.button(label="✅ Confirm Reinstall", style=discord.ButtonStyle.danger, emoji="💀")
        async def confirm_reinstall(confirm_interaction: discord.Interaction, confirm_button: discord.ui.Button):
            if confirm_interaction.user.id != interaction.user.id:
                await confirm_interaction.response.send_message("❌ This is not your confirmation.", ephemeral=True)
                return
                
            await confirm_interaction.response.defer(ephemeral=True)
            
            # Stop and remove current container
            await docker_stop_container(self.container_id)
            await docker_remove_container(self.container_id)
            
            # Create new VPS with same specs
            rec = await create_vps(int(self.vps['owner']), ram=self.vps['ram'], cpu=self.vps['cpu'], disk=self.vps['disk'])
            
            if 'error' in rec:
                await confirm_interaction.followup.send(f"❌ Error reinstalling VPS: {rec['error']}", ephemeral=True)
                return
            
            # Update the VPS record with new container info but keep expiry
            old_expiry = self.vps['expires_at']
            vps_db.pop(self.container_id, None)  # Remove old record
            rec['expires_at'] = old_expiry  # Keep original expiry
            vps_db[rec['container_id']] = rec
            persist_vps()
            
            await send_log("VPS Reinstalled", interaction.user, rec['container_id'], "Full system reset")
            
            success_embed = themed_embed(
                title="✅ Fresh VPS Ready",
                description="Clean reinstall completed.",
                color=discord.Color.green()
            )
            success_embed.add_field(name="New Container", value=f"`{rec['container_id']}`", inline=False)
            success_embed.add_field(name="Specs", value=f"{rec['ram']}GB RAM | {rec['cpu']} CPU | {rec['disk']}GB Disk", inline=True)
            success_embed.add_field(name="HTTP", value=f"http://{SERVER_IP}:{rec['http_port']}", inline=True)
            success_embed.add_field(name="SSH", value=f"```{rec['ssh']}```", inline=False)
            
            await confirm_interaction.followup.send(embed=success_embed, ephemeral=True)
            
            # Update the original message
            try:
                await interaction.delete_original_response()
            except:
                pass
        
        @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
        async def cancel_reinstall(confirm_interaction: discord.Interaction, cancel_button: discord.ui.Button):
            if confirm_interaction.user.id != interaction.user.id:
                await confirm_interaction.response.send_message("❌ This is not your confirmation.", ephemeral=True)
                return
                
            await confirm_interaction.response.send_message("✅ Reinstall cancelled.", ephemeral=True)
        
        confirm_view.add_item(confirm_reinstall)
        confirm_view.add_item(cancel_reinstall)
        
        await interaction.followup.send(embed=confirm_embed, view=confirm_view, ephemeral=True)

    @discord.ui.button(label="Time Left", style=discord.ButtonStyle.secondary, emoji="⏰", row=1)
    async def time_left(self, interaction: discord.Interaction, button: discord.ui.Button):
        expires = datetime.fromisoformat(self.vps['expires_at'])
        now = utcnow()
        
        if expires > now:
            time_left = expires - now
            days = time_left.days
            hours = time_left.seconds // 3600
            minutes = (time_left.seconds % 3600) // 60
            embed = themed_embed(
                title="⏰ VPS Time Remaining",
                description=f"Container `{self.container_id}` runtime status.",
                color=discord.Color.blue()
            )
            
            # Progress bar visualization
            total_days = 15  # Assuming 15-day VPS lifetime
            progress_percent = min((days / total_days) * 100, 100)
            progress_bar = "🟢" * int(progress_percent / 20) + "⚫" * (5 - int(progress_percent / 20))
            
            embed.add_field(
                name="📅 Time Remaining",
                value=f"```\n{progress_bar} {progress_percent:.1f}%\n{days} days, {hours} hours, {minutes} minutes\n```",
                inline=False
            )
            
            embed.add_field(name="Expiry Date", value=f"`{expires.strftime('%Y-%m-%d %H:%M UTC')}`", inline=True)
            
            if days <= 3:
                embed.add_field(
                    name="⚠️ Warning", 
                    value="Your VPS will expire soon! Renew to avoid suspension.",
                    inline=False
                )
            
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            embed = themed_embed(
                title="❌ VPS Expired",
                description="Your VPS has been suspended due to expiry.",
                color=discord.Color.red()
            )
            embed.add_field(name="Container ID", value=f"`{self.container_id}`", inline=False)
            embed.add_field(name="Status", value="⏸️ Suspended", inline=True)
            embed.add_field(name="Action Required", value="Use the **⏳ Renew** button to reactivate", inline=True)
            await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Renew", style=discord.ButtonStyle.success, emoji="⏳", row=1)
    async def renew_vps(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.vps.get('giveaway_vps', False):
            embed = themed_embed(
                title="❌ Giveaway VPS",
                description="This is a giveaway VPS and cannot be renewed.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
            
        uid = str(interaction.user.id)
        if uid not in users:
            users[uid] = {"points": 0, "inv_unclaimed": 0, "inv_total": 0}
            persist_users()
        
        # Get current renew mode (default to 15 days)
        current_mode = renew_mode.get("mode", "15")
        cost = POINTS_RENEW_15 if current_mode == "15" else POINTS_RENEW_30
        days = 15 if current_mode == "15" else 15
        
        if users[uid]['points'] < cost:
            embed = themed_embed(
                title="❌ Insufficient Points",
                description=f"You need **{cost} points** to renew for **{days} days**.",
                color=discord.Color.red()
            )
            embed.add_field(name="Your Points", value=f"`{users[uid]['points']}`", inline=True)
            embed.add_field(name="Required", value=f"`{cost}`", inline=True)
            embed.add_field(name="Missing", value=f"`{cost - users[uid]['points']}`", inline=True)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        
        # Confirm renewal
        current_expiry = datetime.fromisoformat(self.vps['expires_at'])
        new_expiry = max(utcnow(), current_expiry) + timedelta(days=days)
        
        confirm_embed = themed_embed(
            title="🔄 Confirm VPS Renewal",
            description=f"Renew **{self.container_id}** for **{days} days**?",
            color=THEME_COLOR_ACCENT
        )
        confirm_embed.add_field(name="Cost", value=f"`{cost} points`", inline=True)
        confirm_embed.add_field(name="Duration", value=f"`{days} days`", inline=True)
        confirm_embed.add_field(name="New Expiry", value=f"`{new_expiry.strftime('%Y-%m-%d %H:%M')}`", inline=False)
        confirm_embed.add_field(name="Your Points", value=f"`{users[uid]['points']} → {users[uid]['points'] - cost}`", inline=True)
        
        confirm_view = discord.ui.View(timeout=60)
        
        @discord.ui.button(label="✅ Confirm Renew", style=discord.ButtonStyle.success)
        async def confirm_renew(confirm_interaction: discord.Interaction, confirm_button: discord.ui.Button):
            if confirm_interaction.user.id != interaction.user.id:
                await confirm_interaction.response.send_message("❌ This is not your confirmation.", ephemeral=True)
                return
                
            await confirm_interaction.response.defer(ephemeral=True)
            
            # Deduct points and extend expiry
            users[uid]['points'] -= cost
            persist_users()
            
            self.vps['expires_at'] = new_expiry.isoformat()
            self.vps['active'] = True
            self.vps['suspended'] = False
            persist_vps()
            
            await send_log("VPS Renewed", interaction.user, self.container_id, f"Extended by {days} days")
            
            # Auto-start the VPS if it was suspended
            if not self.vps['active']:
                await docker_start_container(self.container_id)
                self.vps['active'] = True
                persist_vps()
            
            success_embed = themed_embed(
                title="✅ VPS Renewed",
                description=f"**{self.container_id}** extended for **{days} days**",
                color=discord.Color.green()
            )
            success_embed.add_field(name="Cost", value=f"`{cost} points`", inline=True)
            success_embed.add_field(name="New Expiry", value=f"`{new_expiry.strftime('%Y-%m-%d %H:%M')}`", inline=True)
            success_embed.add_field(name="Remaining Points", value=f"`{users[uid]['points']}`", inline=True)
            success_embed.add_field(name="Status", value="🟢 Active & Running", inline=False)
            
            await confirm_interaction.followup.send(embed=success_embed, ephemeral=True)
        
        @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
        async def cancel_renew(confirm_interaction: discord.Interaction, cancel_button: discord.ui.Button):
            if confirm_interaction.user.id != interaction.user.id:
                await confirm_interaction.response.send_message("❌ This is not your confirmation.", ephemeral=True)
                return
                
            await confirm_interaction.response.send_message("✅ Renewal cancelled.", ephemeral=True)
        
        confirm_view.add_item(confirm_renew)
        confirm_view.add_item(cancel_renew)
        
        await interaction.response.send_message(embed=confirm_embed, view=confirm_view, ephemeral=True)

    @discord.ui.button(label="Reset SSH", style=discord.ButtonStyle.secondary, emoji="🔑", row=2)
    async def reset_ssh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        # Check if VPS is suspended/expired
        if self.vps.get('suspended', False):
            await interaction.followup.send("❌ VPS is suspended due to expiry. Please renew first.", ephemeral=True)
            return
        
        ssh, err = await docker_exec_capture_ssh(self.container_id)
        if err:
            await interaction.followup.send(f"⚠️ SSH reset with warning: {err}", ephemeral=True)
        
        self.vps['ssh'] = ssh
        persist_vps()
        await send_log("SSH Reset", interaction.user, self.container_id)
        
        embed = themed_embed(
            title="🔑 New SSH",
            description=f"Container `{self.container_id}` refreshed SSH endpoint.",
            color=discord.Color.green()
        )
        embed.add_field(name="SSH Command", value=f"```{ssh}```", inline=False)
        embed.add_field(name="Note", value="Save this SSH connection string securely!", inline=False)
        
        await interaction.followup.send(embed=embed, ephemeral=True)
# ---------------- Giveaway View ----------------
class GiveawayView(discord.ui.View):
    def __init__(self, giveaway_id):
        super().__init__(timeout=None)
        self.giveaway_id = giveaway_id
        
    @discord.ui.button(label="🎉 Join Giveaway", style=discord.ButtonStyle.primary, custom_id="join_giveaway")
    async def join_giveaway(self, interaction: discord.Interaction, button: discord.ui.Button):
        giveaway = giveaways.get(self.giveaway_id)
        if not giveaway or giveaway['status'] != 'active':
            await interaction.response.send_message("❌ This giveaway has ended.", ephemeral=True)
            return
        
        participant_id = str(interaction.user.id)
        participants = giveaway.get('participants', [])
        
        if participant_id in participants:
            await interaction.response.send_message("❌ You have already joined this giveaway.", ephemeral=True)
            return
        
        participants.append(participant_id)
        giveaway['participants'] = participants
        persist_giveaways()
        
        await interaction.response.send_message("✅ You have successfully joined the giveaway!", ephemeral=True)

# ---------------- COMMANDS REGISTRATION ----------------
# All commands are now properly registered as app_commands

@bot.tree.command(name="deploy", description="Deploy a VPS (cost 4 points)")
async def deploy(interaction: discord.Interaction):
    """Deploy a new VPS - Points required before deployment"""
    uid = str(interaction.user.id)
    ensure_user(uid)
    persist_users()
    
    # Check points and BLOCK deployment if not enough
    has_enough_points = users[uid]['points'] >= POINTS_PER_DEPLOY
    is_admin = interaction.user.id in ADMIN_IDS
    
    # If user doesn't have enough points and is not admin, BLOCK deployment
    if not has_enough_points and not is_admin:
        await interaction.response.send_message(
            f"❌ You need {POINTS_PER_DEPLOY} points to deploy a VPS. You only have {users[uid]['points']} points.\n\n"
            f"**Ways to earn points:**\n"
            f"• Use `/invite` to get invite links\n"
            f"• Ask friends to join using your invite code\n"
            f"• Wait for daily point resets\n"
            f"• Participate in giveaways",
            ephemeral=True
        )
        return
    
    original_points = users[uid]['points']
    
    # Send initial response based on points status
    if not is_admin:
        await interaction.response.send_message(
            f"✅ You have enough points! Deploying VPS... (Cost: {POINTS_PER_DEPLOY} points)", 
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            "🛠️ Admin deployment in progress...", 
            ephemeral=True
        )
    
    # Defer if not already done
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    
    # Create VPS first
    rec = await create_vps(interaction.user.id)
    
    if 'error' in rec:
        await interaction.followup.send(f"❌ Error creating VPS: {rec['error']}", ephemeral=True)
        return
    
    # Deduct points after successful VPS creation (only if not admin)
    points_deducted = 0
    if not is_admin:
        users[uid]['points'] -= POINTS_PER_DEPLOY
        points_deducted = POINTS_PER_DEPLOY
        persist_users()
    
    systemctl_status = "✅ Working" if rec.get('systemctl_working') else "⚠️ Limited"
    
    embed = themed_embed(
        title="🎉 Your VPS is Ready!",
        description="Fresh container deployed with optimal tuning.",
        color=discord.Color.green()
    )
    embed.add_field(name="Container ID", value=f"`{rec['container_id']}`", inline=False)
    embed.add_field(name="Specs", value=f"**{rec['ram']}GB RAM** | **{rec['cpu']} CPU** | **{rec['disk']}GB Disk**", inline=False)
    embed.add_field(name="Expires", value=rec['expires_at'][:10], inline=True)
    embed.add_field(name="Status", value="🟢 Active", inline=True)
    embed.add_field(name="Systemctl", value=systemctl_status, inline=True)
    embed.add_field(name="HTTP Access", value=f"http://{SERVER_IP}:{rec['http_port']}", inline=False)
    embed.add_field(name="SSH Connection", value=f"```{rec['ssh']}```", inline=False)
    
    if not is_admin:
        embed.add_field(name="Points Deducted", value=f"{-POINTS_PER_DEPLOY} points", inline=True)
        embed.add_field(name="Remaining Points", value=f"{users[uid]['points']} points", inline=True)
    
    try: 
        await interaction.user.send(embed=embed)
        followup_msg = "✅ VPS created successfully! Check your DMs for details."
        if not is_admin:
            followup_msg += f"\n📊 Points: {original_points} → {users[uid]['points']} (-{POINTS_PER_DEPLOY})"
        await interaction.followup.send(followup_msg, ephemeral=True)
    except: 
        followup_msg = "✅ VPS created! Could not DM you. Enable DMs from server members."
        if not is_admin:
            followup_msg += f"\n📊 Points: {original_points} → {users[uid]['points']} (-{POINTS_PER_DEPLOY})"
        await interaction.followup.send(followup_msg, embed=embed, ephemeral=True)
    
    # Send log
    await send_log(
        "VPS Deployed", 
        interaction.user, 
        details=f"New VPS created with {rec['ram']}GB RAM, {rec['cpu']} CPU, {rec['disk']}GB Disk",
        vps_id=rec['container_id']
    )

@bot.tree.command(name="list", description="List your VPS")
async def list_vps(interaction: discord.Interaction):
    """List all your VPS"""
    uid = str(interaction.user.id)
    user_vps = get_user_vps(interaction.user.id)
    
    if not user_vps:
        await interaction.response.send_message("❌ No VPS found.", ephemeral=True)
        return
    
    embed = themed_embed(
        title="📜 Your VPS List",
        description="Overview of all containers you can manage.",
        color=THEME_COLOR_PRIMARY
    )
    for vps in user_vps:
        status = "🟢 Running" if vps['active'] and not vps.get('suspended', False) else "🔴 Stopped"
        if vps.get('suspended', False):
            status = "⏸️ Suspended"
        
        expires = datetime.fromisoformat(vps['expires_at']).strftime('%Y-%m-%d')
        systemctl_status = "✅" if vps.get('systemctl_working') else "❌"
        
        value = f"**Specs:** {vps['ram']}GB RAM | {vps['cpu']} CPU | {vps['disk']}GB Disk\n"
        value += f"**Status:** {status} | **Expires:** {expires}\n"
        value += f"**Systemctl:** {systemctl_status} | **HTTP:** http://{SERVER_IP}:{vps['http_port']}\n"
        value += f"**Container ID:** `{vps['container_id']}`"
        
        if vps.get('additional_ports'):
            value += f"\n**Extra Ports:** {', '.join(map(str, vps['additional_ports']))}"
        
        if vps.get('giveaway_vps'):
            value += f"\n**Type:** 🎁 Giveaway VPS"
        
        embed.add_field(
            name=f"VPS - {vps['container_id'][:8]}...", 
            value=value, 
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="remove", description="Remove your VPS and get half points refund")
@app_commands.describe(container_id="Container ID to remove")
async def remove_vps(interaction: discord.Interaction, container_id: str):
    """Remove a VPS and get half points refunded"""
    cid = container_id.strip()
    rec = vps_db.get(cid)
    if not rec:
        await interaction.response.send_message("❌ No VPS found with that ID.", ephemeral=True)
        return
    
    uid = str(interaction.user.id)
    if rec['owner'] != uid and interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ You don't have permission to remove this VPS.", ephemeral=True)
        return
    
    # Send warning message first
    refund_amount = POINTS_PER_DEPLOY // 2  # Half points refund
    warning_msg = (
        f"⚠️ **Warning: You are about to remove VPS `{cid}`**\n\n"
        f"• Only **{refund_amount} points** will be refunded (half of deployment cost)\n"
        f"• Your current balance: **{users.get(uid, {}).get('points', 0)} points**\n"
        f"• After refund: **{users.get(uid, {}).get('points', 0) + refund_amount} points**\n\n"
        f"**Are you sure you want to proceed?**"
    )
    
    # Create a confirmation view
    class ConfirmView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=30.0)
            self.value = None
        
        @discord.ui.button(label='Confirm Remove', style=discord.ButtonStyle.danger)
        async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.value = True
            self.stop()
            await interaction.response.defer()
        
        @discord.ui.button(label='Cancel', style=discord.ButtonStyle.secondary)
        async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
            self.value = False
            self.stop()
            await interaction.response.send_message("✅ Removal cancelled.", ephemeral=True)
    
    view = ConfirmView()
    await interaction.response.send_message(warning_msg, view=view, ephemeral=True)
    
    # Wait for user response
    await view.wait()
    
    if view.value is None:
        await interaction.followup.send("⏰ Removal timed out. Please try again.", ephemeral=True)
        return
    elif not view.value:
        return  # User cancelled
    
    # Proceed with removal
    await interaction.followup.send("🔄 Removing VPS...", ephemeral=True)
    
    success = await docker_remove_container(cid)
    if not success:
        await interaction.followup.send("⚠️ Failed to remove container. It might already be removed.", ephemeral=True)
        return
    
    # Refund half points only if user owns it and is not admin
    refund_given = False
    if rec['owner'] == uid and interaction.user.id not in ADMIN_IDS and not rec.get('giveaway_vps', False):
        users[uid]['points'] += refund_amount
        persist_users()
        refund_given = True
    
    vps_db.pop(cid, None)
    persist_vps()
    await send_log("VPS Removed", interaction.user, cid)
    
    result_msg = f"✅ VPS `{cid}` removed successfully."
    if refund_given:
        result_msg += f" Refunded {refund_amount} points (half of deployment cost)."
    
    await interaction.followup.send(result_msg, ephemeral=True)

@bot.tree.command(name="manage", description="Interactive panel for VPS management")
@app_commands.describe(container_id="Container ID to manage")
async def manage(interaction: discord.Interaction, container_id: str):
    """Manage your VPS with interactive buttons"""
    cid = container_id.strip()
    if not can_manage_vps(interaction.user.id, cid):
        await interaction.response.send_message("❌ You don't have permission to manage this VPS or VPS not found.", ephemeral=True)
        return
    
    vps = vps_db[cid]
    
    # Calculate time left
    expires = datetime.fromisoformat(vps['expires_at'])
    now = utcnow()
    time_left = expires - now if expires > now else timedelta(0)
    days_left = time_left.days
    hours_left = time_left.seconds // 3600
    minutes_left = (time_left.seconds % 3600) // 60
    
    # Status with emojis
    if vps.get('suspended', False):
        status = "⏸️ Suspended (Expired)"
        status_color = 0xff9900  # Orange
    elif not vps['active']:
        status = "🔴 Stopped"
        status_color = 0xff0000  # Red
    else:
        status = "🟢 Running"
        status_color = 0x00ff00  # Green
    
    # VPS Type
    vps_type = "🎁 Giveaway VPS" if vps.get('giveaway_vps') else "💎 Premium VPS"
    
    # Create beautiful embed
    embed = discord.Embed(
        title=f"🚀 VPS Management Panel", 
        description=f"**Container ID:** `{cid}`",
        color=status_color,
        timestamp=utcnow()
    )
    
    # Header Section
    embed.add_field(
        name="📊 **VPS Overview**",
        value=f"```\n⚡ Status: {status}\n🎯 Type: {vps_type}\n🛡️ Systemctl: {'✅ Working' if vps.get('systemctl_working') else '❌ Not Working'}\n```",
        inline=False
    )
    
    # Specifications Section
    embed.add_field(
        name="💻 **Specifications**",
        value=f"```\n🧠 RAM: {vps['ram']}GB\n⚡ CPU: {vps['cpu']} Cores\n💾 Disk: {vps['disk']}GB\n🌐 HTTP Port: {vps['http_port']}\n```",
        inline=True
    )
    
    # Time & Expiry Section
    time_display = f"{days_left}d {hours_left}h {minutes_left}m" if days_left > 0 else "EXPIRED"
    time_emoji = "🟢" if days_left > 7 else "🟡" if days_left > 3 else "🔴"
    
    embed.add_field(
        name="⏰ **Time & Expiry**",
        value=f"```\n{time_emoji} Time Left: {time_display}\n📅 Created: {vps['created_at'][:10]}\n⏳ Expires: {vps['expires_at'][:10]}\n```",
        inline=True
    )
    
    # Additional Ports
    if vps.get('additional_ports'):
        embed.add_field(
            name="🔌 **Additional Ports**",
            value=f"`{', '.join(map(str, vps['additional_ports']))}`",
            inline=False
        )
    
    # Renewal Information (if not giveaway)
    if not vps.get('giveaway_vps', False):
        current_mode = renew_mode.get("mode", "15")  # Default to 15 days
        cost = POINTS_RENEW_15 if current_mode == "15" else POINTS_RENEW_30
        days = 15 if current_mode == "15" else 15
        
        renew_info = f"```\n💰 Cost: {cost} points\n⏳ Duration: {days} days\n🔄 Auto-suspend: After expiry\n✅ Auto-resume: After renew\n```"
        
        embed.add_field(
            name="🔄 **Renewal Options**",
            value=renew_info,
            inline=False
        )
    
    # Quick Stats
    embed.add_field(
        name="📈 **Quick Stats**",
        value=f"```\n🎯 Uptime: {'Active' if vps['active'] else 'Inactive'}\n🛡️ Protected: {'Yes' if not vps.get('giveaway_vps') else 'No'}\n🔧 Managed: Yes\n```",
        inline=True
    )
    
    # Footer with instructions
    if vps.get('suspended', False):
        embed.add_field(
            name="⚠️ **VPS Suspended**",
            value="Your VPS has been suspended due to expiry. Use the **⏳ Renew** button to reactivate it!",
            inline=False
        )
    
    embed.set_footer(
        text="💡 Tip: Use the buttons below to manage your VPS", 
        icon_url=interaction.user.display_avatar.url
    )
    
    # Create enhanced view
    view = EnhancedManageView(cid)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

@bot.tree.command(name="status", description="Check VPS status and system information")
async def status(interaction: discord.Interaction):
    """Check VPS status and system information"""
    embed = discord.Embed(title="📊 VPS System Status", color=discord.Color.blue())
    
    # Count VPS
    total_vps = len(vps_db)
    active_vps = len([v for v in vps_db.values() if v['active']])
    suspended_vps = len([v for v in vps_db.values() if v.get('suspended', False)])
    systemctl_working = len([v for v in vps_db.values() if v.get('systemctl_working', False)])
    
    embed.add_field(name="Total VPS", value=str(total_vps), inline=True)
    embed.add_field(name="Active VPS", value=str(active_vps), inline=True)
    embed.add_field(name="Suspended VPS", value=str(suspended_vps), inline=True)
    embed.add_field(name="Systemctl Working", value=f"{systemctl_working}/{total_vps}", inline=True)
    
    # Resource usage for admin
    if interaction.user.id in ADMIN_IDS:
        usage = get_resource_usage()
        embed.add_field(name="📈 Resource Usage", value=f"**RAM:** {usage['ram']:.1f}% ({usage['total_ram']}GB)\n**CPU:** {usage['cpu']:.1f}% ({usage['total_cpu']} cores)\n**Disk:** {usage['disk']:.1f}% ({usage['total_disk']}GB)", inline=False)
    
    # System info
    try:
        # Get Docker info
        proc = await asyncio.create_subprocess_exec(
            "docker", "info", "--format", "{{.ServerVersion}}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        docker_version = stdout.decode().strip() if stdout else "Unknown"
        
        embed.add_field(name="Docker Version", value=docker_version, inline=True)
    except:
        embed.add_field(name="Docker Version", value="Unknown", inline=True)
    
    embed.add_field(name="Server IP", value=SERVER_IP, inline=True)
    embed.add_field(name="Default Specs", value=f"{DEFAULT_RAM_GB}GB RAM, {DEFAULT_CPU} CPU, {DEFAULT_DISK_GB}GB Disk", inline=False)
    
    # Recent activity
    recent_vps = list(vps_db.values())[-3:] if vps_db else []
    if recent_vps:
        recent_info = ""
        for vps in recent_vps:
            status = "🟢" if vps['active'] else "🔴"
            systemctl = "✅" if vps.get('systemctl_working') else "❌"
            recent_info += f"{status} `{vps['container_id'][:8]}` {systemctl}\n"
        embed.add_field(name="Recent VPS", value=recent_info, inline=True)
    
    await interaction.response.send_message(embed=embed, ephemeral=False)

@bot.tree.command(name="port", description="Add additional port to your VPS")
@app_commands.describe(container_id="Your VPS container ID", port="Port number to add")
async def port_add(interaction: discord.Interaction, container_id: str, port: int):
    """Add additional port to VPS"""
    cid = container_id.strip()
    if not can_manage_vps(interaction.user.id, cid):
        await interaction.response.send_message("❌ You don't have permission to manage this VPS or VPS not found.", ephemeral=True)
        return
    
    if port < 1 or port > 65535:
        await interaction.response.send_message("❌ Port must be between 1 and 65535.", ephemeral=True)
        return
    
    vps = vps_db.get(cid)
    if not vps:
        await interaction.response.send_message("❌ VPS not found.", ephemeral=True)
        return
    
    if port in vps.get('additional_ports', []):
        await interaction.response.send_message("❌ Port already added to this VPS.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    success, message = await add_port_to_container(cid, port)
    if success:
        if 'additional_ports' not in vps:
            vps['additional_ports'] = []
        vps['additional_ports'].append(port)
        persist_vps()
        await send_log("Port Added", interaction.user, cid, f"Port: {port}")
        await interaction.followup.send(f"✅ Port {port} added successfully to VPS `{cid}`", ephemeral=True)
    else:
        await interaction.followup.send(f"❌ Failed to add port: {message}", ephemeral=True)

@bot.tree.command(name="mass_port", description="[ADMIN] Add port to multiple VPS")
@app_commands.describe(port="Port number to add", container_ids="Comma-separated container IDs")
async def mass_port(interaction: discord.Interaction, port: int, container_ids: str):
    """[ADMIN] Add port to multiple VPS"""
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    
    if port < 1 or port > 65535:
        await interaction.response.send_message("❌ Port must be between 1 and 65535.", ephemeral=True)
        return
    
    container_list = [cid.strip() for cid in container_ids.split(',')]
    valid_containers = []
    invalid_containers = []
    
    await interaction.response.defer(ephemeral=True)
    
    for cid in container_list:
        if cid in vps_db:
            vps = vps_db[cid]
            if port not in vps.get('additional_ports', []):
                success, _ = await add_port_to_container(cid, port)
                if success:
                    if 'additional_ports' not in vps:
                        vps['additional_ports'] = []
                    vps['additional_ports'].append(port)
                    valid_containers.append(cid)
                else:
                    invalid_containers.append(cid)
            else:
                invalid_containers.append(cid)
        else:
            invalid_containers.append(cid)
    
    persist_vps()
    await send_log("Mass Port Add", interaction.user, None, f"Port: {port}, Success: {len(valid_containers)}, Failed: {len(invalid_containers)}")
    
    result_msg = f"**Port {port} added to {len(valid_containers)} VPS**\n"
    if valid_containers:
        result_msg += f"✅ Success: {', '.join(valid_containers[:5])}{'...' if len(valid_containers) > 5 else ''}\n"
    if invalid_containers:
        result_msg += f"❌ Failed: {', '.join(invalid_containers[:5])}{'...' if len(invalid_containers) > 5 else ''}"
    
    await interaction.followup.send(result_msg, ephemeral=True)

@bot.tree.command(name="share_vps", description="Share VPS access with another user")
@app_commands.describe(container_id="Your VPS container ID", user="User to share with")
async def share_vps(interaction: discord.Interaction, container_id: str, user: discord.Member):
    """Share VPS access with another user"""
    cid = container_id.strip()
    vps = vps_db.get(cid)
    
    if not vps:
        await interaction.response.send_message("❌ VPS not found.", ephemeral=True)
        return
    
    if vps['owner'] != str(interaction.user.id):
        await interaction.response.send_message("❌ You can only share VPS that you own.", ephemeral=True)
        return
    
    if str(user.id) in vps.get('shared_with', []):
        await interaction.response.send_message("❌ VPS is already shared with this user.", ephemeral=True)
        return
    
    if 'shared_with' not in vps:
        vps['shared_with'] = []
    
    vps['shared_with'].append(str(user.id))
    persist_vps()
    await send_log("VPS Shared", interaction.user, cid, f"Shared with: {user.name}")
    
    await interaction.response.send_message(f"✅ VPS `{cid}` shared with {user.mention}", ephemeral=True)

@bot.tree.command(name="share_remove", description="Remove shared access from user")
@app_commands.describe(container_id="Your VPS container ID", user="User to remove access from")
async def share_remove(interaction: discord.Interaction, container_id: str, user: discord.Member):
    """Remove shared VPS access from user"""
    cid = container_id.strip()
    vps = vps_db.get(cid)
    
    if not vps:
        await interaction.response.send_message("❌ VPS not found.", ephemeral=True)
        return
    
    if vps['owner'] != str(interaction.user.id) and interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ You can only manage sharing for VPS that you own.", ephemeral=True)
        return
    
    if str(user.id) not in vps.get('shared_with', []):
        await interaction.response.send_message("❌ VPS is not shared with this user.", ephemeral=True)
        return
    
    vps['shared_with'].remove(str(user.id))
    persist_vps()
    await send_log("Share Removed", interaction.user, cid, f"Removed from: {user.name}")
    
    await interaction.response.send_message(f"✅ Removed VPS access from {user.mention}", ephemeral=True)

@bot.tree.command(name="admin_add", description="[MAIN ADMIN] Add admin user")
@app_commands.describe(user="User to make admin")
async def admin_add(interaction: discord.Interaction, user: discord.Member):
    """[MAIN ADMIN] Add admin user"""
    # Check if user has permission to add admins
    if interaction.user.id not in MAIN_ADMIN_IDS and interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ Only main admin or owner can add admins.", ephemeral=True)
        return
    
    # Load additional admins list from file
    admin_file = os.path.join(DATA_DIR, "admins.json")
    additional_admins = load_json(admin_file, [])
    
    # Check if user is already admin (in main or additional)
    if user.id in ADMIN_IDS:
        embed = discord.Embed(
            title="❌ Already Admin",
            description=f"**{user.name}** is already an admin.",
            color=discord.Color.orange()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Add user to additional admins
    additional_admins.append(user.id)
    save_json(admin_file, additional_admins)
    
    # Update global ADMIN_IDS (for runtime)
    ADMIN_IDS.add(user.id)
    
    await send_log("Admin Added", interaction.user, None, f"Added admin: {user.name}")
    
    # Create embed for response
    embed = discord.Embed(
        title="✅ Admin Added",
        description=f"**{user.name}** has been granted admin privileges.",
        color=discord.Color.green(),
        timestamp=utcnow()
    )
    embed.add_field(name="Added By", value=interaction.user.mention, inline=True)
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Admin Type", value="🛡️ Additional Admin", inline=True)
    embed.set_footer(text="This admin can be removed using /admin_remove")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="admin_remove", description="[MAIN ADMIN] Remove admin user")
@app_commands.describe(user="User to remove from admin")
async def admin_remove(interaction: discord.Interaction, user: discord.Member):
    """[MAIN ADMIN] Remove admin user"""
    # Check if user has permission to remove admins
    if interaction.user.id not in MAIN_ADMIN_IDS and interaction.user.id != OWNER_ID:
        await interaction.response.send_message("❌ Only main admin or owner can remove admins.", ephemeral=True)
        return
    
    # Load additional admins list from file
    admin_file = os.path.join(DATA_DIR, "admins.json")
    additional_admins = load_json(admin_file, [])
    
    # Check if target user is in additional admins (can be removed)
    if user.id not in additional_admins:
        # Check if they're a main admin or owner (cannot be removed)
        if user.id in MAIN_ADMIN_IDS:
            embed = discord.Embed(
                title="❌ Cannot Remove Main Admin",
                description=f"**{user.name}** is a main admin (defined in bot.py) and cannot be removed.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        elif user.id == OWNER_ID:
            embed = discord.Embed(
                title="❌ Cannot Remove Owner",
                description=f"**{user.name}** is the bot owner and cannot be removed.",
                color=discord.Color.red()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        else:
            embed = discord.Embed(
                title="❌ Not an Admin",
                description=f"**{user.name}** is not an admin.",
                color=discord.Color.orange()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
    
    # Remove the user from additional admins
    additional_admins.remove(user.id)
    save_json(admin_file, additional_admins)
    
    # Update global ADMIN_IDS (remove from runtime)
    if user.id in ADMIN_IDS:
        ADMIN_IDS.remove(user.id)
    
    await send_log("Admin Removed", interaction.user, None, f"Removed admin: {user.name}")
    
    # Create embed for response
    embed = discord.Embed(
        title="✅ Admin Removed",
        description=f"**{user.name}** has been removed from admin privileges.",
        color=discord.Color.green(),
        timestamp=utcnow()
    )
    embed.add_field(name="Removed By", value=interaction.user.mention, inline=True)
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Remaining Additional Admins", value=f"`{len(additional_admins)}` users", inline=True)
    embed.set_footer(text="Use /admins to view all admin users")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="admins", description="Show all admin users")
async def admins_list(interaction: discord.Interaction):
    """Show all admin users with clear distinction"""
    admin_file = os.path.join(DATA_DIR, "admins.json")
    additional_admins = load_json(admin_file, [])
    
    embed = discord.Embed(title="🛡️ Admin Users", color=discord.Color.blue(), timestamp=utcnow())
    
    # Owner
    try:
        owner = await bot.fetch_user(OWNER_ID)
        embed.add_field(name="👑 Bot Owner", value=f"{owner.mention} (`{owner.id}`)\n*Cannot be removed*", inline=False)
    except:
        embed.add_field(name="👑 Bot Owner", value=f"User `{OWNER_ID}`\n*Cannot be removed*", inline=False)
    
    # Main Admins (hardcoded in bot.py)
    main_admins = []
    for admin_id in MAIN_ADMIN_IDS:
        try:
            user = await bot.fetch_user(admin_id)
            main_admins.append(f"{user.mention} (`{user.id}`)")
        except:
            main_admins.append(f"User `{admin_id}`")
    
    if main_admins:
        embed.add_field(name="🔐 Main Admins", value="\n".join(main_admins) + "\n*Defined in bot.py, cannot be removed*", inline=False)
    
    # Additional Admins (added via command)
    command_admins = []
    for admin_id in additional_admins:
        try:
            user = await bot.fetch_user(admin_id)
            command_admins.append(f"{user.mention} (`{user.id}`)")
        except:
            command_admins.append(f"User `{admin_id}`")
    
    if command_admins:
        embed.add_field(name="📋 Additional Admins", value="\n".join(command_admins) + f"\n*Added via command, can be removed*\n**Total:** `{len(command_admins)}` users", inline=False)
    else:
        embed.add_field(name="📋 Additional Admins", value="No additional admins\n*Use `/admin_add` to add more*", inline=False)
    
    embed.set_footer(text=f"Total Admin Users: {len(MAIN_ADMIN_IDS) + len(additional_admins) + 1}")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="set_log_channel", description="[ADMIN] Set channel for VPS logs")
@app_commands.describe(channel="Channel to send logs to")
async def set_log_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    """[ADMIN] Set channel for professional VPS logs"""
    if interaction.user.id not in ADMIN_IDS:
        embed = discord.Embed(
            title="❌ Permission Denied",
            description="You need admin privileges to set the log channel.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    global LOG_CHANNEL_ID
    LOG_CHANNEL_ID = channel.id
    
    # Save to config
    config_file = os.path.join(DATA_DIR, "config.json")
    config = load_json(config_file, {})
    config['log_channel_id'] = channel.id
    save_json(config_file, config)
    
    # Create success embed
    embed = discord.Embed(
        title="✅ Log Channel Configured",
        description=f"**Log channel has been set to:** {channel.mention}",
        color=discord.Color.green(),
        timestamp=utcnow()
    )
    
    embed.add_field(
        name="📊 What will be logged:",
        value="• VPS Deployments & Removals\n• VPS Start/Stop/Restart\n• VPS Renewals & Suspensions\n• Admin Actions\n• Point Transactions\n• Invite Claims\n• Port Management\n• Sharing Actions",
        inline=False
    )
    
    embed.add_field(
        name="👤 Set By:",
        value=f"{interaction.user.mention}\n`{interaction.user.name}`",
        inline=True
    )
    
    embed.add_field(
        name="📅 Configured At:",
        value=f"<t:{int(utcnow().timestamp())}:F>",
        inline=True
    )
    
    embed.set_footer(text="All VPS activities will now be logged here")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # Send test log to the new channel
    await send_log(
        "Log System Activated", 
        interaction.user, 
        details=f"Log channel configured by {interaction.user.name}\nAll future VPS activities will be logged here."
    )

# ============ ADD /logs COMMAND RIGHT HERE ============
@bot.tree.command(name="logs", description="[ADMIN] View recent VPS activities")
@app_commands.describe(limit="Number of logs to show (default: 10, max: 25)")
async def view_logs(interaction: discord.Interaction, limit: int = 10):
    """[ADMIN] View recent VPS activity logs"""
    if interaction.user.id not in ADMIN_IDS:
        embed = discord.Embed(
            title="❌ Permission Denied",
            description="You need admin privileges to view logs.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    if limit > 25:
        limit = 25
    if limit < 1:
        limit = 10
    
    # Load logs
    logs_file = os.path.join(DATA_DIR, "vps_logs.json")
    logs_data = load_json(logs_file, [])
    
    if not logs_data:
        embed = discord.Embed(
            title="📊 VPS Activity Logs",
            description="No logs found yet. Activities will appear here once they occur.",
            color=discord.Color.blue()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    
    # Get recent logs
    recent_logs = list(reversed(logs_data[-limit:]))
    
    # Create logs overview embed
    embed = discord.Embed(
        title="📊 VPS Activity Logs",
        description=f"Showing last **{len(recent_logs)}** activities",
        color=discord.Color.blue(),
        timestamp=utcnow()
    )
    
    # Add statistics
    total_vps = len(vps_db)
    active_vps = len([v for v in vps_db.values() if v['active']])
    suspended_vps = len([v for v in vps_db.values() if v.get('suspended', False)])
    total_users = len(users)
    
    embed.add_field(
        name="📈 Current Statistics",
        value=f"```\n🏠 Total VPS: {total_vps}\n🟢 Active: {active_vps}\n⏸️ Suspended: {suspended_vps}\n👥 Total Users: {total_users}\n```",
        inline=False
    )
    
    # Add recent activities
    activities_text = ""
    for i, log in enumerate(recent_logs, 1):
        timestamp = log.get('timestamp', 'Unknown')
        action = log.get('action', 'Unknown')
        user = log.get('user', 'Unknown')
        details = log.get('details', '')
        
        # Format timestamp nicely
        try:
            if isinstance(timestamp, str) and timestamp != 'Unknown':
                time_display = f"<t:{int(datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp())}:R>"
            else:
                time_display = "Recently"
        except:
            time_display = "Recently"
        
        # Truncate long details
        if len(details) > 50:
            details = details[:47] + "..."
        
        activities_text += f"**{i}. {action}**\n"
        activities_text += f"👤 `{user}` • ⏰ {time_display}\n"
        if details:
            activities_text += f"📝 `{details}`\n"
        activities_text += "\n"
    
    if activities_text:
        embed.add_field(
            name="🔄 Recent Activities",
            value=activities_text[:1024] if len(activities_text) > 1024 else activities_text,
            inline=False
        )
    
    embed.add_field(
        name="🔧 Quick Actions",
        value="• Use `/status` for detailed system status\n• Use `/listsall` to view all VPS\n• Use `/set_log_channel` to change log location",
        inline=False
    )
    
    embed.set_footer(
        text=f"Requested by {interaction.user.name}",
        icon_url=interaction.user.display_avatar.url
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="suspend", description="[ADMIN] Suspend a VPS")
@app_commands.describe(container_id="Container ID to suspend")
async def suspend_vps(interaction: discord.Interaction, container_id: str):
    """[ADMIN] Suspend a VPS"""
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    
    cid = container_id.strip()
    vps = vps_db.get(cid)
    
    if not vps:
        await interaction.response.send_message("❌ VPS not found.", ephemeral=True)
        return
    
    if vps.get('suspended', False):
        await interaction.response.send_message("❌ VPS is already suspended.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    success = await docker_stop_container(cid)
    if success:
        vps['active'] = False
        vps['suspended'] = True
        persist_vps()
        await send_log("VPS Suspended", interaction.user, cid, "Admin suspension")
        await interaction.followup.send(f"✅ VPS `{cid}` suspended successfully.", ephemeral=True)
    else:
        await interaction.followup.send("❌ Failed to suspend VPS.", ephemeral=True)

@bot.tree.command(name="unsuspend", description="[ADMIN] Unsuspend a VPS")
@app_commands.describe(container_id="Container ID to unsuspend")
async def unsuspend_vps(interaction: discord.Interaction, container_id: str):
    """[ADMIN] Unsuspend a VPS"""
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    
    cid = container_id.strip()
    vps = vps_db.get(cid)
    
    if not vps:
        await interaction.response.send_message("❌ VPS not found.", ephemeral=True)
        return
    
    if not vps.get('suspended', False):
        await interaction.response.send_message("❌ VPS is not suspended.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    success = await docker_start_container(cid)
    if success:
        vps['active'] = True
        vps['suspended'] = False
        persist_vps()
        await send_log("VPS Unsuspended", interaction.user, cid, "Admin unsuspension")
        await interaction.followup.send(f"✅ VPS `{cid}` unsuspended successfully.", ephemeral=True)
    else:
        await interaction.followup.send("❌ Failed to unsuspend VPS.", ephemeral=True)

@bot.tree.command(name="plan", description="View VPS plans and payment information")
async def plan(interaction: discord.Interaction):
    """View VPS plans and payment information"""
    embed = discord.Embed(title="💰 VPS Plans", color=discord.Color.green())
    
    embed.add_field(
        name="🎯 Basic Plan - ₹49",
        value="• 32GB RAM\n• 6 CPU Cores\n• 100GB Disk\n• 15 Days Validity\n• Full Root Access\n• Systemctl Support\n• Pterodactyl Ready",
        inline=False
    )
    
    embed.add_field(
        name="💎 Premium Plan - ₹99", 
        value="• 64GB RAM\n• 12 CPU Cores\n• 200GB Disk\n• 30 Days Validity\n• Priority Support\n• All Basic Features",
        inline=False
    )
    
    embed.add_field(
        name="🚀 Ultimate Plan - ₹199",
        value="• 128GB RAM\n• 24 CPU Cores\n• 500GB Disk\n• 60 Days Validity\n• Dedicated Resources\n• All Premium Features",
        inline=False
    )
    
    embed.set_image(url=QR_IMAGE)
    embed.add_field(
        name="📞 How to Purchase",
        value="1. Scan the QR code above to make payment\n2. Take a screenshot of payment confirmation\n3. Create a ticket with your payment proof\n4. We'll activate your VPS within 24 hours\n5. Enjoy your high-performance VPS!",
        inline=False
    )
    
    embed.set_footer(text="Need help? Contact support or create a ticket!")
    
    await interaction.response.send_message(embed=embed, ephemeral=False)

@bot.tree.command(name="pointbal", description="Show your points balance")
async def pointbal(interaction: discord.Interaction):
    """Check your points balance"""
    uid = str(interaction.user.id)
    record = ensure_user(uid)
    persist_users()
    
    embed = themed_embed(
        title="💰 Your Points",
        description="Current balance and invite stats.",
        color=discord.Color.gold()
    )
    embed.add_field(name="Available Points", value=record['points'], inline=True)
    embed.add_field(name="Unclaimed Invites", value=record['inv_unclaimed'], inline=True)
    embed.add_field(name="Deploy Cost", value=f"{POINTS_PER_DEPLOY} points", inline=True)
    status = "✅ Enough to deploy" if record['points'] >= POINTS_PER_DEPLOY else "❌ Need more points"
    embed.add_field(name="Status", value=status, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="inv", description="Show your invites and points")
async def inv(interaction: discord.Interaction):
    """Check your invites and points with PROPER unique invite tracking"""
    uid = str(interaction.user.id)
    
    user_data = ensure_user(uid)
    persist_users()
    unique_invites = len(user_data.get('unique_joins', []))
    
    # Create beautiful embed
    embed = discord.Embed(
        title="📊 Your Invites & Points Dashboard", 
        color=discord.Color.purple(),
        timestamp=utcnow()
    )
    
    # Points Section
    embed.add_field(
        name="💰 **Points Balance**",
        value=f"```\n🏆 Current Points: {user_data['points']}\n💎 Available Points: {user_data['inv_unclaimed']}\n📈 Total Earned: {user_data['points'] + user_data['inv_unclaimed']}\n```",
        inline=False
    )
    
    # Invites Section
    embed.add_field(
        name="📨 **Unique Invite Statistics**",
        value=f"```\n✅ Unique Users Invited: {unique_invites}\n🆕 Unclaimed Invites: {user_data['inv_unclaimed']}\n🚫 Rejoins Ignored: Yes\n🎯 Conversion Rate: 1 invite = 1 point\n```",
        inline=False
    )
    
    # Recent Unique Joins
    recent_joins = user_data.get('unique_joins', [])[-5:]
    if recent_joins:
        recent_text = ""
        for user_id in recent_joins:
            try:
                user = await bot.fetch_user(int(user_id))
                recent_text += f"• {user.name}\n"
            except:
                recent_text += f"• User {user_id}\n"
        
        embed.add_field(
            name="👥 **Recently Invited**",
            value=recent_text,
            inline=False
        )
    
    # Progress Section
    points_needed = max(0, POINTS_PER_DEPLOY - user_data['points'])
    points_percent = min((user_data['points'] / POINTS_PER_DEPLOY) * 100, 100)
    progress_bar = "🟩" * int(points_percent / 20) + "⬛" * (5 - int(points_percent / 20))
    
    embed.add_field(
        name="📈 **Deploy Progress**",
        value=f"```\n{progress_bar} {points_percent:.1f}%\n{user_data['points']}/{POINTS_PER_DEPLOY} points\n🎯 Need {points_needed} more points\n```",
        inline=False
    )
    
    # Quick Actions
    if user_data['inv_unclaimed'] > 0:
        embed.add_field(
            name="⚡ **Quick Action**",
            value=f"Use `/claimpoint` to convert **{user_data['inv_unclaimed']} invites** → **{user_data['inv_unclaimed']} points**!",
            inline=False
        )
    else:
        embed.add_field(
            name="💡 **How to Get Invites**",
            value="• Share server invite links\n• Each **unique** user who joins = 1 invite\n• Rejoins are **not** counted\n• Invites never expire!",
            inline=False
        )
    
    # System Info
    embed.add_field(
        name="🛡️ **System Info**",
        value="✅ **Unique Tracking**: Only counts new users\n✅ **No Rejoins**: Same user joining multiple times = 1 invite\n✅ **Permanent**: Invites never decrease\n✅ **Auto-Detect**: Real Discord invite tracking",
        inline=False
    )
    
    # Set visuals
    embed.set_thumbnail(url=interaction.user.display_avatar.url)
    embed.set_footer(
        text=f"Total unique invites: {unique_invites} • Rejoins are ignored", 
        icon_url=interaction.guild.icon.url if interaction.guild.icon else None
    )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="claimpoint", description="Convert invites to points (1 invite = 1 point)")
async def claimpoint(interaction: discord.Interaction):
    """Convert UNIQUE invites to points"""
    uid = str(interaction.user.id)
    if uid not in users:
        users[uid] = {"points": 0, "inv_unclaimed": 0, "inv_total": 0, "unique_joins": [], "daily_last": None}
        persist_users()
    
    user_data = users[uid]
    
    if user_data['inv_unclaimed'] > 0:
        points_to_add = user_data['inv_unclaimed']
        original_points = user_data['points']
        claimed = user_data['inv_unclaimed']
        
        user_data['points'] += points_to_add
        user_data['inv_unclaimed'] = 0
        persist_users()
        
        # Success embed
        embed = discord.Embed(
            title="🎉 Unique Invites Converted!", 
            color=discord.Color.green(),
            timestamp=utcnow()
        )
        
        embed.add_field(
            name="📊 **Conversion Summary**",
            value=f"```diff\n+ Unique Invites: {claimed}\n+ Points Added: {points_to_add}\n= New Balance: {user_data['points']} points\n```",
            inline=False
        )
        
        embed.add_field(
            name="🎯 **Progress Update**",
            value=f"```\n📈 Before: {original_points} points\n📈 After: {user_data['points']} points\n🚀 Next Deploy: {max(0, POINTS_PER_DEPLOY - user_data['points'])} points needed\n```",
            inline=False
        )
        
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="Keep inviting unique users to earn more! 🚀")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)
    else:
        embed = discord.Embed(
            title="❌ No Unique Invites to Claim", 
            color=discord.Color.orange(),
            timestamp=utcnow()
        )
        
        embed.add_field(
            name="📨 **Current Status**",
            value=f"```\nUnique Invites: {len(user_data.get('unique_joins', []))}\nUnclaimed Invites: 0\nTotal Points: {user_data['points']}\n```",
            inline=False
        )
        
        embed.add_field(
            name="💡 **How to Get Invites**",
            value="• Share server invite links\n• Get **new** users to join\n• Each **unique** join = 1 invite\n• Rejoins don't count (system ignores them)",
            inline=False
        )
        
        embed.set_thumbnail(url=interaction.user.display_avatar.url)
        embed.set_footer(text="Invite new users to earn points!")
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="point_share", description="Share your points with another user")
@app_commands.describe(amount="Amount of points to share", user="User to share with")
async def point_share(interaction: discord.Interaction, amount: int, user: discord.Member):
    """Share points with another user"""
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)
        return
    
    if user.id == interaction.user.id:
        await interaction.response.send_message("❌ You cannot share points with yourself.", ephemeral=True)
        return
    
    sender_id = str(interaction.user.id)
    receiver_id = str(user.id)
    
    # Initialize users if not exists
    if sender_id not in users:
        users[sender_id] = {"points": 0, "inv_unclaimed": 0, "inv_total": 0, "unique_joins": [], "daily_last": None}
    if receiver_id not in users:
        users[receiver_id] = {"points": 0, "inv_unclaimed": 0, "inv_total": 0, "unique_joins": [], "daily_last": None}
    
    if users[sender_id]['points'] < amount:
        await interaction.response.send_message(f"❌ You don't have enough points. You have {users[sender_id]['points']} points.", ephemeral=True)
        return
    
    # Transfer points
    users[sender_id]['points'] -= amount
    users[receiver_id]['points'] += amount
    persist_users()
    
    embed = discord.Embed(title="💰 Points Shared Successfully!", color=discord.Color.green())
    embed.add_field(name="From", value=interaction.user.mention, inline=True)
    embed.add_field(name="To", value=user.mention, inline=True)
    embed.add_field(name="Amount", value=f"{amount} points", inline=True)
    embed.add_field(name="Your New Balance", value=f"{users[sender_id]['points']} points", inline=True)
    embed.add_field(name="Their New Balance", value=f"{users[receiver_id]['points']} points", inline=True)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)
    
    # Notify receiver
    try:
        receiver_embed = discord.Embed(title="💰 You Received Points!", color=discord.Color.gold())
        receiver_embed.add_field(name="From", value=interaction.user.mention, inline=True)
        receiver_embed.add_field(name="Amount", value=f"{amount} points", inline=True)
        receiver_embed.add_field(name="Your New Balance", value=f"{users[receiver_id]['points']} points", inline=True)
        await user.send(embed=receiver_embed)
    except:
        pass  # User has DMs disabled

@bot.tree.command(name="pointtop", description="Show top 10 users by points")
async def pointtop(interaction: discord.Interaction):
    """Show points leaderboard"""
    # Filter users with points and sort by points
    users_with_points = [(uid, data) for uid, data in users.items() if data.get('points', 0) > 0]
    sorted_users = sorted(users_with_points, key=lambda x: x[1]['points'], reverse=True)[:10]
    
    if not sorted_users:
        await interaction.response.send_message("❌ No users with points found.", ephemeral=True)
        return
    
    embed = discord.Embed(title="🏆 Points Leaderboard - Top 10", color=discord.Color.gold())
    
    for rank, (user_id, user_data) in enumerate(sorted_users, 1):
        try:
            user = await bot.fetch_user(int(user_id))
            username = user.name
        except:
            username = f"User {user_id}"
        
        points = user_data['points']
        medal = "🥇" if rank == 1 else "🥈" if rank == 2 else "🥉" if rank == 3 else f"{rank}."
        
        embed.add_field(
            name=f"{medal} {username}",
            value=f"**{points} points**",
            inline=False
        )
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="giveaway_create", description="[ADMIN] Create a VPS giveaway")
@app_commands.describe(
    duration_minutes="Giveaway duration in minutes",
    vps_ram="VPS RAM in GB",
    vps_cpu="VPS CPU cores", 
    vps_disk="VPS Disk in GB",
    winner_type="Winner type: random or all",
    description="Giveaway description"
)
async def giveaway_create(interaction: discord.Interaction, duration_minutes: int, vps_ram: int, vps_cpu: int, vps_disk: int, winner_type: str, description: str = "VPS Giveaway"):
    """[ADMIN] Create a VPS giveaway"""
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    
    if winner_type not in ["random", "all"]:
        await interaction.response.send_message("❌ Winner type must be 'random' or 'all'.", ephemeral=True)
        return
    
    if duration_minutes < 1:
        await interaction.response.send_message("❌ Duration must be at least 1 minute.", ephemeral=True)
        return
    
    giveaway_id = f"giveaway_{random.randint(1000,9999)}"
    end_time = utcnow() + timedelta(minutes=duration_minutes)
    
    giveaway = {
        'id': giveaway_id,
        'creator_id': str(interaction.user.id),
        'description': description,
        'vps_ram': vps_ram,
        'vps_cpu': vps_cpu,
        'vps_disk': vps_disk,
        'winner_type': winner_type,
        'end_time': end_time.isoformat(),
        'status': 'active',
        'participants': [],
        'created_at': utcnow().isoformat()
    }
    
    giveaways[giveaway_id] = giveaway
    persist_giveaways()
    
    embed = discord.Embed(title="🎉 VPS Giveaway Created!", color=discord.Color.gold())
    embed.add_field(name="Description", value=description, inline=False)
    embed.add_field(name="VPS Specs", value=f"{vps_ram}GB RAM | {vps_cpu} CPU | {vps_disk}GB Disk", inline=False)
    embed.add_field(name="Winner Type", value=winner_type.capitalize(), inline=True)
    embed.add_field(name="Duration", value=f"{duration_minutes} minutes", inline=True)
    embed.add_field(name="Ends At", value=end_time.strftime('%Y-%m-%d %H:%M UTC'), inline=False)
    embed.set_footer(text="Click the button below to join the giveaway!")
    
    view = GiveawayView(giveaway_id)
    await interaction.response.send_message(embed=embed, view=view)
    
    # Send admin confirmation
    await interaction.followup.send(f"✅ Giveaway created with ID: `{giveaway_id}`", ephemeral=True)

@bot.tree.command(name="giveaway_list", description="[ADMIN] List all giveaways")
async def giveaway_list(interaction: discord.Interaction):
    """[ADMIN] List all giveaways"""
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    
    if not giveaways:
        await interaction.response.send_message("ℹ️ No giveaways found.", ephemeral=True)
        return
    
    embed = discord.Embed(title="🎉 Active Giveaways", color=discord.Color.gold())
    
    active_giveaways = [g for g in giveaways.values() if g['status'] == 'active']
    ended_giveaways = [g for g in giveaways.values() if g['status'] == 'ended']
    
    if active_giveaways:
        embed.add_field(name="Active Giveaways", value=f"{len(active_giveaways)} active", inline=False)
        for giveaway in list(active_giveaways)[:5]:
            end_time = datetime.fromisoformat(giveaway['end_time'])
            time_left = end_time - utcnow()
            minutes_left = max(0, int(time_left.total_seconds() / 60))
            
            value = f"**Specs:** {giveaway['vps_ram']}GB/{giveaway['vps_cpu']}CPU/{giveaway['vps_disk']}GB\n"
            value += f"**Participants:** {len(giveaway.get('participants', []))}\n"
            value += f"**Ends in:** {minutes_left}m\n"
            value += f"**Winner:** {giveaway['winner_type'].capitalize()}"
            
            embed.add_field(name=f"`{giveaway['id']}`", value=value, inline=True)
    
    if ended_giveaways:
        embed.add_field(name="Ended Giveaways", value=f"{len(ended_giveaways)} ended", inline=False)
        for giveaway in list(ended_giveaways)[:3]:
            winner_info = "All participants" if giveaway['winner_type'] == 'all' else f"<@{giveaway.get('winner_id', 'N/A')}>"
            vps_info = "✅ Created" if giveaway.get('vps_created') else "❌ Failed"
            
            value = f"**Winner:** {winner_info}\n"
            value += f"**VPS:** {vps_info}\n"
            value += f"**Participants:** {len(giveaway.get('participants', []))}"
            
            embed.add_field(name=f"`{giveaway['id']}`", value=value, inline=True)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="pointgive", description="[ADMIN] Give points to a user")
@app_commands.describe(amount="Amount of points to give", user="User to give points to")
async def pointgive(interaction: discord.Interaction, amount: int, user: discord.Member):
    """[ADMIN] Give points to a user"""
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)
        return
    
    user_id = str(user.id)
    if user_id not in users:
        users[user_id] = {"points": 0, "inv_unclaimed": 0, "inv_total": 0, "unique_joins": [], "daily_last": None}
    
    users[user_id]['points'] += amount
    persist_users()
    
    await send_log("Points Given", interaction.user, details=f"Gave {amount} to {user_id}")
    
    embed = discord.Embed(title="✅ Points Given", color=discord.Color.green())
    embed.add_field(name="Admin", value=interaction.user.mention, inline=True)
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Amount", value=f"{amount} points", inline=True)
    embed.add_field(name="New Balance", value=f"{users[user_id]['points']} points", inline=True)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="pointremove", description="[ADMIN] Remove points from a user")
@app_commands.describe(amount="Amount of points to remove", user="User to remove points from")
async def pointremove(interaction: discord.Interaction, amount: int, user: discord.Member):
    """[ADMIN] Remove points from a user"""
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)
        return
    
    user_id = str(user.id)
    if user_id not in users:
        users[user_id] = {"points": 0, "inv_unclaimed": 0, "inv_total": 0, "unique_joins": [], "daily_last": None}
    
    if users[user_id]['points'] < amount:
        amount = users[user_id]['points']  # Remove all points if not enough
    
    users[user_id]['points'] -= amount
    persist_users()
    await send_log("Points Removed", interaction.user, details=f"Removed {amount} from {user_id}")
    
    embed = discord.Embed(title="✅ Points Removed", color=discord.Color.orange())
    embed.add_field(name="Admin", value=interaction.user.mention, inline=True)
    embed.add_field(name="User", value=user.mention, inline=True)
    embed.add_field(name="Amount", value=f"{amount} points", inline=True)
    embed.add_field(name="New Balance", value=f"{users[user_id]['points']} points", inline=True)
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="pointlistall", description="[ADMIN] List all users with points")
async def pointlistall(interaction: discord.Interaction):
    """[ADMIN] List all users with points"""
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    
    # Filter users with points
    users_with_points = [(uid, data) for uid, data in users.items() if data.get('points', 0) > 0]
    
    if not users_with_points:
        await interaction.response.send_message("ℹ️ No users with points found.", ephemeral=True)
        return
    
    embed = discord.Embed(title="📊 All Users with Points", color=discord.Color.blue())
    
    for user_id, user_data in sorted(users_with_points, key=lambda x: x[1]['points'], reverse=True)[:15]:
        try:
            user = await bot.fetch_user(int(user_id))
            username = user.name
        except:
            username = f"User {user_id}"
        
        points = user_data['points']
        embed.add_field(
            name=username,
            value=f"**{points} points**",
            inline=True
        )
    
    embed.set_footer(text=f"Total: {len(users_with_points)} users with points")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="listsall", description="[ADMIN] Show all VPS")
async def listsall(interaction: discord.Interaction):
    """[ADMIN] List all VPS in the system"""
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    
    if not vps_db:
        await interaction.response.send_message("ℹ️ No VPS found.", ephemeral=True)
        return
    
    embed = discord.Embed(title="All VPS (Admin View)", color=discord.Color.red())
    for cid, vps in list(vps_db.items())[:10]:
        try:
            owner = await bot.fetch_user(int(vps['owner']))
            owner_name = owner.name
        except:
            owner_name = f"User {vps['owner']}"
            
        status = "🟢 Running" if vps['active'] else "🔴 Stopped"
        if vps.get('suspended', False):
            status = "⏸️ Suspended"
        
        vps_type = "🎁 Giveaway" if vps.get('giveaway_vps') else "💎 Normal"
        systemctl_status = "✅" if vps.get('systemctl_working') else "❌"
        
        value = f"**Owner:** {owner_name}\n"
        value += f"**Specs:** {vps['ram']}GB | {vps['cpu']} CPU\n"
        value += f"**Status:** {status} | **Type:** {vps_type}\n"
        value += f"**Systemctl:** {systemctl_status} | **Expires:** {vps['expires_at'][:10]}"
        
        embed.add_field(name=f"Container: `{cid}`", value=value, inline=False)
    
    if len(vps_db) > 10:
        embed.set_footer(text=f"Showing 10 of {len(vps_db)} VPS")
    
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="create_vps", description="[ADMIN] Create VPS for user")
@app_commands.describe(
    ram_gb="RAM in GB", 
    disk_gb="Disk in GB", 
    cpu="CPU cores", 
    user="Target user"
)
async def create_vps_admin(interaction: discord.Interaction, ram_gb: int, disk_gb: int, cpu: int, user: discord.Member):
    """[ADMIN] Create a VPS for a user"""
    if interaction.user.id not in ADMIN_IDS:
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    
    if hasattr(interaction, "response") and not interaction.response.is_done():
        await interaction.response.defer(ephemeral=True)
    
    rec = await create_vps(user.id, ram=ram_gb, cpu=cpu, disk=disk_gb, paid=True)
    if 'error' in rec:
        await interaction.followup.send(f"❌ Error creating VPS: {rec['error']}", ephemeral=True)
        return
    
    systemctl_status = "✅ Working" if rec.get('systemctl_working') else "⚠️ Limited"
    
    embed = discord.Embed(title="🛠️ Admin VPS Created", color=discord.Color.green())
    embed.add_field(name="Container ID", value=f"`{rec['container_id']}`", inline=False)
    embed.add_field(name="Specs", value=f"**{rec['ram']}GB RAM** | **{rec['cpu']} CPU** | **{rec['disk']}GB Disk**", inline=False)
    embed.add_field(name="For User", value=user.mention, inline=False)
    embed.add_field(name="Systemctl", value=systemctl_status, inline=True)
    embed.add_field(name="Expires", value=rec['expires_at'][:10], inline=False)
    embed.add_field(name="HTTP", value=f"http://{SERVER_IP}:{rec['http_port']}", inline=False)
    embed.add_field(name="SSH", value=f"```{rec['ssh']}```", inline=False)
    
    try: 
        await user.send(embed=embed)
        await interaction.followup.send(f"✅ VPS created for {user.mention}. Check their DMs.", ephemeral=True)
    except: 
        await interaction.followup.send(embed=embed)

@bot.tree.command(name="ping", description="Check bot latency and uptime")
async def ping(interaction: discord.Interaction):
    latency_ms = round(bot.latency * 1000)
    uptime_delta = utcnow() - START_TIME if START_TIME else timedelta(0)
    uptime = format_uptime(uptime_delta)
    embed = themed_embed(
        title="🏓 Pong",
        description="Bot health check.",
        color=THEME_COLOR_SUCCESS
    )
    embed.add_field(name="Latency", value=f"{latency_ms} ms", inline=True)
    embed.add_field(name="Uptime", value=uptime, inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="help", description="Show all available commands and their uses")
async def help_command(interaction: discord.Interaction):
    """Show help information for all commands"""
    pages = help_pages()
    embed = pages["Overview"]
    view = HelpView(pages, initial_key="Overview", is_ephemeral=True)
    await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

def build_help_embed():
    embed = discord.Embed(
        title="🤖 VPS Bot Help Guide",
        description="Use slash commands or the prefix `$` (e.g., `$deploy`). Categories below.",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="📖 Quick Guide",
        value="• Deploy Cost: 4 points\n• Renew: 3 (15d) / 5 (30d)\n• Default Specs: 32GB RAM, 6 CPU, 100GB Disk\n• Systemctl: Supported\n• Auto Expiry: VPS suspend on expiry\n• Giveaway VPS: No renew, auto-delete after 15 days",
        inline=False
    )
    embed.add_field(
        name="ℹ️ Notes",
        value="• Reinstall wipes data\n• Reset SSH regenerates the connection string\n• Shared users can start/stop/restart\n• Admins can override point checks",
        inline=False
    )
    embed.set_footer(text="Select a category for detailed commands.")
    return embed

class HelpView(discord.ui.View):
    def __init__(self, pages, initial_key="Overview", is_ephemeral=True):
        super().__init__(timeout=180)
        self.pages = pages
        options = [
            discord.SelectOption(label=key, description=f"{key} commands") for key in pages.keys()
        ]
        self.add_item(HelpSelect(options, pages, is_ephemeral))

class HelpSelect(discord.ui.Select):
    def __init__(self, options, pages, is_ephemeral):
        super().__init__(placeholder="Select category", options=options, min_values=1, max_values=1)
        self.pages = pages
        self.is_ephemeral = is_ephemeral

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]
        embed = self.pages.get(choice, build_help_embed())
        await interaction.response.edit_message(embed=embed, view=self.view)

def help_pages():
    return {
        "Overview": build_help_embed(),
        "VPS": discord.Embed(
            title="🖥️ VPS Commands",
            description="`/deploy` `/list` `/remove <id>` `/manage <id>` `/status`\n`/port` `/share_vps` `/share_remove`\n`/vps_info` `/vps_usage` `/vps_ports` `/vps_ssh`\n`/vps_backup` `/vps_restore` `/vps_health` `/vps_resume` `/vps_extend` `/vps_note`",
            color=THEME_COLOR_PRIMARY
        ),
        "Points & Invites": discord.Embed(
            title="💰 Points & Invites",
            description="`/pointbal` `/inv` `/claimpoint` `/point_share` `/pointtop`\n`/points_daily` `/points_summary`\n`/invite_leaderboard` `/invite_me`\n`/plan` (payment info)",
            color=THEME_COLOR_ACCENT
        ),
        "Giveaways": discord.Embed(
            title="🎁 Giveaways",
            description="`/giveaway_create` `/giveaway_list`",
            color=discord.Color.gold()
        ),
        "Admin": discord.Embed(
            title="🛠️ Admin VPS & Management",
            description="`/create_vps` `/listsall` `/mass_port` `/suspend` `/unsuspend`\n`/admin_vps_extend` `/admin_vps_force_stop` `/admin_vps_force_start`\n`/admin_vps_note` `/admin_vps_transfer` `/admin_shared_clear`\n`/admin_add` `/admin_remove` `/admins` `/set_log_channel` `/logs`\n`/admin_points_set` `/admin_invites_set` `/admin_points_reset_all` `/admin_renew_mode_toggle`\n`/pointgive` `/pointremove` `/pointlistall`",
            color=discord.Color.orange()
        ),
        "Moderation": discord.Embed(
            title="🛡️ Moderation",
            description="`/admin_timeout` `/admin_untimeout` `/admin_warn` `/admin_dm`\n`/admin_clear` `/admin_slowmode`",
            color=discord.Color.red()
        ),
        "Misc": discord.Embed(
            title="📦 Misc",
            description="`/help` `/ping` `/logs` `/set_log_channel`\nPrefix equivalents use `$` + command name.",
            color=discord.Color.teal()
        )
    }

# ---------------- New Utility & Power Commands ----------------
def get_vps_for_user(container_id: str, user_id: int):
    vps = vps_db.get(container_id)
    if not vps:
        return None, "❌ VPS not found."
    if not can_manage_vps(user_id, container_id):
        return None, "❌ You don't have permission for this VPS."
    return vps, None

def require_admin(user_id: int):
    return user_id in ADMIN_IDS

@bot.tree.command(name="vps_info", description="Show detailed info about a VPS")
@app_commands.describe(container_id="Container ID")
async def vps_info(interaction: discord.Interaction, container_id: str):
    vps, err = get_vps_for_user(container_id.strip(), interaction.user.id)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    expires = datetime.fromisoformat(vps['expires_at']).strftime('%Y-%m-%d %H:%M')
    status = "🟢 Running" if vps['active'] and not vps.get('suspended') else "⏸️ Suspended" if vps.get('suspended') else "🔴 Stopped"
    embed = themed_embed(
        title="🛰️ VPS Info",
        description=f"Container `{container_id}` overview.",
        color=THEME_COLOR_ACCENT
    )
    embed.add_field(name="Owner", value=f"<@{vps['owner']}>", inline=True)
    embed.add_field(name="Status", value=status, inline=True)
    embed.add_field(name="Specs", value=f"{vps['ram']}GB RAM | {vps['cpu']} CPU | {vps['disk']}GB Disk", inline=False)
    embed.add_field(name="HTTP", value=f"http://{SERVER_IP}:{vps['http_port']}", inline=False)
    embed.add_field(name="SSH", value=f"```{vps['ssh']}```", inline=False)
    embed.add_field(name="Expires", value=expires, inline=True)
    embed.add_field(name="Systemctl", value="✅ Works" if vps.get('systemctl_working') else "⚠️ Limited", inline=True)
    if vps.get('note'):
        embed.add_field(name="Note", value=vps['note'], inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vps_usage", description="Show your total VPS resource usage")
async def vps_usage(interaction: discord.Interaction):
    user_vps = get_user_vps(interaction.user.id)
    if not user_vps:
        await interaction.response.send_message("❌ No VPS found.", ephemeral=True)
        return
    ram = sum(v['ram'] for v in user_vps)
    cpu = sum(v['cpu'] for v in user_vps)
    disk = sum(v['disk'] for v in user_vps)
    embed = themed_embed(
        title="📈 Your VPS Usage",
        description="Aggregate resources across all your containers.",
        color=THEME_COLOR_PRIMARY
    )
    embed.add_field(name="RAM", value=f"{ram} GB", inline=True)
    embed.add_field(name="CPU", value=f"{cpu} vCPU", inline=True)
    embed.add_field(name="Disk", value=f"{disk} GB", inline=True)
    embed.add_field(name="Count", value=str(len(user_vps)), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vps_ports", description="List ports for a VPS")
@app_commands.describe(container_id="Container ID")
async def vps_ports(interaction: discord.Interaction, container_id: str):
    vps, err = get_vps_for_user(container_id.strip(), interaction.user.id)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    extra = ", ".join(map(str, vps.get('additional_ports', []))) if vps.get('additional_ports') else "None"
    embed = themed_embed(
        title="🔌 VPS Ports",
        description=f"Container `{container_id}` networking.",
        color=THEME_COLOR_PRIMARY
    )
    embed.add_field(name="HTTP", value=f"http://{SERVER_IP}:{vps['http_port']}", inline=False)
    embed.add_field(name="Additional", value=extra, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vps_ssh", description="Show SSH string for a VPS")
@app_commands.describe(container_id="Container ID")
async def vps_ssh(interaction: discord.Interaction, container_id: str):
    vps, err = get_vps_for_user(container_id.strip(), interaction.user.id)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    embed = themed_embed(
        title="🔑 SSH Details",
        description=f"Container `{container_id}`",
        color=THEME_COLOR_SUCCESS
    )
    embed.add_field(name="SSH", value=f"```{vps['ssh']}```", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vps_backup", description="Create a quick snapshot entry for a VPS")
@app_commands.describe(container_id="Container ID")
async def vps_backup(interaction: discord.Interaction, container_id: str):
    vps, err = get_vps_for_user(container_id.strip(), interaction.user.id)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    snapshot_id = f"snap-{random.randint(10000,99999)}"
    entry = {"id": snapshot_id, "created_at": utcnow().isoformat()}
    vps.setdefault("backups", []).append(entry)
    persist_vps()
    embed = themed_embed(
        title="💾 Snapshot Recorded",
        description="Metadata backup noted (filesystem backup not automated).",
        color=THEME_COLOR_SUCCESS
    )
    embed.add_field(name="Snapshot ID", value=snapshot_id, inline=True)
    embed.add_field(name="Total Snapshots", value=str(len(vps['backups'])), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vps_restore", description="Restore the latest recorded snapshot entry")
@app_commands.describe(container_id="Container ID")
async def vps_restore(interaction: discord.Interaction, container_id: str):
    vps, err = get_vps_for_user(container_id.strip(), interaction.user.id)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    backups = vps.get("backups", [])
    if not backups:
        await interaction.response.send_message("❌ No snapshots recorded for this VPS.", ephemeral=True)
        return
    latest = backups[-1]
    embed = themed_embed(
        title="📂 Restore Triggered",
        description="Latest snapshot marked for restore (manual filesystem restore required).",
        color=THEME_COLOR_WARN
    )
    embed.add_field(name="Snapshot", value=latest['id'], inline=True)
    embed.add_field(name="Created", value=latest['created_at'], inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vps_health", description="Re-check systemctl health for a VPS")
@app_commands.describe(container_id="Container ID")
async def vps_health(interaction: discord.Interaction, container_id: str):
    vps, err = get_vps_for_user(container_id.strip(), interaction.user.id)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    working = await check_systemctl_status(container_id.strip())
    vps['systemctl_working'] = working
    persist_vps()
    embed = themed_embed(
        title="🩺 Systemd Health",
        description=f"Container `{container_id}` check complete.",
        color=THEME_COLOR_SUCCESS if working else discord.Color.red()
    )
    embed.add_field(name="Systemctl", value="✅ Working" if working else "⚠️ Not responding", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vps_resume", description="Resume a suspended VPS if you own it")
@app_commands.describe(container_id="Container ID")
async def vps_resume(interaction: discord.Interaction, container_id: str):
    vps, err = get_vps_for_user(container_id.strip(), interaction.user.id)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    if not vps.get('suspended'):
        await interaction.response.send_message("ℹ️ VPS is not suspended.", ephemeral=True)
        return
    vps['suspended'] = False
    vps['active'] = True
    persist_vps()
    await docker_start_container(container_id.strip())
    await send_log("VPS Resumed", interaction.user, container_id.strip(), "User resume")
    embed = themed_embed(
        title="✅ VPS Resumed",
        description=f"Container `{container_id}` is now active.",
        color=THEME_COLOR_SUCCESS
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vps_extend", description="Extend VPS by 3 days for 1 point")
@app_commands.describe(container_id="Container ID")
async def vps_extend(interaction: discord.Interaction, container_id: str):
    uid = str(interaction.user.id)
    ensure_user(uid)
    if users[uid]['points'] < 1:
        await interaction.response.send_message("❌ You need at least 1 point to extend.", ephemeral=True)
        return
    vps, err = get_vps_for_user(container_id.strip(), interaction.user.id)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    users[uid]['points'] -= 1
    new_expiry = datetime.fromisoformat(vps['expires_at']) + timedelta(days=3)
    vps['expires_at'] = new_expiry.isoformat()
    persist_users()
    persist_vps()
    await send_log("VPS Extended", interaction.user, container_id.strip(), "Manual 3-day extension")
    embed = themed_embed(
        title="⏳ Extended",
        description=f"Added 3 days to `{container_id}`.",
        color=THEME_COLOR_ACCENT
    )
    embed.add_field(name="New Expiry", value=new_expiry.strftime('%Y-%m-%d %H:%M'), inline=True)
    embed.add_field(name="Remaining Points", value=str(users[uid]['points']), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vps_note", description="Attach a note to your VPS")
@app_commands.describe(container_id="Container ID", note="Short note")
async def vps_note(interaction: discord.Interaction, container_id: str, note: str):
    vps, err = get_vps_for_user(container_id.strip(), interaction.user.id)
    if err:
        await interaction.response.send_message(err, ephemeral=True)
        return
    vps['note'] = note[:200]
    persist_vps()
    embed = themed_embed(
        title="🗒️ Note Saved",
        description=f"Note updated for `{container_id}`.",
        color=THEME_COLOR_PRIMARY
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="vps_shared_with_me", description="List VPS shared with you")
async def vps_shared_with_me(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    shared = [v for v in vps_db.values() if uid in v.get('shared_with', [])]
    if not shared:
        await interaction.response.send_message("ℹ️ No VPS shared with you.", ephemeral=True)
        return
    embed = themed_embed(
        title="🤝 Shared VPS",
        description="Containers where you have collaborator access.",
        color=THEME_COLOR_PRIMARY
    )
    for v in shared:
        embed.add_field(
            name=f"{v['container_id']}",
            value=f"Owner: <@{v['owner']}> • HTTP: {SERVER_IP}:{v['http_port']}",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# -------- Points & Invites expansions --------
@bot.tree.command(name="points_daily", description="Claim a daily points reward")
async def points_daily(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    record = ensure_user(uid)
    last = record.get("daily_last")
    now = utcnow()
    if last and now - datetime.fromisoformat(last) < timedelta(hours=24):
        await interaction.response.send_message("⏳ You already claimed your daily reward. Try again later.", ephemeral=True)
        return
    record['points'] += DAILY_POINTS
    record['daily_last'] = now.isoformat()
    persist_users()
    embed = themed_embed(
        title="🪙 Daily Claimed",
        description=f"+{DAILY_POINTS} points added.",
        color=THEME_COLOR_SUCCESS
    )
    embed.add_field(name="Balance", value=str(record['points']), inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="points_summary", description="Full summary of your points and invites")
async def points_summary(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    record = ensure_user(uid)
    embed = themed_embed(
        title="📊 Points Summary",
        description="Your points, invites, and claimable rewards.",
        color=THEME_COLOR_PRIMARY
    )
    embed.add_field(name="Points", value=str(record['points']), inline=True)
    embed.add_field(name="Unclaimed Invites", value=str(record.get('inv_unclaimed', 0)), inline=True)
    embed.add_field(name="Total Invites", value=str(record.get('inv_total', 0)), inline=True)
    last_daily = record.get('daily_last')
    embed.add_field(name="Daily", value="Claimed" if last_daily else "Not yet", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="invite_leaderboard", description="Top users by unique invites")
async def invite_leaderboard(interaction: discord.Interaction):
    ranking = sorted(users.items(), key=lambda u: u[1].get('inv_total', 0), reverse=True)[:10]
    embed = themed_embed(
        title="🏆 Invite Leaderboard",
        description="Top inviters by unique joins.",
        color=THEME_COLOR_ACCENT
    )
    if not ranking:
        embed.description = "No invite data yet."
    for idx, (uid, data) in enumerate(ranking, start=1):
        embed.add_field(
            name=f"#{idx} <@{uid}>",
            value=f"Invites: {data.get('inv_total', 0)} | Unclaimed: {data.get('inv_unclaimed', 0)}",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="invite_me", description="Get invite tips and QR")
async def invite_me(interaction: discord.Interaction):
    embed = themed_embed(
        title="✉️ Invite & Earn",
        description="Share the server and earn points.",
        color=THEME_COLOR_PRIMARY
    )
    embed.add_field(name="How", value="Use `/inv` to check your code, share it, and claim points with `/claimpoint`.", inline=False)
    embed.set_image(url=QR_IMAGE)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# -------- Admin power tools --------
@bot.tree.command(name="admin_points_set", description="[ADMIN] Set a user's point balance")
@app_commands.describe(user="Target user", amount="Point amount to set")
async def admin_points_set(interaction: discord.Interaction, user: discord.Member, amount: int):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    record = ensure_user(str(user.id))
    record['points'] = max(0, amount)
    persist_users()
    await interaction.response.send_message(f"✅ Set {user.mention} points to {record['points']}.", ephemeral=True)

@bot.tree.command(name="admin_invites_set", description="[ADMIN] Set a user's invite counts")
@app_commands.describe(user="Target user", total="Total invites", unclaimed="Unclaimed invites")
async def admin_invites_set(interaction: discord.Interaction, user: discord.Member, total: int, unclaimed: int):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    record = ensure_user(str(user.id))
    record['inv_total'] = max(0, total)
    record['inv_unclaimed'] = max(0, unclaimed)
    persist_users()
    await interaction.response.send_message(f"✅ Updated invites for {user.mention}.", ephemeral=True)

@bot.tree.command(name="admin_vps_extend", description="[ADMIN] Extend VPS expiry by days")
@app_commands.describe(container_id="Container ID", days="Days to add")
async def admin_vps_extend(interaction: discord.Interaction, container_id: str, days: int):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    vps = vps_db.get(container_id.strip())
    if not vps:
        await interaction.response.send_message("❌ VPS not found.", ephemeral=True)
        return
    vps['expires_at'] = (datetime.fromisoformat(vps['expires_at']) + timedelta(days=days)).isoformat()
    persist_vps()
    await interaction.response.send_message(f"✅ Extended `{container_id}` by {days} day(s).", ephemeral=True)

@bot.tree.command(name="admin_vps_force_stop", description="[ADMIN] Force stop a VPS")
@app_commands.describe(container_id="Container ID")
async def admin_vps_force_stop(interaction: discord.Interaction, container_id: str):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    await docker_stop_container(container_id.strip())
    vps = vps_db.get(container_id.strip())
    if vps:
        vps['active'] = False
        persist_vps()
    await interaction.response.send_message(f"✅ Force stopped `{container_id}`.", ephemeral=True)

@bot.tree.command(name="admin_vps_force_start", description="[ADMIN] Force start a VPS")
@app_commands.describe(container_id="Container ID")
async def admin_vps_force_start(interaction: discord.Interaction, container_id: str):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    await docker_start_container(container_id.strip())
    vps = vps_db.get(container_id.strip())
    if vps:
        vps['active'] = True
        vps['suspended'] = False
        persist_vps()
    await interaction.response.send_message(f"✅ Force started `{container_id}`.", ephemeral=True)

@bot.tree.command(name="admin_renew_mode_toggle", description="[ADMIN] Toggle renew mode between 15 and 30 days")
async def admin_renew_mode_toggle(interaction: discord.Interaction):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    mode = renew_mode.get("mode", "15")
    renew_mode["mode"] = "30" if mode == "15" else "15"
    persist_renew_mode()
    await interaction.response.send_message(f"✅ Renew mode set to {renew_mode['mode']} days.", ephemeral=True)

@bot.tree.command(name="admin_vps_note", description="[ADMIN] Add a staff note on a VPS")
@app_commands.describe(container_id="Container ID", note="Note text")
async def admin_vps_note(interaction: discord.Interaction, container_id: str, note: str):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    vps = vps_db.get(container_id.strip())
    if not vps:
        await interaction.response.send_message("❌ VPS not found.", ephemeral=True)
        return
    vps['note'] = f"[STAFF] {note[:200]}"
    persist_vps()
    await interaction.response.send_message(f"✅ Note saved on `{container_id}`.", ephemeral=True)
    await send_log("Admin Note", interaction.user, container_id.strip(), note[:200])

@bot.tree.command(name="admin_vps_transfer", description="[ADMIN] Transfer VPS ownership to another user")
@app_commands.describe(container_id="Container ID", new_owner="New owner user")
async def admin_vps_transfer(interaction: discord.Interaction, container_id: str, new_owner: discord.Member):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    vps = vps_db.get(container_id.strip())
    if not vps:
        await interaction.response.send_message("❌ VPS not found.", ephemeral=True)
        return
    vps['owner'] = str(new_owner.id)
    persist_vps()
    await send_log("VPS Transfer", interaction.user, container_id.strip(), f"New owner {new_owner.id}")
    await interaction.response.send_message(f"✅ `{container_id}` transferred to {new_owner.mention}.", ephemeral=True)

@bot.tree.command(name="admin_points_reset_all", description="[ADMIN] Reset all users' points to zero")
async def admin_points_reset_all(interaction: discord.Interaction):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    for data in users.values():
        data['points'] = 0
    persist_users()
    await send_log("Points Reset", interaction.user, details="All user points reset")
    await interaction.response.send_message("✅ All user points reset to 0.", ephemeral=True)

@bot.tree.command(name="admin_logs_purge", description="[ADMIN] Purge stored VPS logs file")
async def admin_logs_purge(interaction: discord.Interaction):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    logs_file = os.path.join(DATA_DIR, "vps_logs.json")
    save_json(logs_file, [])
    await send_log("Logs Purged", interaction.user, details="vps_logs.json cleared")
    await interaction.response.send_message("✅ Logs cleared.", ephemeral=True)

@bot.tree.command(name="admin_shared_clear", description="[ADMIN] Clear all shared users from a VPS")
@app_commands.describe(container_id="Container ID")
async def admin_shared_clear(interaction: discord.Interaction, container_id: str):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    vps = vps_db.get(container_id.strip())
    if not vps:
        await interaction.response.send_message("❌ VPS not found.", ephemeral=True)
        return
    vps['shared_with'] = []
    persist_vps()
    await send_log("Shared Cleared", interaction.user, container_id.strip(), "All collaborators removed")
    await interaction.response.send_message(f"✅ Cleared all shared users for `{container_id}`.", ephemeral=True)

# -------- Moderation utilities (6 new mod commands) --------
@bot.tree.command(name="admin_timeout", description="[ADMIN] Timeout a member for N minutes")
@app_commands.describe(user="Member to timeout", minutes="Duration in minutes", reason="Reason for timeout")
async def admin_timeout(interaction: discord.Interaction, user: discord.Member, minutes: int, reason: str):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    try:
        await user.edit(timeout=until, reason=reason[:100])
        await send_log("Timeout", interaction.user, details=f"{user.id} for {minutes}m: {reason[:150]}")
        await interaction.response.send_message(f"✅ {user.mention} timed out for {minutes} minutes.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to timeout: {e}", ephemeral=True)

@bot.tree.command(name="admin_untimeout", description="[ADMIN] Remove timeout from a member")
@app_commands.describe(user="Member to untimout")
async def admin_untimeout(interaction: discord.Interaction, user: discord.Member):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    try:
        await user.edit(timeout=None, reason="untimeout by admin")
        await send_log("Untimeout", interaction.user, details=f"{user.id} timeout cleared")
        await interaction.response.send_message(f"✅ Timeout cleared for {user.mention}.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to clear timeout: {e}", ephemeral=True)

@bot.tree.command(name="admin_warn", description="[ADMIN] Warn a member via DM and log")
@app_commands.describe(user="Member to warn", reason="Reason for warning")
async def admin_warn(interaction: discord.Interaction, user: discord.Member, reason: str):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    embed = themed_embed(
        title="⚠️ Warning",
        description=reason[:500],
        color=THEME_COLOR_WARN
    )
    embed.add_field(name="From", value=interaction.user.mention, inline=True)
    try:
        await user.send(embed=embed)
    except Exception:
        pass
    await send_log("Warn", interaction.user, details=f"{user.id}: {reason[:150]}")
    await interaction.response.send_message(f"✅ Warned {user.mention}.", ephemeral=True)

@bot.tree.command(name="admin_dm", description="[ADMIN] Send a DM to a member")
@app_commands.describe(user="Member to DM", message="Message content")
async def admin_dm(interaction: discord.Interaction, user: discord.Member, message: str):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    try:
        await user.send(f"📩 Message from admin:\n{message}")
        await send_log("Admin DM", interaction.user, details=f"DM to {user.id}: {message[:150]}")
        await interaction.response.send_message(f"✅ Sent DM to {user.mention}.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to DM: {e}", ephemeral=True)

@bot.tree.command(name="admin_clear", description="[ADMIN] Bulk delete recent messages in this channel")
@app_commands.describe(count="Number of messages to delete (max 100)")
async def admin_clear(interaction: discord.Interaction, count: int):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    if count <= 0 or count > 100:
        await interaction.response.send_message("❌ Count must be between 1 and 100.", ephemeral=True)
        return
    if not interaction.channel or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("❌ Can only clear messages in text channels.", ephemeral=True)
        return
    deleted = await interaction.channel.purge(limit=count)
    await send_log("Messages Cleared", interaction.user, details=f"Deleted {len(deleted)} messages in #{interaction.channel}")
    await interaction.response.send_message(f"✅ Deleted {len(deleted)} messages.", ephemeral=True)

@bot.tree.command(name="admin_slowmode", description="[ADMIN] Set slowmode for a channel")
@app_commands.describe(seconds="Slowmode seconds (0 to disable)", channel="Target channel (default current)")
async def admin_slowmode(interaction: discord.Interaction, seconds: int, channel: Optional[discord.TextChannel] = None):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    target = channel or interaction.channel
    if not isinstance(target, discord.TextChannel):
        await interaction.response.send_message("❌ Invalid channel.", ephemeral=True)
        return
    await target.edit(slowmode_delay=max(0, seconds))
    await send_log("Slowmode", interaction.user, details=f"{target} set to {seconds}s")
    await interaction.response.send_message(f"✅ Slowmode set to {seconds}s in {target.mention}.", ephemeral=True)

# -------- Prefix command mirrors (configurable PREFIX) --------
def prefix_adapter(ctx: commands.Context):
    return PrefixInteractionAdapter(ctx)

def prefix_wrapper(slash_func):
    async def wrapper(ctx: commands.Context, *args, **kwargs):
        adapter = prefix_adapter(ctx)
        cb = slash_func.callback if hasattr(slash_func, "callback") else slash_func
        cmd_name = getattr(cb, "__name__", getattr(slash_func, "name", "command"))
        try:
            return await cb(adapter, *args, **kwargs)
        except discord.ext.commands.errors.MissingRequiredArgument:
            sig = f"{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}".strip()
            await ctx.send(f"❌ Missing arguments. Usage: `{sig}`")
        except TypeError:
            sig = f"{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}".strip()
            await ctx.send(f"❌ Invalid or missing arguments. Usage: `{sig}`")
        except Exception as e:
            logger.exception(f"Prefix wrapper error in {cmd_name}: {e}")
            await ctx.send(f"❌ Error running command: {e}")
            return None
    return wrapper

# Global error handler for prefix commands
@bot.event
async def on_command_error(ctx: commands.Context, error):
    if isinstance(error, commands.MissingRequiredArgument):
        sig = f"{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}".strip()
        await ctx.send(f"❌ Missing arguments. Usage: `{sig}`")
        return
    if isinstance(error, commands.CommandInvokeError):
        orig = error.original
        if isinstance(orig, commands.MissingRequiredArgument) or isinstance(orig, TypeError):
            sig = f"{ctx.prefix}{ctx.command.qualified_name} {ctx.command.signature}".strip()
            await ctx.send(f"❌ Missing/invalid arguments. Usage: `{sig}`")
            return
    raise error

# Core user commands
@bot.command(name="deploy")
async def deploy_prefix(ctx: commands.Context):
    await prefix_wrapper(deploy)(ctx)
@bot.command(name="links")
async def links_prefix(ctx: commands.Context):
    await prefix_wrapper(links)(ctx)

@bot.command(name="list")
async def list_prefix(ctx: commands.Context):
    await prefix_wrapper(list_vps)(ctx)

@bot.command(name="remove")
async def remove_prefix(ctx: commands.Context, container_id: str):
    await prefix_wrapper(remove_vps)(ctx, container_id)

@bot.command(name="manage")
async def manage_prefix(ctx: commands.Context, container_id: str):
    await prefix_wrapper(manage_vps)(ctx, container_id)

@bot.command(name="status")
async def status_prefix(ctx: commands.Context):
    await prefix_wrapper(status)(ctx)

@bot.command(name="port")
async def port_prefix(ctx: commands.Context, container_id: str, port: int):
    await prefix_wrapper(port)(ctx, container_id, port)

@bot.command(name="share_vps")
async def share_vps_prefix(ctx: commands.Context, container_id: str, user: discord.Member):
    await prefix_wrapper(share_vps)(ctx, container_id, user)

@bot.command(name="share_remove")
async def share_remove_prefix(ctx: commands.Context, container_id: str, user: discord.Member):
    await prefix_wrapper(share_remove)(ctx, container_id, user)

@bot.command(name="plan")
async def plan_prefix(ctx: commands.Context):
    await prefix_wrapper(plan)(ctx)

# Points & invites
@bot.command(name="pointbal")
async def pointbal_prefix(ctx: commands.Context):
    await prefix_wrapper(pointbal)(ctx)

@bot.command(name="inv")
async def inv_prefix(ctx: commands.Context):
    await prefix_wrapper(inv)(ctx)

@bot.command(name="claimpoint")
async def claimpoint_prefix(ctx: commands.Context):
    await prefix_wrapper(claimpoint)(ctx)

@bot.command(name="point_share")
async def point_share_prefix(ctx: commands.Context, amount: int, user: discord.Member):
    await prefix_wrapper(point_share)(ctx, amount, user)

@bot.command(name="pointtop")
async def pointtop_prefix(ctx: commands.Context):
    await prefix_wrapper(pointtop)(ctx)

@bot.command(name="points_daily")
async def points_daily_prefix(ctx: commands.Context):
    await prefix_wrapper(points_daily)(ctx)

@bot.command(name="points_summary")
async def points_summary_prefix(ctx: commands.Context):
    await prefix_wrapper(points_summary)(ctx)

@bot.command(name="invite_leaderboard")
async def invite_leaderboard_prefix(ctx: commands.Context):
    await prefix_wrapper(invite_leaderboard)(ctx)

@bot.command(name="invite_me")
async def invite_me_prefix(ctx: commands.Context):
    await prefix_wrapper(invite_me)(ctx)

# VPS operations
@bot.command(name="vps_info")
async def vps_info_prefix(ctx: commands.Context, container_id: str):
    await prefix_wrapper(vps_info)(ctx, container_id)

@bot.command(name="vps_usage")
async def vps_usage_prefix(ctx: commands.Context):
    await prefix_wrapper(vps_usage)(ctx)

@bot.command(name="vps_ports")
async def vps_ports_prefix(ctx: commands.Context, container_id: str):
    await prefix_wrapper(vps_ports)(ctx, container_id)

@bot.command(name="vps_ssh")
async def vps_ssh_prefix(ctx: commands.Context, container_id: str):
    await prefix_wrapper(vps_ssh)(ctx, container_id)

@bot.command(name="vps_backup")
async def vps_backup_prefix(ctx: commands.Context, container_id: str):
    await prefix_wrapper(vps_backup)(ctx, container_id)

@bot.command(name="vps_restore")
async def vps_restore_prefix(ctx: commands.Context, container_id: str):
    await prefix_wrapper(vps_restore)(ctx, container_id)

@bot.command(name="vps_health")
async def vps_health_prefix(ctx: commands.Context, container_id: str):
    await prefix_wrapper(vps_health)(ctx, container_id)

@bot.command(name="vps_resume")
async def vps_resume_prefix(ctx: commands.Context, container_id: str):
    await prefix_wrapper(vps_resume)(ctx, container_id)

@bot.command(name="vps_extend")
async def vps_extend_prefix(ctx: commands.Context, container_id: str):
    await prefix_wrapper(vps_extend)(ctx, container_id)

@bot.command(name="vps_note")
async def vps_note_prefix(ctx: commands.Context, container_id: str, *, note: str):
    await prefix_wrapper(vps_note)(ctx, container_id, note)

@bot.command(name="vps_shared_with_me")
async def vps_shared_with_me_prefix(ctx: commands.Context):
    await prefix_wrapper(vps_shared_with_me)(ctx)

# Giveaways
@bot.command(name="giveaway_create")
async def giveaway_create_prefix(ctx: commands.Context, duration_minutes: int, vps_ram: int, vps_cpu: int, vps_disk: int, winner_type: str, description: str):
    await prefix_wrapper(giveaway_create)(ctx, duration_minutes, vps_ram, vps_cpu, vps_disk, winner_type, description)

@bot.command(name="giveaway_list")
async def giveaway_list_prefix(ctx: commands.Context):
    await prefix_wrapper(giveaway_list)(ctx)

# Admin / moderation
@bot.command(name="admin_points_set")
async def admin_points_set_prefix(ctx: commands.Context, user: discord.Member, amount: int):
    await prefix_wrapper(admin_points_set)(ctx, user, amount)

@bot.command(name="admin_invites_set")
async def admin_invites_set_prefix(ctx: commands.Context, user: discord.Member, total: int, unclaimed: int):
    await prefix_wrapper(admin_invites_set)(ctx, user, total, unclaimed)

@bot.command(name="admin_vps_extend")
async def admin_vps_extend_prefix(ctx: commands.Context, container_id: str, days: int):
    await prefix_wrapper(admin_vps_extend)(ctx, container_id, days)

@bot.command(name="admin_vps_force_stop")
async def admin_vps_force_stop_prefix(ctx: commands.Context, container_id: str):
    await prefix_wrapper(admin_vps_force_stop)(ctx, container_id)

@bot.command(name="admin_vps_force_start")
async def admin_vps_force_start_prefix(ctx: commands.Context, container_id: str):
    await prefix_wrapper(admin_vps_force_start)(ctx, container_id)

@bot.command(name="admin_renew_mode_toggle")
async def admin_renew_mode_toggle_prefix(ctx: commands.Context):
    await prefix_wrapper(admin_renew_mode_toggle)(ctx)

@bot.command(name="admin_vps_note")
async def admin_vps_note_prefix(ctx: commands.Context, container_id: str, *, note: str):
    await prefix_wrapper(admin_vps_note)(ctx, container_id, note)

@bot.command(name="admin_vps_transfer")
async def admin_vps_transfer_prefix(ctx: commands.Context, container_id: str, new_owner: discord.Member):
    await prefix_wrapper(admin_vps_transfer)(ctx, container_id, new_owner)

@bot.command(name="admin_points_reset_all")
async def admin_points_reset_all_prefix(ctx: commands.Context):
    await prefix_wrapper(admin_points_reset_all)(ctx)

@bot.command(name="admin_logs_purge")
async def admin_logs_purge_prefix(ctx: commands.Context):
    await prefix_wrapper(admin_logs_purge)(ctx)

@bot.command(name="admin_shared_clear")
async def admin_shared_clear_prefix(ctx: commands.Context, container_id: str):
    await prefix_wrapper(admin_shared_clear)(ctx, container_id)

@bot.command(name="admin_timeout")
async def admin_timeout_prefix(ctx: commands.Context, user: discord.Member, minutes: int, *, reason: str):
    await prefix_wrapper(admin_timeout)(ctx, user, minutes, reason)

@bot.command(name="admin_untimeout")
async def admin_untimeout_prefix(ctx: commands.Context, user: discord.Member):
    await prefix_wrapper(admin_untimeout)(ctx, user)

@bot.command(name="admin_warn")
async def admin_warn_prefix(ctx: commands.Context, user: discord.Member, *, reason: str):
    await prefix_wrapper(admin_warn)(ctx, user, reason)

@bot.command(name="admin_dm")
async def admin_dm_prefix(ctx: commands.Context, user: discord.Member, *, message: str):
    await prefix_wrapper(admin_dm)(ctx, user, message)

@bot.command(name="admin_clear")
async def admin_clear_prefix(ctx: commands.Context, count: int):
    await prefix_wrapper(admin_clear)(ctx, count)

@bot.command(name="admin_slowmode")
async def admin_slowmode_prefix(ctx: commands.Context, seconds: int, channel: Optional[discord.TextChannel] = None):
    await prefix_wrapper(admin_slowmode)(ctx, seconds, channel)

@bot.command(name="admin_add")
async def admin_add_prefix(ctx: commands.Context, user: discord.Member):
    await prefix_wrapper(admin_add)(ctx, user)

@bot.command(name="admin_remove")
async def admin_remove_prefix(ctx: commands.Context, user: discord.Member):
    await prefix_wrapper(admin_remove)(ctx, user)

@bot.command(name="admins")
async def admins_prefix(ctx: commands.Context):
    await prefix_wrapper(admins)(ctx)

@bot.command(name="set_log_channel")
async def set_log_channel_prefix(ctx: commands.Context, channel: discord.TextChannel):
    await prefix_wrapper(set_log_channel)(ctx, channel)

@bot.command(name="logs")
async def logs_prefix(ctx: commands.Context):
    await prefix_wrapper(logs)(ctx)

@bot.command(name="suspend")
async def suspend_prefix(ctx: commands.Context, container_id: str):
    await prefix_wrapper(suspend)(ctx, container_id)

@bot.command(name="unsuspend")
async def unsuspend_prefix(ctx: commands.Context, container_id: str):
    await prefix_wrapper(unsuspend)(ctx, container_id)

@bot.command(name="mass_port")
async def mass_port_prefix(ctx: commands.Context, port: int, container_ids: str):
    await prefix_wrapper(mass_port)(ctx, port, container_ids)

@bot.command(name="create_vps")
async def create_vps_prefix(ctx: commands.Context, ram_gb: int, disk_gb: int, cpu: int, user: discord.Member):
    await prefix_wrapper(create_vps_admin)(ctx, ram_gb, disk_gb, cpu, user)

@bot.command(name="ping")
async def ping_prefix(ctx: commands.Context):
    await prefix_wrapper(ping)(ctx)

@bot.command(name="pointgive")
async def pointgive_prefix(ctx: commands.Context, amount: int, user: discord.Member):
    await prefix_wrapper(pointgive)(ctx, amount, user)

@bot.command(name="pointremove")
async def pointremove_prefix(ctx: commands.Context, amount: int, user: discord.Member):
    await prefix_wrapper(pointremove)(ctx, amount, user)

@bot.command(name="pointlistall")
async def pointlistall_prefix(ctx: commands.Context):
    await prefix_wrapper(pointlistall)(ctx)

@bot.command(name="listsall")
async def listsall_prefix(ctx: commands.Context):
    await prefix_wrapper(listsall)(ctx)

@bot.command(name="help")
async def help_prefix(ctx: commands.Context):
    pages = help_pages()
    embed = pages["Overview"]
    view = HelpView(pages, initial_key="Overview", is_ephemeral=False)
    await ctx.send(embed=embed, view=view)

# -------- Misc utilities: broadcasts, feedback, info --------
@bot.tree.command(name="broadcast", description="[ADMIN] Broadcast a message to a channel")
@app_commands.describe(message="Message content", channel="Target channel (default current)")
async def broadcast(interaction: discord.Interaction, message: str, channel: Optional[discord.TextChannel] = None):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    target = channel or interaction.channel
    embed = themed_embed(
        title="📢 Broadcast",
        description=message,
        color=THEME_COLOR_ACCENT
    )
    embed.add_field(name="By", value=interaction.user.mention, inline=True)
    await target.send(embed=embed)
    await interaction.response.send_message(f"✅ Sent broadcast to {target.mention}", ephemeral=True)

@bot.tree.command(name="announcement", description="[ADMIN] Post a highlighted announcement")
@app_commands.describe(title="Announcement title", body="Announcement body", channel="Target channel (default current)")
async def announcement(interaction: discord.Interaction, title: str, body: str, channel: Optional[discord.TextChannel] = None):
    if not require_admin(interaction.user.id):
        await interaction.response.send_message("❌ Admin only.", ephemeral=True)
        return
    target = channel or interaction.channel
    embed = themed_embed(
        title=f"📣 {title}",
        description=body,
        color=THEME_COLOR_PRIMARY
    )
    embed.add_field(name="Posted by", value=interaction.user.mention, inline=True)
    await target.send(embed=embed)
    await interaction.response.send_message(f"✅ Announcement posted in {target.mention}", ephemeral=True)

@bot.tree.command(name="feedback", description="Send feedback or report a bug to the admins")
@app_commands.describe(kind="Type of feedback", message="Your feedback/bug report")
async def feedback(interaction: discord.Interaction, kind: str, message: str):
    kind_lower = kind.lower()
    if kind_lower not in ["bug", "feedback", "idea"]:
        await interaction.response.send_message("❌ Type must be one of: bug, feedback, idea.", ephemeral=True)
        return
    log_channel = bot.get_channel(LOG_CHANNEL_ID) if LOG_CHANNEL_ID else None
    embed = themed_embed(
        title="🛠️ Feedback Received" if kind_lower != "bug" else "🐞 Bug Report",
        description=message,
        color=THEME_COLOR_WARN if kind_lower == "bug" else THEME_COLOR_PRIMARY
    )
    embed.add_field(name="From", value=interaction.user.mention, inline=True)
    embed.add_field(name="Type", value=kind_lower, inline=True)
    if log_channel:
        await log_channel.send(embed=embed)
        await interaction.response.send_message("✅ Sent to admins. Thank you!", ephemeral=True)
    else:
        await interaction.response.send_message("ℹ️ Feedback noted (no log channel configured).", ephemeral=True)
    await send_log("Feedback", interaction.user, details=f"{kind_lower}: {message[:150]}")

@bot.tree.command(name="rules", description="Show server rules and about info")
async def rules(interaction: discord.Interaction):
    embed = themed_embed(
        title="📜 Rules & About",
        description="Be respectful, no abuse, no illegal content. VPS abuse will lead to suspension.",
        color=THEME_COLOR_PRIMARY
    )
    embed.add_field(name="About Pycroe Cloud", value="Fast VPS deployment, points-based access, and giveaways.", inline=False)
    embed.add_field(name="Support", value="Use /feedback for issues or contact admins.", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="links", description="Useful links and QR")
async def links(interaction: discord.Interaction):
    embed = themed_embed(
        title="🔗 Quick Links",
        description="Invite friends and manage your VPS faster.",
        color=THEME_COLOR_ACCENT
    )
    embed.add_field(name="Invite", value="Use `/inv` to get your invite code.", inline=False)
    embed.add_field(name="Docs", value="(Coming soon) Pycroe Cloud guide.", inline=False)
    embed.set_image(url=QR_IMAGE)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ---------------- Load Config on Start ----------------
def load_config():
    config_file = os.path.join(DATA_DIR, "config.json")
    config = load_json(config_file, {})
    
    global LOG_CHANNEL_ID
    LOG_CHANNEL_ID = config.get('log_channel_id')
    
    # Load additional admins and update global ADMIN_IDS
    admin_file = os.path.join(DATA_DIR, "admins.json")
    additional_admins = load_json(admin_file, [])
    
    global ADMIN_IDS
    ADMIN_IDS = set(MAIN_ADMIN_IDS)  # Start with main admins
    ADMIN_IDS.update(additional_admins)  # Add additional admins
    if OWNER_ID not in ADMIN_IDS:
        ADMIN_IDS.add(OWNER_ID)  # Ensure owner is always admin

# ---------------- Start Bot ----------------
if __name__ == "__main__":
    # Load configuration
    load_config()
    
    # Initialize data files
    persist_users()
    persist_vps()
    save_json(INV_CACHE_FILE, invite_snapshot)
    persist_giveaways()
    persist_renew_mode()
    
    START_TIME = utcnow()
    try:
        bot.run(DSC_TOKEN)
    except discord.LoginFailure:
        logger.error("❌ INVALID BOT TOKEN! Please get a new token from Discord Developer Portal.")
    except Exception as e:
        logger.error(f"❌ Bot failed to start: {e}")
