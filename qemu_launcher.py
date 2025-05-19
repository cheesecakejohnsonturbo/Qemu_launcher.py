"""
qemu_launcher.py

A Python script to manage and launch QEMU virtual machines.
Supports interactive configuration for various OS types, with robust audio handling.
"""

import os
import sys
import subprocess
import platform
from pathlib import Path
import shlex
import shutil

# --- Module-Level Constants ---
EXACT_AUDIO_DEVICE_DRIVERS = [
    "ich9-intel-hda", "intel-hda", "hda-duplex",
    "ac97", "es1370", "sb16", "adlib",
    "cs4231a", "gus"
    # "pcspk" is often handled by -machine pcspk=on/off, not typically as a -device for general audio.
]

# --- Configuration Paths ---
SCRIPT_DIR = Path(__file__).resolve().parent
META_DIR_NAME = ".meta"
DICT_DIR_NAME = "dictionaries_py"
VM_CONFIGS_FILE_NAME = "qemu_vm_configs.py"
GLOBAL_SETTINGS_FILE_NAME = "qemu_global_settings.py"

CONFIG_DIR = SCRIPT_DIR / META_DIR_NAME
DICT_DIR = CONFIG_DIR / DICT_DIR_NAME
VM_CONFIGS_PATH = DICT_DIR / VM_CONFIGS_FILE_NAME
GLOBAL_SETTINGS_PATH = DICT_DIR / GLOBAL_SETTINGS_FILE_NAME

# --- Default Settings ---
DEFAULT_GLOBAL_SETTINGS = {
    "qemu_system_exe_windows": "qemu-system-x86_64.exe",
    "qemu_system_exe_linux": "qemu-system-x86_64",
    "qemu_system_exe_macos": "qemu-system-x86_64",
    "qemu_img_exe_windows": "qemu-img.exe",
    "qemu_img_exe_linux": "qemu-img",
    "qemu_img_exe_macos": "qemu-img",
    "default_disk_format": "qcow2",
    "default_vm_storage_dir": str(SCRIPT_DIR / "virtual_machines_storage"),
    "remember_last_iso_dir": str(SCRIPT_DIR),
}

NEW_VM_DEFAULTS = {
    "name": "New_VM",
    "description": "A new virtual machine",
    "os_type": "generic",
    "iso_path": "",
    "floppy_path": "",
    "disk_image": {
        "path": "new_vm_disk.qcow2", # Will be customized with VM ID
        "format": "qcow2",
        "size": "20G",
        "create_if_missing": True,
        "interface": "virtio",
    },
    "ram": "2G",
    "cpu_cores": "2",
    "accelerator": "auto",
    "machine_type": "q35",
    "graphics": "virtio",
    "audio_enabled": True,
    "audio_device_model": "ich9-intel-hda", # Modern Intel HDA controller
    "audio_backend": "auto", # Script will pick based on OS (e.g., wasapi/dsound, pa/alsa, coreaudio)
    "network_enabled": True,
    "network_type": "user",
    "usb_tablet": True,
    "boot_order": "dc", # CD-ROM then Disk
    "extra_qemu_args": "",
}


# --- Utility Functions ---
def get_os_type():
    """Determines the operating system."""
    if sys.platform.startswith('linux'):
        return "linux"
    elif sys.platform.startswith('win'):
        return "windows"
    elif sys.platform.startswith('darwin'):
        return "macos"
    else:
        print(f"Warning: Unrecognized OS platform '{sys.platform}'. Defaulting to generic behavior.")
        return "unknown"

CURRENT_OS = get_os_type()

def ensure_dir_exists(path: Path):
    """Creates a directory if it doesn't exist."""
    path.mkdir(parents=True, exist_ok=True)

def _save_dict_to_py_file(file_path: Path, data_dict_name: str, data_dict: dict):
    """Saves a dictionary to a .py file in a readable format."""
    ensure_dir_exists(file_path.parent)
    content_parts = [f"{data_dict_name} = {{"]
    for key, value in data_dict.items():
        content_parts.append(f"    {repr(key)}: {repr(value)},")
    content_parts.append("}")
    try:
        file_path.write_text("\n".join(content_parts), encoding='utf-8')
    except IOError as e:
        print(f"Error: Could not write to configuration file {file_path}: {e}")
    except Exception as e:
        print(f"An unexpected error occurred while saving to {file_path}: {e}")

