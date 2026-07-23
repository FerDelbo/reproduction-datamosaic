"""signal processor module"""
import asyncio
import time
import os
from typing import List, Optional, Any
import logging

from .context import Doc2DBContext, Doc2DBProcessingState
from ...memory import TableSnapshot, Violation, Fix
from ...signals.core import SignalType
from ...signals.handlers import BaseSignalHandler
from .utils import DocumentUtils


class OrchestratorSignalHandler(BaseSignalHandler):
    """coordinator signal processor"""
    
    def __init__(self, orchestrator):
        super().__init__('unified_orchestrator')
        self.orchestrator = orchestrator
        self.logger = logging.getLogger('orchestrator.signal_handler')
        
        self.add_supported_signal(SignalType.EXTRACTION_COMPLETE)
        self.add_supported_signal(SignalType.VERIFICATION_COMPLETE)
        self.add_supported_signal(SignalType.FIXING_COMPLETE)
        self.add_supported_signal(SignalType.EXTRACTION_ERROR)
        self.add_supported_signal(SignalType.VERIFICATION_ERROR)
        self.add_supported_signal(SignalType.FIXING_ERROR)
        self.add_supported_signal(SignalType.WARM_START_REQUEST)
        
    async def _process_signal(self, signal) -> Optional[Any]:
        """Handle coordinator-related signals"""
        if signal.signal_type == SignalType.EXTRACTION_COMPLETE:
            return await self.orchestrator.handle_extraction_complete(signal)
        elif signal.signal_type == SignalType.VERIFICATION_COMPLETE:
            return await self.orchestrator.handle_verification_complete(signal)
        elif signal.signal_type == SignalType.FIXING_COMPLETE:
            return await self.orchestrator.handle_fixing_complete(signal)
        elif signal.signal_type == SignalType.WARM_START_REQUEST:
            return await self.orchestrator.handle_warm_start_request(signal)
        elif signal.signal_type in [SignalType.EXTRACTION_ERROR, SignalType.VERIFICATION_ERROR, SignalType.FIXING_ERROR]:
            return await self.orchestrator.handle_component_error(signal)
        
        return None


