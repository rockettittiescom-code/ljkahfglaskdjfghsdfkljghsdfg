import discord
from discord import app_commands
from discord.ext import commands
from pymongo import MongoClient
from datetime import datetime, timezone
from discord.ui import View, Button
import aiohttp, re, io, os, subprocess, time
from functools import wraps
from PIL import Image
import config
from config import GODS, BOT_PM2_ID

# ------------------ CONFIG ------------------
mongo_client = MongoClient(config.MONGO_URI)
db = mongo_client["mybot"]
access_collection = db["user_access"]

TOKEN = config.TOKEN
GODS = config.GODS
BOT_NAME_PM2 = config.BOT_NAME_PM2
API_URL = "https://api.voids.top/fakequote"
SINGLE_USER_ID = "277851641976324096"

embed_color = int("3480be", 16)
bot_start_time = datetime.now(timezone.utc)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ------------------ COOLDOWN SETUP ------------------
LAST_USED = {}
COOLDOWN_SECONDS = 2.0

def command_cooldown(func):
    @wraps(func)
    async def wrapper(interaction: discord.Interaction, *args, **kwargs):
        user_id = str(interaction.user.id)
        if user_id not in GODS:
            now = time.time()
            last = LAST_USED.get(user_id, 0)
            if now - last < COOLDOWN_SECONDS:
                return await interaction.response.send_message("> You're using commands too fast — wait 2 seconds.", ephemeral=True)
            LAST_USED[user_id] = now
        return await func(interaction, *args, **kwargs)
    return wrapper

# ------------------ ACCESS CHECK ------------------
def has_access(user_id: int) -> bool:
    if str(user_id) in GODS:
        return True
    return access_collection.find_one({"userId": str(user_id)}) is not None

# ------------------ EVENTS ------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Sync failed: {e}")

# ------------------ RELOAD COMMAND ------------------
@bot.tree.command(name="reload", description="Reload the bot (PM2 restart)")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@command_cooldown
async def reload_bot(interaction: discord.Interaction):
    if str(interaction.user.id) not in GODS:
        return await interaction.response.send_message("> You aren't authorized to reload the bot.", ephemeral=True)

    # Send confirmation before restarting
    await interaction.response.send_message("> Bot reload has been triggered. Restarting via PM2 now...", ephemeral=True)

    try:
        # Run PM2 restart using ID and shell=True for Windows compatibility
        subprocess.Popen(f"pm2 restart {BOT_PM2_ID}", shell=True)
    except Exception as e:
        await interaction.followup.send(f"> Failed to restart: `{e}`", ephemeral=True)

# ------------------ ADMIN COMMANDS (ephemeral) ------------------
@bot.tree.command(name="addaccess", description="Grant someone access to the bot (OWNER ONLY)")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(user="The user to grant access")
@command_cooldown
async def add_access(interaction: discord.Interaction, user: discord.User):
    if str(interaction.user.id) not in GODS:
        return await interaction.response.send_message("> You arent a admin .. <:smh:1423529032707739688>", ephemeral=True)

    if access_collection.find_one({"userId": str(user.id)}):
        return await interaction.response.send_message(f"> {user.mention} already has access.", ephemeral=True)

    access_collection.insert_one({"userId": str(user.id)})
    await interaction.response.send_message(f"> {user.mention} has been granted access.", ephemeral=True)

@bot.tree.command(name="removeaccess", description="Remove someone's access (OWNER ONLY)")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(user="The user to remove access from")
@command_cooldown
async def remove_access(interaction: discord.Interaction, user: discord.User):
    if str(interaction.user.id) not in GODS:
        return await interaction.response.send_message("> You arent a admin .. <:smh:1423529032707739688>", ephemeral=True)

    result = access_collection.delete_one({"userId": str(user.id)})
    if result.deleted_count == 0:
        return await interaction.response.send_message(f"> {user.mention} did not have access.", ephemeral=True)

    await interaction.response.send_message(f"> {user.mention} access removed.", ephemeral=True)


