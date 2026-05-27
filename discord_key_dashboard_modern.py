import asyncio
import csv
import json
import threading
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import discord
from discord.ext import commands

APP_DIR = Path(__file__).resolve().parent / "dashboard_config"
APP_DIR.mkdir(exist_ok=True)
AUTOSAVE_PATH = APP_DIR / "state.json"
LOG_PATH = APP_DIR / "dashboard.log"

COLOURS = {
    "bg": "#070b16",
    "sidebar": "#0a1020",
    "panel": "#0d1427",
    "panel_2": "#111a31",
    "input": "#0b1223",
    "border": "#273760",
    "text": "#f0f5ff",
    "muted": "#90a2cb",
    "purple": "#6c63ff",
    "purple_2": "#3b45d9",
    "green": "#38d16a",
    "red": "#e04f5f",
    "orange": "#ffb648",
    "blue": "#43b5ff",
}


@dataclass
class GuildRoleSnapshot:
    guild_id: int
    guild_name: str
    roles: list[tuple[int, str]]


@dataclass
class ClaimEvent:
    user_id: int
    username: str
    key: str
    timestamp: str


@dataclass
class ServerSettings:
    prefix: str = "!"
    allowed_roles: set[int] = field(default_factory=set)
    default_keys_per_request: int = 1
    claim_cooldown_hours: int = 24


class KeyDistributor:
    def __init__(self):
        self.keys: list[str] = []
        self.claimed: dict[int, list[str]] = defaultdict(list)
        self.claim_history: list[ClaimEvent] = []
        self.allowed_users: set[int] = set()
        self.custom_commands: dict[str, str] = {}
        self.server_settings: dict[int, ServerSettings] = defaultdict(ServerSettings)
        self.username_cache: dict[int, str] = {}
        self.last_claim_at: dict[int, str] = {}
        self.max_claims_per_user = 1
        self.prevent_duplicate_claim = True
        self.lock_mode = False
        self.lock = threading.Lock()

    @staticmethod
    def normalise_command_name(name: str) -> str:
        return "".join(ch for ch in name.strip().lower() if ch.isalnum() or ch == "_")

    def import_preview(self, file_path: str):
        lines = Path(file_path).read_text(encoding="utf-8").splitlines()
        stripped = [line.strip() for line in lines]
        non_empty = [line for line in stripped if line]
        deduped = list(dict.fromkeys(non_empty))
        return {
            "total_lines": len(lines),
            "empty_removed": len(lines) - len(non_empty),
            "duplicates_removed": len(non_empty) - len(deduped),
            "final_count": len(deduped),
            "keys": deduped,
        }

    def load_keys(self, keys: list[str]):
        with self.lock:
            self.keys = list(keys)

    def add_allowed_user(self, user_id: int):
        with self.lock:
            self.allowed_users.add(user_id)

    def remove_allowed_user(self, user_id: int):
        with self.lock:
            self.allowed_users.discard(user_id)

    def load_allowed_users_from_lines(self, lines: list[str]) -> tuple[int, int]:
        added = 0
        skipped = 0
        with self.lock:
            for line in lines:
                clean = line.strip().split(",")[0]
                if not clean:
                    continue
                try:
                    uid = int(clean)
                except ValueError:
                    skipped += 1
                    continue
                if uid in self.allowed_users:
                    skipped += 1
                else:
                    self.allowed_users.add(uid)
                    added += 1
        return added, skipped

    def grant_role(self, guild_id: int, role_id: int):
        with self.lock:
            self.server_settings[guild_id].allowed_roles.add(role_id)

    def revoke_role(self, guild_id: int, role_id: int):
        with self.lock:
            self.server_settings[guild_id].allowed_roles.discard(role_id)

    def can_claim(self, user_id: int, guild_id: int, role_ids: list[int]) -> tuple[bool, str]:
        with self.lock:
            if self.lock_mode:
                return False, "Emergency lock mode is enabled."
            settings = self.server_settings[guild_id]
            has_role = any(role_id in settings.allowed_roles for role_id in role_ids)
            if user_id not in self.allowed_users and not has_role:
                return False, "You are not allowed to receive keys."
            if self.prevent_duplicate_claim and self.claimed.get(user_id):
                return False, "You have already claimed a key."
            if len(self.claimed.get(user_id, [])) >= self.max_claims_per_user:
                return False, f"You have reached the claim limit of {self.max_claims_per_user}."
            if user_id in self.last_claim_at:
                last = datetime.fromisoformat(self.last_claim_at[user_id])
                cooldown_end = last + timedelta(hours=settings.claim_cooldown_hours)
                if datetime.utcnow() < cooldown_end:
                    return False, f"Claim cooldown active until {cooldown_end.isoformat(timespec='seconds')} UTC."
        return True, "User can claim."

    def give_keys(self, user_id: int, username: str, guild_id: int, count: int | None = None) -> tuple[list[str], str]:
        with self.lock:
            settings = self.server_settings[guild_id]
            amount = count if count is not None else settings.default_keys_per_request
            amount = max(1, amount)
            if not self.keys:
                return [], "No keys available."
            given = self.keys[:amount]
            self.keys = self.keys[amount:]
            now = datetime.utcnow().isoformat(timespec="seconds")
            self.claimed[user_id].extend(given)
            self.username_cache[user_id] = username
            self.last_claim_at[user_id] = now
            for key in given:
                self.claim_history.append(ClaimEvent(user_id, username, key, now))
            return given, "Keys granted."

    def summary(self):
        with self.lock:
            return {
                "remaining": len(self.keys),
                "allowed": len(self.allowed_users),
                "claimed_users": len([uid for uid, vals in self.claimed.items() if vals]),
                "claimed_total": sum(len(vals) for vals in self.claimed.values()),
                "commands": len(self.custom_commands),
                "servers": len(self.server_settings),
            }

    def save_state(self, file_path: str):
        with self.lock:
            data = {
                "remaining_keys": self.keys,
                "allowed_users": sorted(self.allowed_users),
                "custom_commands": self.custom_commands,
                "claimed": {str(uid): keys for uid, keys in self.claimed.items()},
                "claim_history": [asdict(event) for event in self.claim_history],
                "username_cache": {str(uid): name for uid, name in self.username_cache.items()},
                "last_claim_at": {str(uid): stamp for uid, stamp in self.last_claim_at.items()},
                "server_settings": {
                    str(gid): {
                        "prefix": settings.prefix,
                        "allowed_roles": sorted(settings.allowed_roles),
                        "default_keys_per_request": settings.default_keys_per_request,
                        "claim_cooldown_hours": settings.claim_cooldown_hours,
                    }
                    for gid, settings in self.server_settings.items()
                },
                "max_claims_per_user": self.max_claims_per_user,
                "prevent_duplicate_claim": self.prevent_duplicate_claim,
                "lock_mode": self.lock_mode,
            }
        path = Path(file_path)
        if path.exists():
            stamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
            backup = path.with_name(f"state_backup_{stamp}.json")
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_state(self, file_path: str):
        data = json.loads(Path(file_path).read_text(encoding="utf-8"))
        with self.lock:
            self.keys = list(data.get("remaining_keys", []))
            self.allowed_users = {int(uid) for uid in data.get("allowed_users", [])}
            self.custom_commands = dict(data.get("custom_commands", {}))
            self.claimed = defaultdict(list, {int(uid): list(keys) for uid, keys in data.get("claimed", {}).items()})
            self.claim_history = [ClaimEvent(**event) for event in data.get("claim_history", [])]
            self.username_cache = {int(uid): name for uid, name in data.get("username_cache", {}).items()}
            self.last_claim_at = {int(uid): stamp for uid, stamp in data.get("last_claim_at", {}).items()}
            loaded = defaultdict(ServerSettings)
            for gid, values in data.get("server_settings", {}).items():
                loaded[int(gid)] = ServerSettings(
                    prefix=values.get("prefix", "!"),
                    allowed_roles={int(role_id) for role_id in values.get("allowed_roles", [])},
                    default_keys_per_request=int(values.get("default_keys_per_request", 1)),
                    claim_cooldown_hours=int(values.get("claim_cooldown_hours", 24)),
                )
            self.server_settings = loaded
            self.max_claims_per_user = int(data.get("max_claims_per_user", 1))
            self.prevent_duplicate_claim = bool(data.get("prevent_duplicate_claim", True))
            self.lock_mode = bool(data.get("lock_mode", False))