class SignalHandlerMixin:
    """Signal processor mix-in class provides signal processing methods"""
    
    async def handle_extraction_complete(self, signal):
        """Process the extraction completion signal (supports fragment processing and batch processing)"""
        data = signal.data
        table_name = data.get('table_name')
        snapshots = data.get('snapshots', [])
        context_data = data.get('context', {})
        segment_info = data.get('segment_info')
        batch_info = data.get('batch_info')
        if self.current_context:
            signal_run_id = context_data.get('run_id') or signal.correlation_id.split('_')[0] if hasattr(signal, 'correlation_id') else None
            current_run_id = self.current_context.run_id
            current_state = getattr(self.current_context, 'current_state', None)
            
            if signal_run_id and signal_run_id != current_run_id:
                self.logger.warning(f'Rejecting mismatched signal: signal run_id={signal_run_id}, current run_id={current_run_id}')
                return
            
            if current_state and str(current_state).endswith('COMPLETED'):
                self.logger.warning(f'Task already completed (state: {current_state}), ignoring extraction complete signal from table {table_name}')
                return
        
        self.logger.info(f'Received extraction complete signal - table: {table_name}, batch_info: {batch_info is not None}, segment_info: {segment_info is not None}')
        
        is_warm_start = context_data.get('warm_start', False) or (hasattr(self.current_context, 'warm_start_attempted') and table_name in self.current_context.warm_start_attempted)
        
        if is_warm_start and self.current_context and hasattr(self.current_context, 'step_outputs'):
            from ...core.io import IOManager
            for step in self.current_context.step_outputs:
                if step.get('step') == f'warm_start_extraction_{table_name}' and step.get('status') == 'in_progress':
                    step['status'] = 'completed'
                    step['description'] = f'Warm Start complete: re-extracted {len(snapshots[0].rows) if snapshots and len(snapshots) > 0 else 0} rows'
                    step['details']['rows_extracted'] = len(snapshots[0].rows) if snapshots and len(snapshots) > 0 else 0
                    step['timestamp_completed'] = IOManager.get_timestamp()
                    self.logger.info(f'Updated warm start step status to completed')
                    break
            
            self.logger.info(f'Warm start extraction complete: {table_name}, waiting for verification...')
        
        if self.current_context and hasattr(self.current_context, 'warm_start_in_progress') and table_name in self.current_context.warm_start_in_progress:
            self.current_context.warm_start_in_progress.remove(table_name)
        
        if batch_info:
            await self._handle_batch_extraction_complete(
                table_name, snapshots, batch_info, context_data
            )
            return
        
        if segment_info:
            await self._handle_segment_extraction_complete(
                table_name, snapshots, segment_info, context_data
            )
            return
        if self.current_context and snapshots:
            for snapshot in snapshots:
                self.logger.info(f'Received extraction complete signal - table: {table_name}, new data: {len(snapshot.rows)} rows')
                self.logger.info(f'Tables in context.all_snapshots: {list(self.current_context.all_snapshots.keys())}')
                
                if table_name in self.current_context.all_snapshots:
                    existing_snapshot = self.current_context.all_snapshots[table_name]
                    self.logger.info(f'Table {table_name} already has snapshot ({len(existing_snapshot.rows)} rows), new data ({len(snapshot.rows)} rows)')
                    
                    existing_desc = getattr(existing_snapshot, 'stage_description', '')
                    is_batch_merged = (
                        '分batch提取完成' in existing_desc or '分片段提取完成' in existing_desc
                        or 'Batch extraction complete' in existing_desc or 'Segment extraction complete' in existing_desc
                    )
                    
                    if not is_batch_merged and hasattr(existing_snapshot, 'is_batch_merged'):
                        is_batch_merged = existing_snapshot.is_batch_merged
                    if not is_batch_merged and hasattr(self.current_context, 'batch_merged_tables') and table_name in self.current_context.batch_merged_tables:
                        is_batch_merged = True
                    
                    is_warm_start = context_data.get('warm_start', False) or context_data.get('is_warm_start', False) if context_data else False
                    
                    if is_batch_merged:
                        self.logger.warning(f'Detected batch/segment merge result, skipping overwrite; keeping existing {len(existing_snapshot.rows)} rows')
                        
                        if is_warm_start and len(snapshot.rows) > 0:
                            self.logger.info(f'Warm start mode: performing cell-level fix merge')
                            existing_snapshot = self._merge_warm_start_cells(existing_snapshot, snapshot, table_name)
                        
                        snapshot = existing_snapshot
                    else:
                        is_warm_start = context_data.get('warm_start', False) if context_data else False
                        warm_start_failed = False
                        
                        if is_warm_start:
                            if len(snapshot.rows) == 0:
                                self.logger.warning(f'Warm start re-extraction returned empty data, keeping original data and marking table complete')
                                snapshot = existing_snapshot
                                warm_start_failed = True
                            elif len(snapshot.rows) < len(existing_snapshot.rows) * 0.5:
                                self.logger.warning(f'Warm start re-extraction significantly reduced row count ({len(snapshot.rows)} < {len(existing_snapshot.rows)}*0.5), keeping original data and marking table complete')
                                snapshot = existing_snapshot
                                warm_start_failed = True
                            else:
                                self.logger.info(f'Warm start re-extraction succeeded, using new data ({len(snapshot.rows)} rows)')
                            
                            if warm_start_failed:
                                self.logger.info(f'Warm start failed, marking table {table_name} as complete')
                                self._set_table_force_completed(table_name)
                                
                                if hasattr(self.current_context, 'warm_start_tracking') and table_name in self.current_context.warm_start_tracking:
                                    self.current_context.warm_start_tracking.remove(table_name)
                                    self.logger.info(f'Removed from warm start tracking: {table_name}')
                        else:
                            if hasattr(existing_snapshot, 'rows') and hasattr(snapshot, 'rows'):
                                existing_snapshot.rows.extend(snapshot.rows)
                                snapshot = existing_snapshot
                
                self.current_context.all_snapshots[table_name] = snapshot
                stage_desc = getattr(snapshot, 'stage_description', '')
                if (
                    '分batch提取完成' not in stage_desc and '分片段提取完成' not in stage_desc
                    and 'Batch extraction complete' not in stage_desc and 'Segment extraction complete' not in stage_desc
                ):
                    snapshot.processing_stage = 'extraction'
                    snapshot.stage_description = f'Data extraction complete - table {table_name}, {len(snapshot.rows)} rows total'
                
                self.current_context.io_manager.append_snapshot(snapshot)
                
                self._sync_current_snapshot_to_context()
        
        self.logger.info(f'[Extraction complete] Starting basic verification: {table_name}')
        basic_violations_triggered_fix = await self._auto_basic_verification(table_name, snapshots, context_data)
        self.logger.info(f'[Extraction complete] Basic verification returned: triggered_fix={basic_violations_triggered_fix}')
        
        if not basic_violations_triggered_fix:
            self.logger.info(f'[Extraction complete] No fix triggered, starting full verification: {table_name}')
            await self._signal_verify_data(table_name, snapshots, context_data)
        else:
            self.logger.info(f'[Extraction complete] Fix triggered, waiting for auto-verification after fix: {table_name}')
    
    async def _handle_batch_extraction_complete(self, table_name: str, snapshots: List, 
                                                batch_info: dict, context_data: dict):
        """Processing batch extraction completed"""
        batch_index = batch_info.get('batch_index')
        total_batches = batch_info.get('total_batches')
        is_warm_start = batch_info.get('is_warm_start', False)
        
        warm_start_label = " (warm start)" if is_warm_start else ""
        self.logger.info(f'Table {table_name} - Batch {batch_index}/{total_batches}{warm_start_label} extraction complete')
        
        if hasattr(self, 'coordinator'):
            self.coordinator.mark_batch_completed(table_name, batch_index, is_warm_start=is_warm_start)
        
        if not hasattr(self.current_context, 'batch_tracking'):
            self.current_context.batch_tracking = {}
        
        if table_name not in self.current_context.batch_tracking:
            self.logger.warning(f'Table {table_name} has no batch tracking info, initializing...')
            self.current_context.batch_tracking[table_name] = {
                'total_batches': total_batches,
                'completed_batches': 0,
                'snapshots': []
            }
        
        tracking = self.current_context.batch_tracking[table_name]
        
        if snapshots:
            tracking['snapshots'].extend(snapshots)
            tracking['completed_batches'] += 1
            
            self.logger.debug(
                f'Batch collection progress: {tracking["completed_batches"]}/{tracking["total_batches"]} '
                f'(collected {len(tracking["snapshots"])} snapshots)'
            )
        
        if snapshots:
            self.logger.info(f'Starting verification for Batch {batch_index} results')
            
            context_data['is_batch_verification'] = True
            context_data['batch_index'] = batch_index
            context_data['batch_total'] = total_batches
            context_data['is_warm_start'] = is_warm_start  # Pass warm start flag
            
            basic_violations_triggered_fix = await self._auto_basic_verification(
                table_name, snapshots, context_data
            )
            
            if not basic_violations_triggered_fix:
                await self._signal_verify_data(table_name, snapshots, context_data)
        
        if tracking['completed_batches'] >= tracking['total_batches']:
            self.logger.info(f'Table {table_name} - all {total_batches} batches processed, starting merge...')
            
            merged_snapshot = self._merge_batch_snapshots(table_name, tracking['snapshots'])
            
            if merged_snapshot:
                self.current_context.all_snapshots[table_name] = merged_snapshot
                merged_snapshot.processing_stage = 'extraction'
                merged_snapshot.stage_description = (
                    f'Batch extraction complete - table {table_name}, '
                    f'{total_batches} batches, {len(merged_snapshot.rows)} rows total'
                )
                
                merged_snapshot.is_batch_merged = True
                merged_snapshot.merged_row_count = len(merged_snapshot.rows)
                
                if not hasattr(self.current_context, 'batch_merged_tables'):
                    self.current_context.batch_merged_tables = {}
                self.current_context.batch_merged_tables[table_name] = len(merged_snapshot.rows)
                self.logger.info(f'Marked table {table_name} as batch merge result with {len(merged_snapshot.rows)} rows to prevent overwrite')
                
                self.current_context.io_manager.append_snapshot(merged_snapshot)
                self._sync_current_snapshot_to_context()
                
                del self.current_context.batch_tracking[table_name]
                
                if hasattr(self, 'coordinator') and self.coordinator:
                    from .signal_coordinator import TableLifecycleState
                    self.coordinator.update_table_state(table_name, TableLifecycleState.EXTRACTED)
                
                self.logger.info(f'Table {table_name} all batches merged')
                
                if total_batches == 1:
                    self.logger.info(f'Table {table_name} has only 1 batch, already verified per batch, skipping post-merge verification')
                else:
                    if 'is_batch_verification' in context_data:
                        del context_data['is_batch_verification']
                    
                    basic_violations_triggered_fix = await self._auto_basic_verification(
                        table_name, [merged_snapshot], context_data
                    )
                    
                    if not basic_violations_triggered_fix:
                        await self._signal_verify_data(table_name, [merged_snapshot], context_data)
            else:
                self.logger.error(f'Table {table_name} batch merge failed')
    
    def _merge_batch_snapshots(self, table_name: str, snapshots: List) -> Optional[Any]:
        """Merge snapshots of multiple batches
        
        Strategy: Intelligent deduplication
        - Only delete identical rows
        - or delete rows that are a subset of other rows"""
        if not snapshots:
            return None
        
        if len(snapshots) == 1:
            return snapshots[0]
        
        try:
            from ...memory import TableSnapshot
            from ...core.io import IOManager
            
            base_snapshot = snapshots[0]
            
            all_rows = []
            for snapshot in snapshots:
                if hasattr(snapshot, 'rows') and snapshot.rows:
                    all_rows.extend(snapshot.rows)
            
            if not all_rows:
                return base_snapshot
            
            unique_rows = []
            removed_count = 0
            
            for i, row1 in enumerate(all_rows):
                should_keep = True
                
                for j, row2 in enumerate(all_rows):
                    if i == j:
                        continue
                    
                    relation = self._compare_rows(row1, row2)
                    
                    if relation == 'identical':
                        if j < i:
                            should_keep = False
                            self.logger.debug(f'Dedup: row {i} identical to row {j}, removing row {i}')
                            removed_count += 1
                            break
                    elif relation == 'row1_subset':
                        should_keep = False
                        self.logger.debug(f'Dedup: row {i} is subset of row {j}, removing row {i}')
                        removed_count += 1
                        break
                
                if should_keep:
                    unique_rows.append(row1)
            
            if removed_count > 0:
                self.logger.info(f'Removed {removed_count} duplicate rows during batch merge (identical or subset)')
            
            merged_snapshot = TableSnapshot(
                run_id=base_snapshot.run_id if hasattr(base_snapshot, 'run_id') else None,
                table=table_name,
                rows=unique_rows,
                created_at=IOManager.get_timestamp(),
                table_id=base_snapshot.table_id if hasattr(base_snapshot, 'table_id') else table_name
            )
            
            self.logger.info(
                f'Batch merge complete: {len(snapshots)} batches -> {len(unique_rows)} rows (after dedup)'
            )
            
            return merged_snapshot
            
        except Exception as e:
            self.logger.error(f'Failed to merge batch snapshots: {e}', exc_info=True)
            return None
    
    def _compare_rows(self, row1, row2) -> str:
        """Compare the relationship between two rows of data
        
        Returns:
            'identical': identical
            'row1_subset': row1 is a subset of row2
            'row2_subset': row2 is a subset of row1
            'different': different"""
        if not hasattr(row1, 'cells') or not hasattr(row2, 'cells'):
            return 'different'
        
        cells1 = row1.cells if isinstance(row1.cells, dict) else {}
        cells2 = row2.cells if isinstance(row2.cells, dict) else {}
        
        values1 = {}
        values2 = {}
        
        for field, cell in cells1.items():
            value = cell.value if hasattr(cell, 'value') else cell
            if value not in [None, '', 'null', 'NULL']:
                values1[field] = str(value).strip()
        
        for field, cell in cells2.items():
            value = cell.value if hasattr(cell, 'value') else cell
            if value not in [None, '', 'null', 'NULL']:
                values2[field] = str(value).strip()
        
        if values1 == values2:
            return 'identical'
        
        if values1 and values2:
            if all(field in values2 and values1[field] == values2[field] for field in values1):
                if len(values1) < len(values2):
                    return 'row1_subset'
                elif len(values1) == len(values2):
                    return 'identical'
            
            if all(field in values1 and values2[field] == values1[field] for field in values2):
                if len(values2) < len(values1):
                    return 'row2_subset'
        
        return 'different'
    
    async def _handle_segment_extraction_complete(self, table_name: str, snapshots: List, 
                                                  segment_info: dict, context_data: dict):
        """Processing fragment extraction completed (collected and merged)"""
        segment_index = segment_info.get('segment_index')
        total_segments = segment_info.get('total_segments')
        
        self.logger.info(f'Table {table_name} - segment {segment_index}/{total_segments} extraction complete')
        
        if not hasattr(self.current_context, 'segment_tracking'):
            self.current_context.segment_tracking = {}
        
        if table_name not in self.current_context.segment_tracking:
            self.logger.warning(f'Table {table_name} has no segment tracking info, initializing...')
            self.current_context.segment_tracking[table_name] = {
                'total_segments': total_segments,
                'completed_segments': 0,
                'snapshots': []
            }
        
        tracking = self.current_context.segment_tracking[table_name]
        
        if snapshots:
            tracking['snapshots'].extend(snapshots)
            tracking['completed_segments'] += 1
            
            self.logger.debug(
                f'Segment collection progress: {tracking["completed_segments"]}/{tracking["total_segments"]} '
                f'(collected {len(tracking["snapshots"])} snapshots)'
            )
        
        if tracking['completed_segments'] >= tracking['total_segments']:
            self.logger.info(f'Table {table_name} - all {total_segments} segments extracted, starting merge...')
            
            merged_snapshot = self._merge_segment_snapshots(table_name, tracking['snapshots'])
            
            if merged_snapshot:
                self.current_context.all_snapshots[table_name] = merged_snapshot
                merged_snapshot.processing_stage = 'extraction'
                merged_snapshot.stage_description = (
                    f'Segment extraction complete - table {table_name}, '
                    f'{total_segments} segments, {len(merged_snapshot.rows)} rows total'
                )
                self.current_context.io_manager.append_snapshot(merged_snapshot)
                self._sync_current_snapshot_to_context()
                
                del self.current_context.segment_tracking[table_name]
                
                self.logger.info(f'Starting verification for merged table {table_name}')
                
                basic_violations_triggered_fix = await self._auto_basic_verification(
                    table_name, [merged_snapshot], context_data
                )
                
                if not basic_violations_triggered_fix:
                    await self._signal_verify_data(table_name, [merged_snapshot], context_data)
            else:
                self.logger.error(f'Table {table_name} segment merge failed')
    
    def _merge_warm_start_cells(self, existing_snapshot, warm_start_snapshot, table_name: str):
        """Warm start's cell level merge: update the batch merge results with the cells repaired by warm start
        
        Args:
            existing_snapshot: full snapshot of batch merge
            warm_start_snapshot: partial snapshot re-extracted by warm start
            table_name: table name
            
        Returns:
            The merged snapshot"""
        try:
            warm_start_rows = {row.tuple_id: row for row in warm_start_snapshot.rows}
            
            updated_cells_count = 0
            
            for existing_row in existing_snapshot.rows:
                if existing_row.tuple_id in warm_start_rows:
                    warm_row = warm_start_rows[existing_row.tuple_id]
                    
                    for attr_name, warm_cell in warm_row.cells.items():
                        if attr_name in existing_row.cells:
                            existing_cell = existing_row.cells[attr_name]
                            warm_value = warm_cell.value if hasattr(warm_cell, 'value') else None
                            existing_value = existing_cell.value if hasattr(existing_cell, 'value') else None
                            
                            if warm_value != existing_value:
                                if hasattr(existing_cell, 'value'):
                                    existing_cell.value = warm_value
                                
                                if hasattr(warm_cell, 'evidences') and hasattr(existing_cell, 'evidences'):
                                    warm_evidences = warm_cell.evidences if isinstance(warm_cell.evidences, list) else [warm_cell.evidences]
                                    existing_evidences = existing_cell.evidences if isinstance(existing_cell.evidences, list) else [existing_cell.evidences]
                                    
                                    warm_evidences_marked = [f"[Warm Start Fix] {e}" if not e.startswith("[Warm Start Fix]") else e for e in warm_evidences]
                                    
                                    all_evidences = existing_evidences + warm_evidences_marked
                                    existing_cell.evidences = list(set(all_evidences))
                                
                                updated_cells_count += 1
            
            self.logger.info(f'Warm start cell-level merge complete: {table_name}, updated {updated_cells_count} cells')
            return existing_snapshot
            
        except Exception as e:
            self.logger.error(f'Warm start cell merge failed: {e}', exc_info=True)
            return existing_snapshot
    
    def _merge_segment_snapshots(self, table_name: str, snapshots: List) -> Optional[Any]:
        """Merge snapshots from multiple fragments
        
        Strategy: Simply splice the rows of all snapshots, and the verifier will be responsible for deduplication and consistency checking.
        
        Returns:
            The merged TableSnapshot, returning None if failed"""
        if not snapshots:
            return None
        
        if len(snapshots) == 1:
            return snapshots[0]
        
        try:
            from ...memory import TableSnapshot
            from ...core.io import IOManager
            
            base_snapshot = snapshots[0]
            
            all_rows = []
            for snapshot in snapshots:
                if hasattr(snapshot, 'rows') and snapshot.rows:
                    all_rows.extend(snapshot.rows)
            
            merged_snapshot = TableSnapshot(
                run_id=base_snapshot.run_id if hasattr(base_snapshot, 'run_id') else None,
                table=table_name,
                rows=all_rows,
                created_at=IOManager.get_timestamp(),
                table_id=base_snapshot.table_id if hasattr(base_snapshot, 'table_id') else table_name
            )
            
            self.logger.info(
                f'Merge complete: {len(snapshots)} segments -> {len(all_rows)} rows'
            )
            
            return merged_snapshot
            
        except Exception as e:
            self.logger.error(f'Failed to merge segment snapshots: {e}', exc_info=True)
            return None
    
    async def handle_verification_complete(self, signal):
        """Handle verification completion signal"""
        data = signal.data
        table_name = data.get('table_name')
        violations = data.get('violations', [])
        
        if self.current_context:
            current_state = getattr(self.current_context, 'current_state', None)
            if current_state and str(current_state).endswith('COMPLETED'):
                self.logger.warning(f'Task already completed (state: {current_state}), ignoring verification complete signal from table {table_name}')
                return
        
        context_data = data.get('context', {})
        batch_index = context_data.get('batch_index')
        if hasattr(self, 'coordinator') and self.coordinator:
            tracker = self.coordinator.get_table_tracker(table_name)
            if tracker:
                current_round = tracker.verification_round
                max_rounds = tracker.max_verification_rounds
                if current_round >= max_rounds:
                    self.logger.warning(
                        f'Force stop: table {table_name} completed {current_round} verification rounds, '
                        f'reached max rounds ({max_rounds})'
                    )
                    self._mark_final(table_name, batch_index)
                    return

        
        if hasattr(self, 'coordinator') and self.coordinator:
            from .signal_coordinator import TableLifecycleState
            if self.coordinator.is_table_in_state(table_name, TableLifecycleState.FINAL):
                self.logger.warning(f'Table {table_name} already marked FINAL, ignoring verification complete signal')
                
                if hasattr(self.current_context, 'warm_start_attempted') and table_name in self.current_context.warm_start_attempted:
                    if hasattr(self.current_context, 'warm_start_tracking') and table_name in self.current_context.warm_start_tracking:
                        self.current_context.warm_start_tracking.remove(table_name)
                        self.logger.info(f'Removed FINAL table from warm_start_tracking: {table_name}')
                
                context_data = data.get('context', {})
                batch_index = context_data.get('batch_index')
                if batch_index is not None:
                    tracker = self.coordinator.get_table_tracker(table_name)
                    if tracker:
                        is_warm_start = context_data.get('is_warm_start_batch', False)
                        batch_key = self.coordinator._get_batch_key(batch_index, is_warm_start)
                        
                        if batch_key in tracker.batch_trackers:
                            batch_tracker = tracker.batch_trackers[batch_key]
                            if batch_tracker.state != 'final':
                                self.logger.info(f'Force marking Batch {batch_index} (warm_start={is_warm_start}) as final because table is already FINAL')
                                self.coordinator.mark_batch_final(table_name, batch_index, is_warm_start)
                
                return
        
        snapshot = data.get('snapshot')
        
        is_warm_start_verification = (
            hasattr(self.current_context, 'warm_start_attempted') and 
            table_name in self.current_context.warm_start_attempted
        )
        
        if is_warm_start_verification:
            error_violations = [v for v in violations if getattr(v, 'severity', 'warn') == 'error']
            
            if hasattr(self.current_context, 'warm_start_tracking') and table_name in self.current_context.warm_start_tracking:
                self.current_context.warm_start_tracking.remove(table_name)
                if len(error_violations) == 0:
                    self.logger.info(
                        f'Warm start verification complete with no errors: {table_name}, removed from tracking, '
                        f'remaining: {list(self.current_context.warm_start_tracking) if self.current_context.warm_start_tracking else []}'
                    )
                else:
                    self.logger.info(
                        f'Warm start verification complete but still has {len(error_violations)} errors, '
                        f'removed from tracking (to avoid blocking), remaining: {list(self.current_context.warm_start_tracking) if self.current_context.warm_start_tracking else []}'
                    )
        
        is_batch_verification = context_data.get('is_batch_verification', False)
        
        if hasattr(self.current_context, 'force_format_check_tables') and table_name in self.current_context.force_format_check_tables:
            format_violations = [v for v in violations if v.constraint_type == 'FORMAT']
            if not format_violations:
                self.current_context.force_format_check_tables.remove(table_name)
            else:
                self.current_context.force_format_check_tables.remove(table_name)
        
        if self.current_context:
            if table_name not in self.current_context.all_violations:
                self.current_context.all_violations[table_name] = []
            self.current_context.all_violations[table_name].extend(violations)
            
            if snapshot:
                if hasattr(self.current_context, 'batch_merged_tables') and table_name in self.current_context.batch_merged_tables:
                    merged_row_count = self.current_context.batch_merged_tables[table_name]
                    
                    if len(snapshot.rows) < merged_row_count:
                        self.logger.warning(
                            f'Post-verification snapshot ({len(snapshot.rows)} rows) fewer than batch merge result ({merged_row_count} rows), '
                            f'likely single-batch verification; refusing to overwrite merge result.'
                        )
                        
                        if table_name in self.current_context.all_snapshots:
                            existing_snapshot = self.current_context.all_snapshots[table_name]
                            snapshot = existing_snapshot
                            self.logger.info(f'Preserved batch merge integrity, continuing with {len(snapshot.rows)} rows')
                
                snapshot.processing_stage = 'verification'
                
                if is_batch_verification:
                    snapshot.stage_description = f'Batch verification complete - table {table_name}, found {len(violations)} quality issues'
                else:
                    should_update_all_snapshots = True
                    
                    if hasattr(self.current_context, 'batch_merged_tables') and table_name in self.current_context.batch_merged_tables:
                        merged_row_count = self.current_context.batch_merged_tables[table_name]
                        if len(snapshot.rows) < merged_row_count:
                            should_update_all_snapshots = False
                            self.logger.warning(
                                f'Skipping all_snapshots update: post-verification snapshot ({len(snapshot.rows)} rows) < batch merge ({merged_row_count} rows), protecting merge data'
                            )
                    
                    if should_update_all_snapshots:
                        snapshot.stage_description = f'Data verification complete - table {table_name}, found {len(violations)} quality issues'
                        self.current_context.all_snapshots[table_name] = snapshot
                    
                self.current_context.io_manager.append_snapshot(snapshot)
                
                self._sync_current_snapshot_to_context()
        
        error_violations = [v for v in violations if getattr(v, 'severity', 'warn') == 'error']
        warn_violations = [v for v in violations if getattr(v, 'severity', 'warn') == 'warn']
        
        
        
        if not violations:
            self.logger.info(f'Table {table_name} verification complete with no violations, marking complete')
            
            if is_batch_verification and batch_index is not None:
                if hasattr(self, 'coordinator'):
                    is_warm_start = context_data.get('warm_start', False) or context_data.get('is_warm_start', False)
                    self.coordinator.mark_batch_final(table_name, batch_index, is_warm_start=is_warm_start)
                    self.logger.info(f'Batch {batch_index} has no violations, marked as final{" (warm start)" if is_warm_start else ""}')
                return  # batch completed, return
            
            if hasattr(self, 'coordinator'):
                from .signal_coordinator import TableLifecycleState
                self.coordinator.update_table_state(table_name, TableLifecycleState.FINAL)
            self._set_table_force_completed(table_name)
            return
        
        total_fixes = len(self.current_context.all_fixes.get(table_name, [])) if self.current_context else 0
        error_count = len([v for v in violations if getattr(v, 'severity', 'warn') == 'error'])
        warn_count = len([v for v in violations if getattr(v, 'severity', 'warn') == 'warn'])
        
        if error_count == 0 and warn_count > 0:
            if total_fixes >= 1:  # Already fixed and can be completed
                if is_batch_verification and batch_index is not None:
                    if hasattr(self, 'coordinator'):
                        is_warm_start = context_data.get('warm_start', False) or context_data.get('is_warm_start', False)
                        self.coordinator.mark_batch_final(table_name, batch_index, is_warm_start=is_warm_start)
                        self.logger.info(f'Batch {batch_index} has warnings only and was fixed, marked as final{" (warm start)" if is_warm_start else ""}')
                    return  # batch completed, return
                self._set_table_force_completed(table_name)
                return
        
        try:
            await asyncio.wait_for(
                self._detect_and_mark_repeated_violations(violations, table_name),
                timeout=10.0  # 10 seconds timeout
            )
        except asyncio.TimeoutError:
            self.logger.warning(f'Detect repeated violations timed out (table {table_name}), skipping step')
        except Exception as e:
            self.logger.error(f'Failed to detect repeated violations (table {table_name}): {e}')
        
        try:
            filtered_violations = await asyncio.wait_for(
                self._filter_unfixable_violations(violations, table_name),
                timeout=10.0  # 10 seconds timeout
            )
        except asyncio.TimeoutError:
            self.logger.warning(f'Filter unfixable violations timed out (table {table_name}), using original violation list')
            filtered_violations = violations
        except Exception as e:
            self.logger.error(f'Failed to filter unfixable violations (table {table_name}): {e}')
            filtered_violations = violations
        if len(filtered_violations) < len(violations):
            removed_count = len(violations) - len(filtered_violations)
            self.logger.info(f"Filtered {removed_count} unfixable violations")
        
        violations = filtered_violations
        
        if not violations:
            self.logger.info(f'No violations after filtering, preparing to mark complete - table: {table_name}, is_batch_verification={is_batch_verification}, batch_index={batch_index}')
            if is_batch_verification and batch_index is not None:
                self.logger.info(f'  -> batch verification, will call mark_batch_final')
                if hasattr(self, 'coordinator'):
                    is_warm_start = context_data.get('warm_start', False) or context_data.get('is_warm_start', False)
                    self.logger.info(f'  -> params: table_name={table_name}, batch_index={batch_index}, is_warm_start={is_warm_start}')
                    self.coordinator.mark_batch_final(table_name, batch_index, is_warm_start=is_warm_start)
                    self.logger.info(f'Batch {batch_index} has no violations after filtering, marked as final{" (warm start)" if is_warm_start else ""}')
                return  # batch completed, return
            else:
                self.logger.info(f'  -> table-level verification (is_batch_verification={is_batch_verification}, batch_index={batch_index}), will call _set_table_force_completed')
            self._set_table_force_completed(table_name)
            return
        
        if hasattr(self.current_context, 'coordinator'):
            coordinator = self.current_context.coordinator
        else:
            self.logger.warning('Context has no coordinator, cannot perform loop control check')
            coordinator = None
        
        tool_fixable = self._get_tool_fixable_violations(violations)
        requires_reextraction = self._get_reextraction_violations(violations)
        
        if coordinator:
            tracker = coordinator.get_table_tracker(table_name)
            current_round = tracker.verification_round if tracker else 0
            max_rounds = tracker.max_verification_rounds if tracker else 2
            self.logger.info(
                f'Table {table_name} verification analysis: '
                f'verification_round={current_round}/{max_rounds}, '
                f'tool_fixable={len(tool_fixable)}, '
                f'requires_reextraction={len(requires_reextraction)}, '
                f'total_violations={len(violations)}'
            )
        else:
            self.logger.info(
                f'Violation classification: tool_fixable={len(tool_fixable)}, requires_reextraction={len(requires_reextraction)}'
            )
        
        if tool_fixable:
            check_batch_index = batch_index if is_batch_verification else None
            
            self.logger.info(
                f'Loop control check: table={table_name}, '
                f'is_batch_verification={is_batch_verification}, '
                f'batch_index={batch_index}, '
                f'check_batch_index={check_batch_index}'
            )
            
            if coordinator and not coordinator.can_verify_fix_iterate(table_name, check_batch_index):
                self.logger.warning(
                    f'Max verify-fix iterations reached, stopping fix - table {table_name}, '
                    f'remaining {len(tool_fixable)} fixable violations will be ignored'
                )
                
                if requires_reextraction:
                    self.logger.info(
                        f'Max fix iterations reached but {len(requires_reextraction)} violations require re-extraction, '
                        f'attempting Warm Start'
                    )
                    
                    if coordinator and coordinator.can_warm_start(table_name, check_batch_index):
                        coordinator.increment_warm_start_attempts(table_name, check_batch_index)
                        
                        if is_batch_verification and batch_index is not None:
                            self._mark_final(table_name, batch_index)
                        
                        if is_batch_verification:
                            batch_document_names = context_data.get('batch_document_names', [])
                            text_contents = context_data.get('text_contents', [])
                            batch_total = context_data.get('batch_total', 1)
                            
                            if batch_document_names and text_contents:
                                self.logger.info(
                                    f'Batch {batch_index}/{batch_total} warm start: using current batch documents {batch_document_names}'
                                )
                                await self._trigger_batch_warm_start_extraction(
                                    table_name, requires_reextraction, snapshot, 
                                    text_contents, batch_document_names, batch_index, batch_total
                                )
                            else:
                                self.logger.warning(f'Batch {batch_index} missing document info, skipping warm start')
                                self._mark_final(table_name, batch_index)
                        else:
                            await self._trigger_smart_warm_start_extraction(
                                table_name, requires_reextraction, snapshot
                            )
                        return
                    else:
                        self.logger.warning(
                            f'Cannot trigger Warm Start (max attempts or other limit) - table {table_name}'
                        )
                
                self._mark_final(table_name, batch_index)
                return
            
            self.logger.info(f'Preparing to fix {len(tool_fixable)} violations...')
            
            if coordinator:
                coordinator.increment_verify_fix_iteration(table_name, check_batch_index)
            
            await self._signal_fix_data(table_name, tool_fixable, snapshot, context_data)
            return  # After the repair is completed, re-verification will be automatically triggered.
        
        if requires_reextraction:
            self.logger.info(f'Detected {len(requires_reextraction)} violations requiring re-extraction')
            
            check_batch_index = batch_index if is_batch_verification else None
            
            if coordinator and not coordinator.can_warm_start(table_name, check_batch_index):
                self.logger.warning(
                    f'Max Warm Start attempts reached, stopping re-extraction - table {table_name}'
                )
                self._mark_final(table_name, batch_index)
                return
            
            if coordinator:
                coordinator.increment_warm_start_attempts(table_name, check_batch_index)
            
            if is_batch_verification and batch_index is not None:
                self._mark_final(table_name, batch_index)
            
            if is_batch_verification:
                batch_document_names = context_data.get('batch_document_names', [])
                text_contents = context_data.get('text_contents', [])
                batch_total = context_data.get('batch_total', 1)
                
                if batch_document_names and text_contents:
                    self.logger.info(
                        f'Batch {batch_index}/{batch_total} warm start: using current batch documents {batch_document_names}'
                    )
                    await self._trigger_batch_warm_start_extraction(
                        table_name, requires_reextraction, snapshot, 
                        text_contents, batch_document_names, batch_index, batch_total
                    )
                else:
                    self.logger.warning(f'Batch {batch_index} missing document info, skipping warm start')
                    self._mark_final(table_name, batch_index)
            else:
                await self._trigger_smart_warm_start_extraction(
                    table_name, requires_reextraction, snapshot
                )
            return
        
        self.logger.info(
            f'No actionable violations, marking complete - table {table_name}, '
            f'remaining {len(violations)} violations (unfixable or require manual handling)'
        )
        self._mark_final(table_name, batch_index)
    
    async def handle_fixing_complete(self, signal):
        """Handle repair completion signal"""
        data = signal.data
        table_name = data.get('table_name')
        fixes = data.get('fixes', [])
        
        if self.current_context:
            current_state = getattr(self.current_context, 'current_state', None)
            if current_state and str(current_state).endswith('COMPLETED'):
                self.logger.warning(f'Task already completed (state: {current_state}), ignoring fixing complete signal from table {table_name}')
                return
        
        if hasattr(self, 'coordinator') and self.coordinator:
            from .signal_coordinator import TableLifecycleState
            if self.coordinator.is_table_in_state(table_name, TableLifecycleState.FINAL):
                self.logger.warning(f'Table {table_name} already marked FINAL, ignoring fixing complete signal')
                return
        
        snapshot = data.get('snapshot')
        
        context_data = data.get('context', {})
        is_batch_verification = context_data.get('is_batch_verification', False)
        batch_index = context_data.get('batch_index')
        
        
        if self.current_context and fixes:
            fix_details = {
                'total_fixes': len(fixes),
                'fixes_by_type': {},
                'fixes_summary': []
            }
            
            for fix in fixes:
                fix_type = getattr(fix, 'fix_type', 'unknown')
                if fix_type not in fix_details['fixes_by_type']:
                    fix_details['fixes_by_type'][fix_type] = 0
                fix_details['fixes_by_type'][fix_type] += 1
                
                fix_details['fixes_summary'].append({
                    'id': getattr(fix, 'id', 'unknown'),
                    'tuple_id': getattr(fix, 'tuple_id', 'unknown'),
                    'attr': getattr(fix, 'attr', 'unknown'),
                    'old': getattr(fix, 'old', 'null'),
                    'new': getattr(fix, 'new', 'null'),
                    'fix_type': fix_type
                })
            
            fix_step = {
                'step': f'fixer_{table_name}_completed',
                'step_name': f'fixer_{table_name}_completed',
                'description': f'Table {table_name} data fixing complete, applied {len(fixes)} fixes',
                'status': 'completed',
                'timestamp': self.current_context.io_manager.get_timestamp(),
                'details': fix_details
            }
            
            self.current_context.step_outputs.append(fix_step)
        
        if self.current_context:
            if table_name not in self.current_context.all_fixes:
                self.current_context.all_fixes[table_name] = []
            self.current_context.all_fixes[table_name].extend(fixes)
            
            if len(fixes) == 0:
                self.logger.warning(f'Fix failed (0 fixes applied), keeping original data and force-completing table {table_name}')
                if snapshot and table_name in self.current_context.all_snapshots:
                    self.logger.info(f'Keeping original data for table {table_name} ({len(self.current_context.all_snapshots[table_name].rows)} rows)')
                
                if is_batch_verification and batch_index is not None:
                    if hasattr(self, 'coordinator'):
                        is_warm_start = context_data.get('warm_start', False) or context_data.get('is_warm_start', False)
                        self.coordinator.mark_batch_final(table_name, batch_index, is_warm_start=is_warm_start)
                        self.logger.info(f'Batch {batch_index} fix failed, marked as final{" (warm start)" if is_warm_start else ""}')
                    return  # batch completed, return
                    
                self._set_table_force_completed(table_name)
                return
            
            if snapshot:
                should_update_snapshot = True
                
                if hasattr(self.current_context, 'batch_merged_tables') and table_name in self.current_context.batch_merged_tables:
                    merged_row_count = self.current_context.batch_merged_tables[table_name]
                    
                    if len(snapshot.rows) < merged_row_count:
                        self.logger.warning(
                            f'Post-fix snapshot ({len(snapshot.rows)} rows) fewer than batch merge ({merged_row_count} rows)! '
                            f'Applying fixes to full batch merge data instead of overwriting.'
                        )
                        
                        if table_name in self.current_context.all_snapshots:
                            existing_snapshot = self.current_context.all_snapshots[table_name]
                            
                            snapshot_dict = {getattr(row, 'tuple_id', None): row for row in snapshot.rows if hasattr(row, 'tuple_id')}
                            
                            updated_count = 0
                            for i, row in enumerate(existing_snapshot.rows):
                                tuple_id = getattr(row, 'tuple_id', None)
                                if tuple_id and tuple_id in snapshot_dict:
                                    existing_snapshot.rows[i] = snapshot_dict[tuple_id]
                                    updated_count += 1
                                    self.logger.debug(f'  Updated row: {tuple_id}')
                            
                            snapshot = existing_snapshot
                            self.logger.info(
                                f'Applied {updated_count} fixes to batch merge result, '
                                f'preserving integrity, final {len(snapshot.rows)} rows'
                            )
                            should_update_snapshot = True  # Needs to be updated because we modified existing_snapshot
                
                if should_update_snapshot:
                    self.current_context.all_snapshots[table_name] = snapshot
                snapshot.processing_stage = 'fixing'
                snapshot.stage_description = f'Data fixing complete - table {table_name}, applied {len(fixes)} fixes'
                self.current_context.io_manager.append_snapshot(snapshot)
                
                self._sync_current_snapshot_to_context()
                
                if self._should_skip_reverification(table_name, len(fixes)):
                    self.logger.info(f'Skipping re-verification, table {table_name} marked complete')
                    
                    if is_batch_verification and batch_index is not None:
                        if hasattr(self, 'coordinator'):
                            is_warm_start = context_data.get('warm_start', False) or context_data.get('is_warm_start', False)
                            self.coordinator.mark_batch_final(table_name, batch_index, is_warm_start=is_warm_start)
                            self.logger.info(f'Batch {batch_index} fix complete, no re-verification needed, marked as final{" (warm start)" if is_warm_start else ""}')
                        return  # batch completed, return
                    
                    if hasattr(self, 'coordinator') and self.coordinator:
                        from .signal_coordinator import TableLifecycleState
                        self.coordinator.update_table_state(table_name, TableLifecycleState.FINAL)
                    self._set_table_force_completed(table_name)
                else:
                    check_batch_index = batch_index if is_batch_verification else None
                    
                    if hasattr(self, 'coordinator') and self.coordinator:
                        if not self.coordinator.can_verify_fix_iterate(table_name, check_batch_index):
                            self.logger.warning(
                                f'Fix complete but max verify-fix iterations reached, stopping re-verification - table {table_name}'
                            )
                            if is_batch_verification and batch_index is not None:
                                is_warm_start = context_data.get('warm_start', False) or context_data.get('is_warm_start', False)
                                self.coordinator.mark_batch_final(table_name, batch_index, is_warm_start=is_warm_start)
                                self.logger.info(f'Batch {batch_index} reached max iterations, marked as final{" (warm start)" if is_warm_start else ""}')
                            else:
                                from .signal_coordinator import TableLifecycleState
                                self.coordinator.update_table_state(table_name, TableLifecycleState.FINAL)
                                self._set_table_force_completed(table_name)
                            return  # No longer triggers revalidation
                    
                    self.logger.info(f'Triggering re-verification for table {table_name}, applied {len(fixes)} fixes')
                    await self._signal_verify_data(table_name, [snapshot], context_data)
            else:
                self.logger.warning(f'Fix complete but snapshot is empty, force-completing table {table_name}')
                
                if is_batch_verification and batch_index is not None:
                    if hasattr(self, 'coordinator'):
                        is_warm_start = context_data.get('warm_start', False) or context_data.get('is_warm_start', False)
                        self.coordinator.mark_batch_final(table_name, batch_index, is_warm_start=is_warm_start)
                        self.logger.info(f'Batch {batch_index} snapshot empty, marked as final{" (warm start)" if is_warm_start else ""}')
                    return  # batch completed, return
                    
                self._set_table_force_completed(table_name)
    
    def _sync_current_snapshot_to_context(self):
        """Synchronize the current snapshot data to context.snapshots in real time to ensure that the service layer can read it immediately"""
        if not self.current_context or not self.current_context.all_snapshots:
            return
            
        self.current_context.snapshots = list(self.current_context.all_snapshots.values())
    
    async def handle_component_error(self, signal):
        """Handle component error signals"""
        data = signal.data
        error = data.get('error')
        table_name = data.get('table_name', 'unknown')
        
        
        if hasattr(self, 'logger'):
            self.logger.error(f"Component error - table {table_name}: {error}")
        
    
    async def _trigger_smart_warm_start_extraction(self, table_name: str, violations_requiring_reextraction, snapshot):
        """Trigger Warm Start reextraction - send a request to Orchestrator via the signaling system
        
        New architecture: instead of calling the orchestrator method directly, the WARM_START_REQUEST signal is sent"""
        self.logger.info(f"Sending Warm Start request: {table_name}, {len(violations_requiring_reextraction)} violations")
        
        if self.current_context and hasattr(self.current_context, 'step_outputs'):
            from ...core.io import IOManager
            warm_start_step = {
                'step': f'warm_start_extraction_{table_name}',
                'step_name': f'warm_start_extraction_{table_name}',
                'status': 'in_progress',
                'description': f'Warm Start: detected {len(violations_requiring_reextraction)} violations requiring re-extraction',
                'details': {
                    'table_name': table_name,
                    'violations_count': len(violations_requiring_reextraction),
                    'violation_types': list(set([v.constraint_type for v in violations_requiring_reextraction])),
                    'mode': 'warm_start_extraction'
                },
                'timestamp': IOManager.get_timestamp()
            }
            self.current_context.step_outputs.append(warm_start_step)
        
        try:
            from ...signals.core import SignalType
            
            signal_data = {
                'table_name': table_name,
                'violations': violations_requiring_reextraction,
                'snapshot': snapshot,
                'run_id': self.current_context.run_id if self.current_context else None,
                'schema': self.current_context.schema if self.current_context else None
            }
            
            await self.broadcaster.emit_simple_signal(
                SignalType.WARM_START_REQUEST,
                data=signal_data,
                correlation_id=f"{signal_data['run_id']}_{table_name}_warmstart"
            )
            
            self.logger.info(f"Warm Start request sent, waiting for Orchestrator")
            
        except Exception as e:
            self.logger.error(f"Failed to send Warm Start request: {e}", exc_info=True)
            
            if self.current_context and hasattr(self.current_context, 'step_outputs'):
                from ...core.io import IOManager
                for step in self.current_context.step_outputs:
                    if step.get('step') == f'warm_start_extraction_{table_name}' and step.get('status') == 'in_progress':
                        step['status'] = 'failed'
                        step['description'] = f'Warm Start request failed: {str(e)}'
                        step['details']['error'] = str(e)
                        step['timestamp_completed'] = IOManager.get_timestamp()
                        break
    
    def _should_skip_reverification(self, table_name: str, fixes_applied: int) -> bool:
        """Determine whether revalidation should be skipped to avoid loops
        
        Simplified logic:
        1. If no fixes are applied, skip
        2. If it is a basic repair, do not skip it (complete verification is required)
        3. Otherwise, revalidation is always triggered (let the coordinator control the number of cycles)"""
        
        if fixes_applied == 0:
            self.logger.info(f"Skipping re-verification: no fixes applied")
            return True
        
        if hasattr(self.current_context, 'basic_fix_tables') and table_name in self.current_context.basic_fix_tables:
            self.current_context.basic_fix_tables.remove(table_name)
            self.logger.info(f"Not skipping re-verification: basic fix complete, full verification required")
            return False
        
        self.logger.info(f"Not skipping re-verification: applied {fixes_applied} fixes")
        return False
    
    async def _detect_and_mark_repeated_violations(self, violations: List, table_name: str):
        """Detect and mark repeated violations: The cell has been repaired but the violation is still there, indicating that the repair failed."""
        if not violations:
            return
        
        try:
            if not hasattr(self, 'memory_manager') or not self.memory_manager:
                return
            
            run_id = getattr(self.current_context, 'run_id', None) if hasattr(self, 'current_context') else None
            if not run_id:
                return
            
            total_fixes = len(self.current_context.all_fixes.get(table_name, [])) if self.current_context else 0
            if total_fixes == 0:
                return
            
            repeated_violations = await self.memory_manager.check_repeated_violations(
                violations, run_id, table_name
            )
            
            if repeated_violations:
                for violation in repeated_violations:
                    try:
                        await self.memory_manager.mark_violation_unfixable(violation.id, run_id)
                        self.logger.info(f"Marked repeated violation as unfixable: {violation.id}")
                    except Exception as mark_error:
                        self.logger.error(f"Failed to mark violation {violation.id} as unfixable: {mark_error}")
                
        except Exception as e:
            self.logger.error(f"Failed to detect repeated violations: {e}")
    
    async def _filter_unfixable_violations(self, violations: List, table_name: str) -> List:
        """Filter out violations that have been marked as irreparable"""
        if not violations:
            return violations
        
        try:
            if not hasattr(self, 'memory_manager') or not self.memory_manager:
                return violations
            
            run_id = getattr(self.current_context, 'run_id', None) if hasattr(self, 'current_context') else None
            if not run_id:
                return violations
            
            unfixable_ids = await self.memory_manager.get_unfixable_violations(run_id)
            
            filtered = [v for v in violations if v.id not in unfixable_ids]
            return filtered
            
        except Exception as e:
            self.logger.error(f"Failed to filter unfixable violations: {e}")
            import traceback
            traceback.print_exc()
            return violations
    
    def _extract_relevant_documents(self, violations: List, snapshot) -> List[str]:
        """Extract relevant documents from violations (enhanced version: supports multiple matching strategies)
        
        Policy priority:
        1. Extract document names from evidences (fuzzy matching)
        2. If there are none, return an empty list (fallback to using all documents)
        
        Args:
            violations: list of violations
            snapshot: table snapshot
            
        Returns:
            List of related document names (e.g. ['2024-CIRTRAN CORP-j.txt', ...])"""
        if not violations or not snapshot or not hasattr(snapshot, 'rows'):
            self.logger.debug('violations or snapshot empty, returning empty document list')
            return []
        
        relevant_docs = set()
        violation_tuple_ids = set([v.tuple_id for v in violations])
        
        evidence_based_docs = set()
        for row in snapshot.rows:
            if row.tuple_id in violation_tuple_ids:
                for cell_name, cell_data in row.cells.items():
                    if hasattr(cell_data, 'evidences') and cell_data.evidences:
                        for evidence in cell_data.evidences:
                            import os
                            doc_name = os.path.basename(evidence) if evidence else None
                            
                            if doc_name and ('.' in doc_name or doc_name.endswith('-j.txt')):
                                evidence_based_docs.add(doc_name)
        
        if evidence_based_docs:
            relevant_docs.update(evidence_based_docs)
            self.logger.info('Selected %d relevant documents using evidence metadata', len(evidence_based_docs))
        
        if not relevant_docs and hasattr(self, 'current_context') and self.current_context:
            if hasattr(self.current_context, 'documents') and self.current_context.documents:
                all_evidences = set()
                for row in snapshot.rows:
                    if row.tuple_id in violation_tuple_ids:
                        for cell_name, cell_data in row.cells.items():
                            if hasattr(cell_data, 'evidences') and cell_data.evidences:
                                all_evidences.update(cell_data.evidences)
                
                import os
                actual_docs = [os.path.basename(d) for d in self.current_context.documents]
                for evidence in all_evidences:
                    for actual_doc in actual_docs:
                        if evidence.lower() in actual_doc.lower() or actual_doc.lower() in evidence.lower():
                            relevant_docs.add(actual_doc)
                
                if relevant_docs:
                    self.logger.info('Selected %d relevant documents using filename matching', len(relevant_docs))
        
        result = list(relevant_docs)
        if not result:
            self.logger.warning(f'Could not extract relevant documents, falling back to all documents')
        else:
            self.logger.info(f'Identified {len(result)} relevant documents: {result}')
        
        return result
    
    def _get_tool_fixable_violations(self, violations: List[Violation]) -> List[Violation]:
        """Extract tool-fixable violations
        
        Violation characteristics that can be repaired by tools:
        - processing_category contains 'tool_fixable' or 'fixable'
        - Or the constraint type is in the repairable list (FORMAT, TYPE, VALUE, etc.)"""
        tool_fixable = []
        for v in violations:
            category = getattr(v, 'processing_category', None)
            if category:
                category_str = category.value if hasattr(category, 'value') else str(category)
                if 'tool_fixable' in category_str.lower() or 'fixable' in category_str.lower():
                    tool_fixable.append(v)
                    continue
            
            constraint_type = getattr(v, 'constraint_type', '').upper()
            if constraint_type in ['FORMAT', 'TYPE', 'VALUE', 'LOGIC', 'AGGREGATION']:
                tool_fixable.append(v)
        
        return tool_fixable
    
    def _get_reextraction_violations(self, violations: List[Violation]) -> List[Violation]:
        """Extract violations that require reextraction
        
        Violating features that need to be re-extracted:
        - processing_category contains 'reextraction' or 'reextract'
        - Or there are problems such as null values and missing values that cannot be repaired by tools."""
        reextraction = []
        for v in violations:
            category = getattr(v, 'processing_category', None)
            if category:
                category_str = category.value if hasattr(category, 'value') else str(category)
                if 'reextract' in category_str.lower():
                    reextraction.append(v)
        
        return reextraction
    
    def _mark_final(self, table_name: str, batch_index: Optional[int] = None):
        """Unified marking completion method
        
        Args:
            table_name: table name
            batch_index: batch index (None means table level)"""
        if batch_index is not None:
            if hasattr(self, 'coordinator') and self.coordinator:
                is_warm_start = context_data.get('is_warm_start', False) if context_data else False
                self.coordinator.mark_batch_final(table_name, batch_index, is_warm_start)
                self.logger.info(f'Batch {batch_index} marked as final')
        else:
            self._set_table_force_completed(table_name)
    
    def _set_table_force_completed(self, table_name: str):
        """Set table force completion mark"""
        if not hasattr(self.current_context, 'force_completed_tables'):
            self.current_context.force_completed_tables = set()
        
        self.current_context.force_completed_tables.add(table_name)
        
        if hasattr(self, 'coordinator') and self.coordinator:
            from .signal_coordinator import TableLifecycleState
            self.coordinator.update_table_state(table_name, TableLifecycleState.FINAL)
            self.logger.info(f'Table {table_name} marked as FINAL')
            
            tracker = self.coordinator.get_table_tracker(table_name)
            if tracker and hasattr(tracker, 'batch_trackers') and tracker.batch_trackers:
                self.logger.info(f'  Marking all batches for table {table_name} as final, total {len(tracker.batch_trackers)} batches')
                for batch_key, batch_tracker in tracker.batch_trackers.items():
                    if batch_tracker.state != 'final':
                        batch_index = batch_tracker.batch_index
                        is_warm_start = batch_tracker.is_warm_start
                        self.logger.info(f'  Marking Batch {batch_index} (warm_start={is_warm_start}, current state={batch_tracker.state})')
                        self.coordinator.mark_batch_final(table_name, batch_index, is_warm_start)
                        self.logger.info(f'  Batch {batch_index} marked as final')
                    else:
                        self.logger.info(f'   Batch {batch_tracker.batch_index} already final, skipping')
                self.logger.info(f'  All batches for table {table_name} marked as final')
            else:
                if hasattr(self.current_context, 'batch_tracking') and table_name in self.current_context.batch_tracking:
                    total_batches = self.current_context.batch_tracking[table_name].get('total_batches', 1)
                    self.logger.info(f'  No batch_trackers found but batch_tracking info exists: total_batches={total_batches}')
                    if total_batches == 1:
                        try:
                            self.coordinator.mark_batch_final(table_name, 0, is_warm_start=False)
                            self.logger.info(f'  Single-batch mode: Batch 0 marked as final')
                        except Exception as e:
                            self.logger.warning(f'  Failed to mark batch 0 as final: {e}')
                    else:
                        self.logger.warning(f'  Multi-batch mode but no batch_trackers, possible state inconsistency!')
    
    def _is_table_force_completed(self, table_name: str) -> bool:
        """Check if the table has been forced to completion"""
        if not hasattr(self.current_context, 'force_completed_tables'):
            return False
        
        is_completed = table_name in self.current_context.force_completed_tables
        return is_completed
    
    async def _auto_basic_verification(self, table_name: str, snapshots: List[TableSnapshot], context_data: dict) -> bool:
        """Automatic basic verification - like a compiler's syntax check
        
        Controlled by Orchestrator, Format and Type validation are enforced after each extraction.
        Basic guarantee to ensure data quality
        
        Returns:
            bool: whether the repair process is triggered"""
        if not snapshots:
            return False
        
        
        try:
            if not hasattr(self, '_basic_verifiers') or self._basic_verifiers is None:
                from ..mcp import FormatMCP, TypeMCP
                self._basic_verifiers = {
                    'format': FormatMCP(),
                    'type': TypeMCP()
                }
                self.logger.info("Initialized basic verifiers (Format + Type)")
            
            all_violations = []
            
            for snapshot in snapshots:
                format_violations = self._basic_verifiers['format'].verify(
                    snapshot=snapshot,
                    schema=context_data.get('schema'),
                    table_name=table_name
                )
                all_violations.extend(format_violations)
                
                type_violations = self._basic_verifiers['type'].verify(
                    snapshot=snapshot,
                    schema=context_data.get('schema'),
                    table_name=table_name
                )
                all_violations.extend(type_violations)
            
            if self.current_context:
                run_id = context_data.get('run_id')
                
                if all_violations:
                    if table_name not in self.current_context.all_violations:
                        self.current_context.all_violations[table_name] = []
                    self.current_context.all_violations[table_name].extend(all_violations)
                
                if self.memory_manager and run_id and all_violations:
                    try:
                        await self.memory_manager.store_violations(all_violations, run_id, table_name)
                    except Exception as store_error:
                        self.logger.warning(f"Failed to store auto-verification results to memory: {store_error}")
            
            error_count = len([v for v in all_violations if getattr(v, 'severity', 'warn') == 'error'])
            warn_count = len([v for v in all_violations if getattr(v, 'severity', 'warn') == 'warn'])
            
            self.logger.info(
                f'[Basic verification] Complete - table: {table_name}, '
                f'FORMAT violations: {len([v for v in all_violations if v.constraint_type == "FORMAT"])}, '
                f'TYPE violations: {len([v for v in all_violations if v.constraint_type == "TYPE"])}, '
                f'total: {len(all_violations)} (errors: {error_count}, warnings: {warn_count})'
            )
            
            if all_violations:
                self.logger.info(f'[Basic verification] Found {len(all_violations)} violations, starting classification...')
                
                violations_requiring_reextraction = []
                violations_for_tool_fixing = []
                
                for violation in all_violations:
                    processing_category = getattr(violation, 'processing_category', None)
                    if not processing_category:
                        from ..verifier.mcp_verifier import ViolationCategory
                        if violation.constraint_type in ['FORMAT', 'TYPE']:
                            processing_category = ViolationCategory.TOOL_FIXABLE
                            violation.processing_category = processing_category
                        else:
                            if violation.severity == 'error':
                                processing_category = ViolationCategory.REQUIRES_REEXTRACTION
                                violation.processing_category = processing_category
                            else:
                                processing_category = ViolationCategory.TOOL_FIXABLE
                                violation.processing_category = processing_category
                    
                    try:
                        from ..verifier.mcp_verifier import ViolationCategory
                        if processing_category == ViolationCategory.TOOL_FIXABLE:
                            violations_for_tool_fixing.append(violation)
                        else:
                            violations_requiring_reextraction.append(violation)
                    except:
                        if getattr(violation, 'severity', 'warn') == 'error':
                            violations_requiring_reextraction.append(violation)
                        else:
                            violations_for_tool_fixing.append(violation)
                
                reextraction_in_tool_fixable = [
                    v for v in violations_for_tool_fixing 
                    if getattr(v, 'processing_category', '') == 'requires_reextraction'
                ]
                
                actual_tool_fixable = [
                    v for v in violations_for_tool_fixing 
                    if v not in reextraction_in_tool_fixable
                ]
                
                if reextraction_in_tool_fixable:
                    violations_requiring_reextraction.extend(reextraction_in_tool_fixable)
                
                self.logger.info(
                    f'[Basic verification] Classification complete: '
                    f'tool_fixable={len(actual_tool_fixable)}, '
                    f'requires_reextraction={len(violations_requiring_reextraction)}'
                )
                
                if not hasattr(self.current_context, 'basic_fix_attempts'):
                    self.current_context.basic_fix_attempts = {}
                
                if table_name not in self.current_context.basic_fix_attempts:
                    self.current_context.basic_fix_attempts[table_name] = 0
                
                if self.current_context.basic_fix_attempts[table_name] >= 1:
                    self.logger.warning(f'Table {table_name} basic fix attempted {self.current_context.basic_fix_attempts[table_name]} times, stopping retries')
                    return False
                
                if actual_tool_fixable:
                    self.logger.info(f'[Basic verification] Preparing to trigger fix flow: {len(actual_tool_fixable)} violations')
                    if table_name in self.current_context.all_snapshots:
                        snapshot = self.current_context.all_snapshots[table_name]
                        
                        if not hasattr(self.current_context, 'basic_fix_tables'):
                            self.current_context.basic_fix_tables = set()
                        self.current_context.basic_fix_tables.add(table_name)
                        
                        self.current_context.basic_fix_attempts[table_name] += 1
                        self.logger.info(f'Triggering basic fix (attempt {self.current_context.basic_fix_attempts[table_name]}): {table_name}, {len(actual_tool_fixable)} violations')
                        
                        try:
                            await asyncio.wait_for(
                                self._signal_fix_data(table_name, actual_tool_fixable, snapshot, context_data),
                                timeout=60.0  # 60 seconds timeout
                            )
                            return True  # Indicates that a repair was triggered
                        except asyncio.TimeoutError:
                            self.logger.error(f'Basic fix timed out: {table_name}, continuing with full verification')
                            return False  # Timeout, return False to trigger full verification
                        except Exception as fix_error:
                            self.logger.error(f'Basic fix failed: {table_name}, error: {fix_error}')
                            import traceback
                            traceback.print_exc()
                            return False  # On failure, return False to trigger full verification
                    else:
                        self.logger.warning(f'[Basic verification] Table {table_name} not in all_snapshots, cannot fix')
                        self.logger.info(f'[Basic verification] Will run full verification to establish snapshot')
                        return False  # Unable to fix, return False to trigger full verification
                else:
                    self.logger.info(f'[Basic verification] No tool-fixable violations')
                    return False  # There is nothing to fix, return False to trigger full verification
                
            self.logger.info(f'[Basic verification] No violations, returning False')
            return False
            
        except Exception as e:
            self.logger.error(f"Auto basic verification failed: {e}")
            import traceback
            traceback.print_exc()
            return False


