"""Doc2DB service layer implementation using the new unified signal-driven orchestrator."""
import os
import json
import logging
import traceback
from typing import Dict, List, Any, Optional, Callable
from pathlib import Path
import uuid
from datetime import datetime
import threading
from queue import Queue
import time
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '../../backend'))

from ..core.io import IOManager
from ..core.ids import IdGenerator
from ..agents.orchestrator import create_signal_driven_orchestrator, create_doc2db_context, Doc2DBProcessingState
from ..agents.orchestrator.parallel_orchestrator import create_parallel_orchestrator
from utils.history_utils import resolve_display_table_name

try:
    from websocket_signals import get_websocket_broadcaster
    websocket_available = True
except ImportError:
    websocket_available = False
    def get_websocket_broadcaster():
        return None


class Doc2DBService:
    """Doc2DB service with real-time step progress support."""
    
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.logger = logging.getLogger('doc2db.service')
        
        self.running_tasks = {}
        self.task_queues = {}  # Per-task progress queue
        self.task_steps = {}   # Per-task accumulated steps
        
        self.history_dir = Path(output_dir).parent / 'history'
        self.history_dir.mkdir(parents=True, exist_ok=True)
        
        import os
        if not os.environ.get('DOC2DB_SERVICE_INITIALIZED'):
            self.logger.debug(f'Doc2DBService initialized history directory: {self.history_dir}')
            os.environ['DOC2DB_SERVICE_INITIALIZED'] = 'true'
        else:
            self.logger.debug(f'Doc2DBService reinitialized, history directory: {self.history_dir}')
    
    def start_processing_async(self, documents: List[str], schema: Dict[str, Any], 
                              table_name: str, nl_prompt: str = "", 
                              user_query: str = "", model: str = "gpt-4o",
                              request_data: Dict[str, Any] = None,
                              processing_mode: str = "auto",
                              max_concurrent_tables: int = 3,
                              document_mode: str = "single") -> str:
        """Start Doc2DB processing asynchronously."""
        
        run_id = str(uuid.uuid4())
        
        progress_queue = Queue()
        self.task_queues[run_id] = progress_queue
        self.task_steps[run_id] = []  # Initialize the steps list
        
        self.running_tasks[run_id] = {
            'status': 'started',
            'start_time': datetime.now().isoformat(),
            'table_name': table_name,
            'documents': documents,
            'steps': [],
            'current_step': 'initializing',
            'error': None,
            'request': request_data or {},
            'running_context': None
        }
        
        if websocket_available:
            broadcaster = get_websocket_broadcaster()
            if broadcaster:
                broadcaster.add_message_to_queue('processing_start', {
                    'run_id': run_id,
                    'table_name': table_name,
                    'documents_count': len(documents),
                    'model': model
                })
        
        thread = threading.Thread(
            target=self._run_processing_thread,
            args=(run_id, documents, schema, table_name, nl_prompt, user_query, model, progress_queue, processing_mode, max_concurrent_tables, document_mode)
        )
        thread.daemon = True
        thread.start()
        
        return run_id
    
    def _determine_processing_mode(self, processing_mode: str, schema: Dict[str, Any], documents: List[str]) -> str:
        """Intelligently determine the processing mode."""
        if processing_mode == "serial":
            return "serial"
        elif processing_mode == "parallel":
            return "parallel"
        elif processing_mode == "auto":
            table_count = self._count_tables_in_schema(schema)
            doc_count = len(documents)
            
            if table_count >= 2 or (table_count >= 1 and doc_count >= 4):
                self.logger.debug(f'Auto-selected parallel mode: {table_count} tables, {doc_count} documents')
                return "parallel"
            else:
                self.logger.debug(f'Auto-selected serial mode: {table_count} tables, {doc_count} documents')
                return "serial"
        else:
            return "serial"
    
    def _count_tables_in_schema(self, schema: Dict[str, Any]) -> int:
        """Count the number of tables in the schema."""
        if isinstance(schema, str):
            try:
                schema = json.loads(schema)
            except:
                return 1
        
        if isinstance(schema, dict):
            if "tables" in schema and isinstance(schema["tables"], list):
                return len(schema["tables"])
            elif "table_name" in schema or "columns" in schema:
                return 1
            else:
                return 1
        
        return 1
    
    def _run_processing_thread(self, run_id: str, documents: List[str], 
                              schema: Dict[str, Any], table_name: str, 
                              nl_prompt: str, user_query: str, model: str,
                              progress_queue: Queue, processing_mode: str = "auto",
                              max_concurrent_tables: int = 3, document_mode: str = "single"):
        """Enhanced processing thread function."""
        self.logger.info(f'Processing thread started: {run_id}')
        try:
            run_output_dir = self.output_dir / run_id
            run_output_dir.mkdir(parents=True, exist_ok=True)
            
            io_manager = IOManager(str(run_output_dir))
            
            context = create_doc2db_context(
                run_id=run_id,
                table_name=table_name,
                schema=schema,
                documents=documents,
                nl_prompt=nl_prompt,
                io_manager=io_manager,
                user_query=user_query,
                model=model,
                document_mode=document_mode
            )
            
            self.running_tasks[run_id]['running_context'] = context
            
            selected_mode = self._determine_processing_mode(processing_mode, schema, documents)
            
            if selected_mode == "parallel":
                self.logger.info(f'Using parallel processing mode: {run_id}, max concurrency: {max_concurrent_tables}')
                orchestrator = create_parallel_orchestrator(max_concurrent_tables=max_concurrent_tables)
            else:
                self.logger.info(f'Using serial processing mode: {run_id}')
                orchestrator = create_signal_driven_orchestrator()
            
            original_step_outputs = context.step_outputs
            context.step_outputs = StepOutputInterceptor(original_step_outputs, progress_queue, run_id)
            
            self.logger.info(f'Starting processing: {run_id}')
            result_context = orchestrator.process(context)
            
            final_status = 'completed' if result_context.current_state == Doc2DBProcessingState.COMPLETED else 'failed'
            self.logger.info(f'Processing complete: {run_id}, status: {final_status}')
            
            total_rows = 0
            total_violations = 0
            total_fixes = 0
            
            for snapshot in result_context.all_snapshots.values():
                if snapshot and hasattr(snapshot, 'rows') and snapshot.rows:
                    total_rows += len(snapshot.rows)
            
            total_violations = sum(len(v) for v in result_context.all_violations.values())
            
            total_fixes = sum(len(f) for f in result_context.all_fixes.values())
            
            self.running_tasks[run_id].update({
                'status': final_status,
                'end_time': datetime.now().isoformat(),
                'result_context': result_context,
                'final_stats': {
                    'total_rows': total_rows,
                    'total_violations': total_violations,
                    'total_fixes': total_fixes,
                    'iterations': getattr(result_context, 'iteration', 1)
                }
            })
            
            progress_queue.put({
                'type': 'final_status',
                'status': final_status,
                'result': self._format_result_for_frontend(result_context) if final_status == 'completed' else None
            })
            
            try:
                self._save_task_to_history(run_id, result_context, final_status)
                self.logger.debug(f'History record saved: {run_id}')
            except Exception as history_e:
                self.logger.error(f'Failed to save history record {run_id}: {history_e}')
            
            import threading
            def delayed_cleanup():
                import time
                time.sleep(2)  # Delay 2s to ensure the history file has finished writing
                self.cleanup_task(run_id)
                self.logger.info(f"Cleaned up runtime state for task {run_id}")
            
            cleanup_thread = threading.Thread(target=delayed_cleanup)
            cleanup_thread.daemon = True
            cleanup_thread.start()
            
        except Exception as e:
            self.logger.error(f"Processing thread error {run_id}: {e}")
            self.logger.error(f"Error details: {traceback.format_exc()}")
            
            self.running_tasks[run_id].update({
                'status': 'failed',
                'end_time': datetime.now().isoformat(),
                'error': str(e)
            })
            
            progress_queue.put({
                'type': 'error',
                'error': str(e)
            })
            
            self._save_task_to_history(run_id, None, 'failed', str(e))
            
            import threading
            def delayed_cleanup_error():
                import time
                time.sleep(2)  # Delay 2s to ensure the history file has finished writing
                self.cleanup_task(run_id)
                self.logger.info(f"Cleaned up runtime state for failed task {run_id}")
            
            cleanup_thread = threading.Thread(target=delayed_cleanup_error)
            cleanup_thread.daemon = True
            cleanup_thread.start()
    
    def force_save_current_task_to_history(self, run_id: str):
        """Manually force-save the current task to the history record."""
        task = self.running_tasks.get(run_id)
        if not task:
            self.logger.debug(f'Task {run_id} not found in the running tasks list')
            return False
        
        result_context = task.get('result_context')
        status = task.get('status', 'unknown')
        
        self._save_task_to_history(run_id, result_context, status)
        return True
    
    def get_task_progress(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get task progress (polling)."""
        if run_id not in self.running_tasks:
            return self._get_task_progress_from_files(run_id)
        
        task = self.running_tasks[run_id]
        
        if run_id in self.task_queues:
            queue = self.task_queues[run_id]
            new_updates = []
            
            while not queue.empty():
                try:
                    update = queue.get_nowait()
                    new_updates.append(update)
                except:
                    break
            
            for update in new_updates:
                if update['type'] == 'step_completed':
                    step_name = update['step']
                    step_timestamp = update.get('timestamp')
                    existing_step = None
                    
                    if run_id in self.task_steps:
                        for step in self.task_steps[run_id]:
                            if (step['step_name'] == step_name and 
                                step_timestamp and 
                                step.get('start_time') == step_timestamp):
                                existing_step = step
                                break
                    
                    if existing_step:
                        existing_step.update({
                            'status': update['status'],
                            'description': update['description'],
                            'end_time': update.get('timestamp') if update['status'] in ['completed', 'failed'] else existing_step.get('end_time'),
                            'result': update.get('details', existing_step.get('result', {}))
                        })
                        self.logger.info(f"Updated existing step: {step_name} (timestamp: {step_timestamp}) - {update['status']}")
                    else:
                        step_data = {
                            'step_name': step_name,
                            'description': update['description'],
                            'status': update['status'],
                            'start_time': update.get('timestamp'),
                            'end_time': update.get('timestamp') if update['status'] in ['completed', 'failed'] else None,
                            'result': update.get('details', {}),
                            'error': None
                        }
                        
                        if run_id not in self.task_steps:
                            self.task_steps[run_id] = []
                        self.task_steps[run_id].append(step_data)
                        self.logger.info(f"Added new step: {step_name} (timestamp: {step_timestamp}) - {update['status']}")
                    
                elif update['type'] == 'final_status':
                    task['status'] = update['status']
                    if update.get('result'):
                        task['result'] = update['result']
                        
                elif update['type'] == 'error':
                    task['status'] = 'failed'
                    task['error'] = update['error']

        current_status = task['status']
        steps = self.task_steps.get(run_id, [])
        
        if current_status == 'started' and steps:
            completed_steps = [s for s in steps if s['status'] == 'completed']
            
            orchestrator_completion_steps = {
                'orchestrator_completion',
                'orchestrator_completion_fallback',
            }
            has_orchestrator_completed = any(
                s.get('step') in orchestrator_completion_steps or
                s.get('step_name') in orchestrator_completion_steps or
                ('Orchestrator completed all processing' in s.get('description', '')) or
                ('Orchestrator完成所有处理流程' in s.get('description', '')) or
                ('Data processing flow completed' in s.get('description', '')) or
                ('数据处理流程完成' in s.get('description', ''))
                for s in completed_steps
            )
            
            if has_orchestrator_completed:
                self.logger.debug('Detected that the orchestrator has completed; auto-updating to completed')
                current_status = 'completed'
                task['status'] = 'completed'  # Update task status
                task['end_time'] = datetime.now().isoformat()
                
                if 'running_context' in task and task['running_context'] is not None:
                    task['result_context'] = task['running_context']
                
                try:
                    result_context = task.get('running_context') or task.get('result_context')
                    self._save_task_to_history(run_id, result_context, 'completed')
                    self.logger.debug(f'History record saved: {run_id}')
                except Exception as save_e:
                    self.logger.error(f'Failed to save history record {run_id}: {save_e}')

        progress_data = {
            'task_id': run_id,
            'status': current_status,
            'start_time': task['start_time'],
            'end_time': task.get('end_time'),
            'table_name': task['table_name'],
            'error': task.get('error'),
            'steps': steps  # Use the accumulated steps list
        }
        
        context = None
        
        if 'result_context' in task:
            context = task['result_context']
        elif 'running_context' in task:
            context = task['running_context']
        
        if context and hasattr(context, 'snapshots') and context.snapshots:
            formatted_result = self._format_result_for_frontend(context)
            progress_data['result'] = formatted_result
            
            formatted_snapshots = self._format_all_snapshots_for_frontend(context.snapshots)
            
            progress_data['result_context'] = {
                'snapshot': formatted_result.get('snapshot'),
                'snapshots': formatted_snapshots,
                'summary': formatted_result.get('summary'),
                'run_id': context.run_id
            }
        
        return progress_data
    
    def _get_task_progress_from_files(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get task progress from history and snapshot files."""
        try:
            import os
            import json
            
            history_file = self.history_dir / f"{run_id}.json"
            
            if not history_file.exists():
                self.logger.debug(f'History file does not exist: {history_file} (task may have been deleted)')
                return None
            
            with open(history_file, 'r', encoding='utf-8') as f:
                history_data = json.load(f)
            
            progress_data = {
                'task_id': run_id,
                'status': history_data.get('status', 'unknown'),
                'start_time': history_data.get('start_time'),
                'end_time': history_data.get('end_time'),
                'table_name': history_data.get('table_name', ''),
                'error': history_data.get('error'),
                'steps': []
            }
            
            result = history_data.get('result', {})
            step_outputs = result.get('step_outputs', [])
            
            for step_output in step_outputs:
                step_data = {
                    'step_name': step_output.get('step'),
                    'step': step_output.get('step'),  # Frontend compatibility
                    'description': step_output.get('description', ''),
                    'status': step_output.get('status', 'completed'),
                    'start_time': step_output.get('timestamp'),
                    'end_time': step_output.get('timestamp'),
                    'timestamp': step_output.get('timestamp'),  # Frontend compatibility
                    'result': step_output.get('details', {}),
                    'details': step_output.get('details', {}),  # Frontend compatibility
                    'error': None
                }
                progress_data['steps'].append(step_data)
            
            snapshot_file = Path(self.output_dir) / run_id / 'snapshots.jsonl'
            
            if snapshot_file.exists():
                snapshots = []
                with open(snapshot_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            snapshot_data = json.loads(line)
                            snapshots.append(snapshot_data)
                
                if snapshots:
                    snapshot = snapshots[0]
                    
                    table_data = self._build_table_data_from_snapshot(snapshot)
                    
                    progress_data['result'] = {
                        'table_data': table_data,
                        'summary': result.get('summary'),
                        'run_id': run_id,
                        'snapshot': snapshot
                    }
                    
                    progress_data['result_context'] = {
                        'snapshot': snapshot,
                        'summary': result.get('summary')
                    }
            
            return progress_data
            
        except Exception as e:
            self.logger.error(f'Failed to read task progress from history file: {e}')
            return None
    
    def _build_table_data_from_snapshot(self, snapshot: Dict[str, Any]) -> Dict[str, Any]:
        """Build table data from snapshot data."""
        try:
            rows = snapshot.get('rows', [])
            if not rows:
                return {'headers': [], 'rows': []}
            
            first_row = rows[0]
            headers = list(first_row.get('cells', {}).keys())
            
            table_rows = []
            for row in rows:
                row_data = {}
                cells = row.get('cells', {})
                for header in headers:
                    cell = cells.get(header, {})
                    best = cell.get('best', {})
                    row_data[header] = {
                        'value': best.get('value', '')
                    }
                table_rows.append(row_data)
            
            return {
                'headers': headers,
                'rows': table_rows
            }
            
        except Exception as e:
            self.logger.error(f'Failed to build table data: {e}')
            return {'headers': [], 'rows': []}
    
    def _format_snapshot_for_frontend(self, snapshots) -> Dict[str, Any]:
        """Format snapshot data for the frontend."""
        if not snapshots:
            return {}
        
        main_snapshot = snapshots[0]
        
        return {
            'table': main_snapshot.get('table', 'unknown'),
            'rows': main_snapshot.get('rows', [])
        }
    
    def _format_all_snapshots_for_frontend(self, snapshots) -> Dict[str, Any]:
        """Format all snapshots for the frontend multi-table format (dict structure)."""
        if not snapshots:
            return {}
        
        formatted_snapshots = {}
        
        for snapshot in snapshots:
            table_name = snapshot.table
            
            formatted_rows = [
                {
                    'tuple_id': row.tuple_id,
                    'cells': {
                        attr: {
                            'value': cell.value,  # New format: use value directly
                            'best': {  # Preserve legacy format compatibility
                                'value': cell.value
                            }
                        }
                        for attr, cell in row.cells.items()
                    }
                }
                for row in snapshot.rows
            ]
            
            formatted_snapshots[table_name] = {
                'run_id': snapshot.run_id,
                'table': table_name,
                'rows': formatted_rows,
                'created_at': snapshot.created_at
            }
        
        return formatted_snapshots
    
    def _format_result_for_frontend(self, context) -> Dict[str, Any]:
        """Format the result for frontend use."""
        try:
            table_data = []
            headers = []
            rows = []
            
            if context.snapshots:
                snapshot = context.snapshots[0]
                
                if snapshot.rows:
                    headers = list(snapshot.rows[0].cells.keys())
                
                for row in snapshot.rows:
                    row_dict = {}
                    for attr, cell in row.cells.items():
                        row_dict[attr] = {
                            'value': cell.value
                        }
                    rows.append(row_dict)
                    
                    simple_row = {}
                    for attr, cell in row.cells.items():
                        simple_row[attr] = cell.value
                    table_data.append(simple_row)
            
            summary = {
                'total_rows': sum(len(s.rows) for s in context.snapshots),
                'total_violations': len(getattr(context, 'violations', [])),
                'total_fixes': len(getattr(context, 'fixes', [])),
                'iterations': getattr(context, 'iteration', 0),
                'processing_steps': len(getattr(context, 'step_outputs', [])) if hasattr(getattr(context, 'step_outputs', []), '__len__') else 0,
                'table_name': getattr(context, 'table_name', 'unknown')
            }
            
            snapshot_data = None
            if context.snapshots:
                snapshot = context.snapshots[0]
                
                snapshot_data = {
                    'run_id': snapshot.run_id,
                    'table': snapshot.table,
                    'rows': [
                        {
                            'tuple_id': row.tuple_id,
                            'cells': {
                                attr: {
                                    'best': {
                                        'value': cell.value
                                    }
                                }
                                for attr, cell in row.cells.items()
                            }
                        }
                        for row in snapshot.rows
                    ],
                    'created_at': snapshot.created_at
                }
            
            result = {
                'table_data': {
                    'headers': headers,
                    'rows': rows
                },
                'summary': summary,
                'run_id': context.run_id,
                'snapshot': snapshot_data
            }
            
            return result
        except Exception as e:
            self.logger.error(f"Failed to format result: {e}")
            return {'error': str(e)}
    
    def cleanup_task(self, run_id: str) -> None:
        """Clean up task data (including data in global singletons)."""
        if run_id in self.running_tasks:
            del self.running_tasks[run_id]
        
        if run_id in self.task_queues:
            del self.task_queues[run_id]
            
        if run_id in self.task_steps:
            del self.task_steps[run_id]
        
        
        try:
            from ..memory import MemoryManager
            import asyncio
            
            memory_manager = MemoryManager.get_instance()
            
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(memory_manager.cleanup_run(run_id))
                    self.logger.info(f"MemoryManager cleanup task submitted: {run_id}")
                else:
                    loop.run_until_complete(memory_manager.cleanup_run(run_id))
                    self.logger.info(f"MemoryManager cleanup completed: {run_id}")
            except RuntimeError:
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    new_loop.run_until_complete(memory_manager.cleanup_run(run_id))
                    self.logger.info(f"MemoryManager cleanup completed (new loop): {run_id}")
                finally:
                    new_loop.close()
                    
        except Exception as e:
            self.logger.error(f"Failed to clean up MemoryManager {run_id}: {e}")
            import traceback
            self.logger.error(f"Cleanup exception details: {traceback.format_exc()}")
        
        try:
            from ..signals.core import BroadcastHub
            
            hub = BroadcastHub.get_instance()
            hub.cleanup_run_signals(run_id)
            self.logger.info(f"BroadcastHub signal history cleaned up: {run_id}")
            
        except Exception as e:
            self.logger.error(f"Failed to clean up BroadcastHub {run_id}: {e}")
    
    def get_task_status(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Get basic task status."""
        if run_id in self.running_tasks:
            task = self.running_tasks[run_id]
            return {
                'run_id': run_id,
                'status': task['status'],
                'start_time': task['start_time'],
                'end_time': task.get('end_time'),
                'error': task.get('error'),
                'table_name': task['table_name']
            }
        return None

    def create_default_schema(self, table_name: str) -> Dict[str, Any]:
        """Create the default database schema."""
        return {
            "tables": [
                {
                    "name": table_name,
                    "attributes": [
                        {
                            "name": "order_id",
                            "type": "string",
                            "description": "Order ID",
                            "not_null": True,
                            "unique": True,
                            "pattern": r"^ORD-\d{4}-\d{3}$"
                        },
                        {
                            "name": "customer_name",
                            "type": "string", 
                            "description": "Customer name",
                            "not_null": True
                        },
                        {
                            "name": "order_date",
                            "type": "date",
                            "description": "Order date",
                            "not_null": True,
                            "pattern": r"^\d{4}-\d{2}-\d{2}$"
                        },
                        {
                            "name": "amount",
                            "type": "decimal",
                            "description": "Order amount",
                            "not_null": True,
                            "min": 0
                        },
                        {
                            "name": "status",
                            "type": "string",
                            "description": "Order status",
                            "not_null": True,
                            "domain": ["已完成", "处理中", "已取消", "待处理"]
                        }
                    ]
                }
            ]
        }
    
    def _save_task_to_history(self, run_id: str, result_context, final_status: str, error_message: str = None):
        """Save task status to the history file."""
        try:
            if not self.history_dir.exists():
                self.history_dir.mkdir(parents=True, exist_ok=True)
            
            test_file = self.history_dir / 'test_write.tmp'
            try:
                with open(test_file, 'w') as f:
                    f.write('test')
                test_file.unlink()
            except Exception as perm_e:
                raise Exception(f'History directory is not writable: {self.history_dir}, error: {perm_e}')
            
            task = self.running_tasks.get(run_id, {})
            request = task.get('request', {})
            display_table_name = resolve_display_table_name(
                task.get('table_name', ''),
                request.get('schema')
            )
            
            history_data = {
                'task_id': run_id,
                'status': final_status,
                'start_time': task.get('start_time'),
                'end_time': datetime.now().isoformat(),
                'table_name': display_table_name,
                'documents': task.get('documents', []),
                'error': error_message,
                'request': task.get('request', {})
            }
            
            if result_context and final_status == 'completed':
                total_rows = 0
                total_violations = 0
                total_fixes = 0
                
                if hasattr(result_context, 'all_snapshots'):
                    for snapshot in result_context.all_snapshots.values():
                        if snapshot and hasattr(snapshot, 'rows') and snapshot.rows:
                            total_rows += len(snapshot.rows)
                
                if hasattr(result_context, 'all_violations'):
                    total_violations = sum(len(v) for v in result_context.all_violations.values())
                
                if hasattr(result_context, 'all_fixes'):
                    total_fixes = sum(len(f) for f in result_context.all_fixes.values())
                
                history_data['result'] = {
                    'summary': {
                        'table_name': display_table_name,
                        'total_rows': total_rows,
                        'violations_found': total_violations,
                        'fixes_applied': total_fixes,
                        'iterations': getattr(result_context, 'iteration', 0)
                    },
                    'step_outputs': list(result_context.step_outputs) if hasattr(result_context.step_outputs, '__iter__') else [],
                    'progress': getattr(result_context, 'progress', {})
                }
                
                raw_result_context = getattr(result_context, 'result_context', {
                    'summary': {
                        'total_rows': total_rows,
                        'total_tables': len(result_context.all_snapshots) if hasattr(result_context, 'all_snapshots') else 0,
                        'total_violations': total_violations,
                        'total_fixes': total_fixes
                    },
                    'status': 'completed'
                })
                
                safe_result_context = {}
                for key, value in raw_result_context.items():
                    if key == 'snapshots' and isinstance(value, dict):
                        safe_result_context[key] = {
                            table_name: snapshot.to_dict() if hasattr(snapshot, 'to_dict') else str(snapshot)
                            for table_name, snapshot in value.items()
                        }
                    elif key in ['violations', 'fixes'] and isinstance(value, dict):
                        safe_result_context[key] = {
                            table_name: [item.to_dict() if hasattr(item, 'to_dict') else str(item) for item in items]
                            for table_name, items in value.items()
                        }
                    else:
                        safe_result_context[key] = value
                
                history_data['result_context'] = safe_result_context
            else:
                history_data['result'] = {
                    'summary': {
                        'table_name': display_table_name,
                        'total_rows': 0,
                        'violations_found': 0,
                        'fixes_applied': 0,
                        'iterations': 0
                    }
                }
            
            history_file = self.history_dir / f"{run_id}.json"
            
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(history_data, f, ensure_ascii=False, indent=2)
            
            if history_file.exists():
                self.logger.info(f"Task history saved: {run_id}")
            else:
                raise Exception(f'File does not exist after saving: {history_file}')
            
        except Exception as e:
            self.logger.error(f"Failed to save task history {run_id}: {str(e)}")
            self.logger.error(f"  History directory: {self.history_dir}")
            
            try:
                fallback_dir = Path(self.output_dir).parent / 'history'
                fallback_dir.mkdir(parents=True, exist_ok=True)
                fallback_file = fallback_dir / f"{run_id}.json"
                
                simple_history = {
                    'task_id': run_id,
                    'status': final_status,
                    'start_time': task.get('start_time', datetime.now().isoformat()),
                    'end_time': datetime.now().isoformat(),
                    'table_name': task.get('table_name', ''),
                    'documents': task.get('documents', []),
                    'error': error_message,
                    'request': task.get('request', {}),
                    'result': {
                        'summary': {
                            'table_name': task.get('table_name', ''),
                            'total_rows': 0,
                            'violations_found': 0,
                            'fixes_applied': 0,
                            'iterations': 0
                        }
                    }
                }
                
                with open(fallback_file, 'w', encoding='utf-8') as f:
                    json.dump(simple_history, f, ensure_ascii=False, indent=2)
                
                self.logger.info(f"Fallback successfully saved task {run_id}")
            except Exception as fallback_e:
                self.logger.error(f"Fallback also failed {run_id}: {fallback_e}")
    
    def debug_history_setup(self):
        """Debug history setup."""
        self.logger.debug(f'History setup check: {self.history_dir}, exists: {self.history_dir.exists()}')
        
        if self.history_dir.exists():
            files = list(self.history_dir.glob('*.json'))
            self.logger.debug(f'Existing file count: {len(files)}')
        
        try:
            test_file = self.history_dir / 'debug_test.tmp'
            with open(test_file, 'w') as f:
                f.write('test')
            test_file.unlink()
            self.logger.debug('Write permission OK')
        except Exception as e:
            self.logger.error(f'Write permission failed: {e}')
        
        return {
            'history_dir': str(self.history_dir),
            'exists': self.history_dir.exists(),
            'files_count': len(list(self.history_dir.glob('*.json'))) if self.history_dir.exists() else 0
        }


class StepOutputInterceptor:
    """Step output interceptor - forwards step output to the progress queue."""
    
    def __init__(self, original_list: list, progress_queue: Queue, run_id: str):
        self.original_list = original_list
        self.progress_queue = progress_queue
        self.run_id = run_id
    
    def append(self, item):
        """Intercept append calls."""
        self.original_list.append(item)
        
        try:
            step_info = {
                'type': 'step_completed',
                'step': item.get('step', 'unknown'),
                'description': item.get('description', ''),
                'status': item.get('status', 'completed'),
                'timestamp': item.get('timestamp'),
                'details': item.get('details', {}),
                'run_id': self.run_id
            }
            
            if 'output' in item:
                step_info['output'] = item['output']
            if 'result' in item:
                step_info['result'] = item['result']
            if 'data_preview' in item:
                step_info['data_preview'] = item['data_preview']
            if 'violation_summary' in item:
                step_info['violation_summary'] = item['violation_summary']
            if 'final_stats' in item:
                step_info['final_stats'] = item['final_stats']
            
            self.progress_queue.put(step_info)
        except Exception as e:
            logging.getLogger('doc2db.service').warning(f"Failed to send progress update: {e}")
    
    def __getattr__(self, name):
        """Delegate other methods to the original list."""
        return getattr(self.original_list, name)
    
    def __iter__(self):
        """Support iteration."""
        return iter(self.original_list)
    
    def __len__(self):
        """Support len()."""
        return len(self.original_list)
    
    def __getitem__(self, index):
        """Support indexed access."""
        return self.original_list[index]
    
    def __setitem__(self, index, value):
        """Support indexed assignment."""
        self.original_list[index] = value
    
    def __delitem__(self, index):
        """Support element deletion."""
        del self.original_list[index]
    
    def __bool__(self):
        """Support boolean conversion."""
        return bool(self.original_list)
    
    def __str__(self):
        """Support string conversion."""
        return str(self.original_list)
    
    def __repr__(self):
        """Support repr."""
        return f"StepOutputInterceptor({repr(self.original_list)})"
    
    def __eq__(self, other):
        """Support equality comparison."""
        if isinstance(other, StepOutputInterceptor):
            return self.original_list == other.original_list
        return self.original_list == other
    
    def extend(self, items):
        """Support extend."""
        self.original_list.extend(items)
        for item in items:
            try:
                self.progress_queue.put({
                    'type': 'step_completed',
                    'step': item.get('step', 'unknown'),
                    'description': item.get('description', ''),                              
                    'status': item.get('status', 'completed'),
                    'timestamp': item.get('timestamp'),
                    'details': item.get('details', {})
                })
            except Exception as e:
                logging.getLogger('doc2db.service').warning(f"Failed to send progress update: {e}")
    
    def clear(self):
        """Support clear."""
        self.original_list.clear()
    
    def count(self, value):
        """Support count."""
        return self.original_list.count(value)
    
    def index(self, value):
        """Support index."""
        return self.original_list.index(value)
    
    def insert(self, index, value):
        """Support insert."""
        self.original_list.insert(index, value)
    
    def pop(self, index=-1):
        """Support pop."""
        return self.original_list.pop(index)
    
    def remove(self, value):
        """Support remove."""
        self.original_list.remove(value)
    
    def reverse(self):
        """Support reverse."""
        self.original_list.reverse()
    
    def sort(self, key=None, reverse=False):
        """Support sort."""
        self.original_list.sort(key=key, reverse=reverse)