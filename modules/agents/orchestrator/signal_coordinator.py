"""Signal coordinator - manages signal lifecycle, batches, and table states."""
import asyncio
import logging
import time
from typing import Dict, Optional, Set, List, Any
from enum import Enum
from dataclasses import dataclass, field
from collections import defaultdict

from ...signals.core import Signal, SignalType


class TableLifecycleState(Enum):
    """Table lifecycle states."""
    PENDING = "pending"  # Pending
    EXTRACTING = "extracting"  # Extracting
    EXTRACTED = "extracted"  # Extraction complete
    VERIFYING = "verifying"  # Verifying
    VERIFIED = "verified"  # Verification complete
    FIXING = "fixing"  # Fixing
    FIXED = "fixed"  # Fixing complete
    WARM_START = "warm_start"  # Warm starting
    FINAL = "final"  # Finalized
    ERROR = "error"  # Error state


@dataclass
class SignalWaiter:
    """Signal waiter - waits for the response to a specific signal."""
    correlation_id: str
    signal_type: SignalType
    created_at: float
    timeout: float
    future: asyncio.Future = field(default_factory=asyncio.Future)
    response_signal: Optional[Signal] = None
    
    def is_expired(self) -> bool:
        """Check whether the waiter has timed out."""
        return time.time() - self.created_at > self.timeout
    
    def complete(self, signal: Signal):
        """Complete the wait."""
        if not self.future.done():
            self.response_signal = signal
            self.future.set_result(signal)
    
    def timeout_cancel(self):
        """Cancel due to timeout."""
        if not self.future.done():
            self.future.set_exception(TimeoutError(f"Signal {self.correlation_id} timeout after {self.timeout}s"))


@dataclass
class BatchTracker:
    """Batch tracker."""
    table_name: str
    batch_index: int  # Original batch index (e.g. 1, 2, 3...)
    total_batches: int
    state: str = "pending"  # pending, extracting, extracted, verifying, verified, fixing, fixed, merged, final
    snapshot: Any = None
    violations: List = field(default_factory=list)
    fixes: List = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    is_warm_start: bool = False  # Whether this is a warm start batch
    warm_start_count: int = 0  # Number of warm starts for this batch
    max_warm_start_attempts: int = 1  # At most 1 warm start per batch
    verification_round: int = 0  # Verification round of this batch
    max_verification_rounds: int = 1  # At most 1 verification round per batch
    
    def get_batch_key(self) -> str:
        """Get the unique key for the batch."""
        prefix = "warm_start_" if self.is_warm_start else ""
        return f"{prefix}batch_{self.batch_index}"


@dataclass
class TableStateTracker:
    """Table state tracker."""
    table_name: str
    current_state: TableLifecycleState = TableLifecycleState.PENDING
    batch_trackers: Dict[str, BatchTracker] = field(default_factory=dict)  # Keyed by string
    total_batches: int = 1  # Default 1 batch (non multi-document mode)
    completed_batches: int = 0
    snapshot: Any = None
    violations: List = field(default_factory=list)
    fixes: List = field(default_factory=list)
    verify_fix_iteration: int = 0  # Verify-fix iteration count
    max_iterations: int = 1
    warm_start_attempted: bool = False
    is_relation_table: bool = False
    created_at: float = field(default_factory=time.time)
    verification_round: int = 0  # Verification round
    max_verification_rounds: int = 2  # Max verification rounds (default 2)
    
    def can_transition_to(self, new_state: TableLifecycleState) -> bool:
        """Check whether a transition to the new state is allowed."""
        valid_transitions = {
            TableLifecycleState.PENDING: [
                TableLifecycleState.EXTRACTING,
                TableLifecycleState.EXTRACTED,  # Allow warm start to go directly to extracted
                TableLifecycleState.VERIFYING,  # Allow warm start to go directly to verifying
                TableLifecycleState.VERIFIED,   # Allow marking verified directly after warm start
                TableLifecycleState.FIXING,     # Allow going to fixing directly after warm start
                TableLifecycleState.FIXED,      # Allow marking fixed directly after warm start
                TableLifecycleState.WARM_START, # Allow entering warm start state
                TableLifecycleState.FINAL,      # Allow finalizing directly after warm start
                TableLifecycleState.ERROR
            ],
            TableLifecycleState.EXTRACTING: [TableLifecycleState.EXTRACTED, TableLifecycleState.ERROR],
            TableLifecycleState.EXTRACTED: [TableLifecycleState.VERIFYING, TableLifecycleState.ERROR],
            TableLifecycleState.VERIFYING: [TableLifecycleState.VERIFIED, TableLifecycleState.ERROR],
            TableLifecycleState.VERIFIED: [
                TableLifecycleState.FIXING,
                TableLifecycleState.WARM_START,
                TableLifecycleState.FINAL,  # If no violations, go directly to final
                TableLifecycleState.ERROR
            ],
            TableLifecycleState.FIXING: [
                TableLifecycleState.FIXED,
                TableLifecycleState.ERROR
            ],
            TableLifecycleState.FIXED: [
                TableLifecycleState.VERIFYING,  # Re-verify after fixing
                TableLifecycleState.FINAL,
                TableLifecycleState.ERROR
            ],
            TableLifecycleState.WARM_START: [
                TableLifecycleState.EXTRACTED,  # Return to extracted after warm start
                TableLifecycleState.VERIFYING,  # Can go directly to verifying after warm start
                TableLifecycleState.ERROR
            ],
            TableLifecycleState.FINAL: [],  # Terminal state
            TableLifecycleState.ERROR: []  # Terminal state
        }
        
        return new_state in valid_transitions.get(self.current_state, [])
    
    def transition_to(self, new_state: TableLifecycleState) -> bool:
        """Transition to a new state."""
        if self.can_transition_to(new_state):
            old_state = self.current_state
            self.current_state = new_state
            return True
        return False
    
    def all_batches_completed(self) -> bool:
        """Check whether all batches are completed."""
        return self.completed_batches >= self.total_batches
    
    def is_batch_mode(self) -> bool:
        """Whether batch mode is in use."""
        return self.total_batches > 1


