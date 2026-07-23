"""Doc2DB Orchestrator detailed logger.

Records snapshot, violation, and fix state for each processing step.
"""
import json
import logging
import os
from typing import Dict, List, Any, Optional
from datetime import datetime
from dataclasses import asdict

from ..memory import TableSnapshot, Violation, Fix
from ..core.io import IOManager


class OrchestratorLogger:
    """Detailed logger dedicated to the Orchestrator."""
    
    def __init__(self, run_id: str, base_path: str = "logs"):
        """Initialize the logger.
        
        Args:
            run_id: Run ID
            base_path: Base path for log files
        """
        self.run_id = run_id
        self.base_path = base_path
        self.log_file = os.path.join(base_path, f"orchestrator_{run_id}.json")
        
        os.makedirs(base_path, exist_ok=True)
        
        self.log_data = {
            "run_id": run_id,
            "start_time": IOManager.get_timestamp(),
            "processing_steps": [],
            "snapshots_history": {},
            "violations_history": {},
            "fixes_history": {},
            "state_transitions": [],
            "error_events": [],
            "performance_metrics": {}
        }
        
        self._write_log()
        
        self.logger = logging.getLogger(f'orchestrator.logger.{run_id}')
        
    def log_state_transition(self, from_state: str, to_state: str, 
                           context: Any = None, extra_info: Dict = None):
        """Log a state transition."""
        transition = {
            "timestamp": IOManager.get_timestamp(),
            "from_state": from_state,
            "to_state": to_state,
            "context_info": {
                "current_table": getattr(context, 'table_name', 'unknown') if context else 'unknown',
                "current_table_index": getattr(context, 'current_table_index', -1) if context else -1,
                "iteration": getattr(context, 'iteration', 0) if context else 0,
                "target_tables": getattr(context, 'target_tables', []) if context else []
            },
            "extra_info": extra_info or {}
        }
        
        self.log_data["state_transitions"].append(transition)
        self._write_log()
        
        self.logger.info(f"State transition: {from_state} -> {to_state}")
    
    def log_step_start(self, step_name: str, description: str, context: Any = None):
        """Log the start of a step."""
        step_info = {
            "step_name": step_name,
            "status": "started",
            "start_time": IOManager.get_timestamp(),
            "description": description,
            "context_snapshot": self._extract_context_info(context) if context else {}
        }
        
        self.log_data["processing_steps"].append(step_info)
        self._write_log()
        
        self.logger.info(f"Step started: {step_name} - {description}")
    
    def log_step_complete(self, step_name: str, result_summary: Dict = None, 
                         context: Any = None):
        """Log the completion of a step."""
        for step in reversed(self.log_data["processing_steps"]):
            if step["step_name"] == step_name and step["status"] == "started":
                step["status"] = "completed"
                step["end_time"] = IOManager.get_timestamp()
                step["result_summary"] = result_summary or {}
                step["final_context"] = self._extract_context_info(context) if context else {}
                break
        
        self._write_log()
        self.logger.info(f"Step completed: {step_name}")
    
    def log_step_error(self, step_name: str, error: Exception, context: Any = None):
        """Log a step error."""
        for step in reversed(self.log_data["processing_steps"]):
            if step["step_name"] == step_name and step["status"] == "started":
                step["status"] = "failed"
                step["end_time"] = IOManager.get_timestamp()
                step["error"] = str(error)
                break
        
        error_event = {
            "timestamp": IOManager.get_timestamp(),
            "step_name": step_name,
            "error_type": type(error).__name__,
            "error_message": str(error),
            "context_info": self._extract_context_info(context) if context else {}
        }
        
        self.log_data["error_events"].append(error_event)
        self._write_log()
        
        self.logger.error(f"Step error: {step_name} - {error}")
    
    def log_snapshot_created(self, table_name: str, snapshot: TableSnapshot, 
                           step_name: str = "unknown"):
        """Log snapshot creation."""
        snapshot_info = {
            "timestamp": IOManager.get_timestamp(),
            "step_name": step_name,
            "action": "created",
            "table_name": table_name,
            "snapshot_summary": {
                "table": snapshot.table,
                "run_id": snapshot.run_id,
                "total_rows": len(snapshot.rows),
                "columns": list(snapshot.rows[0].cells.keys()) if snapshot.rows else [],
                "created_at": snapshot.created_at
            },
            "data_preview": self._create_data_preview(snapshot, max_rows=3)
        }
        
        if table_name not in self.log_data["snapshots_history"]:
            self.log_data["snapshots_history"][table_name] = []
        
        self.log_data["snapshots_history"][table_name].append(snapshot_info)
        self._write_log()
        
        self.logger.info(f"Snapshot created: {table_name} - {len(snapshot.rows)} rows")
    
    def log_snapshot_updated(self, table_name: str, snapshot: TableSnapshot,
                           step_name: str = "unknown", changes_summary: Dict = None):
        """Log snapshot update."""
        snapshot_info = {
            "timestamp": IOManager.get_timestamp(),
            "step_name": step_name,
            "action": "updated",
            "table_name": table_name,
            "snapshot_summary": {
                "table": snapshot.table,
                "run_id": snapshot.run_id,
                "total_rows": len(snapshot.rows),
                "columns": list(snapshot.rows[0].cells.keys()) if snapshot.rows else [],
                "created_at": snapshot.created_at
            },
            "changes_summary": changes_summary or {},
            "data_preview": self._create_data_preview(snapshot, max_rows=3)
        }
        
        if table_name not in self.log_data["snapshots_history"]:
            self.log_data["snapshots_history"][table_name] = []
        
        self.log_data["snapshots_history"][table_name].append(snapshot_info)
        self._write_log()
        
        self.logger.info(f"Snapshot updated: {table_name} - changes: {changes_summary}")
    
    def log_violations_detected(self, table_name: str, violations: List[Violation],
                              step_name: str = "unknown", round_num: int = 1):
        """Log violation detection."""
        violations_info = {
            "timestamp": IOManager.get_timestamp(),
            "step_name": step_name,
            "table_name": table_name,
            "round_number": round_num,
            "total_violations": len(violations),
            "violations_by_severity": self._group_violations_by_severity(violations),
            "violations_by_type": self._group_violations_by_type(violations),
            "detailed_violations": [self._violation_to_log_format(v) for v in violations[:10]]  # Log only the first 10
        }
        
        if table_name not in self.log_data["violations_history"]:
            self.log_data["violations_history"][table_name] = []
        
        self.log_data["violations_history"][table_name].append(violations_info)
        self._write_log()
        
        self.logger.info(f"Violations detected: {table_name} round {round_num} - found {len(violations)} issues")
    
    def log_fixes_applied(self, table_name: str, fixes: List[Fix],
                         step_name: str = "unknown", round_num: int = 1):
        """Log applied fixes."""
        fixes_info = {
            "timestamp": IOManager.get_timestamp(),
            "step_name": step_name,
            "table_name": table_name,
            "round_number": round_num,
            "total_fixes": len(fixes),
            "fixes_by_type": self._group_fixes_by_type(fixes),
            "successful_fixes": len([f for f in fixes if f.fix_success]),
            "failed_fixes": len([f for f in fixes if not f.fix_success]),
            "detailed_fixes": [self._fix_to_log_format(f) for f in fixes[:10]]  # Log only the first 10
        }
        
        if table_name not in self.log_data["fixes_history"]:
            self.log_data["fixes_history"][table_name] = []
        
        self.log_data["fixes_history"][table_name].append(fixes_info)
        self._write_log()
        
        successful = len([f for f in fixes if f.fix_success])
        self.logger.info(f"Fixes applied: {table_name} round {round_num} - {successful}/{len(fixes)} succeeded")
    
    def log_performance_metric(self, metric_name: str, value: float, unit: str = "ms"):
        """Log a performance metric."""
        self.log_data["performance_metrics"][metric_name] = {
            "value": value,
            "unit": unit,
            "timestamp": IOManager.get_timestamp()
        }
        self._write_log()
    
    def log_warm_start_triggered(self, table_name: str, unfixable_violations: List,
                               step_name: str = "warm_start"):
        """Log warm-start trigger."""
        warm_start_info = {
            "timestamp": IOManager.get_timestamp(),
            "step_name": step_name,
            "table_name": table_name,
            "action": "warm_start_triggered",
            "unfixable_violations_count": len(unfixable_violations),
            "unfixable_details": [
                {
                    "violation_id": getattr(v, 'id', 'unknown'),
                    "constraint_type": getattr(v, 'constraint_type', 'unknown'),
                    "attr": getattr(v, 'attr', 'unknown'),
                    "description": getattr(v, 'description', 'unknown')
                }
                for v in unfixable_violations[:5]  # Log only the first 5
            ]
        }
        
        self.log_data["processing_steps"].append(warm_start_info)
        self._write_log()
        
        self.logger.warning(f"Warm start triggered: {table_name} - {len(unfixable_violations)} unfixable violations")
    
    def log_multi_table_verification(self, all_snapshots: Dict, 
                                   multi_table_violations: List[Violation]):
        """Log multi-table verification."""
        multi_table_info = {
            "timestamp": IOManager.get_timestamp(),
            "step_name": "multi_table_verification",
            "action": "completed",
            "tables_verified": list(all_snapshots.keys()),
            "total_tables": len(all_snapshots),
            "cross_table_violations": len(multi_table_violations),
            "violations_by_type": self._group_violations_by_type(multi_table_violations),
            "table_summaries": {
                table_name: {
                    "rows": len(snapshot.rows),
                    "columns": list(snapshot.rows[0].cells.keys()) if snapshot.rows else []
                }
                for table_name, snapshot in all_snapshots.items()
            }
        }
        
        self.log_data["processing_steps"].append(multi_table_info)
        self._write_log()
        
        self.logger.info(f"Multi-table verification complete: {len(all_snapshots)} tables - {len(multi_table_violations)} cross-table issues")
    
    def log_final_summary(self, context: Any):
        """Log the final summary."""
        final_summary = {
            "timestamp": IOManager.get_timestamp(),
            "step_name": "final_summary",
            "total_tables_processed": len(getattr(context, 'all_snapshots', {})),
            "total_rows_extracted": sum(
                len(snapshot.rows) 
                for snapshot in getattr(context, 'all_snapshots', {}).values()
            ),
            "total_violations_found": len(getattr(context, 'violations', [])),
            "total_fixes_applied": len(getattr(context, 'fixes', [])),
            "processing_duration": self._calculate_duration(),
            "tables_summary": {}
        }
        
        if hasattr(context, 'all_snapshots'):
            for table_name, snapshot in context.all_snapshots.items():
                table_violations = len(context.all_violations.get(table_name, []))
                table_fixes = len(context.all_fixes.get(table_name, []))
                
                final_summary["tables_summary"][table_name] = {
                    "rows": len(snapshot.rows),
                    "violations": table_violations,
                    "fixes": table_fixes,
                    "final_state": "processed"
                }
        
        self.log_data["final_summary"] = final_summary
        self.log_data["end_time"] = IOManager.get_timestamp()
        self._write_log()
        
        self.logger.info(f"Processing summary: {final_summary['total_tables_processed']} tables, "
                        f"{final_summary['total_rows_extracted']} rows, "
                        f"{final_summary['total_violations_found']} issues, "
                        f"{final_summary['total_fixes_applied']} fixes")
    
    def _extract_context_info(self, context: Any) -> Dict[str, Any]:
        """Extract context information."""
        if not context:
            return {}
        
        return {
            "run_id": getattr(context, 'run_id', 'unknown'),
            "table_name": getattr(context, 'table_name', 'unknown'),
            "current_state": str(getattr(context, 'current_state', 'unknown')),
            "iteration": getattr(context, 'iteration', 0),
            "current_table_index": getattr(context, 'current_table_index', -1),
            "target_tables": getattr(context, 'target_tables', []),
            "language": getattr(context, 'language', 'unknown'),
            "model": getattr(context, 'model', 'unknown')
        }
    
    def _create_data_preview(self, snapshot: TableSnapshot, max_rows: int = 3) -> Dict[str, Any]:
        """Create a data preview."""
        preview_rows = []
        
        for i, row in enumerate(snapshot.rows[:max_rows]):
            row_preview = {
                "tuple_id": row.tuple_id,
                "cells": {}
            }
            
            for attr, cell in row.cells.items():
                row_preview["cells"][attr] = {
                    "value": cell.value,
                    "evidences_count": len(cell.evidences)
                }
            
            preview_rows.append(row_preview)
        
        return {
            "total_rows": len(snapshot.rows),
            "preview_rows": preview_rows,
            "columns": list(snapshot.rows[0].cells.keys()) if snapshot.rows else []
        }
    
    def _group_violations_by_severity(self, violations: List[Violation]) -> Dict[str, int]:
        """Group violations by severity."""
        groups = {}
        for violation in violations:
            severity = getattr(violation, 'severity', 'unknown')
            groups[severity] = groups.get(severity, 0) + 1
        return groups
    
    def _group_violations_by_type(self, violations: List[Violation]) -> Dict[str, int]:
        """Group violations by type."""
        groups = {}
        for violation in violations:
            constraint_type = getattr(violation, 'constraint_type', 'unknown')
            groups[constraint_type] = groups.get(constraint_type, 0) + 1
        return groups
    
    def _group_fixes_by_type(self, fixes: List[Fix]) -> Dict[str, int]:
        """Group fixes by type."""
        groups = {}
        for fix in fixes:
            fix_type = getattr(fix, 'fix_type', 'unknown')
            groups[fix_type] = groups.get(fix_type, 0) + 1
        return groups
    
    def _violation_to_log_format(self, violation: Violation) -> Dict[str, Any]:
        """Convert a violation to log format."""
        return {
            "id": getattr(violation, 'id', 'unknown'),
            "table": getattr(violation, 'table', 'unknown'),
            "tuple_id": getattr(violation, 'tuple_id', 'unknown'),
            "attr": getattr(violation, 'attr', 'unknown'),
            "constraint_type": getattr(violation, 'constraint_type', 'unknown'),
            "severity": getattr(violation, 'severity', 'unknown'),
            "description": getattr(violation, 'description', 'unknown')[:200],  # Limit length
            "has_suggested_fix": bool(getattr(violation, 'suggested_fix', None))
        }
    
    def _fix_to_log_format(self, fix: Fix) -> Dict[str, Any]:
        """Convert a fix to log format."""
        return {
            "id": getattr(fix, 'id', 'unknown'),
            "table": getattr(fix, 'table', 'unknown'),
            "tuple_id": getattr(fix, 'tuple_id', 'unknown'),
            "attr": getattr(fix, 'attr', 'unknown'),
            "fix_type": getattr(fix, 'fix_type', 'unknown'),
            "success": getattr(fix, 'fix_success', True),
            "failure_reason": getattr(fix, 'failure_reason', '') if not getattr(fix, 'fix_success', True) else None
        }
    
    def _calculate_duration(self) -> str:
        """Calculate processing duration."""
        try:
            start_time = datetime.fromisoformat(self.log_data["start_time"])
            current_time = datetime.now()
            duration = current_time - start_time
            return str(duration)
        except:
            return "unknown"
    
    def _write_log(self):
        """Write to the log file."""
        try:
            with open(self.log_file, 'w', encoding='utf-8') as f:
                json.dump(self.log_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to write log file: {e}")
    
    def get_log_file_path(self) -> str:
        """Get the log file path."""
        return self.log_file
    
    def get_summary_report(self) -> Dict[str, Any]:
        """Get the summary report."""
        return {
            "run_id": self.run_id,
            "start_time": self.log_data.get("start_time"),
            "end_time": self.log_data.get("end_time"),
            "total_steps": len(self.log_data["processing_steps"]),
            "total_state_transitions": len(self.log_data["state_transitions"]),
            "total_errors": len(self.log_data["error_events"]),
            "tables_processed": list(self.log_data["snapshots_history"].keys()),
            "final_summary": self.log_data.get("final_summary", {}),
            "log_file": self.log_file
        }


class OrchestratorLoggerMixin:
    """Orchestrator logger mixin class.
    
    Can be added to Doc2DBOrchestrator to enable detailed logging.
    """
    
    def _init_detailed_logger(self):
        """Initialize the detailed logger."""
        if hasattr(self, 'current_context') and self.current_context:
            run_id = self.current_context.run_id
        else:
            run_id = f"orchestrator_{IOManager.get_timestamp().replace(':', '-')}"
        
        self.detailed_logger = OrchestratorLogger(run_id)
        self.logger.info(f"Detailed logger enabled: {self.detailed_logger.get_log_file_path()}")
    
    def _log_with_detailed_logger(self, method_name: str, *args, **kwargs):
        """Log using the detailed logger."""
        if hasattr(self, 'detailed_logger'):
            method = getattr(self.detailed_logger, method_name, None)
            if method:
                try:
                    method(*args, **kwargs)
                except Exception as e:
                    self.logger.warning(f"Detailed logging failed ({method_name}): {e}")