def _load_dict_from_py_file(file_path: Path, data_dict_name: str, default_data: dict = None):
    """Loads a dictionary from a .py file. Creates with defaults if not found."""
    if not file_path.exists():
        if default_data is not None:
            _save_dict_to_py_file(file_path, data_dict_name, default_data)
            return default_data.copy() # Return a copy
        return {}
    try:
        content = file_path.read_text(encoding='utf-8')
        namespace = {}
        exec(content, globals(), namespace) # Execute in a controlled namespace
        loaded_data = namespace.get(data_dict_name)
        if isinstance(loaded_data, dict):
            return loaded_data
        else:
            # Fallback for old config files that might not have the dict_name wrapper
            if default_data is not None and not namespace: # if namespace is empty, likely old format
                 print(f"Warning: Configuration file {file_path} might be in an old format or empty. Trying to load as raw dict.")
                 exec(f"{data_dict_name} = {content}", globals(), namespace)
                 loaded_data = namespace.get(data_dict_name)
                 if isinstance(loaded_data, dict):
                     print(f"Successfully loaded {file_path} using fallback. Consider resaving.")
                     return loaded_data

            print(f"Warning: '{data_dict_name}' not found or not a dict in {file_path}.")
            if default_data is not None:
                _save_dict_to_py_file(file_path, data_dict_name, default_data)
                return default_data.copy()
            return {}
    except Exception as e:
        print(f"Error loading configuration from {file_path}: {e}")
        print("Consider deleting or checking the file for corruption.")
        if default_data is not None:
            return default_data.copy() # Fallback to defaults on error
        return {}

# --- Load Global and VM Configurations ---
ensure_dir_exists(DICT_DIR)
GLOBAL_SETTINGS = _load_dict_from_py_file(GLOBAL_SETTINGS_PATH, "global_settings_data", DEFAULT_GLOBAL_SETTINGS)
VM_CONFIGURATIONS = _load_dict_from_py_file(VM_CONFIGS_PATH, "vm_configurations_data", {})

# Ensure default VM storage directory exists
try:
    default_vm_storage_path = Path(GLOBAL_SETTINGS.get("default_vm_storage_dir", DEFAULT_GLOBAL_SETTINGS["default_vm_storage_dir"]))
    ensure_dir_exists(default_vm_storage_path)
    GLOBAL_SETTINGS["default_vm_storage_dir"] = str(default_vm_storage_path.resolve()) # Store absolute path
except Exception as e:
    print(f"Error ensuring default VM storage directory: {e}")

def save_global_settings():
    _save_dict_to_py_file(GLOBAL_SETTINGS_PATH, "global_settings_data", GLOBAL_SETTINGS)

def save_vm_configurations():
    _save_dict_to_py_file(VM_CONFIGS_PATH, "vm_configurations_data", VM_CONFIGURATIONS)

def get_qemu_executable(tool_type="system"):
    """Gets the QEMU executable path (qemu-system or qemu-img). Tries settings, then PATH."""
    setting_key_prefix = "qemu_system_exe_" if tool_type == "system" else "qemu_img_exe_"
    default_exe_name = (f"qemu-system-{platform.machine()}"
                        if tool_type == "system" and platform.machine()
                        else ("qemu-system-x86_64" if tool_type == "system" else "qemu-img"))
    os_suffix = CURRENT_OS if CURRENT_OS != "unknown" else "linux"
    exe_path_from_settings = GLOBAL_SETTINGS.get(f"{setting_key_prefix}{os_suffix}")

    if exe_path_from_settings:
        if Path(exe_path_from_settings).is_file(): return str(Path(exe_path_from_settings).resolve())
        if shutil.which(exe_path_from_settings): return exe_path_from_settings
    
    default_name_with_ext = default_exe_name + (".exe" if CURRENT_OS == "windows" else "")
    exe_in_path = shutil.which(default_name_with_ext)
    if exe_in_path: return exe_in_path
    if exe_path_from_settings: return exe_path_from_settings # Fallback to configured name
    return default_name_with_ext # Fallback to default name

def get_user_input(prompt: str, default: str = None, to_lower: bool = False) -> str:
    """Gets user input, with an optional default value."""
    display_prompt = f"{prompt} [{default}]: " if default is not None else f"{prompt}: "
    user_val = input(display_prompt).strip()
    if not user_val and default is not None:
        return default.lower() if to_lower else default
    return user_val.lower() if to_lower else user_val

def get_path_from_user(prompt: str, base_dir_for_relative: Path, default_path_abs: str = "",
                       allow_blank_as_none: bool = False,
                       must_exist_if_provided: bool = False,
                       is_dir_selector: bool = False,
                       remember_dir_key: str = None) -> str:
    """Prompts user for a path. Returns absolute path string or "" if blank is allowed and chosen."""
    current_path_to_show = default_path_abs
    if remember_dir_key and GLOBAL_SETTINGS.get(remember_dir_key) and Path(GLOBAL_SETTINGS[remember_dir_key]).is_dir():
        initial_browse_dir = Path(GLOBAL_SETTINGS[remember_dir_key])
    elif default_path_abs and Path(default_path_abs).exists():
        initial_browse_dir = Path(default_path_abs).parent
    else:
        initial_browse_dir = base_dir_for_relative
    prompt_suffix = f" (current: {current_path_to_show} / blank to keep)" if current_path_to_show \
        else (" (blank for none)" if allow_blank_as_none else "")
    full_prompt = f"{prompt}{prompt_suffix} (context dir: {initial_browse_dir})"

    while True:
        user_path_str = input(f"{full_prompt}: ").strip()
        if not user_path_str:  # User entered blank
            if default_path_abs and current_path_to_show: return default_path_abs # Keeping default
            elif allow_blank_as_none: return ""  # User chose "none"
            else: print("Path cannot be empty."); continue
        resolved_path = Path(user_path_str)
        if not resolved_path.is_absolute(): resolved_path = (base_dir_for_relative / user_path_str).resolve()
        if must_exist_if_provided:
            target_exists = resolved_path.is_dir() if is_dir_selector else resolved_path.is_file()
            if not target_exists: print(f"{'Directory' if is_dir_selector else 'File'} not found: {resolved_path}"); continue
        if remember_dir_key and resolved_path.exists(): GLOBAL_SETTINGS[remember_dir_key] = str(resolved_path.parent)
        return str(resolved_path)

