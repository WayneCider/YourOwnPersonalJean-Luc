"""Test configuration — set up sandbox to allow temp directory access.

Tests need permissive sandbox because they test tool behavior, not sandbox behavior.
Sandbox-specific tests create their own Sandbox instances with strict=True.
"""

import os
import sys
import tempfile

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.sandbox import configure_sandbox

# Configure sandbox permissively for tool tests — sandbox security is tested
# separately in dedicated test_sandbox_* functions that create strict instances
configure_sandbox(
    allowed_dirs=[
        os.path.realpath(os.getcwd()),
        os.path.realpath(tempfile.gettempdir()),
    ],
    strict=False,
)
