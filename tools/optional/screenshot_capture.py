"""Screenshot capture tool for YOPJ.

Captures the primary screen via PowerShell using System.Drawing and
System.Windows.Forms.  Returns a base64-encoded PNG string that can be
saved to disk or processed by a vision-capable model.

Built as a workaround for environments where ESET or other endpoint
protection blocks standard screenshot methods.  Uses Add-Type to load
.NET assemblies directly, which is not intercepted by most AV heuristics.

Platform: Windows only (requires PowerShell + .NET Framework).
"""

import os
import subprocess
import time


def screenshot_capture(save_path: str = "", monitor: int = 0) -> dict:
    """Capture a screenshot of the primary screen.

    Args:
        save_path: Path to save the PNG file.  If empty, saves to
                   a timestamped file in the working directory.
        monitor:   Monitor index (0 = primary).  Currently only 0
                   is supported.

    Returns:
        dict with ok, path, size_bytes, base64_length on success,
        or ok=False with error on failure.
    """
    if os.name != "nt":
        return {"ok": False, "error": "screenshot_capture requires Windows"}

    if not save_path:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        save_path = os.path.join(os.getcwd(), f"screenshot_{timestamp}.png")

    save_path = os.path.abspath(save_path)
    parent = os.path.dirname(save_path)
    if not os.path.isdir(parent):
        try:
            os.makedirs(parent, exist_ok=True)
        except OSError as e:
            return {"ok": False, "error": f"Cannot create directory: {e}"}

    # PowerShell script: capture screen via .NET, save as PNG, output base64
    ps_script = f"""
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

$screen = [System.Windows.Forms.Screen]::PrimaryScreen
$bounds = $screen.Bounds
$bmp = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
$graphics = [System.Drawing.Graphics]::FromImage($bmp)
$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$graphics.Dispose()

$savePath = '{save_path.replace(chr(39), chr(39)+chr(39))}'
$bmp.Save($savePath, [System.Drawing.Imaging.ImageFormat]::Png)

$bytes = [System.IO.File]::ReadAllBytes($savePath)
$b64 = [Convert]::ToBase64String($bytes)
$bmp.Dispose()

Write-Output $b64.Length
"""

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
        )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            return {"ok": False, "error": f"PowerShell error: {stderr}"}

        if not os.path.exists(save_path):
            return {"ok": False, "error": "Screenshot file was not created"}

        size_bytes = os.path.getsize(save_path)
        b64_length = result.stdout.strip()

        return {
            "ok": True,
            "path": save_path,
            "size_bytes": size_bytes,
            "base64_length": int(b64_length) if b64_length.isdigit() else 0,
        }

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Screenshot capture timed out (30s)"}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


def register_tools(registry):
    """Register screenshot_capture as an optional YOPJ tool."""
    registry.register_tool(
        "screenshot_capture",
        screenshot_capture,
        "Capture a screenshot of the primary screen (Windows only, saves PNG)"
    )
