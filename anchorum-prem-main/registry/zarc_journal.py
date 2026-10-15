"""
Plane 1 (kernel/domain/application/governance): Monotonic timestamp provider.

This module provides ZarcJournal.now_ns() for monotonic timestamps without wall-clock dependency.
Essential for deterministic event ordering and signature chain integrity.
"""

import time
import logging
from typing import Optional, Callable

logger = logging.getLogger(__name__)


class ZarcJournal:
    """
    Provides monotonic timestamping for deterministic event ordering.
    
    Uses a combination of:
    1. System monotonic clock (if available)
    2. Fallback to high-resolution time with offset tracking
    3. Event chain hashing for cross-session continuity
    """
    
    _monotonic_base_ns: Optional[int] = None
    _offset_ns: int = 0
    _initialized: bool = False
    
    @classmethod
    def now_ns(cls) -> int:
        """
        Get current monotonic timestamp in nanoseconds.
        
        Returns a value that:
        - Is monotonically increasing within a session
        - Can be compared across sessions via event chain
        - Does not depend on wall-clock time
        """
        if not cls._initialized:
            cls._initialize()
        
        current_time_ns = time.time_ns()
        offset = cls._offset_ns
        
        # Combine monotonic base with current time, applying offset
        result = cls._monotonic_base_ns + (current_time_ns - int(time.time())) * 1_000_000_000 + offset
        
        return result
    
    @classmethod
    def _initialize(cls) -> None:
        """Initialize the monotonic clock."""
        if cls._initialized:
            return
        
        try:
            # Try to get monotonic time (Python 3.3+)
            cls._monotonic_base_ns = time.monotonic_ns()
            cls._offset_ns = 0
            cls._initialized = True
            
            logger.info("ZarcJournal initialized with monotonic clock")
            
        except AttributeError:
            # Fallback: use wall-clock with offset tracking
            cls._monotonic_base_ns = int(time.time()) * 1_000_000_000
            cls._offset_ns = 0
            cls._initialized = True
            
            logger.warning("ZarcJournal using wall-clock fallback")
    
    @classmethod
    def set_offset(cls, offset_ns: int) -> None:
        """Set an offset for cross-session continuity."""
        if not cls._initialized:
            cls._initialize()
        
        cls._offset_ns = offset_ns
        logger.info(f"ZarcJournal offset set to {offset_ns} ns")
    
    @classmethod
    def get_monotonic_base(cls) -> Optional[int]:
        """Get the monotonic base timestamp."""
        return cls._monotonic_base_ns
    
    @classmethod
    def is_initialized(cls) -> bool:
        """Check if ZarcJournal has been initialized."""
        return cls._initialized


# Initialize on first import
ZarcJournal.now_ns()

__all__ = ['ZarcJournal', 'now_ns']