def create_virtual_disk_interactive(vm_config_name: str, disk_config: dict) -> bool:
    """Creates a virtual disk as specified in disk_config if it doesn't exist."""
    disk_filename = disk_config.get("path")
    if not disk_filename: print("Error: Disk path not specified in VM config."); return False
    vm_storage_dir = Path(GLOBAL_SETTINGS["default_vm_storage_dir"])
    disk_full_path = Path(disk_filename) if Path(disk_filename).is_absolute() else vm_storage_dir / disk_filename
    disk_full_path = disk_full_path.resolve()
    if disk_full_path.exists(): print(f"Disk image '{disk_full_path}' already exists."); return True
    if not disk_config.get("create_if_missing", False): print(f"Disk '{disk_full_path}' not found, not auto-creating."); return False
    disk_format = disk_config.get("format", GLOBAL_SETTINGS["default_disk_format"]); disk_size = disk_config.get("size")
    if not disk_size: print(f"Error: Disk size not for '{disk_filename}'. Cannot create."); return False
    qemu_img_exe = get_qemu_executable("img")
    if not qemu_img_exe or (not Path(qemu_img_exe).is_file() and not shutil.which(qemu_img_exe)):
        print(f"Error: qemu-img executable ('{qemu_img_exe}') not found. Check Global Settings or PATH."); return False
    command = [qemu_img_exe, "create", "-f", disk_format, str(disk_full_path), disk_size]
    print(f"\nAttempting to create disk for '{vm_config_name}':\n  Path: {disk_full_path}\n  Format: {disk_format}, Size: {disk_size}")
    user_choice = get_user_input("Proceed with disk creation? (yes/no)", "yes", to_lower=True)
    if user_choice not in ["y", "yes"]: print("Disk creation aborted by user."); return False
    try:
        ensure_dir_exists(disk_full_path.parent); print(f"Executing: {' '.join(command)}")
        process = subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"Disk '{disk_full_path}' created successfully.");
        if process.stdout: print("Output:\n", process.stdout)
        return True
    except subprocess.CalledProcessError as e: print(f"Error creating disk '{disk_full_path}': {e}"); _print_process_streams(e)
    except FileNotFoundError: print(f"Error: '{qemu_img_exe}' command not found.")
    except Exception as e: print(f"An unexpected error occurred during disk creation: {e}")
    return False

def _print_process_streams(process_error: subprocess.CalledProcessError):
    """Helper to print stdout/stderr from a CalledProcessError if they exist."""
    if hasattr(process_error, 'stderr') and process_error.stderr: print("Stderr:\n", process_error.stderr)
    if hasattr(process_error, 'stdout') and process_error.stdout: print("Stdout:\n", process_error.stdout)