class TableProcessingWaiter:
    """Table processing waiter, responsible for waiting for the completion of processing of a single table"""
    
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger('table_processing_waiter')
        self.orchestrator = None  # will be set externally
    
    async def wait_for_table_processing_complete(self, context: Doc2DBContext, table_name: str):
        """Wait for processing of a single table to complete (supports multiple rounds of validation-fix loops)"""
        max_wait_time = 100  # Overall timeout in seconds
        wait_interval = 1.0  # Check interval (seconds)
        waited_time = 0
        max_fix_attempts = 1  # Maximum number of repair attempts
        max_iterations = 2  # Maximum number of waiting iterations (more limited than coordinator)
        iteration_count = 0
        
        
        extraction_done = False
        verification_started = False  # Whether to start verification
        last_total_count = -1  # Track changes in the total number of violations
        fix_attempt_count = 0  # Track repair attempts
        last_violation_snapshot = None  # Record the last violation snapshot to detect the repair effect
        
        while waited_time < max_wait_time:
            if hasattr(context, 'force_completed_tables') and table_name in context.force_completed_tables:
                return True
            
            if not extraction_done and table_name in context.all_snapshots:
                if not (hasattr(context, 'warm_start_in_progress') and table_name in context.warm_start_in_progress):
                    extraction_done = True
            
            if extraction_done:
                if table_name in context.all_violations:
                    verification_started = True
                    violations = context.all_violations[table_name]
                    current_total_count = len(violations)
                    error_violations = [v for v in violations if getattr(v, 'severity', 'warn') == 'error']
                    warn_violations = [v for v in violations if getattr(v, 'severity', 'warn') == 'warn']
                    
                    
                    if len(error_violations) > 0:
                        reextraction_violations = [
                            v for v in error_violations 
                            if getattr(v, 'processing_category', '') == 'requires_reextraction'
                        ]
                        
                        for i, v in enumerate(error_violations[:5]):  # Only show the first 5
                            pc = getattr(v, 'processing_category', 'None')
                        
                        if reextraction_violations:
                            if not hasattr(context, 'warm_start_attempted'):
                                context.warm_start_attempted = set()
                            
                            if table_name not in context.warm_start_attempted:
                                
                                context.warm_start_attempted.add(table_name)
                                fix_attempt_count += 1  # Mark tried
                                
                                if table_name in context.all_snapshots:
                                    old_snapshot = context.all_snapshots[table_name]
                                    if not hasattr(context, 'warm_start_in_progress'):
                                        context.warm_start_in_progress = set()
                                    context.warm_start_in_progress.add(table_name)
                                
                                extraction_done = False
                                verification_started = False  # Reset verification status
                                
                                await self._trigger_warm_start_extraction(context, table_name)
                                waited_time = 0
                                last_total_count = -1  # Reset violation count
                                continue  # Start waiting loop again
                            elif extraction_done:
                                return True
                    
                    violations_signature = f"{len(error_violations)}-{len(warn_violations)}"
                    progress_made = (last_total_count != current_total_count) or (last_total_count == -1)
                    
                    if progress_made:
                        last_total_count = current_total_count
                        iteration_count += 1
                        
                        if current_total_count == 0:
                            return True
                        
                        if len(error_violations) > 0:
                            if fix_attempt_count < max_fix_attempts:
                                fix_attempt_count += 1
                                waited_time = 0  # reset wait time
                            else:
                                if not hasattr(context, 'warm_start_attempted'):
                                    context.warm_start_attempted = set()
                                if table_name not in context.warm_start_attempted:
                                    context.warm_start_attempted.add(table_name)
                                    fix_attempt_count = 0
                                    await self._trigger_warm_start_extraction(context, table_name)
                                    waited_time = 0
                                else:
                                    return True
                        elif len(warn_violations) > 0:
                            total_fixes = len(context.all_fixes.get(table_name, []))
                            
                            min_wait_for_mcp = 3.0  # Minimum verification grace period in seconds
                            
                            should_complete = (
                                (total_fixes >= 1 and waited_time >= min_wait_for_mcp) or  # There is a fix and enough time has passed
                                waited_time >= 15 or  # Waiting time exceeds 15 seconds
                                fix_attempt_count >= 2  # Already tried to fix it 2 times
                            )
                            
                            if should_complete:
                                return True
                            elif fix_attempt_count < max_fix_attempts:
                                fix_attempt_count += 1
                                waited_time = 0
                            else:
                                return True
                    else:
                        if waited_time > 30:
                            if len(error_violations) == 0:
                                return True
                            else:
                                return True
                        
                elif extraction_done and waited_time > 10:
                    if not verification_started and waited_time > 20:
                        return True
            elif extraction_done and waited_time > 30:
                return True
                    
            await asyncio.sleep(wait_interval)
            waited_time += wait_interval
        
        final_total_violations = 0
        final_error_count = 0
        final_warn_count = 0
        if table_name in context.all_violations:
            violations = context.all_violations[table_name]
            error_violations = [v for v in violations if getattr(v, 'severity', 'warn') == 'error']
            warn_violations = [v for v in violations if getattr(v, 'severity', 'warn') == 'warn']
            final_total_violations = len(violations)
            final_error_count = len(error_violations)
            final_warn_count = len(warn_violations)
        
        if iteration_count >= max_iterations:
            self.logger.warning(
                f'Table {table_name} reached max iterations ({max_iterations}), '
                f'final state: {final_total_violations} violations '
                f'(Error: {final_error_count}, Warning: {final_warn_count}), '
                f'force terminating'
            )
            if hasattr(context, 'force_completed_tables'):
                context.force_completed_tables.add(table_name)
            else:
                context.force_completed_tables = {table_name}
        else:
            self.logger.info(
                f'Table {table_name} processing complete or timed out, '
                f'iterations: {iteration_count}/{max_iterations}, '
                f'final violations: {final_total_violations}'
            )
        
        
        return True
    
    async def _trigger_warm_start_extraction(self, context: Doc2DBContext, table_name: str):
        """Trigger warm start re-extraction (with violations information)
        
        NOTE: The caller should have checked the warm_start_attempted flag,
        There is no need to repeat checks and marks here to avoid logical confusion."""
        
        
        violations = context.all_violations.get(table_name, [])
        snapshot = context.all_snapshots.get(table_name)
        
        if not violations:
            return
        
        violations_requiring_reextraction = [
            v for v in violations 
            if getattr(v, 'processing_category', '') == 'requires_reextraction'
        ]
        
        relevant_documents = self._extract_relevant_documents_in_waiter(
            violations_requiring_reextraction, snapshot, context
        )
        
        if hasattr(self, 'orchestrator') and self.orchestrator:
            if hasattr(self.orchestrator, '_trigger_smart_warm_start_extraction'):
                await self.orchestrator._trigger_smart_warm_start_extraction(
                    table_name, violations_requiring_reextraction, snapshot
                )
            else:
                await self._trigger_filtered_extraction(context, table_name, relevant_documents)
    
    def _extract_relevant_documents_in_waiter(self, violations: List, snapshot, context) -> List[str]:
        """Extract relevant documents in the waiter (reuse the logic of SignalHandlerMixin)"""
        if not violations or not snapshot or not hasattr(snapshot, 'rows'):
            return []
        
        relevant_docs = set()
        violation_tuple_ids = set([v.tuple_id for v in violations])
        
        
        for row in snapshot.rows:
            if row.tuple_id in violation_tuple_ids:
                for cell_name, cell_data in row.cells.items():
                    if hasattr(cell_data, 'evidences') and cell_data.evidences:
                        for evidence in cell_data.evidences:
                            import os
                            doc_name = os.path.basename(evidence)
                            if doc_name:
                                relevant_docs.add(doc_name)
        
        result = list(relevant_docs)
        return result
    
    async def _trigger_filtered_extraction(self, context, table_name: str, relevant_documents: List[str]):
        """Trigger extraction using filtered documents"""
        if not relevant_documents:
            if hasattr(self.orchestrator, '_signal_extract_data'):
                await self.orchestrator._signal_extract_data(context, table_name)
            return
        
        
        all_documents = context.documents
        relevant_text_contents = []
        
        from .utils import DocumentUtils
        document_utils = DocumentUtils()
        
        for doc_path in all_documents:
            doc_basename = os.path.basename(doc_path)
            if doc_basename in relevant_documents:
                text_content = document_utils.convert_documents_to_text([doc_path])
                if text_content:
                    relevant_text_contents.extend(text_content)
        
        if relevant_text_contents:
            pass  # The custom text_contents function has not yet been implemented
        else:
            if hasattr(self.orchestrator, '_signal_extract_data'):
                await self.orchestrator._signal_extract_data(context, table_name)