@bot.tree.command(name="listaccess", description="all users who have access (OWNER ONLY)")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@command_cooldown
async def list_access(interaction: discord.Interaction):
    if str(interaction.user.id) not in GODS:
        return await interaction.response.send_message("> You aren't an admin.. <:smh:1423529032707739688>", ephemeral=True)

    gods_list = [f"> God: <@{god_id}>" for god_id in GODS]
    users_list = [f"> <@{user['userId']}>" for user in access_collection.find()]

    full_list = gods_list + users_list

    if not full_list:
        return await interaction.response.send_message("> No one has access .. gg ig", ephemeral=True)

    ITEMS_PER_PAGE = 10
    pages = [full_list[i:i + ITEMS_PER_PAGE] for i in range(0, len(full_list), ITEMS_PER_PAGE)]
    
    current_page = 0

    def create_embed(page_num):
        embed = discord.Embed(
            title="Users",
            color=discord.Color.blurple()
        )
        for item in pages[page_num]:
            embed.add_field(name="\u200b", value=item, inline=True)
        embed.set_footer(text=f"Page {page_num + 1}/{len(pages)}")
        return embed

    embed = create_embed(current_page)

    class AccessView(View):
        def __init__(self):
            super().__init__(timeout=None)
            self.current_page = 0

        @discord.ui.button(label="<-", style=discord.ButtonStyle.gray)
        async def previous(self, interaction_btn: discord.Interaction, button: Button):
            if self.current_page > 0:
                self.current_page -= 1
                await interaction_btn.response.edit_message(embed=create_embed(self.current_page), view=self)

        @discord.ui.button(label="->", style=discord.ButtonStyle.gray)
        async def next(self, interaction_btn: discord.Interaction, button: Button):
            if self.current_page < len(pages) - 1:
                self.current_page += 1
                await interaction_btn.response.edit_message(embed=create_embed(self.current_page), view=self)

    await interaction.response.send_message(embed=embed, view=AccessView(), ephemeral=True)


@bot.tree.command(name="setname", description="Change the username (OWNER ONLY)")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(username="New username")
@command_cooldown
async def set_bot_name(interaction: discord.Interaction, username: str):
    if str(interaction.user.id) not in GODS:
        return await interaction.response.send_message("> You arent a admin .. <:smh:1423529032707739688>", ephemeral=True)

    try:
        await bot.user.edit(username=username)
        await interaction.response.send_message(f"> Username updated to **{username}**", ephemeral=True)
    except Exception as e:
        await interaction.response.send_message(f"> Failed to update the username: {e}", ephemeral=True)



# ------------------ HELP / INFO COMMANDS (public) ------------------
async def send_embed_with_ping(interaction: discord.Interaction, embed: discord.Embed, ping: discord.User = None):
    content = ping.mention if ping else None
    await interaction.response.send_message(content=content, embed=embed, ephemeral=False)

@bot.tree.command(
    name="about",
    description="Show about the bot"
)
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@command_cooldown
async def help_cmd(interaction: discord.Interaction):
    now = datetime.now(timezone.utc)
    uptime_seconds = int((now - bot_start_time).total_seconds())
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"

    embed = discord.Embed(
        title="About",
        description="",
        color=embed_color
    )

    embed.add_field(
        name="Stats",
        value=(
            f"> Uptime: ``{uptime_str}``"
        ),
        inline=True
    )

    embed.add_field(
        name="Commands",
        value=(
            "> `/about` — Show information about the bot\n"
            "> `/nightyauth` — Power nighty auth\n"
            "> `/webview` — Fix weird looking UI issues\n"
            "> `/brokenwebview` — Fix for broken WebView\n"
            "> `/loading` — Fix infinite loading problems\n"
            "> `/cmd` — Fix CMD prompt issues\n"
            "> `/safe` — Nighty safety information\n"
            "> `/ticket` — How to create a support ticket\n"
            "> `/discordfix` — Fix Discord links opening in Canary\n"
            "> `/authbot` — Get the bot authorization link\n"
            "> `/prefix` — Understanding <p>\n"
            "> `/legacy` — Legacy commands\n"
            "> `/gif` — Convert an image (PNG/JPG) into a GIF file\n"
            "> `/rpc` — Fix for Rich Presence not showing\n"
            "> **Context Menu → `Quote`** — Generate a fake quote image (as GIF) from a message"
        ),
        inline=True
    )


    embed.add_field(
        name="Owners",
        value="> <@1361736124858630274>\n> <@277851641976324096>\n> <@1093694817285971988>",
        inline=False
    )

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="webview", description="Fix for weird looking UI issues")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(ping="Optional: Mention someone outside the embed")
@command_cooldown
async def webview(interaction: discord.Interaction, ping: discord.User = None):
    if not has_access(interaction.user.id):
        return await interaction.response.send_message("> You dont have access gng .. ask the owner.", ephemeral=True)

    # Choose link based on single user ID
    if str(interaction.user.id) == SINGLE_USER_ID:
        webview_link = "https://webview.pyro.pics"
    else:
        webview_link = "https://webview.niggy.one"

    embed = discord.Embed(title="Weird looking UI Fix", color=embed_color)
    embed.description = (
        "> 1. Fully close Nighty\n"
        f"> 2. Download WebView2: {webview_link}\n"
        "> 3. Restart Nighty"
    )
    await send_embed_with_ping(interaction, embed, ping)