def build_qemu_command(vm_name: str) -> list | None:
    """Builds the QEMU command list from a VM configuration with robust audio handling."""
    if vm_name not in VM_CONFIGURATIONS: print(f"Error: VM configuration '{vm_name}' not found."); return None
    
    config = VM_CONFIGURATIONS[vm_name]
    qemu_bin = get_qemu_executable("system")
    if not qemu_bin or (not Path(qemu_bin).is_file() and not shutil.which(qemu_bin)):
        print(f"Error: QEMU system executable ('{qemu_bin}') not found."); return None

    command_parts = {"base": [qemu_bin]} # Use a dictionary to build parts and then combine

    # Core components
    command_parts["base"].extend(["-m", config.get("ram", "1G")])
    command_parts["base"].extend(["-smp", str(config.get("cpu_cores", "1"))])
    command_parts["base"].extend(["-machine", config.get("machine_type", "q35")])

    # Accelerator
    accel = config.get("accelerator", "auto")
    if accel == "auto":
        if CURRENT_OS == "linux" and Path("/dev/kvm").exists() and os.access("/dev/kvm", os.R_OK | os.W_OK):
            accel_param = "kvm"; command_parts["base"].extend(["-device", "intel-iommu,intremap=on,caching-mode=on"])
        elif CURRENT_OS == "windows": accel_param = "whpx,kernel-irqchip=on"
        elif CURRENT_OS == "macos": accel_param = "hvf"
        else: accel_param = "tcg"
        print(f"Auto-selected accelerator: {accel_param}")
    else: accel_param = accel
    command_parts["base"].extend(["-accel", accel_param])

    # Graphics & USB Tablet
    command_parts["base"].extend(["-vga", config.get("graphics", "std")])
    if config.get("graphics", "std") != "none": command_parts["base"].extend(["-display", "default,show-cursor=on"])
    if config.get("usb_tablet", True): command_parts["base"].extend(["-usb", "-device", "usb-tablet"])

    # Disk Image
    disk_conf = config.get("disk_image", {}); disk_filename = disk_conf.get("path")
    if disk_filename:
        vm_storage_dir = Path(GLOBAL_SETTINGS["default_vm_storage_dir"])
        disk_full_path = Path(disk_filename) if Path(disk_filename).is_absolute() else vm_storage_dir / disk_filename
        disk_full_path = disk_full_path.resolve()
        if not disk_full_path.exists():
            if disk_conf.get("create_if_missing", False):
                print(f"Disk '{disk_full_path}' for '{vm_name}' not found.")
                if not create_virtual_disk_interactive(vm_name, disk_conf): print(f"Warning: Failed to create or find primary disk.")
                if not disk_full_path.exists():
                    print(f"Primary disk '{disk_full_path}' still missing after creation attempt.")
                    if get_user_input("Primary disk is missing. Continue launch? (yes/no)", "no", to_lower=True) != "yes":
                        raise SystemExit("Launch aborted by user due to missing primary disk.")
            else:
                print(f"Warning: Disk image '{disk_full_path}' not found and not set to auto-create.")
                if get_user_input(f"Disk '{disk_full_path}' missing. Continue launch? (yes/no)", "no", to_lower=True) != "yes":
                    raise SystemExit(f"Launch aborted by user due to missing disk: {disk_full_path}")
        if disk_full_path.exists():
            command_parts["base"].extend(["-drive", f"file={str(disk_full_path)},format={disk_conf.get('format', GLOBAL_SETTINGS['default_disk_format'])},if={disk_conf.get('interface', 'virtio')},index=0,media=disk"])

    # Media (ISO, Floppy)
    iso_path_str = config.get("iso_path", "")
    if iso_path_str and Path(iso_path_str).is_file(): command_parts["base"].extend(["-cdrom", iso_path_str])
    elif iso_path_str: print(f"Warning: ISO image '{iso_path_str}' not found.")
    floppy_path_str = config.get("floppy_path", "")
    if floppy_path_str and Path(floppy_path_str).is_file(): command_parts["base"].extend(["-fda", floppy_path_str])
    elif floppy_path_str: print(f"Warning: Floppy image '{floppy_path_str}' not found.")
    
    # Boot Order
    command_parts["base"].extend(["-boot", f"order={config.get('boot_order', 'c')}"])
    
    # Network
    if config.get("network_enabled", False) and config.get("network_type", "user") == "user":
        command_parts["base"].extend(["-netdev", "user,id=net0", "-device", "e1000,netdev=net0"])

    # --- Audio Configuration Logic ---
    # This section determines audio arguments based on script config and filters extra_qemu_args.
    
    script_generated_audio_args = []
    script_intends_to_disable_audio = False

    audio_enabled_in_config = config.get("audio_enabled", False) # Explicitly get current config
    audio_model = config.get("audio_device_model", "none").lower()
    audio_backend = config.get("audio_backend", "none").lower()

    if audio_enabled_in_config and audio_model != "none" and audio_backend != "none":
        # Script is actively configuring audio
        backend_driver = audio_backend
        if backend_driver == "auto": # Resolve 'auto' to a specific backend
            if CURRENT_OS == "windows": backend_driver = "wasapi" # Preferred for modern Windows
            elif CURRENT_OS == "linux": backend_driver = "pa"      # PulseAudio for Linux
            elif CURRENT_OS == "macos": backend_driver = "coreaudio" # CoreAudio for macOS
            else: backend_driver = "sdl" # General fallback
            print(f"Auto-selected audio backend: {backend_driver}")
        
        audio_id = "audio0" # Consistent ID for the audiodev
        script_generated_audio_args.extend(["-audiodev", f"{backend_driver},id={audio_id}"])
        script_generated_audio_args.extend(["-device", f"{audio_model},audiodev={audio_id}"])
    else:
        # Script intends to disable audio, or config is incomplete for enabling
        script_intends_to_disable_audio = True

    # Process extra_qemu_args: Filter out any audio args if script is managing audio (either enabling or disabling)
    # This ensures script's audio settings take precedence over extra_qemu_args.
    final_extra_args = []
    extra_args_str = config.get("extra_qemu_args", "")
    if extra_args_str:
        temp_extra_args = shlex.split(extra_args_str)
        i = 0
        while i < len(temp_extra_args):
            arg = temp_extra_args[i]
            arg_val_next = temp_extra_args[i+1] if i + 1 < len(temp_extra_args) else None
            
            # If script is providing its own audio args OR intends to disable audio, then filter.
            if script_generated_audio_args or script_intends_to_disable_audio:
                is_filtered_audio_arg = False
                if arg == "-soundhw":
                    print(f"Note: Filtering '{arg} {arg_val_next or ''}' from extra_qemu_args due to script's audio config.")
                    i += 1 # for -soundhw
                    if arg_val_next is not None: i+=1 # for its value
                    is_filtered_audio_arg = True
                elif arg == "-audiodev":
                    print(f"Note: Filtering '{arg} {arg_val_next or ''}' from extra_qemu_args due to script's audio config.")
                    i += 1 # for -audiodev
                    if arg_val_next is not None: i+=1 # for its value
                    is_filtered_audio_arg = True
                elif arg == "-device" and arg_val_next:
                    driver_part = arg_val_next.split(',')[0].lower()
                    if "audiodev=" in arg_val_next.lower() or driver_part in EXACT_AUDIO_DEVICE_DRIVERS:
                        print(f"Note: Filtering audio-related device '{arg} {arg_val_next}' from extra_qemu_args.")
                        i += 2 # for -device and its value
                        is_filtered_audio_arg = True
                
                if is_filtered_audio_arg:
                    continue # Skip adding this arg and its value to final_extra_args

            # If not filtered, add the argument(s)
            final_extra_args.append(arg)
            i += 1
            
    command_parts["extra"] = final_extra_args
    command_parts["script_audio"] = script_generated_audio_args # Will be empty if audio disabled

    # --- Assemble Final Command ---
    # Order: base, then filtered extra_args, then script-generated audio (if any)
    final_command = list(command_parts["base"])
    final_command.extend(command_parts["extra"])
    final_command.extend(command_parts["script_audio"])

    # Final check for disabling audio:
    # If script intended to disable audio, and after all processing,
    # no other active audio configuration is present, add -soundhw none.
    if script_intends_to_disable_audio:
        # Check if any active audio args are ALREADY in the final_command
        # (e.g., from a very unusual extra_arg that slipped filtering, or if script_audio was somehow populated)
        has_any_active_audio_config_in_final_cmd = any(
            arg == "-audiodev" or \
            (arg == "-soundhw" and (final_command.index(arg) + 1 < len(final_command) and final_command[final_command.index(arg)+1].lower() != "none")) or \
            (arg == "-device" and (final_command.index(arg) + 1 < len(final_command) and \
                ("audiodev=" in final_command[final_command.index(arg)+1].lower() or \
                 final_command[final_command.index(arg)+1].split(',')[0].lower() in EXACT_AUDIO_DEVICE_DRIVERS)))
            for arg in final_command
        )
        
        if not has_any_active_audio_config_in_final_cmd:
            # Both -soundhw none and -no-audio have resulted in "invalid option" errors
            # with this QEMU version.
            # The best approach is to add no explicit "disable audio" flag and rely on the
            # absence of audio device configurations, which the script already ensures
            # by not adding its own audio args and filtering extra_qemu_args when audio is disabled.
            print("Note: Audio is disabled by script config. No explicit 'disable audio' flag will be added, "
                  "relying on the absence of audio device configurations.")
            # No command is extended to final_command here.
        elif script_generated_audio_args: # This case should ideally not be met if script_intends_to_disable_audio is true
             print("Warning: Script intended to disable audio, but script-generated audio arguments were found. "
                   "This indicates a potential bug in the script's logic. Audio might still be active.")
        # Optional: Add a case if has_any_active_audio_config_in_final_cmd was true,
        # but script_generated_audio_args was empty. This means an audio option from
        # extra_qemu_args might have slipped through the filtering.
        # else:
        #     print("Warning: Script intended to disable audio, but some existing audio-related arguments "
        #           "might be present (e.g., from 'extra_qemu_args' that were not filtered). "
        #           "Audio might not be fully disabled.")
    return final_command

