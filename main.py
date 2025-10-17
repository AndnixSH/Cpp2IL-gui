import os, subprocess, threading, queue, re, shlex, platform
import dearpygui.dearpygui as dpg
import httpx
import sys, os, shutil, subprocess

# ---- App metadata ----
VERSION = "1.0.0"
UPDATE_URL = "https://raw.githubusercontent.com/AndnixSH/Cpp2IL-gui/main/version.txt"

# ---- Paths / defaults ----
folderpath = os.getcwd()

commands = []

def set_or_append(prefix: str, value: str, quote=True):
    """Set a --key=VALUE style arg (replacing if already present)."""
    global commands
    needle = f"{prefix}="
    formatted = f'{prefix}="{value}"' if quote else f"{prefix}={value}"
    for i, cmd in enumerate(commands):
        if cmd.startswith(needle):
            commands[i] = formatted
            return
    commands.append(formatted)

def toggle_flag(flag: str, enabled: bool):
    """Add/remove a --flag style arg."""
    global commands
    if enabled and flag not in commands:
        commands.append(flag)
    elif not enabled and flag in commands:
        commands.remove(flag)

def list_to_args(lst: list) -> str:
    return " ".join(lst)

# ---- Update checker (unchanged logic) ----
def check_update():
    dpg.set_value("updatetxt", "Update Status: Checking for updates...")
    try:
        r = httpx.get(UPDATE_URL, timeout=10.0)
        if r.text.strip() != VERSION:
            dpg.set_value("updatetxt", f"Update Status: Version {VERSION} is Outdated! Get the latest on https://github.com/AndnixSH/Cpp2IL-gui")
        else:
            dpg.set_value("updatetxt", f"Update Status: GUI version {VERSION} is up to date!")
    except Exception as e:
        dpg.set_value("updatetxt", f"Update Status: Could not check ({e})")

# ---- Setters bound to UI ----
# Linux and macOS hates Tkinter
def open_folder_dialog(callback):
    os_name, _ = detect_os_arch()
    if os_name == "windows":
        from tkinter import Tk
        from tkinter.filedialog import askdirectory
        Tk().withdraw()
        folder_path = askdirectory()
        if folder_path:
            callback(folder_path)
    else:
        with dpg.file_dialog(
            directory_selector=True,
            show=True,
            modal=True,
            callback=lambda s, data: callback(data['file_path_name']),
            width=700,
            height=600
        ):
            dpg.add_file_extension(".apk")
            
def open_file_dialog(callback, extensions=None):
    os_name, _ = detect_os_arch()
    if os_name == "windows":
        from tkinter import Tk
        from tkinter.filedialog import askopenfile
        Tk().withdraw()
        f = askopenfile(filetypes=extensions or [("All Files", "*.*")])
        if getattr(f, "name", None):
            callback(f.name)
    else:
        with dpg.file_dialog(
            show=True,
            modal=True,
            callback=lambda s, data: callback(data['file_path_name']),
            width=700,
            height=600
        ):
            if extensions:
                for ext_label, ext in extensions:
                    dpg.add_file_extension(ext, color=(0, 255, 0, 255))
            else:
                dpg.add_file_extension(".apk")

def choose_game_folder():
    def on_select(folder_path):
        if folder_path:
            dpg.set_value("selected_game_path", f"Selected game folder: {folder_path}")
            set_or_append("--game-path", folder_path)
            output_folder = f"{folder_path}/Cpp2IL dump"
            dpg.set_value("selected_output_to", output_folder)
            set_or_append("--output-to", output_folder)

    open_folder_dialog(on_select)

def choose_apk_file():
    def on_select(file_path):
        if file_path:
            apk_name = file_path.split("/")[-1]
            dpg.set_value("selected_game_path", f"Selected APK: {apk_name}")
            set_or_append("--game-path", file_path)
            output_folder = f"{os.path.dirname(file_path)}/Cpp2IL dump"
            dpg.set_value("selected_output_to", output_folder)
            set_or_append("--output-to", output_folder)

    open_file_dialog(on_select, [("APK Files", ".apk")])