@bot.tree.command(name="brokenwebview", description="Fix for broken WebView")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(ping="Optional: Mention someone outside the embed")
@command_cooldown
async def brokenwebview(interaction: discord.Interaction, ping: discord.User = None):
    # Choose link based on single user ID
    if str(interaction.user.id) == SINGLE_USER_ID:
        webview_link = "https://webview.pyro.pics"
    else:
        webview_link = "https://webview.niggy.one"

    embed = discord.Embed(title="WebView2 Fix Instructions", color=embed_color)
    embed.description = (
        "> 1. Open PowerShell as Administrator\n"
        "> 2. Navigate to the installer folder:\n"
        "> ```cd 'C:\\Program Files (x86)\\Microsoft\\EdgeWebView\\Application\\1*\\Installer'```\n"
        "> If that fails, run this instead:\n"
        "> ```cd 'C:\\Program Files\\Microsoft\\EdgeWebView\\Application\\1*\\Installer'```\n"
        "> 3. Uninstall WebView2:\n"
        "> ```setup.exe --uninstall --msedgewebview --system-level --verbose-logging --force-uninstall```\n"
        "> 4. Reboot your PC\n"
        f"> 5. Reinstall WebView2 → Download from: {webview_link}\n"
        "> Or direct installer link → [Microsoft Edge WebView2 Runtime](https://msedge.sf.dl.delivery.mp.microsoft.com/filestreamingservice/files/dad8096c-1b0c-40c5-9b1c-415164028ec9/MicrosoftEdgeWebView2RuntimeInstallerX64.exe)"
    )
    await send_embed_with_ping(interaction, embed, ping)

@bot.tree.command(name="loading", description="Solution for infinite loading problems")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(ping="Optional: Mention someone outside the embed")
@command_cooldown
async def loading(interaction: discord.Interaction, ping: discord.User = None):
    if not has_access(interaction.user.id):
        return await interaction.response.send_message("> You dont have access gng .. ask the owner.", ephemeral=True)

    embed = discord.Embed(title="Nighty Infinite Loading Fix", color=embed_color)
    embed.description = (
        "> 1. Download a VPN (ProtonVPN is free)\n"
        "> 2. Close Nighty or end `nighty.exe` task\n"
        "> 3. Open the VPN & wait for it to connect\n"
        "> 4. Run Nighty as **admin**\n"
        "> 5. Once Nighty loads, you can disconnect VPN"
    )
    await send_embed_with_ping(interaction, embed, ping)

@bot.tree.command(name="cmd", description="Fix for CMD prompt issues")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(ping="Optional: Mention someone outside the embed")
@command_cooldown
async def cmd_fix(interaction: discord.Interaction, ping: discord.User = None):
    if not has_access(interaction.user.id):
        return await interaction.response.send_message("> You dont have access gng .. ask the owner.", ephemeral=True)

    embed = discord.Embed(title="Nighty CMD Prompt Fix", color=embed_color)
    embed.description = (
        "> 1. Press `WIN + R`\n"
        "> 2. Type `%appdata%`\n"
        "> 3. Find `Nighty Selfbot`\n"
        "> 4. Delete `nighty.config`\n"
        "> 5. Restart Nighty as Admin"
    )
    await send_embed_with_ping(interaction, embed, ping)