class SignalCoordinator:
    """Signal coordinator - unified management of signal lifecycle and state tracking.
    
    Core features:
    1. Signal-level synchronization: send a signal and wait for a response, with timeout support
    2. Batch-level management: track the state of all batches for each table
    3. Table-level management: manage the full lifecycle state machine of a table
    """
    
    def __init__(self, broadcaster, default_timeout: float = 600.0):
        """
        Args:
            broadcaster: Signal broadcaster
            default_timeout: Default timeout in seconds
        """
        self.broadcaster = broadcaster
        self.default_timeout = default_timeout
        self.logger = logging.getLogger('signal.coordinator')
        
        self.signal_waiters: Dict[str, SignalWaiter] = {}
        
        self.table_trackers: Dict[str, TableStateTracker] = {}
        
        self.response_signal_types = {
            SignalType.EXTRACTION_REQUEST: [
                SignalType.EXTRACTION_COMPLETE,
                SignalType.EXTRACTION_ERROR
            ],
            SignalType.VERIFICATION_REQUEST: [
                SignalType.VERIFICATION_COMPLETE,
                SignalType.VERIFICATION_ERROR
            ],
            SignalType.FIXING_REQUEST: [
                SignalType.FIXING_COMPLETE,
                SignalType.FIXING_ERROR
            ]
        }
        
        self._cleanup_task = None
    
    def start(self):
        '''Start coordinator'''
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_waiters())
        self.logger.info("Signal coordinator started")
    
    async def stop(self):
        '''Stop the coordinator'''
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        self.logger.info("Signal coordinator stopped")
    
    async def _cleanup_expired_waiters(self):
        '''Clean up timeout waiters'''
        while True:
            try:
                await asyncio.sleep(10)  # Check every 10 seconds
                
                expired_ids = []
                for correlation_id, waiter in self.signal_waiters.items():
                    if waiter.is_expired():
                        expired_ids.append(correlation_id)
                        waiter.timeout_cancel()
                        self.logger.warning(f"Signal wait timed out: {correlation_id}")
                
                for correlation_id in expired_ids:
                    del self.signal_waiters[correlation_id]
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Cleanup expired waiters exception: {e}")
    
    async def send_and_wait(
        self,
        signal_type: SignalType,
        data: Dict[str, Any],
        correlation_id: str,
        timeout: Optional[float] = None
    ) -> Optional[Signal]:
        '''Send signal and wait for response
        
        Args:
            signal_type: signal type
            data: signal data
            correlation_id: correlation ID
            timeout: timeout (seconds), None uses the default value
            
        Returns:
            Respond to the signal and return None after timeout'''
        timeout = timeout or self.default_timeout
        
        
        waiter = SignalWaiter(
            correlation_id=correlation_id,
            signal_type=signal_type,
            created_at=time.time(),
            timeout=timeout
        )
        self.signal_waiters[correlation_id] = waiter
        
        try:
            await self.broadcaster.emit_simple_signal(
                signal_type=signal_type,
                data=data,
                correlation_id=correlation_id
            )
            
            response = await asyncio.wait_for(waiter.future, timeout=timeout)
            return response
            
        except asyncio.TimeoutError:
            self.logger.error(f"[Coordinator] Signal wait timed out: {correlation_id}, timeout: {timeout}s")
            self.logger.error(f"[Coordinator] Expected response type: {self.response_signal_types.get(signal_type, 'unknown')}")
            return None
        except Exception as e:
            self.logger.error(f"[Coordinator] Signal send or wait exception: {e}")
            import traceback
            traceback.print_exc()
            return None
        finally:
            if correlation_id in self.signal_waiters:
                del self.signal_waiters[correlation_id]
    
    def notify_response(self, signal: Signal):
        '''Notification received response signal
        
        Args:
            signal: response signal'''
        correlation_id = signal.correlation_id
        
        if correlation_id in self.signal_waiters:
            waiter = self.signal_waiters[correlation_id]
            waiter.complete(signal)
            self.logger.debug(f"Response signal notified: {correlation_id}")
        else:
            self.logger.debug(f"Received untracked response signal: {correlation_id}")
    
    
    def init_table_tracker(
        self,
        table_name: str,
        total_batches: int = 1,
        is_relation_table: bool = False,
        max_iterations: int = 1
    ) -> TableStateTracker:
        '''Initialize table tracker
        
        Args:
            table_name: table name
            total_batches: total number of batches
            is_relation_table: whether it is a relational table
            max_iterations: Maximum number of verification-repair iterations (default 1, that is, verify and repair once)
            
        Returns:
            Table status tracker'''
        if table_name in self.table_trackers:
            self.logger.warning(f"Table tracker already exists: {table_name}, will be reset")
        
        tracker = TableStateTracker(
            table_name=table_name,
            total_batches=total_batches,
            is_relation_table=is_relation_table,
            max_iterations=max_iterations
        )
        
        self.table_trackers[table_name] = tracker
        self.logger.info(
            f"Initialized table tracker: {table_name}, "
            f"batches={total_batches}, "
            f"relation={is_relation_table}"
        )
        
        return tracker
    
    def get_table_tracker(self, table_name: str) -> Optional[TableStateTracker]:
        '''Get table tracker'''
        return self.table_trackers.get(table_name)
    
    def update_table_state(
        self,
        table_name: str,
        new_state: TableLifecycleState,
        force: bool = False
    ) -> bool:
        '''Update table status
        
        Args:
            table_name: table name
            new_state: new state
            force: whether to force update (skip state transition check)
            
        Returns:
            Is the update successful?'''
        tracker = self.get_table_tracker(table_name)
        if not tracker:
            self.logger.error(f"Table tracker not found: {table_name}")
            return False
        
        if force:
            old_state = tracker.current_state
            tracker.current_state = new_state
            self.logger.info(f"Force updated table state: {table_name} {old_state.value} -> {new_state.value}")
            return True
        
        if tracker.transition_to(new_state):
            self.logger.info(f"Table state transition: {table_name} -> {new_state.value}")
            return True
        else:
            self.logger.warning(
                f"Invalid state transition: {table_name} "
                f"{tracker.current_state.value} -> {new_state.value}"
            )
            return False
    
    def is_table_in_state(self, table_name: str, state: TableLifecycleState) -> bool:
        '''Check if the table is in the specified state'''
        tracker = self.get_table_tracker(table_name)
        return tracker and tracker.current_state == state
    
    def wait_table_state(
        self,
        table_name: str,
        target_states: List[TableLifecycleState],
        timeout: float = 300.0
    ) -> asyncio.Future:
        '''Wait for expression to reach target state (asynchronous)
        
        Args:
            table_name: table name
            target_states: list of target states
            timeout: timeout time
            
        Returns:
            Future object'''
        async def _wait():
            start_time = time.time()
            while time.time() - start_time < timeout:
                tracker = self.get_table_tracker(table_name)
                if tracker and tracker.current_state in target_states:
                    return tracker.current_state
                await asyncio.sleep(0.5)
            raise TimeoutError(f"Wait for table state timed out: {table_name}")
        
        return asyncio.create_task(_wait())
    
    
    @staticmethod
    def _get_batch_key(batch_index: int, is_warm_start: bool = False) -> str:
        '''Generate the unique key of the batch
        
        Args:
            batch_index: original batch index
            is_warm_start: whether it is warm start batch
            
        Returns:
            batch key, in the format "batch_1" or "warm_start_batch_1"'''
        prefix = "warm_start_" if is_warm_start else ""
        return f"{prefix}batch_{batch_index}"
    
    def init_batch_tracker(
        self,
        table_name: str,
        batch_index: int,
        total_batches: int,
        is_warm_start: bool = False
    ) -> BatchTracker:
        '''Initialize the batch tracker
        
        Args:
            table_name: table name
            batch_index: original batch index
            total_batches: total number of batches
            is_warm_start: whether it is warm start batch'''
        tracker = self.get_table_tracker(table_name)
        if not tracker:
            tracker = self.init_table_tracker(table_name, total_batches)
        
        batch_key = self._get_batch_key(batch_index, is_warm_start)
        batch_tracker = BatchTracker(
            table_name=table_name,
            batch_index=batch_index,
            total_batches=total_batches,
            is_warm_start=is_warm_start
        )
        
        tracker.batch_trackers[batch_key] = batch_tracker
        warm_start_label = " (warm start)" if is_warm_start else ""
        self.logger.debug(f"Initialized batch tracker: {table_name} batch {batch_index}/{total_batches}{warm_start_label}")
        
        return batch_tracker
    
    def update_batch_state(
        self,
        table_name: str,
        batch_index: int,
        state: str,
        **kwargs
    ):
        '''Update batch status
        
        Args:
            table_name: table name
            batch_index: batch index
            state: new state
            **kwargs: other attributes (snapshot, violations, fixes, etc.)'''
        tracker = self.get_table_tracker(table_name)
        if not tracker:
            self.logger.error(f"Table tracker not found: {table_name}")
            return
        
        is_warm_start = kwargs.pop('is_warm_start', False)
        batch_key = self._get_batch_key(batch_index, is_warm_start)
        
        if batch_key not in tracker.batch_trackers:
            self.logger.warning(f"Batch tracker not found: {table_name} {batch_key}")
            return
        
        batch_tracker = tracker.batch_trackers[batch_key]
        batch_tracker.state = state
        
        for key, value in kwargs.items():
            if hasattr(batch_tracker, key):
                setattr(batch_tracker, key, value)
        
        self.logger.debug(f"Updated batch state: {table_name} batch {batch_index} -> {state}")
    
    def mark_batch_completed(self, table_name: str, batch_index: int, is_warm_start: bool = False):
        '''Mark the batch as completed (only marked as completed, does not increment the count)
        
        Note: This method only marks the batch status as completed.
        The real completion count should be incremented when the batch reaches the final state (handled by mark_batch_final)'''
        tracker = self.get_table_tracker(table_name)
        if not tracker:
            return
        
        self.update_batch_state(table_name, batch_index, "completed", is_warm_start=is_warm_start)
        
        self.logger.debug(
            f"Batch marked completed: {table_name} batch {batch_index}"
        )
    
    def all_batches_completed(self, table_name: str) -> bool:
        '''Check whether all batches of the table have been completed'''
        tracker = self.get_table_tracker(table_name)
        return tracker and tracker.all_batches_completed()
    
    async def wait_all_batches(self, table_name: str, timeout: float = 600.0) -> bool:
        '''Wait for all batches of the table to complete
        
        Args:
            table_name: table name
            timeout: timeout time
            
        Returns:
            Whether all batches are completed'''
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self.all_batches_completed(table_name):
                return True
            await asyncio.sleep(0.5)
        
        self.logger.warning(f"Wait for batch completion timed out: {table_name}")
        return False
    
    
    def get_all_tables_status(self) -> Dict[str, str]:
        '''Get the status of all tables'''
        return {
            table_name: tracker.current_state.value
            for table_name, tracker in self.table_trackers.items()
        }
    
    def all_tables_final(self) -> bool:
        '''Check if all tables are completed'''
        if not self.table_trackers:
            return False
        
        return all(
            tracker.current_state == TableLifecycleState.FINAL
            for tracker in self.table_trackers.values()
        )
    
    async def wait_all_tables_final(self, timeout: float = 1800.0) -> bool:
        '''Wait for all tables to complete
        
        Args:
            timeout: timeout time
            
        Returns:
            Are all tables completed?'''
        start_time = time.time()
        last_log_time = 0
        
        while time.time() - start_time < timeout:
            if self.all_tables_final():
                self.logger.info("All tables processing complete")
                return True
            
            elapsed = time.time() - start_time
            if elapsed - last_log_time >= 10:
                status = self.get_all_tables_status()
                pending = [k for k, v in status.items() if v != 'final']
                self.logger.info(
                    f"Waiting for tables: {len(pending)}/{len(status)} incomplete, "
                    f"elapsed {elapsed:.0f}s"
                )
                last_log_time = elapsed
            
            await asyncio.sleep(1.0)
        
        status = self.get_all_tables_status()
        pending = {k: v for k, v in status.items() if v != 'final'}
        self.logger.warning(f"Wait for all tables timed out: {pending}")
        return False
    
    def get_statistics(self) -> Dict[str, Any]:
        '''Get statistics'''
        stats = {
            'total_tables': len(self.table_trackers),
            'total_waiters': len(self.signal_waiters),
            'tables_by_state': defaultdict(int),
            'total_batches': 0,
            'completed_batches': 0
        }
        
        for tracker in self.table_trackers.values():
            stats['tables_by_state'][tracker.current_state.value] += 1
            stats['total_batches'] += tracker.total_batches
            stats['completed_batches'] += tracker.completed_batches
        
        return dict(stats)
    
    
    def can_verify_fix_iterate(self, table_name: str, batch_index: Optional[int] = None) -> bool:
        '''Check if verification-fix loop can continue
        
        Args:
            table_name: table name
            batch_index: batch index (None means table level)
            
        Returns:
            Is it possible to continue iterating?'''
        if batch_index is not None:
            self.logger.info(f'[Loop control] Batch-level check: table={table_name}, batch_index={batch_index}')
            tracker = self.get_table_tracker(table_name)
            batch_key = self._get_batch_key(batch_index, is_warm_start=False)
            
            if not tracker:
                self.logger.warning(f'[Loop control] Table tracker not found: {table_name}')
                return False
            
            if batch_key not in tracker.batch_trackers:
                self.logger.warning(
                    f'[Loop control] Batch tracker not found: {table_name} batch_key={batch_key}, '
                    f'existing keys={list(tracker.batch_trackers.keys())}'
                )
                return False
            
            batch_tracker = tracker.batch_trackers[batch_key]
            can_iterate = batch_tracker.verification_round < batch_tracker.max_verification_rounds
            
            self.logger.info(
                f'[Loop control] Batch-level: round={batch_tracker.verification_round}/{batch_tracker.max_verification_rounds}, '
                f'can_continue={can_iterate}'
            )
            
            if not can_iterate:
                self.logger.warning(
                    f'Batch {batch_index} reached max verify-fix iterations '
                    f'({batch_tracker.verification_round}/{batch_tracker.max_verification_rounds})'
                )
            
            return can_iterate
        else:
            self.logger.info(f'[Loop control] Table-level check: {table_name}')
            tracker = self.get_table_tracker(table_name)
            if not tracker:
                self.logger.warning(f'[Loop control] Table tracker not found: {table_name}')
                return False
            
            can_iterate = tracker.verify_fix_iteration < tracker.max_iterations
            
            self.logger.info(
                f'[Loop control] Table-level: round={tracker.verify_fix_iteration}/{tracker.max_iterations}, '
                f'can_continue={can_iterate}'
            )
            
            if not can_iterate:
                self.logger.warning(
                    f'Table {table_name} reached max verify-fix iterations '
                    f'({tracker.verify_fix_iteration}/{tracker.max_iterations})'
                )
            
            return can_iterate
    
    def increment_verify_fix_iteration(self, table_name: str, batch_index: Optional[int] = None) -> int:
        '''Increase validation - fix iteration count
        
        Args:
            table_name: table name
            batch_index: batch index (None means table level)
            
        Returns:
            Current number of iterations (after increment)'''
        if batch_index is not None:
            tracker = self.get_table_tracker(table_name)
            batch_key = self._get_batch_key(batch_index, is_warm_start=False)
            if not tracker or batch_key not in tracker.batch_trackers:
                return 0
            
            batch_tracker = tracker.batch_trackers[batch_key]
            batch_tracker.verification_round += 1
            
            self.logger.info(
                f'Batch {batch_index} verify-fix cycle '
                f'{batch_tracker.verification_round}/{batch_tracker.max_verification_rounds}'
            )
            
            return batch_tracker.verification_round
        else:
            tracker = self.get_table_tracker(table_name)
            if not tracker:
                return 0
            
            tracker.verify_fix_iteration += 1
            
            self.logger.info(
                f'Table {table_name} verify-fix cycle '
                f'{tracker.verify_fix_iteration}/{tracker.max_iterations}'
            )
            
            return tracker.verify_fix_iteration
    
    def can_warm_start(self, table_name: str, batch_index: Optional[int] = None) -> bool:
        '''Check if Warm Start reextraction can be performed
        
        Args:
            table_name: table name
            batch_index: batch index (None means table level)
            
        Returns:
            Is it possible to execute Warm Start?'''
        if batch_index is not None:
            tracker = self.get_table_tracker(table_name)
            batch_key = self._get_batch_key(batch_index, is_warm_start=False)
            if not tracker or batch_key not in tracker.batch_trackers:
                return False
            
            batch_tracker = tracker.batch_trackers[batch_key]
            can_warm = batch_tracker.warm_start_count < batch_tracker.max_warm_start_attempts
            
            if not can_warm:
                self.logger.warning(
                    f'Batch {batch_index} reached max Warm Start attempts '
                    f'({batch_tracker.warm_start_count}/{batch_tracker.max_warm_start_attempts})'
                )
            
            return can_warm
        else:
            tracker = self.get_table_tracker(table_name)
            if not tracker:
                return False
            
            can_warm = not tracker.warm_start_attempted
            
            if not can_warm:
                self.logger.warning(f'Table {table_name} already attempted Warm Start')
            
            return can_warm
    
    def increment_warm_start_attempts(self, table_name: str, batch_index: Optional[int] = None) -> int:
        '''Increase Warm Start attempts
        
        Args:
            table_name: table name
            batch_index: batch index (None means table level)
            
        Returns:
            Current number of attempts (after increase)'''
        if batch_index is not None:
            tracker = self.get_table_tracker(table_name)
            batch_key = self._get_batch_key(batch_index, is_warm_start=False)
            if not tracker or batch_key not in tracker.batch_trackers:
                return 0
            
            batch_tracker = tracker.batch_trackers[batch_key]
            batch_tracker.warm_start_count += 1
            
            self.logger.info(
                f'Batch {batch_index} Warm Start attempt '
                f'{batch_tracker.warm_start_count}/{batch_tracker.max_warm_start_attempts}'
            )
            
            return batch_tracker.warm_start_count
        else:
            tracker = self.get_table_tracker(table_name)
            if not tracker:
                return 0
            
            tracker.warm_start_attempted = True
            self.logger.info(f'Table {table_name} starting Warm Start attempt')
            
            return 1
    
    
    
    def can_verify(self, table_name: str) -> bool:
        '''Check if verification can continue
        
        Args:
            table_name: table name
            
        Returns:
            Is it possible to continue verification?'''
        tracker = self.get_table_tracker(table_name)
        if not tracker:
            self.logger.warning(f"Table tracker not found: {table_name}")
            return False
        
        if tracker.verification_round >= tracker.max_verification_rounds:
            self.logger.warning(
                f'Table {table_name} completed {tracker.verification_round} verify-fix cycles, '
                f'reached max rounds ({tracker.max_verification_rounds}), '
                f'force terminating to avoid infinite loop'
            )
            return False
        
        return True
    
    def increment_verification_round(self, table_name: str) -> int:
        '''Increase verification rounds
        
        Args:
            table_name: table name
            
        Returns:
            Current round (after increase)'''
        tracker = self.get_table_tracker(table_name)
        if not tracker:
            self.logger.error(f"Table tracker not found: {table_name}")
            return 0
        
        tracker.verification_round += 1
        self.logger.info(
            f'Table {table_name} verify-fix cycle '
            f'{tracker.verification_round}/{tracker.max_verification_rounds}'
        )
        
        return tracker.verification_round
    
    
    def get_verification_round(self, table_name: str) -> int:
        '''Get verification round'''
        tracker = self.get_table_tracker(table_name)
        return tracker.verification_round if tracker else 0
    
    
    def reset_verification_round(self, table_name: str):
        '''Reset verification rounds (for special cases)'''
        tracker = self.get_table_tracker(table_name)
        if tracker:
            tracker.verification_round = 0
            self.logger.info(f"Reset verification round for table {table_name}")
    
    
    def can_batch_warm_start(self, table_name: str, batch_index: int) -> bool:
        '''Check whether the specified batch can continue to execute warm start
        
        Args:
            table_name: table name
            batch_index: batch index
            
        Returns:
            Is it possible to continue warm start?'''
        tracker = self.get_table_tracker(table_name)
        if not tracker:
            self.logger.warning(f"Table tracker not found: {table_name}")
            return False
        
        batch_key = self._get_batch_key(batch_index, is_warm_start=False)
        if batch_key not in tracker.batch_trackers:
            self.logger.warning(f"Batch tracker not found: {table_name} batch {batch_index}")
            return False
        
        batch_tracker = tracker.batch_trackers[batch_key]
        
        if batch_tracker.warm_start_count >= batch_tracker.max_warm_start_attempts:
            self.logger.warning(
                f'Table {table_name} batch {batch_index} reached max warm start attempts '
                f'({batch_tracker.warm_start_count}/{batch_tracker.max_warm_start_attempts}), '
                f'refusing to continue to avoid infinite loop'
            )
            return False
        
        return True
    
    def increment_batch_warm_start_count(self, table_name: str, batch_index: int) -> int:
        '''Increase the warm start count of the specified batch
        
        Args:
            table_name: table name
            batch_index: batch index
            
        Returns:
            Current count (after increment)'''
        tracker = self.get_table_tracker(table_name)
        if not tracker:
            self.logger.error(f"Table tracker not found: {table_name}")
            return 0
        
        batch_key = self._get_batch_key(batch_index, is_warm_start=False)
        if batch_key not in tracker.batch_trackers:
            self.logger.error(f"Batch tracker not found: {table_name} batch {batch_index}")
            return 0
        
        batch_tracker = tracker.batch_trackers[batch_key]
        batch_tracker.warm_start_count += 1
        
        self.logger.info(
            f'Table {table_name} warm start attempt '
            f'{batch_tracker.warm_start_count}/{batch_tracker.max_warm_start_attempts}'
        )
        
        return batch_tracker.warm_start_count
    
    def get_batch_warm_start_count(self, table_name: str, batch_index: int) -> int:
        '''Get the warm start count of the specified batch'''
        tracker = self.get_table_tracker(table_name)
        batch_key = self._get_batch_key(batch_index, is_warm_start=False)
        if not tracker or batch_key not in tracker.batch_trackers:
            return 0
        return tracker.batch_trackers[batch_key].warm_start_count
    
    
    def can_batch_verify(self, table_name: str, batch_index: int) -> bool:
        '''Check whether the specified batch can continue to perform verification
        
        Args:
            table_name: table name
            batch_index: batch index
            
        Returns:
            Is it possible to continue verification?'''
        tracker = self.get_table_tracker(table_name)
        if not tracker:
            self.logger.warning(f"Table tracker not found: {table_name}")
            return False
        
        batch_key = self._get_batch_key(batch_index, is_warm_start=False)
        if batch_key not in tracker.batch_trackers:
            self.logger.warning(f"Batch tracker not found: {table_name} batch {batch_index}")
            return False
        
        batch_tracker = tracker.batch_trackers[batch_key]
        
        if batch_tracker.verification_round >= batch_tracker.max_verification_rounds:
            self.logger.warning(
                f'Table {table_name} batch {batch_index} reached max verification rounds '
                f'({batch_tracker.verification_round}/{batch_tracker.max_verification_rounds}), '
                f'force terminating to avoid infinite loop'
            )
            return False
        
        return True
    
    def increment_batch_verification_round(self, table_name: str, batch_index: int) -> int:
        '''Increase the verification rounds of the specified batch
        
        Args:
            table_name: table name
            batch_index: batch index
            
        Returns:
            Current round (after increase)'''
        tracker = self.get_table_tracker(table_name)
        if not tracker:
            self.logger.error(f"Table tracker not found: {table_name}")
            return 0
        
        batch_key = self._get_batch_key(batch_index, is_warm_start=False)
        if batch_key not in tracker.batch_trackers:
            self.logger.error(f"Batch tracker not found: {table_name} batch {batch_index}")
            return 0
        
        batch_tracker = tracker.batch_trackers[batch_key]
        batch_tracker.verification_round += 1
        
        self.logger.info(
            f'Table {table_name} batch {batch_index} verify-fix cycle '
            f'{batch_tracker.verification_round}/{batch_tracker.max_verification_rounds}'
        )
        
        return batch_tracker.verification_round
    
    def mark_batch_final(self, table_name: str, batch_index: int, is_warm_start: bool = False):
        '''Mark the batch as final (processing completed)
        
        Args:
            table_name: table name
            batch_index: original batch index
            is_warm_start: whether it is warm start batch'''
        tracker = self.get_table_tracker(table_name)
        if not tracker:
            return
        
        batch_key = self._get_batch_key(batch_index, is_warm_start)
        
        if batch_key in tracker.batch_trackers:
            batch_tracker = tracker.batch_trackers[batch_key]
            was_final = (batch_tracker.state == "final")
            
            self.update_batch_state(table_name, batch_index, "final", is_warm_start=is_warm_start)
            
            if not was_final:
                if not is_warm_start:
                    tracker.completed_batches += 1
                warm_start_label = " (warm start)" if is_warm_start else ""
                self.logger.info(
                    f"Batch completed: {table_name} batch {batch_index}{warm_start_label}, "
                    f"progress: {tracker.completed_batches}/{tracker.total_batches}"
                )
                
                if tracker.all_batches_completed():
                    self.logger.info(f"All batches completed: {table_name}")
                    if tracker.current_state != TableLifecycleState.FINAL:
                        self.logger.info(f"All batches completed, updating table {table_name} state to FINAL")
                        self.update_table_state(table_name, TableLifecycleState.FINAL)
            else:
                self.logger.debug(
                    f"Batch {batch_index} already final, skipping duplicate count"
                )
        else:
            self.logger.warning(f"Batch tracker not found: {table_name} batch {batch_index}")
    
    def is_batch_final(self, table_name: str, batch_index: int, is_warm_start: bool = False) -> bool:
        '''Check whether the batch has reached final status
        
        Args:
            table_name: table name
            batch_index: original batch index
            is_warm_start: whether it is warm start batch
            
        Returns:
            Has the final state been reached?'''
        tracker = self.get_table_tracker(table_name)
        if not tracker:
            return False
        
        batch_key = self._get_batch_key(batch_index, is_warm_start)
        if batch_key not in tracker.batch_trackers:
            return False
        
        batch_tracker = tracker.batch_trackers[batch_key]
        return batch_tracker.state == "final"
    
    async def wait_batch_final(self, table_name: str, batch_index: int, is_warm_start: bool = False, timeout: float = 600.0) -> bool:
        '''Wait for the batch to reach final state
        
        Args:
            table_name: table name
            batch_index: original batch index
            is_warm_start: whether it is warm start batch
            timeout: timeout (seconds)
            
        Returns:
            Whether the final state is successfully reached (False indicates timeout)'''
        if self.is_table_in_state(table_name, TableLifecycleState.FINAL):
            self.logger.info(f"Table {table_name} already FINAL, no need to wait for batch {batch_index}")
            if not self.is_batch_final(table_name, batch_index, is_warm_start):
                self.logger.info(f"Also marking Batch {batch_index} (warm_start={is_warm_start}) as final")
                self.mark_batch_final(table_name, batch_index, is_warm_start)
            return True
        
        start_time = time.time()
        last_log_time = 0
        
        warm_start_label = " (warm start)" if is_warm_start else ""
        self.logger.info(f"Waiting for batch {batch_index}{warm_start_label} to complete: {table_name}")
        
        while time.time() - start_time < timeout:
            if self.is_batch_final(table_name, batch_index, is_warm_start):
                elapsed = time.time() - start_time
                self.logger.info(f"Batch {batch_index}{warm_start_label} completed: {table_name}, elapsed {elapsed:.1f}s")
                return True
            
            elapsed = time.time() - start_time
            if elapsed - last_log_time >= 10:
                tracker = self.get_table_tracker(table_name)
                batch_key = self._get_batch_key(batch_index, is_warm_start)
                if tracker and batch_key in tracker.batch_trackers:
                    batch_tracker = tracker.batch_trackers[batch_key]
                    self.logger.info(
                        f"Batch {batch_index}{warm_start_label} in progress: {table_name}, "
                        f"state={batch_tracker.state}, "
                        f"elapsed {elapsed:.0f}s"
                    )
                last_log_time = elapsed
            
            await asyncio.sleep(0.5)
        
        if is_warm_start:
            self.logger.warning(
                f"Warm start batch {batch_index} timed out: {table_name}, "
                f"waited {timeout}s, skipping this batch"
            )
        else:
            self.logger.warning(
                f"Wait for batch {batch_index} timed out: {table_name}, "
                f"timeout {timeout}s"
            )
        return False
    