def set_exe_name(sender, data):
    name = dpg.get_value("exe_name_tag").strip()
    if name:
        set_or_append("--exe-name", name)

def choose_force_binary():
    Tk().withdraw()
    f = askopenfile(filetypes=[("All Files", "*.*")])
    if getattr(f, "name", None):
        dpg.set_value("force_binary_txt", f'Path: {f.name}')
        set_or_append("--force-binary-path", f.name)

def choose_force_metadata():
    Tk().withdraw()
    f = askopenfile(filetypes=[("Global-metadata.dat", "global-metadata.dat"), ("All Files", "*.*")])
    if getattr(f, "name", None):
        dpg.set_value("force_metadata_txt", f'Path: {f.name}')
        set_or_append("--force-metadata-path", f.name)

def choose_wasm_framework():
    Tk().withdraw()
    f = askopenfile(filetypes=[("WASM framework.js", "*.framework.js"), ("JavaScript", "*.js"), ("All Files", "*.*")])
    if getattr(f, "name", None):
        dpg.set_value("wasm_framework_txt", f'Path: {f.name}')
        set_or_append("--wasm-framework-file", f.name)

def set_force_unity_version(sender, data):
    v = dpg.get_value("unity_version_tag").strip()
    if v:
        set_or_append("--force-unity-version", v, quote=True)

def set_use_processor(sender, data):
    val = dpg.get_value("use_processor_tag").strip()
    if val:
        set_or_append("--use-processor", val)

def set_processor_config(sender, data):
    val = dpg.get_value("processor_config_tag").strip()
    if val:
        set_or_append("--processor-config", val)

def set_output_as(sender=None, data=None):
    fmt = dpg.get_value("output_as_tag").strip()
    if fmt:
        set_or_append("--output-as", fmt)

def choose_output_to():
    Tk().withdraw()
    folder_path = askdirectory()
    if folder_path:
        dpg.set_value("selected_output_to", f"Output to: {folder_path}")
        set_or_append("--output-to", folder_path)

def toggle_verbose(sender, data):
    toggle_flag("--verbose", bool(dpg.get_value("verbosetag")))

def toggle_low_memory(sender, data):
    toggle_flag("--low-memory-mode", bool(dpg.get_value("lowmemtag")))

def _strip_ansi(s: str) -> str:
    return re.sub(r'\x1B\[[0-9;?]*[ -/]*[A-Za-z]', '', s)

# ---- Live log helpers ----
_log_queue = queue.Queue()
_current_proc = None

def _enqueue(text: str):
    _log_queue.put(text)

def _pump_log():
    try:
        while True:
            line = _log_queue.get_nowait()
            old = dpg.get_value("logoutput")
            dpg.set_value("logoutput", (old or "") + line)
            dpg.set_y_scroll("log_window", 1e9)
    except queue.Empty:
        pass

def _reader_thread(proc):
    # Read merged stdout+stderr and enqueue lines
    with proc.stdout:
        for raw in iter(proc.stdout.readline, b""):
            if not raw:
                break
            line = raw.decode(errors="replace")
            _enqueue(_strip_ansi(line))

    code = proc.wait()
    if code > 0x7FFFFFFF:
        code -= 0x100000000
    _enqueue(f"\n[process exited with code {code}]\n")

log_buffer = []
def _enqueue(text: str):
    log_buffer.append(text)
    _log_queue.put(text)
    
def copy_log_to_clipboard():
    dpg.set_clipboard_text("".join(log_buffer))

def clear_log():
    try:
        dpg.set_value("logoutput", "")
        dpg.set_y_scroll("log_window", 0)
    except Exception:
        pass

    log_buffer.clear()

    try:
        with _log_queue.mutex:
            _log_queue.queue.clear()
    except Exception:
        pass

