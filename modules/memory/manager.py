"""Memory manager acting as the central data exchange."""
import asyncio
import logging
import threading
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime
import uuid
from concurrent.futures import ThreadPoolExecutor
import weakref

from .snapshot import TableSnapshot
from .violation import Violation
from .fix import Fix
from ..core.io import IOManager


@dataclass
class MemoryReference:
    """Memory reference. A lightweight reference passed within signals."""
    run_id: str
    table_name: str
    snapshot_id: Optional[str] = None
    violation_ids: List[str] = field(default_factory=list)
    fix_ids: List[str] = field(default_factory=list)
    operation_type: str = "read"  # read, write, update
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to a dict."""
        return {
            'run_id': self.run_id,
            'table_name': self.table_name,
            'snapshot_id': self.snapshot_id,
            'violation_ids': self.violation_ids,
            'fix_ids': self.fix_ids,
            'operation_type': self.operation_type,
            'timestamp': self.timestamp.isoformat()
        }


class MemoryManager:
    """Memory manager providing centralized data storage and access."""
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(MemoryManager, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not hasattr(self, '_initialized'):
            self.logger = logging.getLogger('memory.manager')
            
            self._snapshots: Dict[str, TableSnapshot] = {}  # {snapshot_id: TableSnapshot}
            self._violations: Dict[str, Violation] = {}     # {violation_id: Violation}
            self._fixes: Dict[str, Fix] = {}                # {fix_id: Fix}
            
            self._snapshot_index: Dict[str, Dict[str, str]] = {}  # {run_id: {table_name: snapshot_id}}
            self._violation_index: Dict[str, Dict[str, List[str]]] = {}  # {run_id: {table_name: [violation_ids]}}
            self._fix_index: Dict[str, Dict[str, List[str]]] = {}  # {run_id: {table_name: [fix_ids]}}
            
            self._unfixable_violations: Dict[str, Set[str]] = {}  # {run_id: {violation_id}}
            
            self._run_metadata: Dict[str, Dict[str, Any]] = {}  # {run_id: metadata}
            
            self._rw_locks: Dict[str, asyncio.Lock] = {}  # {run_id: Lock}
            self._access_stats: Dict[str, Dict[str, int]] = {}  # {run_id: {operation: count}}
            
            self._observers: Set[weakref.ref] = set()
            self._cleanup_threshold = 100  # Automatic cleanup threshold
            
            self._initialized = True
            self.logger.info("MemoryManager initialized")
    
    @classmethod
    def get_instance(cls) -> 'MemoryManager':
        """Return the singleton instance."""
        return cls()
    
    def _get_run_lock(self, run_id: str) -> asyncio.Lock:
        """Return the run-level lock."""
        if run_id not in self._rw_locks:
            self._rw_locks[run_id] = asyncio.Lock()
        return self._rw_locks[run_id]
    
    def _record_access(self, run_id: str, operation: str):
        """Record access statistics."""
        if run_id not in self._access_stats:
            self._access_stats[run_id] = {}
        self._access_stats[run_id][operation] = self._access_stats[run_id].get(operation, 0) + 1
    
    async def initialize_run(self, run_id: str, metadata: Dict[str, Any] = None):
        """Initialize a run."""
        async with self._get_run_lock(run_id):
            self._run_metadata[run_id] = metadata or {}
            self._snapshot_index[run_id] = {}
            self._violation_index[run_id] = {}
            self._fix_index[run_id] = {}
            self._record_access(run_id, 'initialize')
            
            self.logger.info(f"Initialized run: {run_id}")
    
    
    async def store_snapshot(self, snapshot: TableSnapshot, run_id: str = None) -> str:
        """Store a snapshot and return its ID, with support for staged snapshots."""
        if run_id is None:
            run_id = snapshot.run_id
        
        stage = getattr(snapshot, 'processing_stage', 'unknown')
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]  # Millisecond precision
        snapshot_id = f"snapshot_{run_id}_{snapshot.table}_{stage}_{timestamp}"
        
        async with self._get_run_lock(run_id):
            self._snapshots[snapshot_id] = snapshot
            
            if run_id not in self._snapshot_index:
                self._snapshot_index[run_id] = {}
            if snapshot.table not in self._snapshot_index[run_id]:
                self._snapshot_index[run_id][snapshot.table] = {}
            
            if 'stages' not in self._snapshot_index[run_id][snapshot.table]:
                self._snapshot_index[run_id][snapshot.table]['stages'] = {}
            self._snapshot_index[run_id][snapshot.table]['stages'][stage] = snapshot_id
            
            self._snapshot_index[run_id][snapshot.table]['latest'] = snapshot_id
            self._snapshot_index[run_id][snapshot.table]['latest_stage'] = stage
            
            self._record_access(run_id, 'store_snapshot')
            
            self.logger.debug(f"Stored staged snapshot: {snapshot_id} (table: {snapshot.table}, stage: {stage}, rows: {len(snapshot.rows)})")
            
        return snapshot_id
    
    async def get_snapshot(self, run_id: str, table_name: str, stage: str = None) -> Optional[TableSnapshot]:
        """Get a snapshot, with support for fetching by stage."""
        async with self._get_run_lock(run_id):
            if (run_id in self._snapshot_index and 
                table_name in self._snapshot_index[run_id]):
                
                table_index = self._snapshot_index[run_id][table_name]
                
                if isinstance(table_index, dict):
                    if stage and 'stages' in table_index and stage in table_index['stages']:
                        snapshot_id = table_index['stages'][stage]
                    elif 'latest' in table_index:
                        snapshot_id = table_index['latest']
                    else:
                        return None
                else:
                    snapshot_id = table_index
                
                snapshot = self._snapshots.get(snapshot_id)
                self._record_access(run_id, 'get_snapshot')
                
                if snapshot:
                    current_stage = getattr(snapshot, 'processing_stage', 'unknown')
                    self.logger.debug(f"Fetched snapshot: {table_name} (stage: {current_stage})")
                
                return snapshot
        
        return None
    
    async def get_snapshot_by_id(self, snapshot_id: str) -> Optional[TableSnapshot]:
        """Get a snapshot by ID."""
        return self._snapshots.get(snapshot_id)
    
    async def get_snapshots_by_stage(self, run_id: str, table_name: str) -> Dict[str, TableSnapshot]:
        """Get all staged snapshots for a table."""
        result = {}
        async with self._get_run_lock(run_id):
            if (run_id in self._snapshot_index and 
                table_name in self._snapshot_index[run_id]):
                
                table_index = self._snapshot_index[run_id][table_name]
                
                if isinstance(table_index, dict) and 'stages' in table_index:
                    for stage, snapshot_id in table_index['stages'].items():
                        snapshot = self._snapshots.get(snapshot_id)
                        if snapshot:
                            result[stage] = snapshot
                
                self._record_access(run_id, 'get_snapshots_by_stage')
                
        return result
    
    async def get_snapshot_stages(self, run_id: str, table_name: str) -> List[str]:
        """Get the list of all snapshot stages for a table."""
        stages = []
        async with self._get_run_lock(run_id):
            if (run_id in self._snapshot_index and 
                table_name in self._snapshot_index[run_id]):
                
                table_index = self._snapshot_index[run_id][table_name]
                
                if isinstance(table_index, dict) and 'stages' in table_index:
                    stages = list(table_index['stages'].keys())
                
        return stages
    
    async def get_all_snapshots(self, run_id: str) -> Dict[str, TableSnapshot]:
        """Get the latest snapshot for every table in a run, with staged snapshot support."""
        result = {}
        async with self._get_run_lock(run_id):
            if run_id in self._snapshot_index:
                for table_name, table_index in self._snapshot_index[run_id].items():
                    if isinstance(table_index, dict):
                        if 'latest' in table_index:
                            snapshot_id = table_index['latest']
                            if snapshot_id in self._snapshots:
                                result[table_name] = self._snapshots[snapshot_id]
                    else:
                        snapshot_id = table_index
                        if snapshot_id in self._snapshots:
                            result[table_name] = self._snapshots[snapshot_id]
            
            self._record_access(run_id, 'get_all_snapshots')
            
        return result
    
    
    async def store_violations(self, violations: List[Violation], run_id: str, table_name: str) -> List[str]:
        """Store a list of violations and return their IDs."""
        violation_ids = []
        
        async with self._get_run_lock(run_id):
            for violation in violations:
                violation_id = f"violation_{run_id}_{table_name}_{uuid.uuid4().hex[:8]}"
                self._violations[violation_id] = violation
                violation_ids.append(violation_id)
            
            if run_id not in self._violation_index:
                self._violation_index[run_id] = {}
            if table_name not in self._violation_index[run_id]:
                self._violation_index[run_id][table_name] = []
            
            self._violation_index[run_id][table_name].extend(violation_ids)
            self._record_access(run_id, 'store_violations')
            
            self.logger.debug(f"Stored violations: {len(violations)} (table: {table_name})")
        
        return violation_ids
    
    async def get_violations(self, run_id: str, table_name: str) -> List[Violation]:
        """Get the violations for a table."""
        violations = []
        async with self._get_run_lock(run_id):
            if (run_id in self._violation_index and 
                table_name in self._violation_index[run_id]):
                
                violation_ids = self._violation_index[run_id][table_name]
                violations = [
                    self._violations[vid] for vid in violation_ids 
                    if vid in self._violations
                ]
                
                self._record_access(run_id, 'get_violations')
        
        return violations
    
    async def get_violations_by_ids(self, violation_ids: List[str]) -> List[Violation]:
        """Get violations by a list of IDs."""
        return [
            self._violations[vid] for vid in violation_ids 
            if vid in self._violations
        ]
    
    async def clear_violations(self, run_id: str, table_name: str):
        """Clear the violation records for a table."""
        async with self._get_run_lock(run_id):
            if (run_id in self._violation_index and 
                table_name in self._violation_index[run_id]):
                
                violation_ids = self._violation_index[run_id][table_name]
                for vid in violation_ids:
                    if vid in self._violations:
                        del self._violations[vid]
                
                self._violation_index[run_id][table_name] = []
                self._record_access(run_id, 'clear_violations')
                
                self.logger.debug(f"Cleared violations for table {table_name}")
    
    async def mark_violation_unfixable(self, violation_id: str, run_id: str):
        """Mark a violation as unfixable."""
        async with self._get_run_lock(run_id):
            if run_id not in self._unfixable_violations:
                self._unfixable_violations[run_id] = set()
            self._unfixable_violations[run_id].add(violation_id)
            self.logger.info(f"Marked violation {violation_id} as unfixable")
    
    async def is_violation_unfixable(self, violation_id: str, run_id: str) -> bool:
        """Check whether a violation has been marked as unfixable."""
        async with self._get_run_lock(run_id):
            if run_id not in self._unfixable_violations:
                return False
            return violation_id in self._unfixable_violations[run_id]
    
    async def get_unfixable_violations(self, run_id: str) -> Set[str]:
        """Get all unfixable violation IDs."""
        async with self._get_run_lock(run_id):
            return self._unfixable_violations.get(run_id, set()).copy()
    
    async def check_repeated_violations(self, violations: List[Violation], run_id: str, 
                                       table_name: str) -> List[Violation]:
        """
        Detect repeated violations: if a cell was already fixed but the violation
        persists, the fix failed.
        
        Args:
            violations: The current list of violations
            run_id: Run ID
            table_name: Table name
            
        Returns:
            List of violations that reappeared (failed fixes)
        """
        repeated = []
        
        async with self._get_run_lock(run_id):
            if (run_id not in self._fix_index or 
                table_name not in self._fix_index[run_id]):
                return repeated
            
            fix_ids = self._fix_index[run_id][table_name]
            fixes = [self._fixes[fid] for fid in fix_ids if fid in self._fixes]
            
            fixed_cells = set()
            for fix in fixes:
                if hasattr(fix, 'tuple_id') and hasattr(fix, 'attr'):
                    fixed_cells.add((fix.tuple_id, fix.attr))
            
            for violation in violations:
                cell_key = (violation.tuple_id, violation.attr)
                if cell_key in fixed_cells:
                    repeated.append(violation)
                    self.logger.info(f"Detected repeated violation (failed fix): {violation.table}.{violation.tuple_id}.{violation.attr}")
        
        return repeated
    
    
    async def store_fixes(self, fixes: List[Fix], run_id: str, table_name: str) -> List[str]:
        """Store a list of fixes and return their IDs."""
        fix_ids = []
        
        async with self._get_run_lock(run_id):
            for fix in fixes:
                fix_id = f"fix_{run_id}_{table_name}_{uuid.uuid4().hex[:8]}"
                self._fixes[fix_id] = fix
                fix_ids.append(fix_id)
            
            if run_id not in self._fix_index:
                self._fix_index[run_id] = {}
            if table_name not in self._fix_index[run_id]:
                self._fix_index[run_id][table_name] = []
            
            self._fix_index[run_id][table_name].extend(fix_ids)
            self._record_access(run_id, 'store_fixes')
            
            self.logger.debug(f"Stored fixes: {len(fixes)} (table: {table_name})")
        
        return fix_ids
    
    async def get_fixes(self, run_id: str, table_name: str) -> List[Fix]:
        """Get the fixes for a table."""
        fixes = []
        async with self._get_run_lock(run_id):
            if (run_id in self._fix_index and 
                table_name in self._fix_index[run_id]):
                
                fix_ids = self._fix_index[run_id][table_name]
                fixes = [
                    self._fixes[fid] for fid in fix_ids 
                    if fid in self._fixes
                ]
                
                self._record_access(run_id, 'get_fixes')
        
        return fixes
    
    async def get_fixes_by_ids(self, fix_ids: List[str]) -> List[Fix]:
        """Get fixes by a list of IDs."""
        return [
            self._fixes[fid] for fid in fix_ids 
            if fid in self._fixes
        ]
    
    
    async def get_run_summary(self, run_id: str) -> Dict[str, Any]:
        """Get a run summary."""
        async with self._get_run_lock(run_id):
            summary = {
                'run_id': run_id,
                'tables': [],
                'total_snapshots': 0,
                'total_violations': 0,
                'total_fixes': 0,
                'access_stats': self._access_stats.get(run_id, {}).copy(),
                'metadata': self._run_metadata.get(run_id, {}).copy()
            }

            for table_name, table_index in self._snapshot_index.get(run_id, {}).items():
                if isinstance(table_index, dict):
                    snapshot_id = table_index.get('latest')
                else:
                    snapshot_id = table_index
                snapshot = self._snapshots.get(snapshot_id)

                violation_ids = self._violation_index.get(run_id, {}).get(table_name, [])
                violations = [
                    self._violations[violation_id]
                    for violation_id in violation_ids
                    if violation_id in self._violations
                ]
                fix_ids = self._fix_index.get(run_id, {}).get(table_name, [])
                fixes = [
                    self._fixes[fix_id]
                    for fix_id in fix_ids
                    if fix_id in self._fixes
                ]

                table_info = {
                    'table_name': table_name,
                    'rows': len(snapshot.rows) if snapshot else 0,
                    'violations': len(violations),
                    'fixes': len(fixes)
                }
                summary['tables'].append(table_info)
                summary['total_snapshots'] += 1
                summary['total_violations'] += len(violations)
                summary['total_fixes'] += len(fixes)

        return summary
    
    async def create_memory_reference(self, run_id: str, table_name: str, 
                                     operation_type: str = "read") -> MemoryReference:
        """Create a memory reference."""
        ref = MemoryReference(
            run_id=run_id,
            table_name=table_name,
            operation_type=operation_type
        )
        
        async with self._get_run_lock(run_id):
            if (run_id in self._snapshot_index and 
                table_name in self._snapshot_index[run_id]):
                ref.snapshot_id = self._snapshot_index[run_id][table_name]
            
            if (run_id in self._violation_index and 
                table_name in self._violation_index[run_id]):
                ref.violation_ids = self._violation_index[run_id][table_name][:]
            
            if (run_id in self._fix_index and 
                table_name in self._fix_index[run_id]):
                ref.fix_ids = self._fix_index[run_id][table_name][:]
        
        return ref
    
    
    async def persist_run_data(self, run_id: str, io_manager: IOManager):
        """Persist run data."""
        async with self._get_run_lock(run_id):
            try:
                snapshots = []
                for table_index in self._snapshot_index.get(run_id, {}).values():
                    if isinstance(table_index, dict):
                        snapshot_id = table_index.get('latest')
                    else:
                        snapshot_id = table_index
                    if snapshot_id in self._snapshots:
                        snapshots.append(self._snapshots[snapshot_id])

                all_violations = [
                    self._violations[violation_id]
                    for violation_ids in self._violation_index.get(run_id, {}).values()
                    for violation_id in violation_ids
                    if violation_id in self._violations
                ]
                all_fixes = [
                    self._fixes[fix_id]
                    for fix_ids in self._fix_index.get(run_id, {}).values()
                    for fix_id in fix_ids
                    if fix_id in self._fixes
                ]

                io_manager.write_violations(all_violations)
                io_manager.write_fixes(all_fixes)

                self.logger.info(f"Persistence complete: {run_id} - staged snapshots kept, {len(all_violations)} violations, {len(all_fixes)} fixes")

            except Exception as e:
                self.logger.error(f"Persistence failed: {run_id} - {e}")
                raise


    def add_observer(self, observer):
        """Add an observer."""
        self._observers.add(weakref.ref(observer))
    
    async def cleanup_run(self, run_id: str):
        """Clean up run data."""
        async with self._get_run_lock(run_id):
            try:
                if run_id in self._snapshot_index:
                    for snapshot_id in self._snapshot_index[run_id].values():
                        if snapshot_id in self._snapshots:
                            del self._snapshots[snapshot_id]
                    del self._snapshot_index[run_id]
                
                if run_id in self._violation_index:
                    for violation_ids in self._violation_index[run_id].values():
                        for vid in violation_ids:
                            if vid in self._violations:
                                del self._violations[vid]
                    del self._violation_index[run_id]
                
                if run_id in self._fix_index:
                    for fix_ids in self._fix_index[run_id].values():
                        for fid in fix_ids:
                            if fid in self._fixes:
                                del self._fixes[fid]
                    del self._fix_index[run_id]
                
                if run_id in self._run_metadata:
                    del self._run_metadata[run_id]
                
                if run_id in self._access_stats:
                    del self._access_stats[run_id]
                
                if run_id in self._rw_locks:
                    del self._rw_locks[run_id]
                
                self.logger.info(f"Cleanup complete: {run_id}")
                
            except Exception as e:
                self.logger.error(f"Cleanup failed: {run_id} - {e}")
    
    def get_memory_status(self) -> Dict[str, Any]:
        """Get memory status."""
        return {
            'snapshots_count': len(self._snapshots),
            'violations_count': len(self._violations),
            'fixes_count': len(self._fixes),
            'active_runs': list(self._run_metadata.keys()),
            'total_access_stats': sum(
                sum(stats.values()) for stats in self._access_stats.values()
            )
        }
