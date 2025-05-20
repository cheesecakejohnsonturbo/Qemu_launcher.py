"""
qemu_launcher.py

A Python script to manage and launch QEMU virtual machines.
Supports interactive configuration for various OS types, with robust audio handling
and shared disk support.
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
    "default_disk_format": "qcow2", # Used for NEWLY created disks primarily
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
        "path": "new_vm_disk.qcow2", 
        "format": "qcow2", # Default for new disks
        "size": "20G",
        "create_if_missing": True,
        "interface": "virtio",
    },
    "shared_disks": [], 
    "ram": "2G",
    "cpu_cores": "2",
    "accelerator": "auto",
    "machine_type": "q35",
    "graphics": "virtio",
    "audio_enabled": True,
    "audio_device_model": "ich9-intel-hda",
    "audio_backend": "auto",
    "network_enabled": True,
    "network_type": "user",
    "usb_tablet": True,
    "boot_order": "dc", 
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
            return default_data.copy() 
        return {}
    try:
        content = file_path.read_text(encoding='utf-8')
        namespace = {}
        exec(content, globals(), namespace) 
        loaded_data = namespace.get(data_dict_name)
        if isinstance(loaded_data, dict):
            return loaded_data
        else:
            if default_data is not None and not namespace: 
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
            return default_data.copy() 
        return {}

# --- Load Global and VM Configurations ---
ensure_dir_exists(DICT_DIR)
GLOBAL_SETTINGS = _load_dict_from_py_file(GLOBAL_SETTINGS_PATH, "global_settings_data", DEFAULT_GLOBAL_SETTINGS)
VM_CONFIGURATIONS = _load_dict_from_py_file(VM_CONFIGS_PATH, "vm_configurations_data", {})

try:
    default_vm_storage_path = Path(GLOBAL_SETTINGS.get("default_vm_storage_dir", DEFAULT_GLOBAL_SETTINGS["default_vm_storage_dir"]))
    ensure_dir_exists(default_vm_storage_path)
    GLOBAL_SETTINGS["default_vm_storage_dir"] = str(default_vm_storage_path.resolve()) 
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
    if exe_path_from_settings: return exe_path_from_settings 
    return default_name_with_ext 

def get_user_input(prompt: str, default: str = None, to_lower: bool = False) -> str:
    """Gets user input, with an optional default value. Handles None default correctly."""
    prompt_text = f"{prompt} "
    if default is not None: # Only add default to prompt if it's not None
        prompt_text += f"[{default}]: "
    else:
        prompt_text += ": "
        
    user_val = input(prompt_text).strip()
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
    
    prompt_suffix = ""
    if current_path_to_show : # If there's a current value to show
        prompt_suffix = f" (current: {current_path_to_show} / blank to keep)"
    elif allow_blank_as_none: # If blank is allowed and there's no current value
        prompt_suffix = " (blank for none)"
    
    full_prompt = f"{prompt}{prompt_suffix} (context dir: {initial_browse_dir})"


    while True:
        user_path_str = input(f"{full_prompt}: ").strip()
        if not user_path_str:  
            if current_path_to_show: return default_path_abs 
            elif allow_blank_as_none: return ""  
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
    
    disk_format = disk_config.get("format")
    # For creation, a format is needed. If user left it blank (for auto-detect of existing), use global default.
    if not disk_format: 
        disk_format = GLOBAL_SETTINGS["default_disk_format"]
        print(f"Note: No format specified for new disk, using global default: {disk_format}")

    disk_size = disk_config.get("size")
    if not disk_size: print(f"Error: Disk size not specified for '{disk_filename}'. Cannot create."); return False
    
    qemu_img_exe = get_qemu_executable("img")
    if not qemu_img_exe or (not Path(qemu_img_exe).is_file() and not shutil.which(qemu_img_exe)):
        print(f"Error: qemu-img executable ('{qemu_img_exe}') not found. Check Global Settings or PATH."); return False
    
    command = [qemu_img_exe, "create", "-f", disk_format, str(disk_full_path), disk_size]
    print(f"\nAttempting to create disk for '{vm_config_name}':\n  Path: {disk_full_path}\n  Format: {disk_format}, Size: {disk_size}")
    
    # Updated prompt and check for disk creation confirmation
    user_choice = get_user_input("Proceed with disk creation? (y/n)", "y", to_lower=True)
    if user_choice != "y": # Only proceed if user explicitly enters 'y' (or accepts default 'y')
        print("Disk creation aborted by user.")
        return False
        
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
    """Builds the QEMU command list from a VM configuration."""
    if vm_name not in VM_CONFIGURATIONS: print(f"Error: VM configuration '{vm_name}' not found."); return None
    
    config = VM_CONFIGURATIONS[vm_name]
    qemu_bin = get_qemu_executable("system")
    if not qemu_bin or (not Path(qemu_bin).is_file() and not shutil.which(qemu_bin)):
        print(f"Error: QEMU system executable ('{qemu_bin}') not found."); return None

    command_parts = {"base": [qemu_bin]} 

    command_parts["base"].extend(["-m", config.get("ram", "1G")])
    command_parts["base"].extend(["-smp", str(config.get("cpu_cores", "1"))])
    command_parts["base"].extend(["-machine", config.get("machine_type", "q35")])

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

    command_parts["base"].extend(["-vga", config.get("graphics", "std")])
    if config.get("graphics", "std") != "none": command_parts["base"].extend(["-display", "default,show-cursor=on"])
    if config.get("usb_tablet", True): command_parts["base"].extend(["-usb", "-device", "usb-tablet"])

    current_drive_index = 0 

    # Primary Disk Image
    disk_conf = config.get("disk_image", {}); disk_filename = disk_conf.get("path")
    if disk_filename:
        vm_storage_dir = Path(GLOBAL_SETTINGS["default_vm_storage_dir"])
        disk_full_path = Path(disk_filename) if Path(disk_filename).is_absolute() else vm_storage_dir / disk_filename
        disk_full_path = disk_full_path.resolve()
        if not disk_full_path.exists():
            if disk_conf.get("create_if_missing", False):
                print(f"Primary disk '{disk_full_path}' for '{vm_name}' not found.")
                if not create_virtual_disk_interactive(vm_name, disk_conf): 
                    print(f"Warning: Failed to create or find primary disk '{disk_full_path}'.")
                if not disk_full_path.exists(): 
                    print(f"Primary disk '{disk_full_path}' still missing after creation attempt.")
                    if get_user_input("Primary disk is missing. Continue launch? (y/n)", "y", to_lower=True) != "y": # Default to yes, proceed if not 'n'
                        raise SystemExit("Launch aborted by user due to missing primary disk.")
            else:
                print(f"Warning: Primary disk image '{disk_full_path}' not found and not set to auto-create.")
                if get_user_input(f"Primary disk '{disk_full_path}' missing. Continue launch? (y/n)", "y", to_lower=True) != "y":
                    raise SystemExit(f"Launch aborted by user due to missing primary disk: {disk_full_path}")
        
        if disk_full_path.exists(): 
            drive_params_list = [
                f"file={str(disk_full_path)}",
                f"if={disk_conf.get('interface', 'virtio')}",
                f"index={current_drive_index}",
                "media=disk"
            ]
            primary_disk_format = disk_conf.get('format', "") 
            if primary_disk_format: 
                drive_params_list.insert(1, f"format={primary_disk_format}") 
            
            command_parts["base"].extend(["-drive", ",".join(drive_params_list)])
            current_drive_index += 1

    # Shared Disks
    shared_disks_config = config.get("shared_disks", [])
    if not isinstance(shared_disks_config, list): 
        print(f"Warning: 'shared_disks' configuration for VM '{vm_name}' is not a list. Skipping shared disks.")
        shared_disks_config = []

    for shared_disk in shared_disks_config:
        shared_disk_path_str = shared_disk.get("path")
        if not shared_disk_path_str:
            print(f"Warning: A shared disk entry for VM '{vm_name}' is missing a path. Skipping.")
            continue
        shared_disk_full_path = Path(shared_disk_path_str)
        if not shared_disk_full_path.exists():
            print(f"Warning: Shared disk image '{shared_disk_full_path}' for VM '{vm_name}' not found. Skipping this shared disk.")
            continue

        drive_params_list = [
            f"file={str(shared_disk_full_path)}",
            f"if={shared_disk.get('interface', 'virtio')}",
            f"index={current_drive_index}",
            "media=disk"
        ]
        specified_format = shared_disk.get('format', "") 
        if specified_format: 
            drive_params_list.insert(1, f"format={specified_format}")

        if shared_disk.get("readonly", False):
            drive_params_list.append("readonly=on")

        command_parts["base"].extend(["-drive", ",".join(drive_params_list)])
        print(f"Info: Attaching shared disk '{shared_disk_full_path}' at index {current_drive_index} "
              f"(Format: {specified_format or 'auto-detect'}, Read-Only: {shared_disk.get('readonly', False)})")
        current_drive_index += 1

    iso_path_str = config.get("iso_path", "")
    if iso_path_str and Path(iso_path_str).is_file(): command_parts["base"].extend(["-cdrom", iso_path_str])
    elif iso_path_str: print(f"Warning: ISO image '{iso_path_str}' not found.")
    floppy_path_str = config.get("floppy_path", "")
    if floppy_path_str and Path(floppy_path_str).is_file(): command_parts["base"].extend(["-fda", floppy_path_str])
    elif floppy_path_str: print(f"Warning: Floppy image '{floppy_path_str}' not found.")
    
    command_parts["base"].extend(["-boot", f"order={config.get('boot_order', 'c')}"])
    
    if config.get("network_enabled", False) and config.get("network_type", "user") == "user":
        command_parts["base"].extend(["-netdev", "user,id=net0", "-device", "e1000,netdev=net0"])

    script_generated_audio_args = []
    script_intends_to_disable_audio = False
    audio_enabled_in_config = config.get("audio_enabled", False) 
    audio_model = config.get("audio_device_model", "none").lower()
    audio_backend = config.get("audio_backend", "none").lower()

    if audio_enabled_in_config and audio_model != "none" and audio_backend != "none":
        backend_driver = audio_backend
        if backend_driver == "auto": 
            if CURRENT_OS == "windows": backend_driver = "wasapi" 
            elif CURRENT_OS == "linux": backend_driver = "pa"      
            elif CURRENT_OS == "macos": backend_driver = "coreaudio" 
            else: backend_driver = "sdl" 
            print(f"Auto-selected audio backend: {backend_driver}")
        
        audio_id = "audio0" 
        script_generated_audio_args.extend(["-audiodev", f"{backend_driver},id={audio_id}"])
        script_generated_audio_args.extend(["-device", f"{audio_model},audiodev={audio_id}"])
    else:
        script_intends_to_disable_audio = True

    final_extra_args = []
    extra_args_str = config.get("extra_qemu_args", "")
    if extra_args_str:
        temp_extra_args = shlex.split(extra_args_str)
        i = 0
        while i < len(temp_extra_args):
            arg = temp_extra_args[i]
            arg_val_next = temp_extra_args[i+1] if i + 1 < len(temp_extra_args) else None
            
            if script_generated_audio_args or script_intends_to_disable_audio:
                is_filtered_audio_arg = False
                if arg == "-soundhw":
                    print(f"Note: Filtering '{arg} {arg_val_next or ''}' from extra_qemu_args due to script's audio config.")
                    i += 1 
                    if arg_val_next is not None: i+=1 
                    is_filtered_audio_arg = True
                elif arg == "-audiodev":
                    print(f"Note: Filtering '{arg} {arg_val_next or ''}' from extra_qemu_args due to script's audio config.")
                    i += 1 
                    if arg_val_next is not None: i+=1 
                    is_filtered_audio_arg = True
                elif arg == "-device" and arg_val_next:
                    driver_part = arg_val_next.split(',')[0].lower()
                    if "audiodev=" in arg_val_next.lower() or driver_part in EXACT_AUDIO_DEVICE_DRIVERS:
                        print(f"Note: Filtering audio-related device '{arg} {arg_val_next}' from extra_qemu_args.")
                        i += 2 
                        is_filtered_audio_arg = True
                
                if is_filtered_audio_arg:
                    continue 

            final_extra_args.append(arg)
            i += 1
            
    command_parts["extra"] = final_extra_args
    command_parts["script_audio"] = script_generated_audio_args 

    final_command = list(command_parts["base"])
    final_command.extend(command_parts["extra"])
    final_command.extend(command_parts["script_audio"])

    if script_intends_to_disable_audio:
        has_any_active_audio_config_in_final_cmd = any(
            arg == "-audiodev" or \
            (arg == "-soundhw" and (final_command.index(arg) + 1 < len(final_command) and final_command[final_command.index(arg)+1].lower() != "none")) or \
            (arg == "-device" and (final_command.index(arg) + 1 < len(final_command) and \
                ("audiodev=" in final_command[final_command.index(arg)+1].lower() or \
                 final_command[final_command.index(arg)+1].split(',')[0].lower() in EXACT_AUDIO_DEVICE_DRIVERS)))
            for arg in final_command
        )
        
        if not has_any_active_audio_config_in_final_cmd:
            print("Note: Audio is disabled by script config. No explicit 'disable audio' flag will be added, "
                  "relying on the absence of audio device configurations.")
        elif script_generated_audio_args: 
             print("Warning: Script intended to disable audio, but script-generated audio arguments were found. "
                   "This indicates a potential bug in the script's logic. Audio might still be active.")
    return final_command

def launch_vm(vm_name: str):
    """Launches the specified VM."""
    try:
        qemu_command_list = build_qemu_command(vm_name)
        if not qemu_command_list:
            print(f"Could not prepare launch command for '{vm_name}'. Aborting launch.")
            return

        print("\n--- QEMU Launch Command ---")
        display_cmd = [f'"{arg}"' if (' ' in arg and not arg.startswith('-')) else arg for arg in qemu_command_list]
        print(' '.join(display_cmd))
        print("---------------------------\n")

        print(f"Launching VM: {vm_name}...")
        process = subprocess.Popen(qemu_command_list)
        process.wait() 
        print(f"VM '{vm_name}' has exited. Return code: {process.returncode}")
    except FileNotFoundError:
        qemu_exe_path = get_qemu_executable("system") 
        print(f"Error: QEMU executable ('{qemu_exe_path}') not found. Please check Global Settings or ensure QEMU is in PATH.")
    except SystemExit as e: 
        print(f"Launch aborted: {e}")
    except Exception as e:
        print(f"An unexpected error occurred while trying to launch '{vm_name}': {e}")
        import traceback
        traceback.print_exc()


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
        try: 
            choice_idx = int(choice_str) - 1
            if 0 <= choice_idx < len(keys): return keys[choice_idx]
        except ValueError: pass 
        if choice_str in keys: return choice_str
        print("Invalid selection. Please enter a valid number from the list or an exact ID.")

def create_edit_vm_config(vm_name_to_edit: str = None):
    """Interactive CUI to create or edit a VM configuration."""
    is_new_vm = vm_name_to_edit is None
    config = {}
    vm_id = ""

    if is_new_vm:
        print("\n--- Create New VM Configuration ---")
        base_name = get_user_input("Enter a base name for the new VM")
        if not base_name: 
            print("VM name cannot be empty.")
            return
        sanitized_name = "".join(c if c.isalnum() or c in ['_','-'] else '_' for c in base_name.lower())
        temp_vm_id = sanitized_name
        counter = 1
        while temp_vm_id in VM_CONFIGURATIONS:
            temp_vm_id = f"{sanitized_name}_{counter:02}" 
            counter += 1
        vm_id = temp_vm_id
        print(f"Generated unique VM ID: {vm_id}")
        
        config = NEW_VM_DEFAULTS.copy() 
        config["name"] = base_name 
        config["disk_image"] = config.get("disk_image", {}).copy()
        config["disk_image"]["path"] = f"{vm_id}_disk.{config['disk_image'].get('format', GLOBAL_SETTINGS['default_disk_format'])}"
        config["shared_disks"] = [] 
    else: 
        vm_id = vm_name_to_edit
        if vm_id not in VM_CONFIGURATIONS:
            print(f"Error: VM configuration with ID '{vm_id}' not found.")
            return
        print(f"\n--- Edit VM Configuration: {VM_CONFIGURATIONS[vm_id].get('name', vm_id)} (ID: {vm_id}) ---")
        config = VM_CONFIGURATIONS[vm_id].copy() 
        config["disk_image"] = config.get("disk_image", {}).copy()
        loaded_shared_disks = config.get("shared_disks", [])
        if isinstance(loaded_shared_disks, list):
            config["shared_disks"] = [disk.copy() for disk in loaded_shared_disks if isinstance(disk, dict)]
        else:
            config["shared_disks"] = [] 

    config["name"] = get_user_input("VM Name (friendly display name)", config.get("name", vm_id))
    config["description"] = get_user_input("Description", config.get("description", ""))

    print("\n--- Installation Media ---")
    iso_base_dir = Path(GLOBAL_SETTINGS.get("remember_last_iso_dir", SCRIPT_DIR))
    config["iso_path"] = get_path_from_user("Path to ISO image", iso_base_dir, config.get("iso_path", ""), 
                                            allow_blank_as_none=True, must_exist_if_provided=True, 
                                            remember_dir_key="remember_last_iso_dir")
    config["floppy_path"] = get_path_from_user("Path to floppy image", SCRIPT_DIR, config.get("floppy_path", ""), 
                                               allow_blank_as_none=True, must_exist_if_provided=True)

    print("\n--- Virtual Hard Disk (Primary) ---")
    disk_conf = config.get("disk_image", {}) 
    vm_storage_dir = Path(GLOBAL_SETTINGS["default_vm_storage_dir"])
    common_disk_formats_prompt = "qcow2, vhd, vhdx, vmdk, vdi, raw"
    format_prompt_suffix = "- blank for auto-detect"


    if get_user_input("Configure primary virtual hard disk? (yes/no)", "yes" if disk_conf or is_new_vm else "no", to_lower=True) == "yes": # Changed default to 'yes' for consistency
        default_primary_disk_path = disk_conf.get("path", f"{vm_id}_disk.{GLOBAL_SETTINGS['default_disk_format']}")
        disk_conf["path"] = get_path_from_user("Primary disk image filename (relative to VM storage or absolute)", 
                                               vm_storage_dir, default_primary_disk_path, 
                                               allow_blank_as_none=False, must_exist_if_provided=False)
        if disk_conf["path"]: 
            current_primary_format = disk_conf.get("format") 
            default_format_for_prompt = current_primary_format if current_primary_format is not None else GLOBAL_SETTINGS["default_disk_format"]
            
            disk_conf["format"] = get_user_input(f"Primary disk format ({common_disk_formats_prompt} {format_prompt_suffix})", 
                                                 default_format_for_prompt)
            disk_conf["interface"] = get_user_input("Primary disk interface type (ide, sata, scsi, virtio)", 
                                                    disk_conf.get("interface", "virtio"))
            
            prospective_disk_path = Path(disk_conf["path"])
            if not prospective_disk_path.is_absolute():
                prospective_disk_path = (vm_storage_dir / disk_conf["path"]).resolve()

            if not prospective_disk_path.exists():
                disk_conf["size"] = get_user_input("Primary disk size (e.g., 10G, 512M) - if creating", 
                                                   disk_conf.get("size", "20G"))
                # Ensure create_if_missing is asked with y/n and defaults to 'y'
                disk_conf["create_if_missing"] = get_user_input("Create primary disk if missing at launch? (y/n)", 
                                                                "y" if disk_conf.get("create_if_missing",True) else "n" , 
                                                                to_lower=True) == "y"
            else:
                print(f"Primary disk '{prospective_disk_path}' already exists. Size/Create options skipped.")
                disk_conf.pop("size", None) 
                disk_conf["create_if_missing"] = False 
        else: 
            disk_conf = {} 
    elif not disk_conf: 
        disk_conf = {}
    config["disk_image"] = disk_conf 

    print("\n--- Shared Disks (Additional) ---")
    if config["shared_disks"]:
        print("Current shared disks:")
        for i, disk_item in enumerate(config["shared_disks"]):
            print(f"  {i+1}. Path: {disk_item.get('path', 'N/A')}, "
                  f"Format: {disk_item.get('format', '') or 'auto-detect'}, " 
                  f"Interface: {disk_item.get('interface', 'virtio')}, "
                  f"ReadOnly: {disk_item.get('readonly', False)}")
        if get_user_input("Modify existing shared disks? (This will clear current list and let you re-add) (y/n)", "n", to_lower=True) == "y":
            config["shared_disks"] = [] 

    while True:
        # Changed prompt to y/n
        if get_user_input(f"Add {'another' if config['shared_disks'] else 'a'} shared disk? (y/n)", "n", to_lower=True) != "y":
            break
        
        shared_disk_item = {}
        print(f"\nConfiguring Shared Disk #{len(config['shared_disks']) + 1}")
        
        shared_disk_item["path"] = get_path_from_user(
            "Shared disk image path (absolute recommended, or relative to script dir for existing files)",
            SCRIPT_DIR, default_path_abs="", allow_blank_as_none=False, must_exist_if_provided=True 
        )
        if not shared_disk_item["path"]: 
            print("Shared disk path cannot be empty. Skipping this shared disk.")
            continue
        
        shared_disk_item["format"] = get_user_input(
            f"Shared disk format ({common_disk_formats_prompt} {format_prompt_suffix})",
            "" 
        )
        shared_disk_item["interface"] = get_user_input(
            "Shared disk interface type (ide, sata, scsi, virtio)", "virtio" 
        )
        # Changed prompt to y/n
        shared_disk_item["readonly"] = get_user_input(
            "Mount as read-only? (y/n)", "n", to_lower=True
        ) == "y"
        
        config["shared_disks"].append(shared_disk_item)
        print(f"Shared disk '{shared_disk_item['path']}' added.")

    print("\n--- System Resources ---")
    config["ram"] = get_user_input("RAM (e.g., 4G, 1024M)", config.get("ram", "2G"))
    config["cpu_cores"] = get_user_input("CPU cores (number)", str(config.get("cpu_cores", "2")))

    print("\n--- QEMU Specifics ---")
    config["machine_type"] = get_user_input("Machine type (e.g., pc, q35, microvm)", config.get("machine_type", "q35"))
    config["accelerator"] = get_user_input("Accelerator (auto, kvm, whpx, hvf, tcg)", config.get("accelerator", "auto"), to_lower=True)
    config["graphics"] = get_user_input("Graphics card (std, virtio, vmware, qxl, none)", config.get("graphics", "virtio"))
    
    # Changed prompt to y/n
    config["audio_enabled"] = get_user_input("Enable Audio? (y/n)", "y" if config.get("audio_enabled", True) else "n", to_lower=True) == "y"
    if config["audio_enabled"]:
        audio_model_options = EXACT_AUDIO_DEVICE_DRIVERS + ["none"] 
        current_audio_model = config.get("audio_device_model", "ich9-intel-hda")
        config["audio_device_model"] = get_user_input(f"Audio Device Model ({','.join(audio_model_options)})", current_audio_model, to_lower=True)
        
        audio_backends = ["auto", "wasapi", "dsound", "sdl", "pa", "alsa", "coreaudio", "none"] 
        current_audio_backend = config.get("audio_backend", "auto")
        config["audio_backend"] = get_user_input(f"Audio Backend ({','.join(audio_backends)})", current_audio_backend, to_lower=True)
        
        if config["audio_device_model"] == "none" or config["audio_backend"] == "none":
            print("Audio device model or backend set to 'none', audio will be disabled by QEMU config logic.")
    else: 
        config["audio_device_model"] = "none" 
        config["audio_backend"] = "none"

    # Changed prompt to y/n
    config["network_enabled"] = get_user_input("Enable Network? (y/n)", "y" if config.get("network_enabled", True) else "n", to_lower=True) == "y"
    if config["network_enabled"]:
        config["network_type"] = get_user_input("Network type (user, bridge, tap - 'user' is simplest)", config.get("network_type", "user"), to_lower=True)
    
    # Changed prompt to y/n
    config["usb_tablet"] = get_user_input("Enable USB tablet for mouse (y/n recommended)?", "y" if config.get("usb_tablet", True) else "n", to_lower=True) == "y"
    
    default_bo = "c" 
    if config.get("iso_path"): default_bo = "dc" 
    elif config.get("floppy_path"): default_bo = "ac" 
    if config.get("iso_path") and not disk_conf.get("path"): default_bo = "d" 

    config["boot_order"] = get_user_input("Boot order (c=disk,d=cdrom,a=floppy,n=net - e.g. 'dc')", config.get("boot_order", default_bo))
    config["extra_qemu_args"] = get_user_input("Extra QEMU arguments (ADVANCED - use with care)", config.get("extra_qemu_args", ""))

    VM_CONFIGURATIONS[vm_id] = config
    save_vm_configurations()
    print(f"Configuration for VM '{config['name']}' (ID: {vm_id}) {'created' if is_new_vm else 'updated'}.")


def delete_vm_config():
    """Lets the user select and delete a VM configuration and optionally its disk."""
    if not VM_CONFIGURATIONS: print("No VM configurations to delete."); return
    print("\n--- Delete VM Configuration ---")
    vm_id_to_delete = select_from_list_keys(VM_CONFIGURATIONS, "Select VM configuration to delete")
    if vm_id_to_delete:
        vm_config = VM_CONFIGURATIONS[vm_id_to_delete]; vm_display_name = vm_config.get('name', vm_id_to_delete)
        # Changed prompt to y/n
        if get_user_input(f"Are you sure you want to delete the configuration for '{vm_display_name}' (ID: {vm_id_to_delete})? (y/n)", "n", to_lower=True) == 'y':
            disk_path_str = vm_config.get("disk_image", {}).get("path")
            if disk_path_str:
                disk_full_path = Path(disk_path_str) if Path(disk_path_str).is_absolute() else Path(GLOBAL_SETTINGS["default_vm_storage_dir"]) / disk_path_str
                disk_full_path = disk_full_path.resolve()
                if disk_full_path.exists():
                    # Changed prompt to y/n
                    if get_user_input(f"Also delete the primary disk image '{disk_full_path}'? THIS IS PERMANENT. (y/n)", "n",to_lower=True) == 'y':
                        try: 
                            disk_full_path.unlink()
                            print(f"Primary disk image '{disk_full_path}' deleted.")
                        except OSError as e: 
                            print(f"Error deleting primary disk image '{disk_full_path}': {e}")
            
            del VM_CONFIGURATIONS[vm_id_to_delete]
            save_vm_configurations()
            print(f"VM configuration '{vm_display_name}' (ID: {vm_id_to_delete}) deleted.")
        else: 
            print("Deletion cancelled.")

def manage_global_settings_interactive():
    print("\n--- Manage Global Settings ---"); gs = GLOBAL_SETTINGS 
    print(f"Current Operating System: {CURRENT_OS.capitalize()}")
    print("\nQEMU Executable Paths:")
    print(f"  System (Windows): {gs.get('qemu_system_exe_windows', 'Not set')}")
    print(f"  System (Linux):   {gs.get('qemu_system_exe_linux', 'Not set')}")
    print(f"  System (macOS):   {gs.get('qemu_system_exe_macos', 'Not set')}")
    print(f"  Img    (Windows): {gs.get('qemu_img_exe_windows', 'Not set')}")
    print(f"  Img    (Linux):   {gs.get('qemu_img_exe_linux', 'Not set')}")
    print(f"  Img    (macOS):   {gs.get('qemu_img_exe_macos', 'Not set')}")
    print("\nDefault Storage Settings:")
    print(f"  Default Disk Format:    {gs.get('default_disk_format', 'Not set')}") 
    print(f"  Default VM Storage Dir: {gs.get('default_vm_storage_dir', 'Not set')}")
    print("\nUser Experience:")
    print(f"  Last Used ISO Directory: {gs.get('remember_last_iso_dir', 'Not set')}")

    # Changed prompt to y/n
    if get_user_input("\nModify global settings? (y/n)", "n", to_lower=True) == 'y':
        print("\nEnter new values or press Enter to keep current.")
        
        gs["qemu_system_exe_windows"] = get_user_input("QEMU System for Windows", gs.get("qemu_system_exe_windows"))
        gs["qemu_system_exe_linux"] = get_user_input("QEMU System for Linux", gs.get("qemu_system_exe_linux"))
        gs["qemu_system_exe_macos"] = get_user_input("QEMU System for macOS", gs.get("qemu_system_exe_macos"))
        
        gs["qemu_img_exe_windows"] = get_user_input("QEMU Img for Windows", gs.get("qemu_img_exe_windows"))
        gs["qemu_img_exe_linux"] = get_user_input("QEMU Img for Linux", gs.get("qemu_img_exe_linux"))
        gs["qemu_img_exe_macos"] = get_user_input("QEMU Img for macOS", gs.get("qemu_img_exe_macos"))
        
        common_disk_formats_global_prompt = "qcow2, vhd, vhdx, vmdk, vdi, raw"
        gs["default_disk_format"] = get_user_input(f"Default Disk Format for NEW disks (e.g., {common_disk_formats_global_prompt})", gs.get("default_disk_format"))
        
        new_vm_dir = get_path_from_user("Default VM Storage Directory", SCRIPT_DIR, 
                                        gs.get("default_vm_storage_dir"), 
                                        allow_blank_as_none=False, must_exist_if_provided=False, 
                                        is_dir_selector=True)
        if new_vm_dir: 
            ensure_dir_exists(Path(new_vm_dir)) 
            gs["default_vm_storage_dir"] = str(Path(new_vm_dir).resolve()) 

        new_iso_dir = get_path_from_user("Default Directory for ISO selection (blank to reset to script dir)", SCRIPT_DIR, 
                                         gs.get("remember_last_iso_dir"), 
                                         allow_blank_as_none=True, must_exist_if_provided=False, 
                                         is_dir_selector=True)
        gs["remember_last_iso_dir"] = new_iso_dir if new_iso_dir else str(SCRIPT_DIR) 

        save_global_settings()
        print("Global settings updated.")
    print("--- End of Global Settings ---")

def initial_setup_check():
    """Checks for QEMU and offers to create a default generic VM config."""
    q_sys = get_qemu_executable("system"); q_img = get_qemu_executable("img")
    q_ok = True
    if not q_sys or (not Path(q_sys).is_file() and not shutil.which(q_sys)): 
        print(f"Warning: QEMU system executable ('{q_sys or 'Not configured'}') not found or configured incorrectly."); q_ok=False
    if not q_img or (not Path(q_img).is_file() and not shutil.which(q_img)): 
        print(f"Warning: qemu-img executable ('{q_img or 'Not configured'}') not found or configured incorrectly."); q_ok=False
    
    if not q_ok:
        # Changed prompt to y/n
        if get_user_input("QEMU does not seem to be fully configured. Go to Global Settings to configure QEMU paths now? (y/n)", "y",to_lower=True) == "y":
            manage_global_settings_interactive()
            q_sys = get_qemu_executable("system"); q_img = get_qemu_executable("img")
            if not q_sys or (not Path(q_sys).is_file() and not shutil.which(q_sys)) or \
               not q_img or (not Path(q_img).is_file() and not shutil.which(q_img)):
                print("Warning: QEMU still appears to be not fully configured after settings update.")
            else:
                print("QEMU paths seem to be configured now.")

    if not VM_CONFIGURATIONS:
        # Changed prompt to y/n
        if get_user_input("\nNo VM configurations found. Create a new generic VM configuration to get started? (y/n)", "y",to_lower=True) == "y":
            create_edit_vm_config(None) 

def main_menu():
    """Displays the main menu and handles user choices."""
    initial_setup_check() 
    while True:
        qemu_system_path = get_qemu_executable('system')
        qemu_status = qemu_system_path if (qemu_system_path and (Path(qemu_system_path).is_file() or shutil.which(qemu_system_path))) else "Not Found/Configured!"
        
        print(f"\n--- QEMU VM Launcher ---")
        print(f"OS: {CURRENT_OS.capitalize()} | QEMU System: {qemu_status}")
        print(f"VM Configurations available: {len(VM_CONFIGURATIONS)}")
        print("------------------------")
        print("1. Launch VM")
        print("2. Create New VM Configuration")
        print("3. Edit Existing VM Configuration")
        print("4. Delete VM Configuration")
        print("5. Manage Global Settings")
        print("0. Exit")
        print("------------------------")
        
        choice = input("Enter your choice: ").strip()
        
        if choice == '1':
            if not VM_CONFIGURATIONS: 
                print("No VM configurations available. Please create one first.")
                continue
            vm_id = select_from_list_keys(VM_CONFIGURATIONS, "Select VM to launch")
            if vm_id: 
                launch_vm(vm_id)
        elif choice == '2': 
            create_edit_vm_config(None)
        elif choice == '3':
            if not VM_CONFIGURATIONS: 
                print("No VM configurations to edit. Please create one first.")
                continue
            vm_id = select_from_list_keys(VM_CONFIGURATIONS, "Select VM configuration to edit")
            if vm_id: 
                create_edit_vm_config(vm_id)
        elif choice == '4': 
            delete_vm_config()
        elif choice == '5': 
            manage_global_settings_interactive()
        elif choice == '0': 
            print("Exiting QEMU VM Launcher.")
            break
        else: 
            print("Invalid choice. Please try again.")

if __name__ == "__main__":
    try: 
        main_menu()
    except KeyboardInterrupt: 
        print("\nOperation cancelled by user. Exiting.")
    except SystemExit as e: 
        print(f"Exiting: {e}") 
    except Exception as e:
        print(f"\n--- An Unexpected Error Occurred ---")
        print(f"Error Type: {type(e).__name__}")
        print(f"Error Message: {e}")
        import traceback
        print("\n--- Traceback ---")
        traceback.print_exc()
        print("-------------------")
    finally:
        input("Press Enter to exit program...")
