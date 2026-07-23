"""Parallel table processing orchestrator - supports parallel extraction, verification, and fixing of multiple tables."""
import asyncio
import logging
import time
from typing import List, Dict, Any, Optional, Set
from concurrent.futures import ThreadPoolExecutor
import threading

from .unified_orchestrator import UnifiedSignalDrivenOrchestrator
from .context import Doc2DBContext, Doc2DBProcessingState
from .utils import SignalUtils, StepUtils, DataTransferUtils
from ...signals.core import SignalType
from ...memory import TableSnapshot, Violation, Fix


class ParallelTableProcessor:
    """Parallel table processor - manages the full processing flow for a single table."""
    
    def __init__(self, table_name: str, orchestrator, logger=None):
        self.table_name = table_name
        self.orchestrator = orchestrator
        self.logger = logger or logging.getLogger(f'parallel.{table_name}')
        self.processing_state = 'pending'
        self.start_time = None
        self.end_time = None
        self.error = None
        
        self.snapshots = []
        self.violations = []
        self.fixes = []
        
    async def process_table(self, context: Doc2DBContext) -> Dict[str, Any]:
        """Process the full flow for a single table."""
        self.start_time = time.time()
        self.processing_state = 'processing'
        
        try:
            self.logger.info(f"Starting parallel processing of table: {self.table_name}")
            
            await self._extract_data(context)
            
            await self._verify_and_fix_loop(context)
            
            self.processing_state = 'completed'
            self.end_time = time.time()
            
            self.logger.info(f"Table {self.table_name} processed, elapsed: {self.end_time - self.start_time:.2f}s")
            
            return {
                'table_name': self.table_name,
                'status': 'completed',
                'processing_time': self.end_time - self.start_time,
                'snapshots': self.snapshots,
                'violations': self.violations,
                'fixes': self.fixes
            }
            
        except Exception as e:
            self.processing_state = 'failed'
            self.end_time = time.time()
            self.error = str(e)
            
            self.logger.error(f"Table {self.table_name} processing failed: {e}")
            
            return {
                'table_name': self.table_name,
                'status': 'failed',
                'error': str(e),
                'processing_time': self.end_time - self.start_time if self.start_time else 0
            }
    
    async def _extract_data(self, context: Doc2DBContext):
        """Extract data."""
        self.logger.info(f"Starting data extraction for table {self.table_name}...")
        
        table_specific_schema = self.orchestrator.schema_utils.extract_table_specific_schema(
            context.schema, self.table_name
        )
        if not table_specific_schema:
            table_specific_schema = context.schema
        
        signal_data = SignalUtils.create_extraction_signal_data(
            context, self.table_name, table_specific_schema
        )
        
        await self.orchestrator.broadcaster.emit_simple_signal(
            SignalType.EXTRACTION_REQUEST,
            data=signal_data,
            correlation_id=SignalUtils.get_correlation_id(
                context.run_id, self.table_name, "parallel_extract"
            )
        )
        
        await self._wait_for_extraction_complete(context)
    
    async def _wait_for_extraction_complete(self, context: Doc2DBContext, timeout: float = 30.0):
        """Wait for extraction to complete."""
        start_time = time.time()
        
        initial_snapshot_id = None
        if self.table_name in context.all_snapshots:
            initial_snapshot = context.all_snapshots[self.table_name]
            if hasattr(initial_snapshot, 'created_at'):
                initial_snapshot_id = initial_snapshot.created_at
            elif hasattr(initial_snapshot, 'table_id'):
                initial_snapshot_id = initial_snapshot.table_id
        
        while time.time() - start_time < timeout:
            if self.table_name in context.all_snapshots:
                snapshot = context.all_snapshots[self.table_name]
                
                is_new_snapshot = False
                if initial_snapshot_id is None:
                    is_new_snapshot = True
                elif hasattr(snapshot, 'created_at') and snapshot.created_at != initial_snapshot_id:
                    is_new_snapshot = True
                elif hasattr(snapshot, 'table_id') and snapshot.table_id != initial_snapshot_id:
                    is_new_snapshot = True
                
                if is_new_snapshot:
                    self.snapshots.append(snapshot)
                    return
            
            await asyncio.sleep(0.5)
        
        raise TimeoutError(f"Table {self.table_name} extraction timed out")
    
    async def _verify_and_fix_loop(self, context: Doc2DBContext, max_iterations: int = 3):
        """Verification and fixing loop."""
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            self.logger.info(f"Table {self.table_name} verification round {iteration}...")
            
            if self.table_name not in context.all_snapshots:
                self.logger.warning(f"Table {self.table_name} has no available snapshot, skipping verification")
                break
            
            snapshot = context.all_snapshots[self.table_name]
            
            await self._request_verification(context, snapshot)
            
            violations = await self._wait_for_verification_complete(context)
            
            if not violations:
                self.logger.info(f"Table {self.table_name} passed verification, no violations")
                break
            
            violations_requiring_reextraction = []
            violations_for_tool_fixing = []
            
            for i, violation in enumerate(violations):
                processing_category = getattr(violation, 'processing_category', None)
                severity = getattr(violation, 'severity', 'warn')
                
                if processing_category == 'requires_reextraction':
                    violations_requiring_reextraction.append(violation)
                    self.logger.debug(f"Requires re-extraction: {violation.tuple_id}.{violation.attr}")
                elif processing_category == 'tool_fixable' or processing_category is None:
                    violations_for_tool_fixing.append(violation)
                else:
                    if severity == 'error':
                        violations_requiring_reextraction.append(violation)
                    else:
                        violations_for_tool_fixing.append(violation)
            
            error_violations = [v for v in violations if getattr(v, 'severity', 'warn') == 'error']
            warn_violations = [v for v in violations if getattr(v, 'severity', 'warn') == 'warn']
            
            self.logger.info(f"Table {self.table_name} found violations: Error {len(error_violations)}, Warning {len(warn_violations)}")
            self.logger.info(f"Classification: requires re-extraction {len(violations_requiring_reextraction)}, tool-fixable {len(violations_for_tool_fixing)}")
            
            if violations_requiring_reextraction:
                self.logger.info(f"Table {self.table_name} has violations requiring re-extraction, triggering warm start")
                await self._trigger_warm_start_extraction(context, violations_requiring_reextraction, snapshot)
                continue
            
            if not error_violations and len(self.fixes) > 0:
                self.logger.info(f"Table {self.table_name} only has warning-level violations and has been fixed, ending processing")
                break
            
            violations_to_fix = violations_for_tool_fixing[:10]  # Limit count
            
            if violations_to_fix:
                await self._request_fixing(context, violations_to_fix, snapshot)
                
                fixes = await self._wait_for_fixing_complete(context)
                
                if fixes:
                    self.fixes.extend(fixes)
                    self.logger.info(f"Table {self.table_name} fixing complete, applied {len(fixes)} fixes")
                else:
                    self.logger.warning(f"Table {self.table_name} fixing failed or no fixes")
                    break
            else:
                break
        
        self.logger.info(f"Table {self.table_name} verify-fix loop complete, {iteration} rounds total")
    
    async def _request_verification(self, context: Doc2DBContext, snapshot: TableSnapshot):
        """Request verification."""
        table_specific_schema = self.orchestrator.schema_utils.extract_table_specific_schema(
            context.schema, self.table_name
        )
        if not table_specific_schema:
            table_specific_schema = context.schema
        
        signal_data = SignalUtils.create_verification_signal_data(
            context, self.table_name, table_specific_schema, [snapshot]
        )
        
        timestamp = int(time.time() * 1000)
        await self.orchestrator.broadcaster.emit_simple_signal(
            SignalType.VERIFICATION_REQUEST,
            data=signal_data,
            correlation_id=f"{context.run_id}_{self.table_name}_parallel_verify_{timestamp}"
        )
    
    async def _wait_for_verification_complete(self, context: Doc2DBContext, timeout: float = 20.0) -> List[Violation]:
        """Wait for verification to complete."""
        start_time = time.time()
        initial_violation_count = len(context.all_violations.get(self.table_name, []))
        
        while time.time() - start_time < timeout:
            if self.table_name in context.all_violations:
                current_violations = context.all_violations[self.table_name]
                if len(current_violations) > initial_violation_count:
                    new_violations = current_violations[initial_violation_count:]
                    self.violations.extend(new_violations)
                    return new_violations
            
            await asyncio.sleep(0.5)
        
        return []
    
    async def _request_fixing(self, context: Doc2DBContext, violations: List[Violation], snapshot: TableSnapshot):
        """Request fixing."""
        table_specific_schema = self.orchestrator.schema_utils.extract_table_specific_schema(
            context.schema, self.table_name
        )
        if not table_specific_schema:
            table_specific_schema = context.schema
        
        signal_data = SignalUtils.create_fixing_signal_data(
            context, self.table_name, table_specific_schema, violations, snapshot
        )
        
        timestamp = int(time.time() * 1000)
        await self.orchestrator.broadcaster.emit_simple_signal(
            SignalType.FIXING_REQUEST,
            data=signal_data,
            correlation_id=f"{context.run_id}_{self.table_name}_parallel_fix_{timestamp}"
        )
    
    async def _wait_for_fixing_complete(self, context: Doc2DBContext, timeout: float = 20.0) -> List[Fix]:
        """Wait for fixing to complete."""
        start_time = time.time()
        initial_fix_count = len(context.all_fixes.get(self.table_name, []))
        
        while time.time() - start_time < timeout:
            if self.table_name in context.all_fixes:
                current_fixes = context.all_fixes[self.table_name]
                if len(current_fixes) > initial_fix_count:
                    new_fixes = current_fixes[initial_fix_count:]
                    return new_fixes
            
            await asyncio.sleep(0.5)
        
        return []
    
    async def _trigger_warm_start_extraction(self, context: Doc2DBContext, violations_requiring_reextraction: List[Violation], snapshot: TableSnapshot):
        """Trigger warm start re-extraction (with violation information)."""
        self.logger.info(f"Starting warm start re-extraction for table {self.table_name} - based on {len(violations_requiring_reextraction)} violations requiring re-extraction")
        
        table_specific_schema = self.orchestrator.schema_utils.extract_table_specific_schema(
            context.schema, self.table_name
        )
        if not table_specific_schema:
            table_specific_schema = context.schema
        
        signal_data = SignalUtils.create_extraction_signal_data(
            context, self.table_name, table_specific_schema
        )
        
        signal_data.update({
            'warm_start': True,
            'previous_snapshot': snapshot.to_dict() if snapshot else None,
            'violations_requiring_reextraction': [
                {
                    'id': v.id,
                    'tuple_id': v.tuple_id,
                    'attr': v.attr,
                    'constraint_type': v.constraint_type,
                    'description': v.description,
                    'severity': v.severity,
                    'suggested_fix': v.suggested_fix.value if hasattr(v, 'suggested_fix') and v.suggested_fix else None
                } 
                for v in violations_requiring_reextraction
            ]
        })
        
        await self.orchestrator.broadcaster.emit_simple_signal(
            SignalType.EXTRACTION_REQUEST,
            data=signal_data,
            correlation_id=SignalUtils.get_correlation_id(
                context.run_id, self.table_name, "parallel_warm_start_extract"
            )
        )
        
        await self._wait_for_extraction_complete(context, timeout=30.0)
        
        self.logger.info(f"Warm start re-extraction complete: {self.table_name}")