def launch_vm(vm_name: str):
    """Launches the specified VM."""
    try:
        qemu_command_list = build_qemu_command(vm_name)
        if not qemu_command_list:
            print(f"Could not prepare launch command for '{vm_name}'. Aborting launch.")
            return

        print("\n--- QEMU Launch Command ---")
        display_cmd = [f'"{arg}"' if ' ' in arg and not arg.startswith('-') else arg for arg in qemu_command_list]
        print(' '.join(display_cmd))
        print("---------------------------\n")

        print(f"Launching VM: {vm_name}...")
        process = subprocess.Popen(qemu_command_list)
        process.wait() 
        print(f"VM '{vm_name}' has exited. Return code: {process.returncode}")
    except FileNotFoundError:
        print(f"Error: QEMU executable not found. Please check Global Settings or ensure QEMU is in PATH.")
    except SystemExit as e: # Catch explicit aborts from build_qemu_command
        print(f"Launch aborted: {e}")
    except Exception as e:
        print(f"An unexpected error occurred while trying to launch '{vm_name}': {e}")

def select_from_list_keys(options_dict: dict, prompt_message: str):
    """Helper to let user select a key from a dictionary."""
    if not options_dict: print("No options available."); return None
    keys = list(options_dict.keys())
    for i, key_name in enumerate(keys):
        item_display = options_dict[key_name].get('name', key_name)
        print(f"{i+1}. {item_display} (ID: {key_name})")
    while True:
        choice_str = input(f"{prompt_message} (enter number or ID, blank to cancel): ").strip()
        if not choice_str: return None
        try: # Try as number first
            choice_idx = int(choice_str) - 1
            if 0 <= choice_idx < len(keys): return keys[choice_idx]
        except ValueError: pass # Not a number, try as ID
        if choice_str in keys: return choice_str
        print("Invalid selection. Please enter a valid number from the list or an exact ID.")

