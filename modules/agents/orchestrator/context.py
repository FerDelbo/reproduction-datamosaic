"""Doc2DB processing context and state definitions."""
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum

from ...core.io import IOManager
from ...memory import TableSnapshot, Violation, Fix


class Doc2DBProcessingState(Enum):
    """Doc2DB processing state enumeration."""
    INIT = "init"
    ANALYZING = "analyzing"                   # Analysis phase - identify all tables to process
    EXTRACTING = "extracting"                 # Single-table extraction phase
    VERIFYING = "verifying"                   # Single-table verification phase
    FIXING = "fixing"                         # Single-table fixing phase
    MULTI_TABLE_VERIFYING = "multi_table_verifying"  # Multi-table verification phase
    FINALIZING = "finalizing"                 # Finalization phase
    COMPLETED = "completed"                   # Completed
    FAILED = "failed"                         # Failed


@dataclass 
class Doc2DBContext:
    """Doc2DB processing context."""
    run_id: str
    table_name: str
    schema: Dict[str, Any]
    documents: List[str]
    nl_prompt: str
    io_manager: IOManager
    
    user_query: str = ""              # User query/requirement
    analysis_steps: List[Dict] = None # Analysis steps
    current_step: int = 0             # Current execution step
    step_results: Dict = None         # Step execution results
    language: str = "chinese"         # Detected language
    model: str = "gpt-4o"            # LLM model used for processing
    
    document_mode: str = "single"     # Document mode: "single" (one document) or "multi" (concatenated documents)
    
    target_tables: List[str] = None                       # Names of tables to process
    entity_tables: List[str] = None                       # Entity tables
    relation_tables: List[str] = None                 # Relation tables
    current_table_index: int = 0                          # Index of the table being processed
    all_snapshots: Dict[str, TableSnapshot] = None       # Snapshots of all tables
    all_violations: Dict[str, List[Violation]] = None    # Single-table violations of all tables
    all_fixes: Dict[str, List[Fix]] = None               # Fix records of all tables
    multi_table_violations: List[Violation] = None       # Multi-table verification violations
    
    current_state: Doc2DBProcessingState = Doc2DBProcessingState.INIT
    iteration: int = 0
    max_iterations: int = 3
    
    progress: Dict[str, Any] = None   # Progress information
    step_outputs: List[Dict] = None   # Output of each step
    
    signal_history: List[Dict] = None # Signal history
    correlation_ids: Dict[str, str] = None  # Correlation ID mapping
    
    snapshots: List[TableSnapshot] = None
    violations: List[Violation] = None
    fixes: List[Fix] = None
    
    def __post_init__(self):
        if self.analysis_steps is None:
            self.analysis_steps = []
        if self.step_results is None:
            self.step_results = {}
        if self.progress is None:
            self.progress = {}
        if self.step_outputs is None:
            self.step_outputs = []
        if self.target_tables is None:
            self.target_tables = []
        if self.entity_tables is None:
            self.entity_tables = []
        if self.relation_tables is None:
            self.relation_tables = []
        if self.all_snapshots is None:
            self.all_snapshots = {}
        if self.all_violations is None:
            self.all_violations = {}
        if self.all_fixes is None:
            self.all_fixes = {}
        if self.multi_table_violations is None:
            self.multi_table_violations = []
        if self.signal_history is None:
            self.signal_history = []
        if self.correlation_ids is None:
            self.correlation_ids = {}
        if self.snapshots is None:
            self.snapshots = []
        if self.violations is None:
            self.violations = []
        if self.fixes is None:
            self.fixes = []
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the context to a dictionary."""
        return {
            'run_id': self.run_id,
            'table_name': self.table_name,
            'schema': self.schema,
            'documents': self.documents,
            'nl_prompt': self.nl_prompt,
            'user_query': self.user_query,
            'analysis_steps': self.analysis_steps,
            'current_step': self.current_step,
            'step_results': self.step_results,
            'language': self.language,
            'model': self.model,
            'document_mode': self.document_mode,
            'target_tables': self.target_tables,
            'current_table_index': self.current_table_index,
            'current_state': self.current_state.value,
            'iteration': self.iteration,
            'max_iterations': self.max_iterations,
            'progress': self.progress,
            'step_outputs': self.step_outputs,
            'signal_history': self.signal_history,
            'correlation_ids': self.correlation_ids,
            'snapshots_count': len(self.snapshots) if self.snapshots else 0,
            'violations_count': len(self.violations) if self.violations else 0,
            'fixes_count': len(self.fixes) if self.fixes else 0,
            'all_snapshots_count': len(self.all_snapshots) if self.all_snapshots else 0,
            'all_violations_count': sum(len(v) for v in self.all_violations.values()) if self.all_violations else 0,
            'all_fixes_count': sum(len(f) for f in self.all_fixes.values()) if self.all_fixes else 0,
            'multi_table_violations_count': len(self.multi_table_violations) if self.multi_table_violations else 0
        }


def create_doc2db_context(run_id: str, table_name: str, schema: Dict[str, Any], 
                         documents: List[str], nl_prompt: str, io_manager: IOManager,
                         user_query: str = "", model: str = "gpt-4o", 
                         document_mode: str = "single") -> Doc2DBContext:
    """Create a Doc2DB processing context.
    
    Args:
        document_mode: Document mode, "single" (process documents one by one) or "multi" (process concatenated documents)
    """
    return Doc2DBContext(
        run_id=run_id,
        table_name=table_name,
        schema=schema,
        documents=documents,
        nl_prompt=nl_prompt,
        io_manager=io_manager,
        user_query=user_query,
        model=model,
        document_mode=document_mode,
        max_iterations=3
    )