class BotController:
    def __init__(self, distributor: KeyDistributor, log_cb, status_cb, guild_sync_cb, autosave_cb):
        self.dist = distributor
        self.log_cb = log_cb
        self.status_cb = status_cb
        self.guild_sync_cb = guild_sync_cb
        self.autosave_cb = autosave_cb
        self.bot: commands.Bot | None = None
        self.thread: threading.Thread | None = None
        self.running = False

    async def validate_token(self, token: str):
        bot = commands.Bot(command_prefix="!", intents=discord.Intents.none())
        try:
            await bot.login(token)
            await bot.close()
            return True, "Token is valid."
        except discord.LoginFailure:
            return False, "Invalid bot token."
        except Exception as exc:
            return False, f"Token validation failed: {exc}"

    def start(self, token: str, prefix: str):
        if self.running:
            self.log_cb("WARNING", "Bot is already running.")
            return

        try:
            ok, msg = asyncio.run(self.validate_token(token))
        except Exception as exc:
            self.status_cb("Offline")
            self.log_cb("ERROR", f"Token check failed: {exc}")
            return

        if not ok:
            self.status_cb("Offline")
            self.log_cb("ERROR", msg)
            return

        def runner():
            intents = discord.Intents.default()
            intents.message_content = True
            intents.members = True
            self.bot = commands.Bot(command_prefix=prefix, intents=intents)
            self.status_cb("Starting")

            @self.bot.event
            async def on_ready():
                self.running = True
                self.status_cb("Online")
                self.log_cb("SUCCESS", f"Logged in as {self.bot.user}")
                snapshots = []
                for guild in self.bot.guilds:
                    roles = [(role.id, role.name) for role in guild.roles if not role.managed]
                    roles.sort(key=lambda item: item[1].lower())
                    snapshots.append(GuildRoleSnapshot(guild.id, f"{guild.name} ({guild.id})", roles))
                self.guild_sync_cb(snapshots)

            @self.bot.command(name="getkeys")
            async def getkeys(ctx, count: int | None = None):
                if not ctx.guild:
                    await ctx.reply("Use this command inside a server channel.")
                    return
                role_ids = [role.id for role in getattr(ctx.author, "roles", [])]
                can, reason = self.dist.can_claim(ctx.author.id, ctx.guild.id, role_ids)
                if not can:
                    await ctx.reply(reason)
                    self.log_cb("WARNING", f"Claim denied for {ctx.author}: {reason}")
                    return
                keys, reason = self.dist.give_keys(ctx.author.id, str(ctx.author), ctx.guild.id, count)
                if not keys:
                    await ctx.reply(reason)
                    self.log_cb("WARNING", reason)
                    return
                try:
                    await ctx.author.send("Your keys:\n" + "\n".join(keys))
                    await ctx.reply(f"Sent {len(keys)} key(s) in DM.")
                    self.log_cb("SUCCESS", f"Sent {len(keys)} key(s) to {ctx.author} ({ctx.author.id})")
                    self.autosave_cb()
                except discord.Forbidden:
                    await ctx.reply("I cannot DM you. Open your DMs and try again.")
                    self.log_cb("ERROR", f"Failed to DM {ctx.author} ({ctx.author.id})")

            for command_name, response in self.dist.custom_commands.items():
                clean = self.dist.normalise_command_name(command_name)
                if not clean or self.bot.get_command(clean):
                    continue

                async def custom_reply(ctx, text=response):
                    await ctx.reply(text)

                self.bot.command(name=clean)(custom_reply)

            try:
                self.bot.run(token)
            except Exception as exc:
                self.status_cb("Crashed")
                self.log_cb("ERROR", f"Bot crashed: {exc}")
            finally:
                self.running = False
                self.status_cb("Offline")

        self.thread = threading.Thread(target=runner, daemon=True)
        self.thread.start()
        self.log_cb("INFO", "Bot thread started.")

    def stop(self):
        if not self.bot or not self.running:
            self.log_cb("WARNING", "Bot is not running.")
            return

        async def shutdown():
            await self.bot.close()

        try:
            loop = self.bot.loop
            asyncio.run_coroutine_threadsafe(shutdown(), loop)
            self.log_cb("INFO", "Stop request sent.")
        except Exception as exc:
            self.log_cb("ERROR", f"Failed to stop bot: {exc}")