# ---- Run Cpp2IL ----
def detect_os_arch():
    """
    Returns: (os_name, arch)
      os_name in {"windows","linux","macos"}
      arch in {"x64","arm64"}
    """
    os_sys = platform.system().lower()
    if os_sys.startswith("darwin") or os_sys == "mac" or os_sys == "macos":
        os_name = "macos"
    elif os_sys.startswith("win"):
        os_name = "windows"
    elif os_sys.startswith("linux"):
        os_name = "linux"
    else:
        os_name = os_sys  # fallback

    m = platform.machine().lower()
    if any(tok in m for tok in ("arm64", "aarch64", "armv8")):
        arch = "arm64"
    else:
        # treats x86_64/amd64/i686 as x64 target binary
        arch = "x64"

    return os_name, arch

def resolve_cpp2il_path():
    """
    Maps to your folder layout:
    Cpp2IL/
      Windows/Cpp2IL.exe
      Linux/Cpp2IL (x64) or Cpp2ILarm64
      macOS/Cpp2IL (x64) or Cpp2ILarm64
    """
    cpp2ilfolder = os.path.join("Cpp2IL")
    assetsfolder = os.path.join("Assets")
    os_name, arch = detect_os_arch()

    if os.path.isdir(cpp2ilfolder):
        if os_name == "windows":
            exe = os.path.join(cpp2ilfolder, "windows", "cpp2il.exe")
        elif os_name == "linux":
            exe = os.path.join(cpp2ilfolder, "linux", "cpp2il")
        elif os_name == "macos":
            exe = os.path.join(cpp2ilfolder, "macos", "cpp2il")
        elif os_name == "linux":
            exe = os.path.join(cpp2ilfolder, "linux-arm64", "cpp2il" if arch == "arm64" else "cpp2il")
        elif os_name == "macos":
            exe = os.path.join(cpp2ilfolder, "macos-arm64", "cpp2il" if arch == "arm64" else "cpp2il")
    else:
        if os_name == "windows":
            exe = os.path.join(assetsfolder, "cpp2il.exe")
        else:
            exe = os.path.join(assetsfolder, "cpp2il")

    if os_name in ("linux", "macos") and os.path.isfile(exe):
        try:
            os.chmod(exe, 0o777)
        except Exception as e:
            _enqueue(f"[warn] Could not chmod 777 on {exe}: {e}\n")

    return exe

def startcpp2il(_, __, args):
    global _current_proc

    clear_log()

    exe = resolve_cpp2il_path()
    _enqueue(f"[cmd] {exe} {args}\n\n")

    if not os.path.isfile(exe):
        _enqueue("[error] Cpp2IL binary not found for this OS/arch.\n")
        try:
            dpg.set_value("statustxt", "Error: Cpp2IL binary not found!")
        except Exception:
            pass
        return

    try:
        # Build argv list
        os_name, _ = detect_os_arch()
        raw_args = shlex.split(args or "", posix=True)
        cmd = [exe] + raw_args

        # Spawn without shell for better real-time output
        proc = subprocess.Popen(
            cmd,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
            env=dict(os.environ, NO_COLOR='1', TERM='dumb'),
        )
        _current_proc = proc
        t = threading.Thread(target=_reader_thread, args=(proc,), daemon=True)
        t.start()
        try:
            dpg.set_value("statustxt", "Running Cpp2IL...")
        except Exception:
            pass
    except Exception as e:
        _enqueue(f"[spawn error] {e}\n")
        try:
            dpg.set_value("statustxt", "Failed to start Cpp2IL.")
        except Exception:
            pass
        return