def create_edit_vm_config(vm_name_to_edit: str = None):
    """Interactive CUI to create or edit a VM configuration."""
    is_new_vm = vm_name_to_edit is None; config = {}; vm_id = ""
    if is_new_vm:
        print("\n--- Create New VM Configuration ---")
        base_name = get_user_input("Enter a base name for the new VM")
        if not base_name: print("VM name cannot be empty."); return
        sanitized_name = "".join(c if c.isalnum() or c in ['_','-'] else '_' for c in base_name.lower())
        temp_vm_id = sanitized_name; counter = 1
        while temp_vm_id in VM_CONFIGURATIONS: temp_vm_id = f"{sanitized_name}_{counter:02}"; counter += 1 # Pad counter
        vm_id = temp_vm_id; print(f"Generated unique VM ID: {vm_id}")
        config = NEW_VM_DEFAULTS.copy(); config["name"] = base_name
        config["disk_image"] = config.get("disk_image", {}).copy() # Ensure deep copy
        config["disk_image"]["path"] = f"{vm_id}_disk.{config['disk_image'].get('format', GLOBAL_SETTINGS['default_disk_format'])}"
    else: # Editing existing VM
        vm_id = vm_name_to_edit
        if vm_id not in VM_CONFIGURATIONS: print(f"Error: VM configuration with ID '{vm_id}' not found."); return
        print(f"\n--- Edit VM Configuration: {VM_CONFIGURATIONS[vm_id].get('name', vm_id)} (ID: {vm_id}) ---")
        config = VM_CONFIGURATIONS[vm_id].copy()
    config["disk_image"] = config.get("disk_image", {}).copy() # Ensure nested dicts are copied

    config["name"] = get_user_input("VM Name (friendly display name)", config.get("name", vm_id))
    config["description"] = get_user_input("Description", config.get("description", ""))
    print("\n--- Installation Media ---")
    iso_base_dir = Path(GLOBAL_SETTINGS.get("remember_last_iso_dir", SCRIPT_DIR))
    config["iso_path"] = get_path_from_user("Path to ISO image", iso_base_dir, config.get("iso_path", ""), allow_blank_as_none=True, must_exist_if_provided=True, remember_dir_key="remember_last_iso_dir")
    config["floppy_path"] = get_path_from_user("Path to floppy image", SCRIPT_DIR, config.get("floppy_path", ""), allow_blank_as_none=True, must_exist_if_provided=True)

    print("\n--- Virtual Hard Disk ---")
    disk_conf = config.get("disk_image", {}); vm_storage_dir = Path(GLOBAL_SETTINGS["default_vm_storage_dir"])
    if get_user_input("Configure virtual hard disk? (yes/no)", "yes" if disk_conf else "no", to_lower=True) == "yes":
        disk_conf["path"] = get_path_from_user("Disk image filename (relative to VM storage or absolute)", vm_storage_dir, disk_conf.get("path", f"{vm_id}_disk.{GLOBAL_SETTINGS['default_disk_format']}"), allow_blank_as_none=False, must_exist_if_provided=False)
        if disk_conf["path"]:
            disk_conf["format"] = get_user_input("Disk format (qcow2, vmdk, vdi, raw)", disk_conf.get("format", GLOBAL_SETTINGS["default_disk_format"]))
            disk_conf["interface"] = get_user_input("Disk interface type (ide, sata, scsi, virtio)", disk_conf.get("interface", "virtio"))
            prospective_disk_path = Path(disk_conf["path"]);
            if not prospective_disk_path.is_absolute(): prospective_disk_path = (vm_storage_dir / disk_conf["path"]).resolve()
            if not prospective_disk_path.exists():
                disk_conf["size"] = get_user_input("Disk size (e.g., 10G, 512M) - if creating", disk_conf.get("size", "20G"))
                disk_conf["create_if_missing"] = get_user_input("Create disk if missing at launch? (y/n)", "y" if disk_conf.get("create_if_missing",True) else "n" , to_lower=True) == "y"
            else: print(f"Disk '{prospective_disk_path}' already exists. Size/Create options skipped."); disk_conf.pop("size", None); disk_conf["create_if_missing"] = False
        else: disk_conf = {} # No disk path provided, clear disk config
    elif not disk_conf : disk_conf = {} # No disk and chose not to configure one
    config["disk_image"] = disk_conf

    print("\n--- System Resources ---")
    config["ram"] = get_user_input("RAM (e.g., 4G, 1024M)", config.get("ram", "2G"))
    config["cpu_cores"] = get_user_input("CPU cores (number)", str(config.get("cpu_cores", "2")))
    print("\n--- QEMU Specifics ---")
    config["machine_type"] = get_user_input("Machine type (e.g., pc, q35, microvm)", config.get("machine_type", "q35"))
    config["accelerator"] = get_user_input("Accelerator (auto, kvm, whpx, hvf, tcg)", config.get("accelerator", "auto"), to_lower=True)
    config["graphics"] = get_user_input("Graphics card (std, virtio, vmware, qxl, none)", config.get("graphics", "virtio"))
    
    # Updated Audio Prompts
    config["audio_enabled"] = get_user_input("Enable Audio? (y/n)", "y" if config.get("audio_enabled", True) else "n", to_lower=True) == "y"
    if config["audio_enabled"]:
        # Use EXACT_AUDIO_DEVICE_DRIVERS for the prompt, adding "none"
        audio_model_options = EXACT_AUDIO_DEVICE_DRIVERS + ["none"]
        config["audio_device_model"] = get_user_input(f"Audio Device Model ({','.join(audio_model_options)})", config.get("audio_device_model", "ich9-intel-hda"), to_lower=True)
        
        audio_backends = ["auto", "wasapi", "dsound", "sdl", "pa", "alsa", "coreaudio", "none"]
        config["audio_backend"] = get_user_input(f"Audio Backend ({','.join(audio_backends)})", config.get("audio_backend", "auto"), to_lower=True)
        
        if config["audio_device_model"] == "none" or config["audio_backend"] == "none":
            print("Audio device model or backend set to 'none', will disable audio settings.")
            config["audio_enabled"] = False # Ensure this is false if model/backend is none
    else: # Ensure model/backend are 'none' if audio_enabled is false from the start
        config["audio_device_model"] = "none"
        config["audio_backend"] = "none"

    config["network_enabled"] = get_user_input("Enable Network? (y/n)", "y" if config.get("network_enabled", True) else "n", to_lower=True) == "y"
    if config["network_enabled"]: config["network_type"] = get_user_input("Network type (user, bridge, tap - 'user' is simplest)", config.get("network_type", "user"), to_lower=True)
    config["usb_tablet"] = get_user_input("Enable USB tablet for mouse (y/n recommended)?", "y" if config.get("usb_tablet", True) else "n", to_lower=True) == "y"
    default_bo = "dc" if config.get("iso_path") else ("ac" if config.get("floppy_path") else "c");
    if config.get("iso_path") and not disk_conf.get("path"): default_bo = "d" # If only ISO and no disk, boot from ISO
    config["boot_order"] = get_user_input("Boot order (c=disk,d=cdrom,a=floppy,n=net - e.g. 'dc')", config.get("boot_order", default_bo))
    config["extra_qemu_args"] = get_user_input("Extra QEMU arguments (ADVANCED - use with care)", config.get("extra_qemu_args", ""))

    VM_CONFIGURATIONS[vm_id] = config
    save_vm_configurations(); print(f"Configuration for VM '{config['name']}' (ID: {vm_id}) {'created' if is_new_vm else 'updated'}.")