class ModernDashboard:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Discord Key Distributor Dashboard")
        self.root.geometry("1550x980")
        self.root.minsize(1280, 780)
        self.root.configure(bg=COLOURS["bg"])

        self.dist = KeyDistributor()
        self.status = tk.StringVar(value="Offline")
        self.token_var = tk.StringVar()
        self.prefix_var = tk.StringVar(value="!")
        self.theme_var = tk.StringVar(value="True Dark")
        self.search_keys = tk.StringVar()
        self.search_allowed_users = tk.StringVar()
        self.search_claimed = tk.StringVar()
        self.search_roles = tk.StringVar()
        self.search_commands = tk.StringVar()
        self.user_id_var = tk.StringVar()
        self.command_name_var = tk.StringVar()
        self.command_reply_var = tk.StringVar()
        self.only_allowed_roles_var = tk.BooleanVar(value=False)
        self.mask_keys_var = tk.BooleanVar(value=True)
        self.guild_data: dict[str, GuildRoleSnapshot] = {}

        self.controller = BotController(self.dist, self.log, self.set_status, self.sync_guilds, self.autosave)

        self.style = ttk.Style(self.root)
        self.setup_styles()
        self.build_ui()
        self.bind_refreshes()

        if AUTOSAVE_PATH.exists():
            try:
                self.dist.load_state(str(AUTOSAVE_PATH))
                self.log("INFO", "Loaded autosaved state.")
            except Exception as exc:
                self.log("ERROR", f"Could not load autosave: {exc}")

        self.refresh_all()

    def setup_styles(self):
        self.style.theme_use("clam")
        self.style.configure("TCombobox", fieldbackground=COLOURS["input"], background=COLOURS["input"], foreground=COLOURS["text"], arrowcolor=COLOURS["text"], bordercolor=COLOURS["border"])
        self.style.map("TCombobox", fieldbackground=[("readonly", COLOURS["input"])] , foreground=[("readonly", COLOURS["text"])])

    def make_frame(self, parent, bg=None, **kwargs):
        return tk.Frame(parent, bg=bg or COLOURS["panel"], **kwargs)

    def make_panel(self, parent, **kwargs):
        frame = tk.Frame(parent, bg=COLOURS["panel"], highlightbackground=COLOURS["border"], highlightthickness=1, **kwargs)
        return frame

    def label(self, parent, text, size=10, weight="normal", colour=None, bg=None, **kwargs):
        return tk.Label(parent, text=text, font=("Segoe UI", size, weight), fg=colour or COLOURS["text"], bg=bg or parent.cget("bg"), anchor="w", **kwargs)

    def button(self, parent, text, command=None, bg=None, fg=None, width=None):
        return tk.Button(parent, text=text, command=command, bg=bg or COLOURS["purple_2"], fg=fg or COLOURS["text"], activebackground=COLOURS["purple"], activeforeground="white", bd=0, padx=12, pady=8, width=width, font=("Segoe UI", 9), cursor="hand2")

    def entry(self, parent, textvariable=None, show=None):
        return tk.Entry(parent, textvariable=textvariable, show=show, bg=COLOURS["input"], fg=COLOURS["text"], insertbackground=COLOURS["text"], relief="flat", highlightbackground=COLOURS["border"], highlightcolor=COLOURS["purple"], highlightthickness=1, font=("Segoe UI", 10))

    def listbox(self, parent):
        return tk.Listbox(parent, bg=COLOURS["input"], fg=COLOURS["text"], selectbackground=COLOURS["purple"], selectforeground="white", relief="flat", highlightbackground=COLOURS["border"], highlightthickness=1, font=("Consolas", 10), activestyle="none")

    def build_ui(self):
        root = self.make_frame(self.root, COLOURS["bg"])
        root.pack(fill="both", expand=True)

        self.sidebar = self.make_frame(root, COLOURS["sidebar"], width=210)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        content = self.make_frame(root, COLOURS["bg"])
        content.pack(side="left", fill="both", expand=True)

        self.build_sidebar()
        self.build_top_controls(content)
        self.build_dashboard(content)
        self.build_footer(content)

    def build_sidebar(self):
        header = self.make_frame(self.sidebar, COLOURS["sidebar"])
        header.pack(fill="x", padx=14, pady=(14, 18))
        self.label(header, "🔑  Discord Key", 13, "bold", bg=COLOURS["sidebar"]).pack(fill="x")
        self.label(header, "Distributor Dashboard", 10, "normal", COLOURS["muted"], COLOURS["sidebar"]).pack(fill="x")

        nav_items = ["🏠  Dashboard", "🔑  Keys", "👥  Users", "🛡  Roles & Servers", "⚙  Commands", "💬  Messages", "📄  Logs", "📊  Analytics", "💾  Backups", "🔧  Tools"]
        for item in nav_items:
            active = item.startswith("🏠")
            btn = self.button(self.sidebar, item, bg=COLOURS["purple_2"] if active else COLOURS["sidebar"])
            btn.config(anchor="w", padx=18)
            btn.pack(fill="x", padx=10, pady=3)

        bottom = self.make_panel(self.sidebar)
        bottom.pack(side="bottom", fill="x", padx=10, pady=10)
        self.label(bottom, "Bot Status", 9, "normal", COLOURS["muted"]).pack(fill="x", padx=10, pady=(10, 2))
        self.sidebar_status = self.label(bottom, "Offline", 14, "bold", COLOURS["red"])
        self.sidebar_status.pack(fill="x", padx=10)
        self.label(bottom, "Logged in as\nNot connected", 8, "normal", COLOURS["muted"]).pack(fill="x", padx=10, pady=(6, 10))
        self.button(bottom, "■  Stop Bot", self.stop_bot, COLOURS["purple_2"]).pack(fill="x", padx=10, pady=(0, 8))
        self.button(bottom, "🔒  Emergency Lock", self.toggle_lock, COLOURS["red"]).pack(fill="x", padx=10, pady=(0, 10))

    def build_top_controls(self, parent):
        top = self.make_panel(parent)
        top.pack(fill="x", padx=12, pady=(12, 8))

        left = self.make_frame(top)
        left.pack(side="left", fill="both", expand=True, padx=12, pady=12)

        row = self.make_frame(left)
        row.pack(fill="x")
        token_box = self.make_frame(row)
        token_box.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.label(token_box, "Bot Token", 9, colour=COLOURS["muted"]).pack(fill="x", pady=(0, 4))
        token_row = self.make_frame(token_box)
        token_row.pack(fill="x")
        self.token_entry = self.entry(token_row, self.token_var, show="*")
        self.token_entry.pack(side="left", fill="x", expand=True, ipady=7)
        self.button(token_row, "👁", self.toggle_token, COLOURS["input"], width=3).pack(side="left", padx=(6, 0))

        prefix_box = self.make_frame(row)
        prefix_box.pack(side="left", padx=(0, 12))
        self.label(prefix_box, "Prefix", 9, colour=COLOURS["muted"]).pack(fill="x", pady=(0, 4))
        self.entry(prefix_box, self.prefix_var).pack(ipady=7)

        btn_box = self.make_frame(row)
        btn_box.pack(side="left")
        self.label(btn_box, " ", 9).pack(fill="x", pady=(0, 4))
        self.button(btn_box, "▶  Start Bot", self.start_bot, COLOURS["green"], width=14).pack(side="left", padx=4)
        self.button(btn_box, "↻  Restart", self.restart_bot, COLOURS["purple_2"], width=12).pack(side="left", padx=4)
        self.button(btn_box, "■  Stop Bot", self.stop_bot, COLOURS["red"], width=12).pack(side="left", padx=4)

        meta = self.make_frame(left)
        meta.pack(fill="x", pady=(12, 0))
        ttk.Combobox(meta, textvariable=self.theme_var, values=["True Dark", "Dark Pink"], state="readonly", width=16).pack(side="left")
        self.token_status_label = self.label(meta, "  ● Token not checked", 10, colour=COLOURS["muted"])
        self.token_status_label.pack(side="left", padx=18)
        self.label(meta, "Latency: --", 10, colour=COLOURS["green"]).pack(side="left", padx=14)
        self.server_count_label = self.label(meta, "Servers: 0", 10, colour=COLOURS["text"])
        self.server_count_label.pack(side="left", padx=14)

        checklist = self.make_panel(top)
        checklist.pack(side="right", fill="y", padx=12, pady=12)
        self.label(checklist, "Setup Checklist", 11, "bold").pack(fill="x", padx=12, pady=(10, 6))
        self.checklist_labels = {}
        for item in ["Token Added", "Bot Online", "Keys Loaded", "Servers Detected", "Role Access Set", "Message Content Intent"]:
            lbl = self.label(checklist, f"○  {item}", 9, colour=COLOURS["muted"])
            lbl.pack(fill="x", padx=12, pady=2)
            self.checklist_labels[item] = lbl

    def build_dashboard(self, parent):
        dash = self.make_frame(parent, COLOURS["bg"])
        dash.pack(fill="both", expand=True, padx=12, pady=4)

        cards = self.make_frame(dash, COLOURS["bg"])
        cards.pack(fill="x", pady=(0, 8))
        self.card_labels = {}
        for title, icon, colour, key in [
            ("Keys Overview", "🔑", COLOURS["purple"], "keys"),
            ("Users Overview", "👥", COLOURS["blue"], "users"),
            ("Claims Overview", "📈", COLOURS["green"], "claims"),
            ("Servers", "🖥", COLOURS["orange"], "servers"),
        ]:
            card = self.make_panel(cards)
            card.pack(side="left", fill="both", expand=True, padx=(0, 8))
            self.label(card, f"{icon}  {title}", 10, "bold", colour).pack(fill="x", padx=14, pady=(12, 4))
            number = self.label(card, "0", 22, "bold")
            number.pack(fill="x", padx=14)
            sub = self.label(card, "", 9, colour=COLOURS["muted"])
            sub.pack(fill="x", padx=14, pady=(0, 12))
            self.card_labels[key] = (number, sub)

        middle = self.make_frame(dash, COLOURS["bg"])
        middle.pack(fill="both", expand=True)
        self.build_keys_panel(middle)
        self.build_claimed_panel(middle)
        self.build_allowed_users_panel(middle)
        self.build_roles_panel(middle)

        bottom = self.make_frame(dash, COLOURS["bg"])
        bottom.pack(fill="both", expand=True, pady=(8, 0))
        self.build_commands_panel(bottom)
        self.build_logs_panel(bottom)
        self.build_analytics_panel(bottom)

    def build_keys_panel(self, parent):
        panel = self.make_panel(parent)
        panel.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.keys_title = self.label(panel, "Keys", 11, "bold")
        self.keys_title.pack(fill="x", padx=10, pady=(10, 4))
        self.entry(panel, self.search_keys).pack(fill="x", padx=10, ipady=5)
        self.keys_list = self.listbox(panel)
        self.keys_list.pack(fill="both", expand=True, padx=10, pady=8)
        buttons = self.make_frame(panel)
        buttons.pack(fill="x", padx=10, pady=(0, 8))
        self.button(buttons, "Import Keys", self.load_keys, COLOURS["purple_2"]).pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.button(buttons, "Export", self.export_keys, COLOURS["input"]).pack(side="left", fill="x", expand=True, padx=4)
        self.button(buttons, "Clear", self.clear_keys, COLOURS["red"]).pack(side="left", fill="x", expand=True, padx=(4, 0))
        tk.Checkbutton(panel, text="Mask keys", variable=self.mask_keys_var, command=self.refresh_keys, bg=COLOURS["panel"], fg=COLOURS["text"], selectcolor=COLOURS["input"], activebackground=COLOURS["panel"], activeforeground=COLOURS["text"]).pack(anchor="w", padx=10, pady=(0, 8))

    def build_claimed_panel(self, parent):
        panel = self.make_panel(parent)
        panel.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.claimed_title = self.label(panel, "Users Who Gained Keys", 11, "bold")
        self.claimed_title.pack(fill="x", padx=10, pady=(10, 4))
        self.entry(panel, self.search_claimed).pack(fill="x", padx=10, ipady=5)
        self.claimed_list = self.listbox(panel)
        self.claimed_list.pack(fill="both", expand=True, padx=10, pady=8)
        self.claimed_list.bind("<<ListboxSelect>>", self.show_claim_history)
        buttons = self.make_frame(panel)
        buttons.pack(fill="x", padx=10, pady=(0, 8))
        self.button(buttons, "View Details", self.show_claim_history, COLOURS["purple_2"]).pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.button(buttons, "Export CSV", self.export_claims_csv, COLOURS["input"]).pack(side="left", fill="x", expand=True, padx=(4, 0))

    def build_allowed_users_panel(self, parent):
        panel = self.make_panel(parent)
        panel.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.users_title = self.label(panel, "Allowed Users", 11, "bold")
        self.users_title.pack(fill="x", padx=10, pady=(10, 4))
        self.entry(panel, self.search_allowed_users).pack(fill="x", padx=10, ipady=5)
        row = self.make_frame(panel)
        row.pack(fill="x", padx=10, pady=8)
        self.entry(row, self.user_id_var).pack(side="left", fill="x", expand=True, ipady=5)
        self.button(row, "Add", self.add_user, COLOURS["purple_2"]).pack(side="left", padx=(6, 0))
        self.allowed_users_list = self.listbox(panel)
        self.allowed_users_list.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        buttons = self.make_frame(panel)
        buttons.pack(fill="x", padx=10, pady=(0, 8))
        self.button(buttons, "Import", self.import_users, COLOURS["input"]).pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.button(buttons, "Remove", self.remove_selected_user, COLOURS["red"]).pack(side="left", fill="x", expand=True, padx=(4, 0))

    def build_roles_panel(self, parent):
        panel = self.make_panel(parent)
        panel.pack(side="left", fill="both", expand=True)
        self.label(panel, "Allowed Roles (per server)", 11, "bold").pack(fill="x", padx=10, pady=(10, 4))
        self.guild_combo = ttk.Combobox(panel, state="readonly")
        self.guild_combo.pack(fill="x", padx=10, pady=(0, 8))
        self.guild_combo.bind("<<ComboboxSelected>>", lambda _e: self.refresh_roles())
        self.entry(panel, self.search_roles).pack(fill="x", padx=10, ipady=5)
        tk.Checkbutton(panel, text="Only allowed roles", variable=self.only_allowed_roles_var, command=self.refresh_roles, bg=COLOURS["panel"], fg=COLOURS["text"], selectcolor=COLOURS["input"], activebackground=COLOURS["panel"], activeforeground=COLOURS["text"]).pack(anchor="w", padx=10, pady=6)
        self.roles_list = self.listbox(panel)
        self.roles_list.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        buttons = self.make_frame(panel)
        buttons.pack(fill="x", padx=10, pady=(0, 8))
        self.button(buttons, "Toggle Role", self.toggle_selected_role, COLOURS["purple_2"]).pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.button(buttons, "Sync Roles", self.refresh_roles, COLOURS["input"]).pack(side="left", fill="x", expand=True, padx=(4, 0))

    def build_commands_panel(self, parent):
        panel = self.make_panel(parent)
        panel.pack(side="left", fill="both", expand=True, padx=(0, 8))
        self.label(panel, "Custom Commands", 11, "bold").pack(fill="x", padx=10, pady=(10, 4))
        self.entry(panel, self.search_commands).pack(fill="x", padx=10, ipady=5)
        row = self.make_frame(panel)
        row.pack(fill="x", padx=10, pady=8)
        self.entry(row, self.command_name_var).pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 4))
        self.entry(row, self.command_reply_var).pack(side="left", fill="x", expand=True, ipady=5, padx=(4, 0))
        self.commands_list = self.listbox(panel)
        self.commands_list.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        buttons = self.make_frame(panel)
        buttons.pack(fill="x", padx=10, pady=(0, 8))
        self.button(buttons, "Add Command", self.save_command, COLOURS["purple_2"]).pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.button(buttons, "Delete", self.delete_command, COLOURS["red"]).pack(side="left", fill="x", expand=True, padx=(4, 0))

    def build_logs_panel(self, parent):
        panel = self.make_panel(parent)
        panel.pack(side="left", fill="both", expand=True, padx=(0, 8))
        row = self.make_frame(panel)
        row.pack(fill="x", padx=10, pady=(10, 4))
        self.label(row, "Recent Logs", 11, "bold").pack(side="left", fill="x", expand=True)
        self.button(row, "Clear", self.clear_logs, COLOURS["input"]).pack(side="right")
        self.log_text = tk.Text(panel, bg=COLOURS["input"], fg=COLOURS["text"], insertbackground=COLOURS["text"], relief="flat", highlightbackground=COLOURS["border"], highlightthickness=1, height=10, state="disabled", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        self.button(panel, "Open Log File", self.open_log_file, COLOURS["input"]).pack(anchor="w", padx=10, pady=(0, 8))

    def build_analytics_panel(self, parent):
        panel = self.make_panel(parent)
        panel.pack(side="left", fill="both", expand=True)
        self.label(panel, "Key Stats (7 Days)", 11, "bold").pack(fill="x", padx=10, pady=(10, 4))
        self.analytics_canvas = tk.Canvas(panel, bg=COLOURS["input"], highlightbackground=COLOURS["border"], highlightthickness=1, height=150)
        self.analytics_canvas.pack(fill="both", expand=True, padx=10, pady=8)
        self.button(panel, "View Analytics", self.draw_analytics, COLOURS["purple_2"]).pack(anchor="w", padx=10, pady=(0, 8))

    def build_footer(self, parent):
        footer = self.make_frame(parent, COLOURS["bg"], height=42)
        footer.pack(fill="x", padx=12, pady=(4, 10))
        footer.pack_propagate(False)
        self.footer_label = self.label(footer, "● Auto-save: Enabled   |   State file: dashboard_config/state.json", 9, colour=COLOURS["muted"], bg=COLOURS["bg"])
        self.footer_label.pack(side="left", padx=6)
        self.button(footer, "⚙ Settings", None, COLOURS["input"]).pack(side="right", padx=4, pady=6)
        self.button(footer, "💾 Backup Now", self.manual_backup, COLOURS["input"]).pack(side="right", padx=4, pady=6)

    def bind_refreshes(self):
        for var in [self.search_keys, self.search_allowed_users, self.search_claimed, self.search_roles, self.search_commands]:
            var.trace_add("write", lambda *_: self.refresh_all())

    def set_check(self, name, ok):
        if name in self.checklist_labels:
            self.checklist_labels[name].config(text=("●  " if ok else "○  ") + name, fg=COLOURS["green"] if ok else COLOURS["muted"])

    def set_status(self, status: str):
        self.root.after(0, lambda: self._set_status_ui(status))

    def _set_status_ui(self, status: str):
        self.status.set(status)
        colour = COLOURS["green"] if status == "Online" else COLOURS["orange"] if status == "Starting" else COLOURS["red"] if status == "Crashed" else COLOURS["muted"]
        self.sidebar_status.config(text=status, fg=colour)
        self.set_check("Bot Online", status == "Online")
        self.refresh_all()

    def toggle_token(self):
        self.token_entry.config(show="" if self.token_entry.cget("show") == "*" else "*")

    def start_bot(self):
        token = self.token_var.get().strip()
        if not token:
            messagebox.showwarning("Missing Token", "Enter your Discord bot token first.")
            return
        self.set_check("Token Added", True)
        self.token_status_label.config(text="  ● Checking token...", fg=COLOURS["orange"])
        self.controller.start(token, self.prefix_var.get().strip() or "!")
        self.token_status_label.config(text="  ● Token check started", fg=COLOURS["green"])

    def stop_bot(self):
        self.controller.stop()

    def restart_bot(self):
        self.stop_bot()
        self.root.after(1500, self.start_bot)

    def toggle_lock(self):
        self.dist.lock_mode = not self.dist.lock_mode
        self.autosave()
        self.log("WARNING", f"Emergency lock {'enabled' if self.dist.lock_mode else 'disabled'}.")

    def load_keys(self):
        path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            preview = self.dist.import_preview(path)
            msg = (
                f"Total lines: {preview['total_lines']}\n"
                f"Empty removed: {preview['empty_removed']}\n"
                f"Duplicates removed: {preview['duplicates_removed']}\n"
                f"Final usable keys: {preview['final_count']}\n\n"
                "Import these keys?"
            )
            if messagebox.askyesno("Key Import Preview", msg):
                self.dist.load_keys(preview["keys"])
                self.autosave()
                self.log("SUCCESS", f"Imported {preview['final_count']} key(s).")
                self.refresh_all()
        except Exception as exc:
            messagebox.showerror("Import Error", str(exc))

    def export_keys(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text files", "*.txt")])
        if not path:
            return
        Path(path).write_text("\n".join(self.dist.keys), encoding="utf-8")
        self.log("SUCCESS", f"Exported remaining keys to {path}")

    def clear_keys(self):
        if messagebox.askyesno("Clear Keys", "Remove all remaining keys from the dashboard?"):
            self.dist.keys.clear()
            self.autosave()
            self.refresh_all()
            self.log("WARNING", "Cleared remaining keys.")

    def add_user(self):
        try:
            uid = int(self.user_id_var.get().strip())
            self.dist.add_allowed_user(uid)
            self.user_id_var.set("")
            self.autosave()
            self.refresh_all()
            self.log("SUCCESS", f"Added allowed user {uid}")
        except ValueError:
            messagebox.showwarning("Invalid User ID", "User ID must be a number.")

    def remove_selected_user(self):
        selection = self.allowed_users_list.curselection()
        if not selection:
            return
        row = self.allowed_users_list.get(selection[0])
        try:
            uid = int(row.split("(")[-1].split(")")[0])
            self.dist.remove_allowed_user(uid)
            self.autosave()
            self.refresh_all()
            self.log("WARNING", f"Removed allowed user {uid}")
        except Exception:
            pass

    def import_users(self):
        path = filedialog.askopenfilename(filetypes=[("Text/CSV", "*.txt *.csv"), ("All files", "*.*")])
        if not path:
            return
        lines = Path(path).read_text(encoding="utf-8").splitlines()
        added, skipped = self.dist.load_allowed_users_from_lines(lines)
        self.autosave()
        self.refresh_all()
        self.log("SUCCESS", f"Imported allowed users. Added: {added}, skipped: {skipped}")

    def save_command(self):
        name = self.dist.normalise_command_name(self.command_name_var.get())
        reply = self.command_reply_var.get().strip()
        if not name or not reply:
            messagebox.showwarning("Invalid Command", "Command name and reply message are required.")
            return
        self.dist.custom_commands[name] = reply
        self.autosave()
        self.refresh_all()
        self.log("SUCCESS", f"Saved command !{name}")

    def delete_command(self):
        selection = self.commands_list.curselection()
        if not selection:
            return
        row = self.commands_list.get(selection[0])
        name = row.split(" ", 1)[0].replace("!", "")
        self.dist.custom_commands.pop(name, None)
        self.autosave()
        self.refresh_all()
        self.log("WARNING", f"Deleted command !{name}")

    def toggle_selected_role(self):
        selected_guild = self.guild_combo.get()
        selected_role = self.roles_list.curselection()
        if selected_guild not in self.guild_data or not selected_role:
            return
        snap = self.guild_data[selected_guild]
        row = self.roles_list.get(selected_role[0])
        role_id = int(row.split("(")[-1].split(")")[0])
        role_name = row.split(" ", 1)[1].rsplit(" (", 1)[0]
        allowed = self.dist.server_settings[snap.guild_id].allowed_roles
        if role_id in allowed:
            self.dist.revoke_role(snap.guild_id, role_id)
            self.log("WARNING", f"Revoked role access: {role_name}")
        else:
            self.dist.grant_role(snap.guild_id, role_id)
            self.log("SUCCESS", f"Granted role access: {role_name}")
        self.autosave()
        self.refresh_roles()

    def show_claim_history(self, _evt=None):
        selection = self.claimed_list.curselection()
        if not selection:
            return
        row = self.claimed_list.get(selection[0])
        uid = int(row.split("(")[-1].split(")")[0])
        events = [event for event in self.dist.claim_history if event.user_id == uid]
        if not events:
            messagebox.showinfo("Claim History", "No detailed history found for this user.")
            return
        text = "\n".join(f"{event.timestamp} - {event.key}" for event in events)
        messagebox.showinfo(f"Claim History - {uid}", text)

    def export_claims_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(["User ID", "Username", "Key", "Date Claimed"])
            for event in self.dist.claim_history:
                writer.writerow([event.user_id, event.username, event.key, event.timestamp])
        self.log("SUCCESS", f"Exported claims CSV to {path}")

    def clear_logs(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def open_log_file(self):
        LOG_PATH.touch(exist_ok=True)
        messagebox.showinfo("Log File", str(LOG_PATH))

    def manual_backup(self):
        stamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
        path = APP_DIR / f"manual_backup_{stamp}.json"
        self.dist.save_state(str(path))
        self.log("SUCCESS", f"Backup created: {path}")

    def autosave(self):
        try:
            self.dist.save_state(str(AUTOSAVE_PATH))
        except Exception as exc:
            self.log("ERROR", f"Autosave failed: {exc}")

    def sync_guilds(self, snapshots: list[GuildRoleSnapshot]):
        def apply():
            self.guild_data = {snap.guild_name: snap for snap in snapshots}
            self.guild_combo["values"] = list(self.guild_data.keys())
            if snapshots and not self.guild_combo.get():
                self.guild_combo.set(snapshots[0].guild_name)
            for snap in snapshots:
                _ = self.dist.server_settings[snap.guild_id]
            self.set_check("Servers Detected", bool(snapshots))
            self.server_count_label.config(text=f"Servers: {len(snapshots)}")
            self.autosave()
            self.refresh_all()
        self.root.after(0, apply)

    def refresh_all(self):
        if not hasattr(self, "keys_list"):
            return
        self.refresh_keys()
        self.refresh_allowed_users()
        self.refresh_claimed_users()
        self.refresh_commands()
        self.refresh_roles()
        self.refresh_cards()
        self.refresh_checklist()
        self.draw_analytics()

    def refresh_keys(self):
        query = self.search_keys.get().lower()
        self.keys_list.delete(0, "end")
        for key in self.dist.keys:
            if query and query not in key.lower():
                continue
            shown = self.mask_key(key) if self.mask_keys_var.get() else key
            self.keys_list.insert("end", shown)
        self.keys_title.config(text=f"Keys ({len(self.dist.keys)} remaining)")

    @staticmethod
    def mask_key(key: str):
        if len(key) <= 10:
            return "*" * len(key)
        return f"{key[:5]}-*****-{key[-5:]}"

    def refresh_allowed_users(self):
        query = self.search_allowed_users.get().lower()
        self.allowed_users_list.delete(0, "end")
        for uid in sorted(self.dist.allowed_users):
            name = self.dist.username_cache.get(uid, "Unknown")
            row = f"{name} ({uid})"
            if not query or query in row.lower():
                self.allowed_users_list.insert("end", row)
        self.users_title.config(text=f"Allowed Users ({len(self.dist.allowed_users)})")

    def refresh_claimed_users(self):
        query = self.search_claimed.get().lower()
        self.claimed_list.delete(0, "end")
        for uid, keys in sorted(self.dist.claimed.items()):
            if not keys:
                continue
            name = self.dist.username_cache.get(uid, "Unknown")
            row = f"{name} ({uid}) - {len(keys)} key(s)"
            if not query or query in row.lower():
                self.claimed_list.insert("end", row)
        self.claimed_title.config(text=f"Users Who Gained Keys ({len([u for u, k in self.dist.claimed.items() if k])})")

    def refresh_commands(self):
        query = self.search_commands.get().lower()
        self.commands_list.delete(0, "end")
        for name, reply in sorted(self.dist.custom_commands.items()):
            row = f"!{name}    {reply}"
            if not query or query in row.lower():
                self.commands_list.insert("end", row)

    def refresh_roles(self):
        if not hasattr(self, "roles_list"):
            return
        self.roles_list.delete(0, "end")
        selected = self.guild_combo.get()
        if selected not in self.guild_data:
            return
        snap = self.guild_data[selected]
        allowed = self.dist.server_settings[snap.guild_id].allowed_roles
        query = self.search_roles.get().lower()
        for role_id, role_name in snap.roles:
            is_allowed = role_id in allowed
            if self.only_allowed_roles_var.get() and not is_allowed:
                continue
            if query and query not in role_name.lower():
                continue
            marker = "✅" if is_allowed else "❌"
            self.roles_list.insert("end", f"{marker} {role_name} ({role_id})")

    def refresh_cards(self):
        summary = self.dist.summary()
        self.card_labels["keys"][0].config(text=f"{summary['remaining']:,}")
        self.card_labels["keys"][1].config(text="Remaining Keys")
        self.card_labels["users"][0].config(text=f"{summary['allowed']:,}")
        self.card_labels["users"][1].config(text="Allowed Users")
        self.card_labels["claims"][0].config(text=f"{summary['claimed_total']:,}")
        self.card_labels["claims"][1].config(text="Total Claims")
        self.card_labels["servers"][0].config(text=f"{len(self.guild_data):,}")
        self.card_labels["servers"][1].config(text="Connected Servers")

    def refresh_checklist(self):
        self.set_check("Token Added", bool(self.token_var.get().strip()))
        self.set_check("Bot Online", self.status.get() == "Online")
        self.set_check("Keys Loaded", bool(self.dist.keys))
        self.set_check("Servers Detected", bool(self.guild_data))
        has_role = any(settings.allowed_roles for settings in self.dist.server_settings.values())
        self.set_check("Role Access Set", has_role)
        self.set_check("Message Content Intent", self.status.get() == "Online")

    def draw_analytics(self):
        if not hasattr(self, "analytics_canvas"):
            return
        canvas = self.analytics_canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 280)
        height = max(canvas.winfo_height(), 120)
        points = []
        today = datetime.utcnow().date()
        counts = []
        for i in range(6, -1, -1):
            day = today - timedelta(days=i)
            count = sum(1 for event in self.dist.claim_history if datetime.fromisoformat(event.timestamp).date() == day)
            counts.append((day.strftime("%d %b"), count))
        max_count = max([count for _, count in counts] + [1])
        left, right, top, bottom = 38, width - 16, 18, height - 28
        canvas.create_line(left, bottom, right, bottom, fill=COLOURS["border"])
        canvas.create_line(left, top, left, bottom, fill=COLOURS["border"])
        for idx, (label, count) in enumerate(counts):
            x = left + (right - left) * (idx / max(1, len(counts) - 1))
            y = bottom - ((bottom - top) * (count / max_count))
            points.append((x, y))
            canvas.create_text(x, height - 12, text=label, fill=COLOURS["muted"], font=("Segoe UI", 8))
            canvas.create_oval(x - 4, y - 4, x + 4, y + 4, fill=COLOURS["purple"], outline="")
        for a, b in zip(points, points[1:]):
            canvas.create_line(a[0], a[1], b[0], b[1], fill=COLOURS["purple"], width=2)
        canvas.create_text(left, top, text=str(max_count), fill=COLOURS["muted"], anchor="w", font=("Segoe UI", 8))
        canvas.create_text(left, bottom - 2, text="0", fill=COLOURS["muted"], anchor="w", font=("Segoe UI", 8))

    def log(self, level: str, message: str):
        stamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{stamp}] {level:<7} {message}"
        LOG_PATH.parent.mkdir(exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as file:
            file.write(line + "\n")
        if hasattr(self, "log_text"):
            self.log_text.config(state="normal")
            self.log_text.insert("end", line + "\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")


def main():
    root = tk.Tk()
    ModernDashboard(root)
    root.mainloop()


if __name__ == "__main__":
    main()
