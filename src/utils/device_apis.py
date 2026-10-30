import ctypes
import subprocess
import logging
from typing import Optional

log = logging.getLogger(__name__)

# Windows Virtual Key Codes for Media Keys
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF

def _press_key(hex_key_code: int):
    """Simulates a physical key press and release using Windows ctypes."""
    try:
        # keybd_event (virtual-key, hardware scan code, flags, extra info)
        ctypes.windll.user32.keybd_event(hex_key_code, 0, 0, 0) # Press
        ctypes.windll.user32.keybd_event(hex_key_code, 0, 2, 0) # Release
    except Exception as e:
        log.error(f"Failed to press key {hex_key_code}: {e}")

class DeviceController:
    """
    OS-level wrappers for controlling device hardware like volume and brightness.
    Currently optimized for Windows environments without requiring external C-bindings.
    """

    @staticmethod
    def volume_up(steps: int = 2):
        """Increases system volume by stepping the volume up key."""
        log.info(f"Increasing system volume by {steps} steps.")
        for _ in range(steps):
            _press_key(VK_VOLUME_UP)

    @staticmethod
    def volume_down(steps: int = 2):
        """Decreases system volume by stepping the volume down key."""
        log.info(f"Decreasing system volume by {steps} steps.")
        for _ in range(steps):
            _press_key(VK_VOLUME_DOWN)

    @staticmethod
    def toggle_mute():
        """Toggles the system volume mute state."""
        log.info("Toggling system mute state.")
        _press_key(VK_VOLUME_MUTE)

    @staticmethod
    def set_brightness(level: int):
        """
        Sets the screen brightness to a specific percentage (0-100).
        Uses PowerShell WMI bindings (no third-party pip packages required).
        """
        if not (0 <= level <= 100):
            log.warning(f"Brightness level {level} is out of bounds. Clamping to 0-100.")
            level = max(0, min(100, level))
            
        log.info(f"Setting screen brightness to {level}%.")
        
        # PowerShell command to interface with WMI monitors and set brightness
        ps_script = f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1, {level})"
        
        try:
            subprocess.run(
                ["powershell", "-Command", ps_script],
                capture_output=True,
                text=True,
                check=True,
                creationflags=subprocess.CREATE_NO_WINDOW # Hides the flashing console window
            )
        except subprocess.CalledProcessError as e:
            log.error(f"Failed to set brightness. PowerShell error: {e.stderr}")
        except Exception as e:
            log.error(f"Failed to execute brightness command: {e}")