def delete_vm_config():
    """Lets the user select and delete a VM configuration and optionally its disk."""
    if not VM_CONFIGURATIONS: print("No VM configurations to delete."); return
    print("\n--- Delete VM Configuration ---")
    vm_id_to_delete = select_from_list_keys(VM_CONFIGURATIONS, "Select VM configuration to delete")
    if vm_id_to_delete:
        vm_config = VM_CONFIGURATIONS[vm_id_to_delete]; vm_display_name = vm_config.get('name', vm_id_to_delete)
        if get_user_input(f"Delete config '{vm_display_name}' (ID: {vm_id_to_delete})? (y/n)", "n", to_lower=True) == 'y':
            disk_path_str = vm_config.get("disk_image", {}).get("path")
            if disk_path_str:
                disk_full_path = Path(disk_path_str) if Path(disk_path_str).is_absolute() else Path(GLOBAL_SETTINGS["default_vm_storage_dir"]) / disk_path_str
                disk_full_path = disk_full_path.resolve()
                if disk_full_path.exists() and get_user_input(f"Delete disk '{disk_full_path}'? THIS IS PERMANENT. (y/n)", "n",to_lower=True) == 'y':
                    try: disk_full_path.unlink(); print(f"Disk image '{disk_full_path}' deleted.")
                    except OSError as e: print(f"Error deleting disk image '{disk_full_path}': {e}")
            del VM_CONFIGURATIONS[vm_id_to_delete]; save_vm_configurations()
            print(f"VM configuration '{vm_display_name}' (ID: {vm_id_to_delete}) deleted.")
        else: print("Deletion cancelled.")