class ParallelSignalDrivenOrchestrator(UnifiedSignalDrivenOrchestrator):
    """Signal-driven orchestrator with parallel processing support."""
    
    def __init__(self, max_iterations: int = 3, max_concurrent_tables: int = 3):
        super().__init__(max_iterations)
        self.max_concurrent_tables = max_concurrent_tables
        self.logger = logging.getLogger('parallel.orchestrator')
    
    async def _run_signal_driven_pipeline(self, context: Doc2DBContext):
        """Run the parallel signal-driven processing pipeline."""
        self.logger.info(f'Parallel processing pipeline started - run ID: {context.run_id}, target tables: {len(context.target_tables)}')
        await self.broadcaster.emit_simple_signal(
            SignalType.PROCESSING_START,
            data={'context': context.to_dict()},
            correlation_id=context.run_id
        )
        
        await self._signal_analyze_tables(context)
        
        if len(context.target_tables) > 1:
            await self._process_tables_in_parallel(context)
        else:
            await super()._run_signal_driven_pipeline(context)
            return
        
        await self._signal_multi_table_verify(context)
        
        await self._finalize_parallel_processing(context)
    
    async def _process_tables_in_parallel(self, context: Doc2DBContext):
        """Process multiple tables in parallel."""
        self.logger.info(f"Starting parallel processing of {len(context.target_tables)} tables")
        
        processors = []
        for table_name in context.target_tables:
            processor = ParallelTableProcessor(table_name, self, self.logger)
            processors.append(processor)
        
        semaphore = asyncio.Semaphore(self.max_concurrent_tables)
        
        async def process_with_semaphore(processor):
            async with semaphore:
                return await processor.process_table(context)
        
        tasks = [process_with_semaphore(processor) for processor in processors]
        
        try:
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            successful_tables = []
            failed_tables = []
            
            for i, result in enumerate(results):
                table_name = context.target_tables[i]
                
                if isinstance(result, Exception):
                    self.logger.error(f"Table {table_name} processing exception: {result}")
                    failed_tables.append(table_name)
                elif isinstance(result, dict) and result.get('status') == 'completed':
                    self.logger.info(f"Table {table_name} processed successfully")
                    successful_tables.append(table_name)
                else:
                    self.logger.warning(f"Table {table_name} processing status unknown: {result}")
                    failed_tables.append(table_name)
            
            parallel_step = StepUtils.create_custom_step(
                context,
                step_name="parallel_processing_complete",
                description=f"Parallel processing complete - succeeded: {len(successful_tables)}, failed: {len(failed_tables)}",
                details={
                    'successful_tables': successful_tables,
                    'failed_tables': failed_tables,
                    'total_tables': len(context.target_tables),
                    'concurrent_limit': self.max_concurrent_tables,
                    'results': [r for r in results if not isinstance(r, Exception)]
                }
            )
            context.step_outputs.append(parallel_step)
            
            self.logger.info(f"Parallel processing complete - succeeded: {len(successful_tables)}, failed: {len(failed_tables)}")
            
        except Exception as e:
            self.logger.error(f"Parallel processing failed: {e}")
            raise
    
    async def _finalize_parallel_processing(self, context: Doc2DBContext):
        """Finalize parallel processing results."""
        total_snapshots = len(context.all_snapshots)
        total_violations = sum(len(v) for v in context.all_violations.values())
        total_fixes = sum(len(f) for f in context.all_fixes.values())
        
        self.logger.info(f'All tables processed - snapshots:{total_snapshots}, violations:{total_violations}, fixes:{total_fixes}')
        
        DataTransferUtils.transfer_processing_results(context)
        
        self._sync_snapshots_to_context(context)
        
        self._setup_result_context(context)
        
        context.current_state = Doc2DBProcessingState.COMPLETED
        
        completion_step = StepUtils.create_completion_step(context)
        completion_step['details']['processing_mode'] = 'parallel'
        completion_step['details']['concurrent_tables'] = self.max_concurrent_tables
        context.step_outputs.append(completion_step)
        
        DataTransferUtils.save_final_snapshots(context)
        
        await self.broadcaster.emit_simple_signal(
            SignalType.PROCESSING_COMPLETE,
            data={
                'context': context.to_dict(),
                'processing_mode': 'parallel',
                'concurrent_tables': self.max_concurrent_tables
            },
            correlation_id=context.run_id
        )


def create_parallel_orchestrator(max_iterations: int = 3, max_concurrent_tables: int = 3) -> ParallelSignalDrivenOrchestrator:
    """Create a parallel signal-driven orchestrator."""
    return ParallelSignalDrivenOrchestrator(max_iterations=max_iterations, max_concurrent_tables=max_concurrent_tables)


async def run_parallel_signal_orchestrator(context: Doc2DBContext, max_concurrent_tables: int = 3) -> Doc2DBContext:
    """Run the parallel signal-driven orchestrator."""
    orchestrator = create_parallel_orchestrator(max_concurrent_tables=max_concurrent_tables)
    return await orchestrator.process_with_signals(context)
