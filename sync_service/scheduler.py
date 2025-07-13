"""
Sync Scheduler - Manages scheduled sync operations.
"""

import asyncio
from datetime import datetime, timedelta
from typing import Callable, Optional, Awaitable
from loguru import logger

from config.logging import LogExecutionTime


class SyncScheduler:
    """
    Manages scheduled sync operations.
    """
    
    def __init__(self, sync_interval_minutes: int, sync_callback: Callable[[], Awaitable[bool]]):
        self.sync_interval_minutes = sync_interval_minutes
        self.sync_callback = sync_callback
        self._running = False
        self._task = None
        self._next_sync_time = None
        self._sync_count = 0
        self._last_sync_success = None
        self._last_sync_time = None
    
    async def start(self):
        """Start the scheduler."""
        if self._running:
            logger.warning("Scheduler is already running")
            return
        
        logger.info(f"Starting scheduler with {self.sync_interval_minutes} minute intervals")
        self._running = True
        self._next_sync_time = datetime.now() + timedelta(minutes=self.sync_interval_minutes)
        
        # Start the scheduler task
        self._task = asyncio.create_task(self._scheduler_loop())
        
        logger.info("Scheduler started successfully")
    
    async def stop(self):
        """Stop the scheduler."""
        if not self._running:
            return
        
        logger.info("Stopping scheduler...")
        self._running = False
        
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("Scheduler stopped")
    
    async def _scheduler_loop(self):
        """Main scheduler loop."""
        try:
            while self._running:
                now = datetime.now()
                
                # Check if it's time for a sync
                if now >= self._next_sync_time:
                    await self._execute_sync()
                
                # Sleep for a short interval before checking again
                await asyncio.sleep(10)  # Check every 10 seconds
                
        except asyncio.CancelledError:
            logger.info("Scheduler loop cancelled")
        except Exception as e:
            logger.exception(f"Error in scheduler loop: {e}")
    
    async def _execute_sync(self):
        """Execute a scheduled sync."""
        logger.info("Executing scheduled sync")
        
        try:
            with LogExecutionTime("scheduled_sync"):
                # Execute the sync callback
                success = await self.sync_callback()
                
                # Update statistics
                self._sync_count += 1
                self._last_sync_success = success
                self._last_sync_time = datetime.now()
                
                # Schedule next sync
                self._next_sync_time = self._last_sync_time + timedelta(minutes=self.sync_interval_minutes)
                
                if success:
                    logger.info(f"Scheduled sync completed successfully. Next sync at {self._next_sync_time}")
                else:
                    logger.warning(f"Scheduled sync failed. Next sync at {self._next_sync_time}")
                
        except Exception as e:
            logger.exception(f"Error executing scheduled sync: {e}")
            # Still schedule next sync even if this one failed
            self._next_sync_time = datetime.now() + timedelta(minutes=self.sync_interval_minutes)
    
    async def trigger_immediate_sync(self) -> bool:
        """
        Trigger an immediate sync outside of the schedule.
        
        Returns:
            True if sync was successful, False otherwise
        """
        logger.info("Triggering immediate sync")
        
        try:
            success = await self.sync_callback()
            
            if success:
                logger.info("Immediate sync completed successfully")
                # Update last sync time but don't change next scheduled sync
                self._last_sync_time = datetime.now()
                self._last_sync_success = success
                self._sync_count += 1
            else:
                logger.warning("Immediate sync failed")
            
            return success
            
        except Exception as e:
            logger.exception(f"Error in immediate sync: {e}")
            return False
    
    def get_status(self) -> dict:
        """
        Get scheduler status.
        
        Returns:
            Dictionary with scheduler status
        """
        return {
            "running": self._running,
            "sync_interval_minutes": self.sync_interval_minutes,
            "next_sync_time": self._next_sync_time.isoformat() if self._next_sync_time else None,
            "sync_count": self._sync_count,
            "last_sync_time": self._last_sync_time.isoformat() if self._last_sync_time else None,
            "last_sync_success": self._last_sync_success,
            "time_until_next_sync": self._get_time_until_next_sync()
        }
    
    def _get_time_until_next_sync(self) -> Optional[int]:
        """
        Get seconds until next sync.
        
        Returns:
            Seconds until next sync or None if not scheduled
        """
        if not self._next_sync_time:
            return None
        
        delta = self._next_sync_time - datetime.now()
        return max(0, int(delta.total_seconds()))
    
    def reschedule(self, new_interval_minutes: int):
        """
        Reschedule with a new interval.
        
        Args:
            new_interval_minutes: New sync interval in minutes
        """
        logger.info(f"Rescheduling sync interval from {self.sync_interval_minutes} to {new_interval_minutes} minutes")
        
        self.sync_interval_minutes = new_interval_minutes
        
        # Update next sync time
        if self._last_sync_time:
            self._next_sync_time = self._last_sync_time + timedelta(minutes=new_interval_minutes)
        else:
            self._next_sync_time = datetime.now() + timedelta(minutes=new_interval_minutes)
        
        logger.info(f"Next sync rescheduled to {self._next_sync_time}")
    
    def pause(self):
        """Pause the scheduler (stop executing syncs but keep running)."""
        logger.info("Pausing scheduler")
        self._next_sync_time = None
    
    def resume(self):
        """Resume the scheduler from pause."""
        logger.info("Resuming scheduler")
        self._next_sync_time = datetime.now() + timedelta(minutes=self.sync_interval_minutes)
        logger.info(f"Next sync scheduled for {self._next_sync_time}")
    
    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running
    
    @property
    def is_paused(self) -> bool:
        """Check if scheduler is paused."""
        return self._running and self._next_sync_time is None