# ---- Documentation table (synced to current help) ----
cpp2ilcmds = {
    "--game-path": "Specify path to the game folder (containing the exe). Required.",
    "--exe-name": "Override the Unity executable name if auto-detection fails.",
    "--force-binary-path": "Force path to the il2cpp binary (advanced; use with other force options).",
    "--force-metadata-path": "Force path to the il2cpp metadata file (advanced; use with other force options).",
    "--force-unity-version": "Override unity version detection (advanced; use with other force options).",
    "--list-processors": "List available processing layers and exit.",
    "--use-processor": "Comma-separated IDs of processing layers to use, executed in order.",
    "--processor-config": "Config for selected processors in key=value pairs; separate pairs with backticks (`).",
    "--list-output-formats": "List available output formats and exit.",
    "--output-as": "ID of the output format to use.",
    "--output-to": "Root directory to output to (defaults to cpp2il_out in CWD).",
    "--verbose": "Enable verbose logging.",
    "--low-memory-mode": "Reduce memory usage at the cost of performance.",
    "--wasm-framework-file": "Path to *.framework.js (WASM only) to help remap obfuscated dynCall exports.",
}

# ---- UI ----
        
imguiW, imguiH = 840, 750
dpg.create_context()
dpg.create_viewport(title=f"Cpp2IL GUI | {VERSION}", width=imguiW, height=imguiH, resizable=True)
dpg.setup_dearpygui()
#dpg.set_viewport_width(imguiW + 16)
#dpg.set_viewport_height(imguiH + 38)
dpg.set_viewport_resizable(True)

with dpg.font_registry():
    default_font = dpg.add_font("Assets/SF Pro Display Semibold.ttf", 20)

with dpg.theme(tag="green_theme"):
    with dpg.theme_component(dpg.mvButton):
        dpg.add_theme_color(dpg.mvThemeCol_Button, (61, 153, 114), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (54, 179, 125), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (48, 117, 88), category=dpg.mvThemeCat_Core)
        
with dpg.theme(tag="blue_theme"):
    with dpg.theme_component(dpg.mvButton):
        dpg.add_theme_color(dpg.mvThemeCol_Button, (61, 114, 153), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (54, 125, 179), category=dpg.mvThemeCat_Core)
        dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (45, 83, 111), category=dpg.mvThemeCat_Core)

def tab_main():
    with dpg.group():
        dpg.bind_font(default_font)
        
        with dpg.group(horizontal=True):
            sel_folder_btn = dpg.add_button(label="Select Game Folder", callback=choose_game_folder, width=200, height=40)
            dpg.add_text("Or")
            sel_apk_btn = dpg.add_button(label="Select APK file", callback=choose_apk_file, width=200, height=40)
            dpg.add_text("(not an APKM or XAPK)")
            
        dpg.bind_item_theme(sel_folder_btn, "blue_theme")
        dpg.bind_item_theme(sel_apk_btn, "blue_theme")
            
        dpg.add_text("Selected game: (none)", tag="selected_game_path")
        
        with dpg.group(horizontal=True):     
            dpg.add_button(label="Choose Output Folder", callback=choose_output_to, width=200, height=26)
            dpg.add_text("Output to: (none)", tag="selected_output_to")
        
        dpg.add_separator()
        
        with dpg.group(horizontal=True): 
            dpg.add_button(label="Force Binary Path... (optional)", callback=choose_force_binary, width=300, height=26)
            dpg.add_text("Path: (none)", tag="force_binary_txt")
        
        with dpg.group(horizontal=True): 
            dpg.add_button(label="Force Metadata Path... (optional)", callback=choose_force_metadata, width=300, height=26)
            dpg.add_text("Path: (none)", tag="force_metadata_txt")
                
        with dpg.group(horizontal=True):
            dpg.add_input_text(label="  Force Unity Version", tag="unity_version_tag", callback=set_force_unity_version, width=250, hint="e.g. 2021.3.14f1 (optional)")
        
        dpg.add_separator()
        
        with dpg.group(horizontal=True): 
            dpg.add_button(label="WASM framework.js... (optional)", callback=choose_wasm_framework, width=300, height=26)
            dpg.add_text("Path: (none)", tag="wasm_framework_txt")

        with dpg.group(horizontal=True):
            dpg.add_input_text(label="  Exe Name", tag="exe_name_tag", callback=set_exe_name, width=250, hint="e.g. MyGame (optional)")
            dpg.add_input_text(label="  Output As", tag="output_as_tag", callback=set_output_as, width=250, hint="e.g. dummydll", default_value="dummydll")
        
        dpg.add_input_text(label="  Use Processor(s)", tag="use_processor_tag", callback=set_use_processor, width=500, hint="e.g. attributeinjector,dummydll (optional)")
        dpg.add_input_text(label="  Processor Config", tag="processor_config_tag", callback=set_processor_config, width=500, hint="key=value`key2=value2 (optional)")
  
        dpg.add_separator()
 
        with dpg.group(horizontal=True):
            dpg.add_button(label="List Output Formats", callback=startcpp2il, user_data="--list-output-formats", width=170, height=48)
            dpg.add_button(label="List Processors", callback=startcpp2il, user_data="--list-processors", width=170, height=48)
            green_btn = dpg.add_button(label="Start", callback=lambda s, a, u: startcpp2il(s, a, " ".join(commands)), width=300, height=48)
        
        dpg.bind_item_theme(green_btn, "green_theme")

        dpg.add_separator()
        
        with dpg.group(horizontal=True):
            dpg.add_text("Log output")
            dpg.add_button(label="Copy All", callback=lambda: copy_log_to_clipboard())
            
        with dpg.child_window(tag="log_window", width=800, height=250, border=True, autosize_x=False, autosize_y=False):
            dpg.add_text("Log output will appear here...", tag="logoutput", wrap=580)