@bot.tree.command(name="rpc", description="Fix for Rich Presence not showing")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(ping="Optional: Mention someone outside the embed")
@command_cooldown
async def presence_fix(interaction: discord.Interaction, ping: discord.User = None):
    if not has_access(interaction.user.id):
        return await interaction.response.send_message("> You dont have access gng .. ask the owner.", ephemeral=True)

    embed = discord.Embed(title="Rich Presence Troubleshooting", color=embed_color)
    embed.description = (
        "> 1. Set your Discord status to: ``Online``, ``Do Not Disturb``, or ``Idle``\n"
        "> 2. If using custom images → Upload to [`Imgur`](https://imgur.com/) → Copy ``Direct Image URL``\n"
        "> Enable Activity Privacy:\n"
        "> 3. ``User Settings`` → ``Activity Privacy`` → ``Enable all options``\n"
        "> Enable Server Activity Privacy:\n"
        "> 4. ``Click server name`` → ``Privacy Settings`` → ``Enable both options``"
    )
    await send_embed_with_ping(interaction, embed, ping)


@bot.tree.command(name="safe", description="Nighty safety information")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(ping="Optional: Mention someone outside the embed")
@command_cooldown
async def safety_info(interaction: discord.Interaction, ping: discord.User = None):
    if not has_access(interaction.user.id):
        return await interaction.response.send_message("> You dont have access gng .. ask the owner.", ephemeral=True)

    embed = discord.Embed(title="Is Nighty Safe?", color=embed_color)
    embed.description = (
        "> Yes, Nighty is safe to use.\n\n"
        "> We test thoroughly to ensure it is **undetectable**.\n"
        "> Reminder: Discord **prohibits selfbots** in ToS.\n"
        "> Ban reports in last 3 years: **0**\n\n"
        "So technically against ToS, but in practice no bans happened."
    )
    await send_embed_with_ping(interaction, embed, ping)

@bot.tree.command(name="ticket", description="Instructions for creating a support ticket")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(ping="Optional: Mention someone outside the embed")
@command_cooldown
async def ticket_info(interaction: discord.Interaction, ping: discord.User = None):
    if not has_access(interaction.user.id):
        return await interaction.response.send_message("> You dont have access gng .. ask the owner.", ephemeral=True)

    embed = discord.Embed(title="How to Make a Ticket", color=embed_color)
    embed.description = (
        "> Type `//newticket` in any channel you can type in.\n"
        "> Or use this link: https://nighty.support"
    )
    await send_embed_with_ping(interaction, embed, ping)

@bot.tree.command(name="discordfix", description="Fix for Discord links opening in Canary")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(ping="Optional: Mention someone outside the embed")
@command_cooldown
async def discord_fix(interaction: discord.Interaction, ping: discord.User = None):
    if not has_access(interaction.user.id):
        return await interaction.response.send_message("> You dont have access gng .. ask the owner.", ephemeral=True)

    embed = discord.Embed(title="Discord Canary Link Fix", color=embed_color)
    embed.description = (
        "> 1. Download this bat file: https://discordfix.niggy.one\n"
        "> 2. Run the file\n"
        "> 3. Restart Nighty"
    )
    await send_embed_with_ping(interaction, embed, ping)

@bot.tree.command(name="authbot", description="Get the bot authorization link")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@command_cooldown
async def auth_bot(interaction: discord.Interaction):
    if not has_access(interaction.user.id):
        return await interaction.response.send_message("> You dont have access gng .. ask the owner.", ephemeral=True)

    message = "https://discord.com/oauth2/authorize?client_id=1423488983148531763"

    await interaction.response.send_message(message, ephemeral=False)

@bot.tree.command(name="prefix", description="Understanding <p> commands")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(ping="Optional: Mention someone outside the embed")
@command_cooldown
async def prefix_cmd(interaction: discord.Interaction, ping: discord.User = None):
    if not has_access(interaction.user.id):
        return await interaction.response.send_message("> You dont have access gng .. ask the owner.", ephemeral=True)

    embed = discord.Embed(title="Understanding <p>", color=embed_color)
    embed.description = (
        "> 1. You will see ``<p>`` in a script’s Usage section (usually at the top).\n"
        "> 2. ``<p>`` means prefix.\n"
        "> 3. The default prefix is → ``.`` (a period).\n"
        "> 4. Example: ``<p>lock`` = ``.lock``\n"
        "> 5. You can change your prefix anytime with → ``/settings prefix``"
    )
    await send_embed_with_ping(interaction, embed, ping)

@bot.tree.command(name="legacy", description="Legacy commands")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(ping="Optional: Mention someone outside the embed")
@command_cooldown
async def legacy_cmd(interaction: discord.Interaction, ping: discord.User = None):
    # Removed access check if you want anyone to use it
    embed = discord.Embed(title="Legacy Commands", color=embed_color)
    embed.description = (
        "> All of Nighty's commands are `/` commands other than scripts.\n"
        "> However, if you wish to use all of Nighty's commands as prefix commands, "
        "you can use the `Legacy Commands` script."
    )
    await send_embed_with_ping(interaction, embed, ping)

