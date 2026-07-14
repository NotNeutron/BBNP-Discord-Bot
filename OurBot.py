#Importing libraries and modules
from flask import Flask
import io
import os
import discord
import sqlite3
import time
import asyncio
import re
import random
import spotipy
import requests
import threading
from bs4 import BeautifulSoup
from yt_dlp import YoutubeDL
from gtts import gTTS
from spotipy.oauth2 import SpotifyClientCredentials
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
from datetime import timedelta

#tricking into thinking its a web
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = threading.Thread(target=run)
    t.start()

keep_alive()

#Environment variables for tokens and other sensitive data
load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")

sp = spotipy.Spotify(
    auth_manager=SpotifyClientCredentials(
        client_id=SPOTIFY_CLIENT_ID,
        client_secret=SPOTIFY_CLIENT_SECRET
    )
)

#Database (global variables/dictionaries)
music_loop = {}
music_mode = {}
music_queue = {}
music_channel = {}
current_song = {}
proton_mode = {}
last_speaker = {}
tts_mode = {}
tts_language = {}
tts_channel = {}
tts_queue = {}

db = sqlite3.connect("warnings.db")
cursor = db.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS warnings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    reason TEXT
)
""")
db.commit()

# permissions/intents
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Bot setup
bot = commands.Bot(command_prefix="!", intents=intents)

# ==========================================
# HELPER FUNCTIONS
# ==========================================

def spotify_to_search(url):
    if "spotify.com" not in url.lower():
        return url

    clean_url = url.split("?")[0]

    if "/track/" in clean_url:
        try:
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            response = requests.get(clean_url, headers=headers, timeout=5)
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, "html.parser")
                meta_title = soup.find("meta", property="og:title")
                if meta_title and meta_title.get("content"):
                    title_text = meta_title["content"].strip()
                    if "· Song by" in title_text:
                        song_part, artist_part = title_text.split("· Song by")
                        return f"{artist_part.strip()} - {song_part.strip()}"
                    return title_text.replace(" | Spotify", "")
        except Exception as e:
            print(f"[LOCAL TRACK SCRAPER ERROR]: {e}")
            
    return url

async def process_music_queue(guild_id):
    played_at_least_once = False
    
    while True:
        await asyncio.sleep(0.5)
        if guild_id not in music_queue:
            continue
            
        guild = bot.get_guild(guild_id)
        if guild is None:
            continue
        vc = guild.voice_client
        if vc is None:
            continue

        if not music_queue[guild_id] and not vc.is_playing() and not vc.is_paused():
            if played_at_least_once:
                current_song.pop(guild_id, None)
                channel_id = music_channel.get(guild_id)
                if channel_id:
                    channel = bot.get_channel(channel_id)
                    if channel:
                        empty_embed = discord.Embed(
                            title="📭 Playlist Concluded", 
                            description="The playlist is now empty. No more tracks left to play!", 
                            color=discord.Color.teal()
                        )
                        await channel.send(embed=empty_embed)
                played_at_least_once = False
            continue

        if vc.is_playing() or vc.is_paused():
            continue

        query = music_queue[guild_id].pop(0)
        
        if isinstance(query, list):
            if len(query) == 0:
                continue
            first_item = query.pop(0)
            for track_name in reversed(query):
                music_queue[guild_id].insert(0, track_name)
            query = first_item

        search_query = spotify_to_search(query)
        
        if isinstance(search_query, list):
            if len(search_query) == 0:
                continue
            first_item = search_query.pop(0)
            for track_name in reversed(search_query):
                music_queue[guild_id].insert(0, track_name)
            search_query = first_item

        current_song[guild_id] = search_query

        if not isinstance(search_query, str) or "spotify.com" in search_query.lower():
            print(f"[MUSIC SKIPPED] Gagal mengonversi atau format salah: {search_query}")
            continue

        try:
            ydl_opts = {
                "format": "bestaudio",
                "noplaylist": True,
                "quiet": True,
                "default_search": "ytsearch",
                "nocheckcertificate": True,
                "extract_flat": False,
            }
            with YoutubeDL(ydl_opts) as ydl:
                if "youtube.com/" in search_query or "youtu.be/" in search_query:
                    info = ydl.extract_info(search_query, download=False)
                else:
                    info = ydl.extract_info(f"ytsearch:{search_query}", download=False)
                
                if "entries" in info:
                    if len(info["entries"]) == 0:
                        continue
                    info = info["entries"][0]

            resolved_title = info.get("title", search_query)
            current_song[guild_id] = resolved_title
            url = info["url"]

            ffmpeg_options = {
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                'options': '-vn'
            }
            
            # PERBAIKAN DI SINI: Mengarahkan path ffmpeg ke folder lokal Render
            audio_source = discord.FFmpegOpusAudio(
                url,
                executable="./ffmpeg_bin/ffmpeg",
                **ffmpeg_options
            )
            
            vc.play(audio_source)
            
            await asyncio.sleep(0.3)
            played_at_least_once = True

            while vc.is_playing() or vc.is_paused():
                await asyncio.sleep(0.2)

            if music_loop.get(guild_id, False) and current_song.get(guild_id) == resolved_title:
                music_queue[guild_id].insert(0, search_query) 
                
        except Exception as e:
            print(f"[MUSIC ERROR] {e}")

async def process_tts_queue(guild_id):
    while True:
        try:
            if guild_id not in tts_queue or not tts_queue[guild_id]:
                await asyncio.sleep(0.1)
                continue
            guild = bot.get_guild(guild_id)
            if guild is None or guild.voice_client is None:
                await asyncio.sleep(0.1)
                continue
            vc = guild.voice_client

            text = tts_queue[guild_id].pop(0)
            if not text.strip():
                continue

            lang = tts_language.get(guild_id, "id")
            filename = f"tts_{guild_id}.mp3"

            try:
                tts = gTTS(text=text, lang=lang)
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, tts.save, filename)
            except Exception as e:
                print(f"gTTS ERROR: {e}")
                continue

            try:
                # PERBAIKAN DI SINI: Mengarahkan path ffmpeg ke folder lokal Render
                audio_source = discord.FFmpegOpusAudio(
                    filename,
                    executable="./ffmpeg_bin/ffmpeg",
                    stderr=None
                )
                vc.play(audio_source)
            except Exception as play_error:
                print(f"Play ERROR: {play_error}")
                
            while vc.is_playing():
                await asyncio.sleep(0.1)

            if os.path.exists(filename):
                os.remove(filename)

        except Exception as e:
            print(f"TTS QUEUE ERROR: {e}")
            await asyncio.sleep(1)
            
# ==========================================
# BOT EVENTS
# ==========================================

@bot.event
async def on_ready():
    print("ON READY TRIGGERED")
    try:
        print("SYNCING...")
        synced = await bot.tree.sync()
        print("SYNC SUCCESS")
        print(f"Synced {len(synced)} commands")
        for cmd in synced:
            print(cmd.name)
        print(f"{bot.user} is online!")

        for guild in bot.guilds:
            if guild.id not in tts_queue:
                tts_queue[guild.id] = []
            if guild.id not in music_queue:
                music_queue[guild.id] = []
            bot.loop.create_task(process_tts_queue(guild.id))
            bot.loop.create_task(process_music_queue(guild.id))
    except Exception as e:
        print("SYNC ERROR:", repr(e))

# ==========================================
# SLASH COMMANDS (/)
# ==========================================

@bot.tree.command(name="ping", description="Check bot latency")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    await interaction.response.send_message(f"🏓 Pong! {latency}ms")

@bot.tree.command(name="serverinfo", description="Show server information")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None:
        await interaction.response.send_message("❌ This command can only be used in a server.", ephemeral=True)
        return
    await interaction.response.send_message(f"📌 Server: {guild.name}\n👥 Members: {guild.member_count}\n🆔 ID: {guild.id}")

@bot.tree.command(name="userinfo", description="Show your information")
async def userinfo(interaction: discord.Interaction):
    await interaction.response.send_message(f"👤 Username: {interaction.user.name}\n🆔 ID: {interaction.user.id}")

@bot.tree.command(name="avatar", description="Show someone's avatar")
async def avatar(interaction: discord.Interaction, member: discord.Member = None):
    if member is None:
        member = interaction.user
    embed = discord.Embed(title=f"{member.display_name}'s Avatar")
    embed.set_image(url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="say", description="Make the bot say something")
@app_commands.describe(message="Message to send")
async def say(interaction: discord.Interaction, message: str):
    await interaction.response.send_message(message)

@bot.tree.command(name="help", description="Show all commands")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📖 BBNP BOT COMMANDS MENU",
        description="Here is the list of official commands available.",
        color=discord.Color.teal()
    )
    embed.add_field(
        name="⚙️ UTILITY COMMANDS (Slash)",
        value=(
            "`/ping` - Check bot latency\n"
            "`/botinfo` - Detailed bot information\n"
            "`/serverinfo` - Server information\n"
            "`/userinfo` - User account information\n"
            "`/avatar` - View a member's avatar\n"
            "`/membercount` - Server member statistics\n"
            "`/uptime` - Bot online duration\n"
            "`/say` - Make the bot say something\n"
            "`/help` - Show this menu"
        ),
        inline=False
    )
    embed.add_field(
        name="🛡️ MODERATION COMMANDS (Slash)",
        value=(
            "`/clear` - Delete chat messages\n"
            "`/timeout` - Mute/Timeout a member\n"
            "`/kick` - Kick a member\n"
            "`/ban` / `/unban` - Ban or unban a user\n"
            "`/lock` / `/unlock` - Lock or unlock the active channel\n"
            "`/lockdown` / `/unlockdown` - Lock or unlock all text channels\n"
            "`/warn` / `/warnings` - Manage warning points\n"
            "`/removewarning` / `/clearwarnings` - Remove warnings from a member\n"
            "`/checkadmin` - Check if the bot has administrator permissions"
        ),
        inline=False
    )
    embed.add_field(
        name="🔊 FEATURES ACTIVATE (Slash)",
        value=(
            "`/join` / `/leave` - Join or leave a voice channel\n"
            "`/ttsmode` / `/ttsdisable` - Enable or disable text-to-speech mode\n"
            "`/protonmode` - Lock TTS to read only your messages\n"
            "`/musicmode` / `/musicdisable` - Enable or disable the music player system"
        ),
        inline=False
    )
    embed.add_field(
        name="🎵 MUSIC CONTROLS (Prefix , | Active during /musicmode)",
        value=(
            "`,play <title/link>` or `,p <title/link>` - Play a song\n"
            "`,pause` - Pause the active playback\n"
            "`,resume` - Resume the paused song\n"
            "`,skip` - Skip the current track\n"
            "`,nowplaying` - Show what is currently playing\n"
            "`,queue` - View the current song queue\n"
            "`,clearqueue` - Clear all songs from the queue\n"
            "`,remove <number>` - Remove a specific song from the queue\n"
            "`,shuffle` - Shuffle the song order\n"
            "`,loop` / `,unloop` - Toggle song looping"
        ),
        inline=False
    )
    embed.add_field(
        name="💬 TEXT COMMANDS (Prefix !)",
        value=(
            "`!ruleslevel1` - Show server rules Level 1\n"
            "`!ruleslevel2` - Show server rules Level 2\n"
            "`!ruleslevel3` - Show server rules Level 3\n"
            "✨ *The rest? Find out for yourself! There are some secret Easter Egg commands hidden.*"
        ),
        inline=False
    )
    embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="botinfo", description="Show bot information")
async def botinfo(interaction: discord.Interaction):
    embed = discord.Embed(title="🤖 Bot Information", color=discord.Color.blue())
    embed.add_field(name="Name", value=bot.user.name, inline=False)
    embed.add_field(name="Servers", value=len(bot.guilds), inline=True)
    embed.add_field(name="Users", value=sum(g.member_count for g in bot.guilds), inline=True)
    embed.add_field(name="Latency", value=f"{round(bot.latency * 1000)}ms", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="membercount", description="Show member count")
async def membercount(interaction: discord.Interaction):
    guild = interaction.guild
    humans = len([m for m in guild.members if not m.bot])
    bots = len([m for m in guild.members if m.bot])
    await interaction.response.send_message(f"👥 Total Members: {guild.member_count}\n🧑 Humans: {humans}\n🤖 Bots: {bots}")

start_time = time.time()
@bot.tree.command(name="uptime", description="Show bot uptime")
async def uptime(interaction: discord.Interaction):
    uptime_seconds = int(time.time() - start_time)
    days = uptime_seconds // 86400
    hours = (uptime_seconds % 86400) // 3600
    minutes = (uptime_seconds % 3600) // 60
    seconds = uptime_seconds % 60
    await interaction.response.send_message(f"⏱️ Uptime: {days}d {hours}h {minutes}m {seconds}s")

@bot.tree.command(name="clear", description="Delete messages")
@app_commands.describe(amount="Number of messages to delete")
async def clear(interaction: discord.Interaction, amount: int):
    if not interaction.user.guild_permissions.manage_messages:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.followup.send(f"🗑️ Deleted {len(deleted)} messages.", ephemeral=True)

@bot.tree.command(name="timeout", description="Timeout a member")
@app_commands.describe(member="Member to timeout", minutes="Duration in minutes", reason="Reason")
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: int, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    try:
        await member.timeout(timedelta(minutes=minutes), reason=reason)
        await interaction.response.send_message(f"🔇 {member.mention} timed out for {minutes} minute(s).\n📄 Reason: {reason}")
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to timeout that member.", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

@bot.tree.command(name="kick", description="Kick a member")
@app_commands.describe(member="Member to kick", reason="Reason")
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.kick_members:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    await member.kick(reason=reason)
    await interaction.response.send_message(f"👢 Kicked {member.mention}\nReason: {reason}")

@bot.tree.command(name="ban", description="Ban a member")
@app_commands.describe(member="Member to ban", reason="Reason")
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    await member.ban(reason=reason)
    await interaction.response.send_message(f"🔨 Banned {member.mention}\nReason: {reason}")

@bot.tree.command(name="unban", description="Unban a user")
@app_commands.describe(user_id="User ID to unban")
async def unban(interaction: discord.Interaction, user_id: str):
    if not interaction.user.guild_permissions.ban_members:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        await interaction.response.send_message(f"✅ Unbanned {user.name}")
    except Exception as e:
        await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)

@bot.tree.command(name="lock", description="Lock current channel")
async def lock(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False
    await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message("🔒 Channel locked.")

@bot.tree.command(name="unlock", description="Unlock current channel")
async def unlock(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = True
    await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message("🔓 Channel unlocked.")

@bot.tree.command(name="warn", description="Warn a member")
@app_commands.describe(member="Member to warn", reason="Reason")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    cursor.execute("INSERT INTO warnings (user_id, reason) VALUES (?, ?)", (str(member.id), reason))
    db.commit()
    await interaction.response.send_message(f"⚠️ {member.mention} has been warned.\n📄 Reason: {reason}")

@bot.tree.command(name="warnings", description="View warnings")
@app_commands.describe(member="Member to check")
async def warnings(interaction: discord.Interaction, member: discord.Member):
    cursor.execute("SELECT id, reason FROM warnings WHERE user_id = ?", (str(member.id),))
    warns = cursor.fetchall()
    if not warns:
        await interaction.response.send_message(f"✅ {member.mention} has no warnings.")
        return
    text = ""
    for i, (warn_id, reason) in enumerate(warns, start=1):
        text += f"{i}. {reason}\n"
    await interaction.response.send_message(f"⚠️ Warnings for {member.mention}\n\n{text}")

@bot.tree.command(name="removewarning", description="Remove a warning")
@app_commands.describe(member="Member", warning_number="Warning number")
async def removewarning(interaction: discord.Interaction, member: discord.Member, warning_number: int):
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    cursor.execute("SELECT id, reason FROM warnings WHERE user_id = ?", (str(member.id),))
    warns = cursor.fetchall()
    if not warns:
        await interaction.response.send_message("❌ No warnings found.")
        return
    if warning_number < 1 or warning_number > len(warns):
        await interaction.response.send_message("❌ Invalid warning number.")
        return
    warn_id, reason = warns[warning_number - 1]
    cursor.execute("DELETE FROM warnings WHERE id = ?", (warn_id,))
    db.commit()
    await interaction.response.send_message(f"✅ Removed warning #{warning_number}\n📄 Reason: {reason}")

@bot.tree.command(name="clearwarnings", description="Remove all warnings from a member")
@app_commands.describe(member="Member")
async def clearwarnings(interaction: discord.Interaction, member: discord.Member):
    if not interaction.user.guild_permissions.moderate_members:
        await interaction.response.send_message("❌ You don't have permission.", ephemeral=True)
        return
    cursor.execute("DELETE FROM warnings WHERE user_id = ?", (str(member.id),))
    db.commit()
    await interaction.response.send_message(f"🧹 Cleared all warnings for {member.mention}")

@bot.tree.command(name="lockdown", description="Lock all channels")
async def lockdown(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Administrator permission required.", ephemeral=True)
        return
    await interaction.response.defer()
    count = 0
    for channel in interaction.guild.text_channels:
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        count += 1
    await interaction.followup.send(f"🔒 Locked {count} channels.")

@bot.tree.command(name="unlockdown", description="Unlock all channels")
async def unlockdown(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ Administrator permission required.", ephemeral=True)
        return
    await interaction.response.defer()
    count = 0
    for channel in interaction.guild.text_channels:
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
        count += 1
    await interaction.followup.send(f"🔓 Unlocked {count} channels.")

@bot.tree.command(name="checkadmin")
async def checkadmin(interaction: discord.Interaction):
    perms = interaction.guild.me.guild_permissions
    await interaction.response.send_message(f"Administrator = {perms.administrator}")

@bot.tree.command(name="join", description="Join your voice channel")
async def join(interaction: discord.Interaction):
    if not interaction.user.voice:
        await interaction.response.send_message("❌ You are not in a voice channel.", ephemeral=True)
        return
    channel = interaction.user.voice.channel
    if interaction.guild.voice_client:
        await interaction.response.send_message("❌ I'm already connected.", ephemeral=True)
        return
    await channel.connect()
    await interaction.guild.change_voice_state(channel=channel, self_deaf=True)
    await interaction.response.send_message(f"🔊 Joined **{channel.name}**")

@bot.tree.command(name="leave", description="Leave the voice channel")
async def leave(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    vc = interaction.guild.voice_client
    if vc is None:
        await interaction.response.send_message("❌ I'm not in a voice channel.")
        return
    await vc.disconnect()
    
    tts_mode[guild_id] = False
    tts_channel.pop(guild_id, None)
    tts_language.pop(guild_id, None)
    last_speaker.pop(guild_id, None)
    proton_mode.pop(guild_id, None)
    if guild_id in tts_queue:
        tts_queue[guild_id].clear()

    music_mode[guild_id] = False
    music_channel.pop(guild_id, None)
    if guild_id in music_queue:
        music_queue[guild_id].clear()
    current_song.pop(guild_id, None)
    await interaction.response.send_message("👋 Disconnected from voice channel.")

@bot.tree.command(name="ttsmode", description="Enable TTS mode")
@app_commands.describe(language="Choose a language")
@app_commands.choices(
    language=[
        app_commands.Choice(name="Indonesian", value="id"),
        app_commands.Choice(name="English", value="en"),
        app_commands.Choice(name="Mandarin", value="zh-cn"),
        app_commands.Choice(name="Ara", value="jw"),
    ]
)
async def ttsmode(interaction: discord.Interaction, language: app_commands.Choice[str]):
    guild_id = interaction.guild.id
    if music_mode.get(guild_id):
        await interaction.response.send_message("❌ Music mode is active.")
        return
    vc = interaction.guild.voice_client
    if vc is None:
        await interaction.response.send_message("❌ Bot is not in a voice channel. Use /join first.", ephemeral=True)
        return
    if tts_mode.get(guild_id) and tts_language.get(guild_id) == language.value:
        await interaction.response.send_message(f"❌ TTS is already using {language.name}.", ephemeral=True)
        return
    
    tts_mode[guild_id] = True
    tts_language[guild_id] = language.value
    tts_channel[guild_id] = interaction.channel.id
    if guild_id not in tts_queue:
        tts_queue[guild_id] = []
    await interaction.response.send_message(f"🗣️ TTS enabled in {interaction.channel.mention}\nLanguage: {language.name}")

@bot.tree.command(name="ttsdisable", description="Disable TTS mode")
async def ttsdisable(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    vc = interaction.guild.voice_client
    if vc and vc.is_playing():
        vc.stop()
    tts_mode[guild_id] = False
    proton_mode.pop(guild_id, None)
    last_speaker.pop(guild_id, None)
    if guild_id in tts_queue:
        tts_queue[guild_id].clear()
    await interaction.response.send_message("🔇 TTS disabled.")

@bot.tree.command(name="protonmode", description="Only read your messages in TTS")
async def protonmode(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if not tts_mode.get(guild_id):
        await interaction.response.send_message("❌ TTS mode is not enabled.", ephemeral=True)
        return
    if guild_id in proton_mode:
        await interaction.response.send_message("❌ Proton Mode is already being used by someone else.", ephemeral=True)
        return
    proton_mode[guild_id] = interaction.user.id
    await interaction.response.send_message(f"🔒 Proton Mode enabled for {interaction.user.display_name}")

@bot.tree.command(name="musicmode", description="Enable music mode")
async def musicmode(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    if music_mode.get(guild_id):
        await interaction.response.send_message("❌ Music mode is already enabled.", ephemeral=True)
        return
    if tts_mode.get(guild_id):
        await interaction.response.send_message("❌ TTS mode is active.", ephemeral=True)
        return
    vc = interaction.guild.voice_client
    if vc is None:
        await interaction.response.send_message("❌ Bot is not in a voice channel. Use /join first.", ephemeral=True)
        return

    music_mode[guild_id] = True
    music_channel[guild_id] = interaction.channel.id
    if guild_id not in music_queue:
        music_queue[guild_id] = []

    embed = discord.Embed(
        title="🎵 Music Mode Activated",
        description=f"Sleek playback system successfully initialized in {interaction.channel.mention}.",
        color=discord.Color.teal()
    )
    embed.add_field(
        name="🎧 Playback Commands",
        value=(
            "`,play <title/link>` or `,p <title/link>` - Play a song\n"
            "`,pause` - Pause the current song\n"
            "`,resume` - Resume the paused song\n"
            "`,skip` - Skip the active track"
        ),
        inline=False
    )
    embed.add_field(
        name="📋 Queue Commands",
        value=(
            "`,queue` - View the song queue\n"
            "`,clearqueue` - Clear the entire queue\n"
            "`,remove <number>` - Remove a specific song number\n"
            "`,shuffle` - Shuffle the queue order"
        ),
        inline=False
    )
    embed.add_field(
        name="🔁 Loop & Info Commands",
        value=(
            "`,nowplaying` - Check the currently playing song\n"
            "`,loop` - Enable song looping\n"
            "`,unloop` - Disable song looping"
        ),
        inline=False
    )
    embed.add_field(
        name="🛑 Disable",
        value="`/musicdisable` - Turn off music control system",
        inline=False
    )
    embed.set_footer(text=f"Activated by {interaction.user.display_name}", icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="musicdisable", description="Disable music mode")
async def musicdisable(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    vc = interaction.guild.voice_client
    if vc and (vc.is_playing() or vc.is_paused()):
        vc.stop()
    music_mode[guild_id] = False
    if guild_id in music_queue:
        music_queue[guild_id].clear()
    current_song.pop(guild_id, None)
    await interaction.response.send_message("🎵 Music mode disabled.")

@bot.tree.command(name="cina", description="中文 中文 中文 中文 中文 (Requires TTS mode to be active)")
async def cina(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    
    if not interaction.user.voice:
        await interaction.response.send_message("❌ You must be in a voice channel to use this command.", ephemeral=True)
        return
        
    vc = interaction.guild.voice_client
    
    if vc is None:
        channel = interaction.user.voice.channel
        await channel.connect()
        await interaction.guild.change_voice_state(channel=channel, self_deaf=True)
        vc = interaction.guild.voice_client
    
    if not tts_mode.get(guild_id):
        await interaction.response.send_message("❌ TTS mode is not enabled. Please activate it using `/ttsmode` first.", ephemeral=True)
        return

    sound_path = "cina.mp4" # File here
    
    if not os.path.exists(sound_path):
        await interaction.response.send_message("❌ Sound effect file `cina.mp4` was not found in the bot directory.", ephemeral=True)
        return

    if vc.is_playing():
        await interaction.response.send_message("⏳ Please wait for the current TTS audio to finish playing.", ephemeral=True)
        return
        
    try:
        ffmpeg_options = "-filter:a volume=10.0"
        
        # PERBAIKAN DI SINI: Mengarahkan path ffmpeg ke folder lokal Render
        audio_source = discord.FFmpegOpusAudio(
            sound_path,
            executable="./ffmpeg_bin/ffmpeg",
            options=ffmpeg_options
        )
        vc.play(audio_source)
        await interaction.response.send_message("中文 中文 中文 中文 中文 🗣️")
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to play audio: {e}", ephemeral=True)

@bot.tree.command(name="jawa", description="EHEHEHEHEHEHEHE (Requires TTS mode to be active)")
async def jawa(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    
    if not interaction.user.voice:
        await interaction.response.send_message("❌ You must be in a voice channel to use this command.", ephemeral=True)
        return
        
    vc = interaction.guild.voice_client
    
    if vc is None:
        channel = interaction.user.voice.channel
        await channel.connect()
        await interaction.guild.change_voice_state(channel=channel, self_deaf=True)
        vc = interaction.guild.voice_client
    
    if not tts_mode.get(guild_id):
        await interaction.response.send_message("❌ TTS mode is not enabled. Please activate it using `/ttsmode` first.", ephemeral=True)
        return

    sound_path = "kobo-jawa.mp3" #File here
    
    if not os.path.exists(sound_path):
        await interaction.response.send_message("❌ Sound effect file `jawa.mp4` was not found in the bot directory.", ephemeral=True)
        return

    if vc.is_playing():
        await interaction.response.send_message("⏳ Please wait for the current TTS audio to finish playing.", ephemeral=True)
        return
        
    try:
        # PERBAIKAN DI SINI: Mengarahkan path ffmpeg ke folder lokal Render
        audio_source = discord.FFmpegOpusAudio( 
            sound_path,
            executable="./ffmpeg_bin/ffmpeg"
        )
        vc.play(audio_source)
        await interaction.response.send_message("JAWA JAWA JAWA JAWA 🗣️")
    except Exception as e:
        await interaction.response.send_message(f"❌ Failed to play audio: {e}", ephemeral=True)

# ==========================================
# TEXT COMMANDS CORNER (!)
# ==========================================

@bot.command()
async def ruleslevel1(ctx):
    embed = discord.Embed(title="SERVER RULES", description="These rules must be followed at all times.", color=discord.Color.green())
    embed.add_field(name="🟢 FREEDOM OF SPEECH", value="Most discussions are allowed. Friendly banter and dark humor are permitted as long as they are not targeted harassment.", inline=False)
    embed.add_field(name="🟢 NSFW CONTENT", value="mild NSFW content is allowed. However, illegal content, real exploitation, and content involving minors are strictly forbidden.", inline=False)
    embed.add_field(name="🟢 RESPECT OTHER MEMBERS", value="Do not engage in targeted harassment, stalking, doxxing, or threats toward other members.", inline=False)
    embed.add_field(name="🟢 SPAM", value="Do not flood channels with repeated messages, excessive mentions, or disruptive content.", inline=False)
    embed.add_field(name="🟢 ILLEGAL ACTIVITIES", value="No promotion of illegal activities, malware, scams, phishing, or account theft.", inline=False)
    embed.add_field(name="🟢 STAFF DECISIONS", value="Moderators may intervene if behavior becomes disruptive to the community.", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def ruleslevel2(ctx):
    embed = discord.Embed(title="SERVER RULES", description="These rules must be followed at all times.", color=discord.Color.gold())
    embed.add_field(name="🟡 RESPECT THE COMMUNITY", value="Toxic behavior is allowed only in moderation. Excessive insults, harassment, or creating a hostile environment may result in punishment.", inline=False)
    embed.add_field(name="🟡 NSFW POLICY", value="Explicit NSFW content is not allowed. Light discussion of mature topics is acceptable, but do not sexualize members of the server.", inline=False)
    embed.add_field(name="🟡 NO HARASSMENT", value="Repeated targeting of individuals, bullying, or encouraging dogpiling is prohibited.", inline=False)
    embed.add_field(name="🟡 NO HATE SPEECH", value="Slurs and hateful attacks against groups or individuals are not allowed.", inline=False)
    embed.add_field(name="🟡 SPAM & ADVERTISING", value="No spam, self-promotion, invite links, or advertisements without permission.", inline=False)
    embed.add_field(name="🟡 PRIVACY", value="Do not share personal information belonging to yourself or others unless trusted.", inline=False)
    embed.add_field(name="🟡 FOLLOW STAFF INSTRUCTIONS", value="Moderator decisions should be respected. Use designated channels to appeal actions if necessary.", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def ruleslevel3(ctx):
    embed = discord.Embed(title="SERVER RULES", description="These rules must be followed at all times.", color=discord.Color.red())
    embed.add_field(name="🔴 NO TOXICITY", value="Be respectful at all times. Insults, harassment, bullying, and hostile behavior are not allowed.", inline=False)
    embed.add_field(name="🔴 NO NSFW CONTENT", value="NSFW content, sexual discussions, explicit jokes, and suggestive media are prohibited.", inline=False)
    embed.add_field(name="🔴 KEEP IT FAMILY FRIENDLY", value="This server is intended to be comfortable for all ages. Use appropriate language and topics.", inline=False)
    embed.add_field(name="🔴 NO HATE SPEECH", value="Discrimination, slurs, extremist content, or attacks against groups are forbidden.", inline=False)
    embed.add_field(name="🔴 NO SPAM", value="Do not flood channels, abuse mentions, send excessive emojis, or disrupt conversations.", inline=False)
    embed.add_field(name="🔴 NO ADVERTISING", value="Do not promote servers, products, social media accounts, or services without permission.", inline=False)
    embed.add_field(name="🔴 PRIVACY & SAFETY", value="Never share personal information. Respect everyone's privacy and boundaries.", inline=False)
    embed.add_field(name="🔴 FOLLOW STAFF", value="Staff decisions are final. Repeated violations may result in mutes, kicks, or bans.", inline=False)
    await ctx.send(embed=embed)

@bot.command()
async def neutron(ctx):
    await ctx.send("Namanya Neutron.")

@bot.command()
async def pya(ctx):
    file_gambar = discord.File("pyadongos.png") 
    await ctx.send(file=file_gambar)

@bot.command()
async def vino(ctx):
    await ctx.send("Streamer kecup")

@bot.command()
async def amel(ctx):
    await ctx.send("cewe paling cantik, kyut, menawan, dan anggun!")

@bot.command()
async def ara(ctx):
    await ctx.send("Iy gapapa makasihh")

@bot.command()
async def isla(ctx):
    await ctx.send("Dipikir2 pacarny ad 5?")

@bot.command()
async def ucup(ctx):
    await ctx.send("Ucup baik")

@bot.command()
async def ken(ctx):
    await ctx.send("# Buaya, gay, dan matre")

@bot.command()
async def rey(ctx):
    await ctx.send("Stop nyari tobrut2")

# ==========================================
# ON MESSAGE HANDLER (DENGAN KENDALI KOMA ',')
# ==========================================

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    guild_id = message.guild.id

    if music_mode.get(guild_id):
        if message.channel.id != music_channel.get(guild_id):
            await bot.process_commands(message)
            return

        vc = message.guild.voice_client
        if vc is None or message.author.voice is None or message.author.voice.channel != vc.channel:
            await bot.process_commands(message)
            return

        content = message.content.strip()
        content_lower = content.lower()

        def make_music_embed(title, description, color=discord.Color.teal()):
            return discord.Embed(title=title, description=description, color=color)

        if content_lower.startswith(",play ") or content_lower.startswith(",p "):
            query = content[6:].strip() if content_lower.startswith(",play ") else content[3:].strip()
            if query:
                if guild_id not in music_queue:
                    music_queue[guild_id] = []

                if "spotify.com" in query.lower() and ("/playlist/" in query.lower() or "/album/" in query.lower()):
                    try:
                        headers = {
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                            "Accept-Language": "en-US,en"
                        }
                        response = requests.get(query.split("?")[0], headers=headers, timeout=8)
                        
                        if response.status_code == 200:
                            soup = BeautifulSoup(response.text, "html.parser")
                            playlist_tracks = []
                            for a_tag in soup.find_all("a", href=True):
                                href = a_tag["href"]
                                if "/track/" in href:
                                    track_name = a_tag.get_text().strip()
                                    if track_name and track_name not in playlist_tracks and len(track_name) > 1:
                                        playlist_tracks.append(track_name)
                            
                            if not playlist_tracks:
                                import json
                                for script in soup.find_all("script", type="application/ld+json"):
                                    try:
                                        js_data = json.loads(script.string)
                                        if "track" in js_data:
                                            for item in js_data["track"]:
                                                playlist_tracks.append(f"{item.get('name')}")
                                        elif "itemListElement" in js_data:
                                            for item in js_data["itemListElement"]:
                                                track_item = item.get("item", {})
                                                if track_item.get("name"):
                                                    playlist_tracks.append(track_item.get("name"))
                                    except:
                                        continue

                            if len(playlist_tracks) == 0:
                                await message.channel.send(embed=make_music_embed("❌ Error", "Failed to read the playlist contents.", discord.Color.red()))
                                return
                                
                            for track_name in playlist_tracks:
                                music_queue[guild_id].append(track_name)
                            
                            embed = make_music_embed(
                                "🎵 Playlist Added", 
                                f"Successfully added **{len(playlist_tracks)}** tracks to the queue!"
                            )
                            await message.channel.send(embed=embed)
                            return
                    except Exception as e:
                        print(f"[LOCAL PLAYLIST SCRAPER ERROR]: {e}")

                converted_data = spotify_to_search(query)
                music_queue[guild_id].append(converted_data)
                embed = make_music_embed("🎵 Track Added", f"Added **{converted_data}** to the queue.")
                await message.channel.send(embed=embed)

        elif content_lower == ",pause":
            if vc.is_playing():
                vc.pause()
                await message.channel.send(embed=make_music_embed("⏸️ Paused", "Playback has been paused."))

        elif content_lower == ",resume":
            if vc.is_paused():
                vc.resume()
                await message.channel.send(embed=make_music_embed("▶️ Resumed", "Playback has been resumed."))

        elif content_lower == ",skip":
            if vc.is_playing() or vc.is_paused():
                current_song.pop(guild_id, None)
                vc.stop()
                await message.channel.send(embed=make_music_embed("⏭️ Track Skipped", "Skipped to the next track."))
            else:
                await message.channel.send(embed=make_music_embed("❌ Error", "No song is currently playing.", discord.Color.red()))

        elif content_lower == ",nowplaying":
            if guild_id not in current_song:
                await message.channel.send(embed=make_music_embed("❌ Idle", "Nothing is playing right now.", discord.Color.red()))
            else:
                await message.channel.send(embed=make_music_embed("🎧 Now Playing", f"**{current_song[guild_id]}**"))

        elif content_lower == ",queue":
            current = current_song.get(guild_id)
            embed = discord.Embed(title="📋 Current Music Queue", color=discord.Color.teal())
            if current:
                embed.add_field(name="✨ Now Playing", value=f"👉 **{current}**", inline=False)
            if guild_id in music_queue and music_queue[guild_id]:
                queue_list = "\n".join(f"`{i}.` {song}" for i, song in enumerate(music_queue[guild_id], start=1))
                embed.add_field(name="Up Next", value=queue_list, inline=False)
            elif not current:
                embed.description = "The queue is completely empty."
            else:
                embed.add_field(name="Up Next", value="No upcoming songs in queue.", inline=False)
            await message.channel.send(embed=embed)

        elif content_lower == ",clearqueue":
            if guild_id in music_queue:
                music_queue[guild_id].clear()
            current_song.pop(guild_id, None)
            if vc and (vc.is_playing() or vc.is_paused()):
                vc.stop()
            await message.channel.send(embed=make_music_embed("🗑️ Queue Cleared", "Cleared all songs and stopped audio playback."))

        elif content_lower.startswith(",remove "):
            try:
                num = int(content[8:].strip())
                if guild_id not in music_queue or not music_queue[guild_id]:
                    await message.channel.send(embed=make_music_embed("❌ Empty", "The queue is already empty.", discord.Color.red()))
                elif num < 1 or num > len(music_queue[guild_id]):
                    await message.channel.send(embed=make_music_embed("❌ Error", "Invalid queue position number.", discord.Color.red()))
                else:
                    removed = music_queue[guild_id].pop(num - 1)
                    await message.channel.send(embed=make_music_embed("🗑️ Track Removed", f"Removed **{removed}** from queue."))
            except ValueError:
                await message.channel.send(embed=make_music_embed("ℹ️ Usage Help", "Correct usage: `,remove <number>`", discord.Color.gold()))

        elif content_lower == ",loop":
            music_loop[guild_id] = not music_loop.get(guild_id, False)
            status = "**enabled** 🔁" if music_loop[guild_id] else "**disabled** ⏹️"
            await message.channel.send(embed=make_music_embed("🔁 Loop Configuration", f"Track loop has been {status}."))

        elif content_lower == ",unloop":
            music_loop[guild_id] = False
            await message.channel.send(embed=make_music_embed("⏹️ Loop Configuration", "Track loop has been **disabled**."))

        elif content_lower == ",shuffle":
            if guild_id not in music_queue or len(music_queue[guild_id]) < 2:
                await message.channel.send(embed=make_music_embed("❌ Error", "You need at least 2 tracks in queue to shuffle.", discord.Color.red()))
            else:
                random.shuffle(music_queue[guild_id])
                await message.channel.send(embed=make_music_embed("🔀 Shuffled", "The queue has been successfully shuffled!"))

        await bot.process_commands(message)
        return

    vc = message.guild.voice_client
    if vc is None or message.author.voice is None or message.author.voice.channel != vc.channel:
        await bot.process_commands(message)
        return

    if not tts_mode.get(guild_id) or message.channel.id != tts_channel.get(guild_id):
        await bot.process_commands(message)
        return

    raw_speaker = message.author.display_name
    speaker = re.sub(r'\[.*?\]', '', raw_speaker).strip()
    if not speaker:
        speaker = message.author.name

    if guild_id in proton_mode and message.author.id != proton_mode[guild_id]:
        return

    if guild_id not in last_speaker:
        last_speaker[guild_id] = None

    text = ""
    content_lower = message.content.lower()

    if any(x in content_lower for x in [".gif", "tenor.com", "giphy.com", "/gif", "/gifs/"]):
        text = f"{speaker} sent a gif"
        last_speaker[guild_id] = speaker

    elif content_lower.startswith("http://") or content_lower.startswith("https://"):
        text = f"{speaker} sent a link"
        last_speaker[guild_id] = speaker

    elif message.content:
        if last_speaker[guild_id] != speaker:
            text += f"{speaker} said "
            last_speaker[guild_id] = speaker

        content = message.content
        for user in message.mentions:
            content = content.replace(user.mention, user.display_name)
        for role in message.role_mentions:
            content = content.replace(role.mention, role.name)
        for channel in message.channel_mentions:
            content = content.replace(channel.mention, channel.name)

        content = content.replace("@everyone", "everyone").replace("@here", "here")
        content = re.sub(r'<a?:([^:]+):\d+>', r'\1 emoji', content)
        text += content

    elif message.attachments:
        attachment = message.attachments[0]
        text = f"{speaker} "
        filename = attachment.filename.lower()

        if filename.endswith(".gif"):
            text += "sent a gif"
        elif attachment.content_type and attachment.content_type.startswith("image"):
            text += "sent an image"
        elif attachment.content_type and attachment.content_type.startswith("video"):
            text += "sent a video"
        else:
            text += "sent a document"
        last_speaker[guild_id] = speaker

    elif message.embeds:
        text = f"{speaker} sent an embed"
        last_speaker[guild_id] = speaker
    elif message.stickers:
        text = f"{speaker} sent a sticker"
        last_speaker[guild_id] = speaker
    else:
        text = f"{speaker} sent a message"
        last_speaker[guild_id] = speaker

    if not text.strip():
        await bot.process_commands(message)
        return

    tts_queue[guild_id].append(text)
    await bot.process_commands(message)

bot.run(TOKEN)