def tab_docs():
    with dpg.group():
        dpg.add_text(" ")
        with dpg.table(header_row=False, row_background=True, borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True, policy=dpg.mvTable_SizingFixedFit):
            dpg.add_table_column()
            dpg.add_table_column()
            with dpg.table_row():
                dpg.add_text("Option")
                dpg.add_text("Description")
            for key, value in cpp2ilcmds.items():
                with dpg.table_row():
                    dpg.add_text(key)
                    dpg.add_text(value)

def tab_credits():
    with dpg.group():
        dpg.add_text("Credits:")
        dpg.add_text(" ")
        dpg.add_text("Updated by AndnixSH | https://github.com/AndnixSH")
        dpg.add_text("Source code: https://github.com/AndnixSH/Cpp2IL-gui")
        dpg.add_text(" ")
        dpg.add_text("YeetDisDude - GUI | https://github.com/YeetDisDude")
        dpg.add_text("Source code: https://github.com/YeetDisDude/Cpp2IL-gui")
        dpg.add_text(" ")
        dpg.add_text("Samboy - Cpp2IL | github.com/SamboyCoding")
        dpg.add_text("Source code: github.com/SamboyCoding/Cpp2IL")

def tab_settings():
    with dpg.group():
        
        dpg.add_checkbox(label="  Verbose", tag="verbosetag", callback=toggle_verbose)
        dpg.add_checkbox(label="  Low Memory Mode", tag="lowmemtag", callback=toggle_low_memory)
        
        dpg.add_text(" ")
        
        dpg.add_button(label="Check update", callback=check_update, width=150, height=40)
        dpg.add_text("Update Status: idle", tag="updatetxt")


with dpg.window(tag="root_window", width=imguiW, height=imguiH, no_resize=True,
                label=f"Cpp2IL GUI | Version {VERSION}", no_collapse=True, no_move=True) as window:
    with dpg.tab_bar():
        with dpg.tab(label="     Cpp2IL     "):
            tab_main()
        with dpg.tab(label="     CLI Documentation     "):
            tab_docs()
        with dpg.tab(label="    Credits     "):
            tab_credits()
        with dpg.tab(label="    Settings     "):
            tab_settings()

set_output_as()

dpg.set_primary_window("root_window", True)

dpg.show_viewport()

# Pump logs every frame
try:
    dpg.set_render_callback(lambda: _pump_log())
except Exception:
    with dpg.handler_registry():
        try:
            dpg.add_mouse_move_handler(callback=lambda s, a, u: _pump_log())
        except Exception:
            pass

dpg.start_dearpygui()

dpg.destroy_context()