# ------------------ QUOTE COMMAND ------------------

async def generate_quote(interaction: discord.Interaction, message: discord.Message):
    if not has_access(interaction.user.id):
        return await interaction.response.send_message("> You dont have access gng .. ask the owner.", ephemeral=True)

    await interaction.response.defer()

    try:
        if not message.content:
            return await interaction.followup.send("> The selected message must contain text.", ephemeral=True)

        author = message.author
        display_name = author.display_name or author.name
        username = author.name
        avatar_url = str(author.avatar.url) if getattr(author, "avatar", None) else str(author.default_avatar.url)
        message_text = message.content

        quote_data = {
            "username": username,
            "display_name": display_name,
            "text": message_text,
            "avatar": avatar_url,
            "color": True,
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(API_URL, json=quote_data) as response:
                response_text = await response.text()
                url_match = re.search(r'https?://[^\s"]+\.png', response_text)
                if not url_match:
                    return await interaction.followup.send("> Failed to generate quote image", ephemeral=True)

                png_url = url_match.group(0)

                async with session.get(png_url) as img_resp:
                    if img_resp.status != 200:
                        return await interaction.followup.send("> Failed to download generated image.", ephemeral=True)
                    img_bytes = await img_resp.read()

                try:
                    from PIL import Image
                    buf = io.BytesIO(img_bytes)
                    img = Image.open(buf)

                    gif_bytes = io.BytesIO()
                    if img.mode not in ("L", "P"):
                        img = img.convert("RGBA")
                    img.save(gif_bytes, format="GIF")
                    gif_bytes.seek(0)

                    await interaction.followup.send(file=discord.File(gif_bytes, "quote.gif"))

                except ModuleNotFoundError:
                    await interaction.followup.send(png_url)
                    print("Pillow not installed -- send png link instead. Install via: pip install pillow")

                except Exception as e:
                    print(f"Error converting quote PNG to GIF: {e}")
                    await interaction.followup.send(png_url)

    except Exception as e:
        await interaction.followup.send("> An unexpected error occurred while generating the quote.", ephemeral=True)
        print(f"Error in generate_quote: {str(e)}")

@bot.tree.context_menu(name="Quote")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@command_cooldown
async def quote_context_menu(interaction: discord.Interaction, message: discord.Message):
    await generate_quote(interaction, message)


# ------------------ GIF COMMAND ------------------

@bot.tree.command(name="gif", description="Convert an image (PNG/JPG) into a GIF file")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@app_commands.describe(image="Upload an image", url="Or provide an image link")
@command_cooldown
async def gif_cmd(interaction: discord.Interaction, image: discord.Attachment = None, url: str = None):
    if not has_access(interaction.user.id):
        return await interaction.response.send_message("> You dont have access gng .. ask the owner.", ephemeral=True)

    if not image and not url:
        return await interaction.response.send_message("> You must upload an image or provide a link.", ephemeral=True)

    await interaction.response.defer()

    try:
        import aiohttp, io
        from PIL import Image

        image_url = url or image.url

        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as resp:
                if resp.status != 200:
                    return await interaction.followup.send("> Failed to download the image.", ephemeral=True)
                data = await resp.read()

        img = Image.open(io.BytesIO(data))

        gif_bytes = io.BytesIO()
        img.save(gif_bytes, format="GIF")
        gif_bytes.seek(0)

        await interaction.followup.send(file=discord.File(gif_bytes, "converted.gif"))

    except Exception as e:
        await interaction.followup.send("> An unexpected error occurred while converting the image.", ephemeral=True)
        print(f"Error in /gif: {str(e)}")

@bot.tree.command(name="nightyauth", description="Power nighty auth")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@command_cooldown
async def nighty_auth(interaction: discord.Interaction):
    await interaction.response.send_message("https://i.imgur.com/5Kupoxu.gif")

@bot.tree.command(name="dexter", description="I knew you where a fucking creep")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
@command_cooldown
async def dexter(interaction: discord.Interaction):
    await interaction.response.send_message("https://files.catbox.moe/vanxj7.mp4")

# ------------------ RUN BOT ------------------
bot.run(TOKEN)
