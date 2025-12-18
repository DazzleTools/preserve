"""
Operation handlers for preserve commands.

This module contains the implementation of various preserve operations,
organized to keep the main preserve.py file manageable.
"""

from .verify import handle_verify_operation
from .copy import handle_copy_operation
from .move import handle_move_operation
from .restore import handle_restore_operation
from .config import handle_config_operation
from .cleanup import handle_cleanup_operation

__all__ = [
    'handle_verify_operation',
    'handle_copy_operation',
    'handle_move_operation',
    'handle_restore_operation',
    'handle_config_operation',
    'handle_cleanup_operation'
]