def manage_global_settings_interactive():
    print("\n--- Manage Global Settings ---"); gs = GLOBAL_SETTINGS
    print(f"OS: {CURRENT_OS.capitalize()}")
    print(f"  QEMU System (Win/Lin/Mac): {gs.get('qemu_system_exe_windows') or 'N/A'} / {gs.get('qemu_system_exe_linux') or 'N/A'} / {gs.get('qemu_system_exe_macos') or 'N/A'}")
    print(f"  QEMU Img    (Win/Lin/Mac): {gs.get('qemu_img_exe_windows') or 'N/A'} / {gs.get('qemu_img_exe_linux') or 'N/A'} / {gs.get('qemu_img_exe_macos') or 'N/A'}")
    print(f"  Default Disk Format: {gs.get('default_disk_format', 'N/A')}")
    print(f"  Default VM Storage Dir: {gs.get('default_vm_storage_dir', 'N/A')}")
    print(f"  Last Used ISO Directory: {gs.get('remember_last_iso_dir', 'N/A')}")
    if get_user_input("\nModify global settings? (y/n)", "n", to_lower=True) == 'y':
        print("\nEnter new values or press Enter to keep current.")
        gs["qemu_system_exe_windows"] = get_user_input("QEMU System for Windows", gs.get("qemu_system_exe_windows"))
        gs["qemu_system_exe_linux"] = get_user_input("QEMU System for Linux", gs.get("qemu_system_exe_linux"))
        gs["qemu_system_exe_macos"] = get_user_input("QEMU System for macOS", gs.get("qemu_system_exe_macos"))
        gs["qemu_img_exe_windows"] = get_user_input("QEMU Img for Windows", gs.get("qemu_img_exe_windows"))
        gs["qemu_img_exe_linux"] = get_user_input("QEMU Img for Linux", gs.get("qemu_img_exe_linux"))
        gs["qemu_img_exe_macos"] = get_user_input("QEMU Img for macOS", gs.get("qemu_img_exe_macos"))
        gs["default_disk_format"] = get_user_input("Default Disk Format", gs.get("default_disk_format"))
        new_vm_dir = get_path_from_user("Default VM Storage Directory", SCRIPT_DIR, gs.get("default_vm_storage_dir"), allow_blank_as_none=False, must_exist_if_provided=False, is_dir_selector=True)
        if new_vm_dir: ensure_dir_exists(Path(new_vm_dir)); gs["default_vm_storage_dir"] = new_vm_dir
        new_iso_dir = get_path_from_user("Default Directory for ISO selection", SCRIPT_DIR, gs.get("remember_last_iso_dir"), allow_blank_as_none=True, must_exist_if_provided=False, is_dir_selector=True)
        gs["remember_last_iso_dir"] = new_iso_dir if new_iso_dir else str(SCRIPT_DIR) # Reset to script dir if blanked

        save_global_settings(); print("Global settings updated.")
    print("--- End of Global Settings ---")

def initial_setup_check():
    """Checks for QEMU and offers to create a default generic VM config."""
    q_sys = get_qemu_executable("system"); q_img = get_qemu_executable("img")
    q_ok = True
    if not q_sys or (not Path(q_sys).is_file() and not shutil.which(q_sys)): print(f"Warning: QEMU system executable ('{q_sys}') not found or configured incorrectly."); q_ok=False
    if not q_img or (not Path(q_img).is_file() and not shutil.which(q_img)): print(f"Warning: qemu-img executable ('{q_img}') not found or configured incorrectly."); q_ok=False
    if not q_ok and get_user_input("QEMU does not seem to be fully configured. Go to Global Settings to configure QEMU paths now? (y/n)", "y",to_lower=True) == "y":
        manage_global_settings_interactive()
    if not VM_CONFIGURATIONS and get_user_input("\nNo VM configurations found. Create a new generic VM configuration to get started? (y/n)", "y",to_lower=True) == "y":
        create_edit_vm_config(None) # Go directly to the VM creation dialogue

def main_menu():
    """Displays the main menu and handles user choices."""
    initial_setup_check()
    while True:
        print(f"\n--- QEMU VM Launcher ---\nOS: {CURRENT_OS.capitalize()} | QEMU System: {get_qemu_executable('system') or 'Not Found!'}")
        print(f"VM Configurations available: {len(VM_CONFIGURATIONS)}\n------------------------")
        print("1. Launch VM\n2. Create New VM Configuration\n3. Edit Existing VM Configuration\n4. Delete VM Configuration\n5. Manage Global Settings\n0. Exit")
        choice = input("Enter your choice: ").strip()
        if choice == '1':
            if not VM_CONFIGURATIONS: print("No VM configurations available. Please create one first."); continue
            vm_id = select_from_list_keys(VM_CONFIGURATIONS, "Select VM to launch")
            if vm_id: launch_vm(vm_id)
        elif choice == '2': create_edit_vm_config(None)
        elif choice == '3':
            if not VM_CONFIGURATIONS: print("No VM configurations to edit. Please create one first."); continue
            vm_id = select_from_list_keys(VM_CONFIGURATIONS, "Select VM configuration to edit")
            if vm_id: create_edit_vm_config(vm_id)
        elif choice == '4': delete_vm_config()
        elif choice == '5': manage_global_settings_interactive();
        elif choice == '0': print("Exiting QEMU VM Launcher."); break
        else: print("Invalid choice. Please try again.")

if __name__ == "__main__":
    try: main_menu()
    except KeyboardInterrupt: print("\nOperation cancelled by user. Exiting.")
    except SystemExit as e: print(f"Exiting: {e}") # Catch explicit SystemExits from build_qemu_command
    except Exception as e:
        print(f"\n--- An Unexpected Error Occurred ---")
        print(f"Error Type: {type(e).__name__}")
        print(f"Error Message: {e}")
        import traceback
        print("\n--- Traceback ---"); traceback.print_exc(); print("-------------------")
    finally: input("Press Enter to exit program...")
