"""Unified signal-driven orchestrator module."""

from .context import Doc2DBContext, Doc2DBProcessingState, create_doc2db_context
from .unified_orchestrator import (
    UnifiedSignalDrivenOrchestrator,
    create_unified_orchestrator,
    run_unified_signal_orchestrator
)
from .signal_components import SignalComponentManager, SignalAwareExtractor, SignalAwareVerifier, SignalAwareFixer
from .signal_handlers import OrchestratorSignalHandler, SignalHandlerMixin, TableProcessingWaiter
from .utils import SchemaUtils, DocumentUtils, SignalUtils, StepUtils, DataTransferUtils, DebugUtils
from .memory_operations import MemoryOperationsMixin, MemoryQueryMixin

Doc2DBOrchestrator = UnifiedSignalDrivenOrchestrator

def create_signal_driven_orchestrator(max_iterations: int = 3) -> UnifiedSignalDrivenOrchestrator:
    """Create a unified signal-driven orchestrator."""
    return create_unified_orchestrator(max_iterations=max_iterations)

def create_doc2db_context_with_signals(run_id: str, table_name: str, schema: dict, 
                                     documents: list, nl_prompt: str, io_manager,
                                     user_query: str = "", model: str = "gpt-4o",
                                     document_mode: str = "single") -> Doc2DBContext:
    """Create a Doc2DB context with signal system support.
    
    Args:
        document_mode: Document mode, "single" (process documents one by one) or "multi" (process concatenated documents)
    """
    return create_doc2db_context(
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

async def run_orchestrator(context: Doc2DBContext) -> Doc2DBContext:
    """Run the unified signal-driven orchestrator."""
    return await run_unified_signal_orchestrator(context)

__all__ = [
    'UnifiedSignalDrivenOrchestrator', 'Doc2DBOrchestrator', 'Doc2DBContext', 'Doc2DBProcessingState',
    'SignalComponentManager', 'SignalAwareExtractor', 'SignalAwareVerifier', 'SignalAwareFixer',
    'create_unified_orchestrator', 'create_signal_driven_orchestrator',
    'create_doc2db_context', 'create_doc2db_context_with_signals',
    'run_unified_signal_orchestrator', 'run_orchestrator'
]
