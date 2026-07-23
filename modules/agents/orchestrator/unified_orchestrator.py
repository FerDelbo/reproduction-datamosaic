"""Unified signal-driven coordinator - refactored version"""
import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import List, Any, Optional

from .context import Doc2DBContext, Doc2DBProcessingState, create_doc2db_context
from .signal_handlers import OrchestratorSignalHandler, SignalHandlerMixin, TableProcessingWaiter
from .utils import SchemaUtils, DocumentUtils, SignalUtils, StepUtils, DataTransferUtils, DebugUtils
from .memory_operations import MemoryOperationsMixin, MemoryQueryMixin
from .signal_coordinator import SignalCoordinator, TableLifecycleState

from ...memory import TableSnapshot, Violation, Fix
from .signal_components import SignalComponentManager
from ...signals.core import SignalBroadcaster, SignalReceiver, BroadcastHub, SignalType
from ...utils.orchestrator_logger import OrchestratorLogger


class UnifiedSignalDrivenOrchestrator(SignalHandlerMixin, MemoryOperationsMixin, MemoryQueryMixin):
    """Unified signal-driven coordinator - focused on signal communication and broadcast mechanisms"""
    
    def __init__(self, max_iterations: int = 3):
        MemoryOperationsMixin.__init__(self)
        MemoryQueryMixin.__init__(self)
        
        self.max_iterations = max_iterations
        self.logger = logging.getLogger('unified.orchestrator')
        
        self.detailed_logger = None
        
        self.broadcaster = SignalBroadcaster('unified_orchestrator')
        self.receiver = SignalReceiver('unified_orchestrator')
        self.hub = BroadcastHub.get_instance()
        
        self.coordinator = SignalCoordinator(self.broadcaster, default_timeout=600.0)
        
        self.signal_component_manager = None
        
        self.schema_utils = SchemaUtils()
        self.document_utils = DocumentUtils(self.logger)
        self.table_waiter = TableProcessingWaiter(self.logger)
        self.table_waiter.orchestrator = self
        
        self.current_context: Optional[Doc2DBContext] = None
        self.processing_tasks: List[Any] = []
        
        self._setup_basic_signal_system()
        

    
    def _setup_basic_signal_system(self):
        """Set up the basic signaling system (excluding components that require memory_manager)"""
        self.broadcaster.set_hub(self.hub)
        
        self.hub.register_receiver(self.receiver)
        
        self._setup_orchestrator_signal_handlers()
        

    
    def _setup_signal_components(self):
        """Set up the signal component (called after memory_manager is initialized)"""
        if self.signal_component_manager is None:
            self.signal_component_manager = SignalComponentManager(
                memory_manager=self.memory_manager,
                orchestrator=self,
                coordinator=self.coordinator
            )
            
            self.signal_component_manager.setup_receivers(self.hub)
            

    
    def _setup_orchestrator_signal_handlers(self):
        """Set the coordinator's signal handler"""
        handler = OrchestratorSignalHandler(self)
        self.receiver.add_handler(handler)
    
    async def process_with_signals(self, context: Doc2DBContext) -> Doc2DBContext:
        """Using the signal system to handle Doc2DB processes"""
        self.logger.info(f"Starting unified signal processing, run ID: {context.run_id}")
        
        self.current_context = context
        context.current_state = Doc2DBProcessingState.INIT
        
        context.coordinator = self.coordinator
        
        self.detailed_logger = OrchestratorLogger(context.run_id)
        
        start_step = StepUtils.create_start_step(context)
        context.step_outputs.append(start_step)
        
        try:
            await self.initialize_memory(context)
            
            self._setup_signal_components()
            
            await self._start_signal_processing()
            
            await self._run_signal_driven_pipeline(context)
            
            if context.current_state == Doc2DBProcessingState.COMPLETED:
                await self.persist_results(context)
                self.logger.info("Signal-driven processing completed successfully")
            else:
                self.logger.error("Signal-driven processing failed")
                
        except Exception as e:
            self.logger.error(f"Signal-driven processing exception: {e}")
            context.current_state = Doc2DBProcessingState.FAILED
            
            error_step = StepUtils.create_error_step(context, e)
            context.step_outputs.append(error_step)
        
        finally:
            await self._stop_signal_processing()
        
        return context
    
    async def _start_signal_processing(self):
        """Start signal processing"""
        self.processing_tasks = []
        
        self.coordinator.start()
        component_tasks = await self.signal_component_manager.start_all()
        self.processing_tasks.extend(component_tasks)
        orchestrator_task = asyncio.create_task(self.receiver.start_processing())
        self.processing_tasks.append(orchestrator_task)
        
        self.logger.info("Signal processing system started")
        await asyncio.sleep(0.1)
    
    async def _stop_signal_processing(self):
        """Stop signal processing"""
        await self.coordinator.stop()
        self.signal_component_manager.stop_all()
        self.receiver.stop_processing()
        for task in self.processing_tasks:
            if not task.done():
                task.cancel()
        
        await asyncio.gather(*self.processing_tasks, return_exceptions=True)
        self.logger.info("Signal processing system stopped")
    
    async def _run_signal_driven_pipeline(self, context: Doc2DBContext):
        """Run a signal-driven processing pipeline"""
        await self.broadcaster.emit_simple_signal(
            SignalType.PROCESSING_START,
            data={'context': context.to_dict()},
            correlation_id=context.run_id
        )
        
        await self._signal_analyze_tables(context)
        
        for table_name in context.target_tables:
            is_relation = table_name in context.relation_tables
            self.coordinator.init_table_tracker(
                table_name=table_name,
                total_batches=1,
                is_relation_table=is_relation,
                max_iterations=self.max_iterations
            )
            self.logger.debug(f'Initialized table tracker: {table_name}')
        
        self.logger.info(f'Staged extraction strategy: entity tables ({len(context.entity_tables)}) -> relation tables ({len(context.relation_tables)})')
        if context.entity_tables:
            self.logger.info(f'Phase 1: extracting {len(context.entity_tables)} entity tables')
            
            for table_name in context.entity_tables:
                context.current_table_index = context.target_tables.index(table_name)
                
                await self._signal_extract_data(context, table_name, is_relation_table=False)
                
                processing_result = await self.table_waiter.wait_for_table_processing_complete(context, table_name)
                
                if not processing_result:
                    self.logger.warning(f'Entity table {table_name} timed out or failed, continuing to next table')
            
            self.logger.info(f'Phase 1 complete: all entity tables extracted')
        
        if context.relation_tables:
            self.logger.info(f'Phase 2: extracting {len(context.relation_tables)} relation tables')
            
            for table_name in context.relation_tables:
                context.current_table_index = context.target_tables.index(table_name)
                
                await self._signal_extract_data(context, table_name, is_relation_table=True)
                
                processing_result = await self.table_waiter.wait_for_table_processing_complete(context, table_name)
                
                if not processing_result:
                    self.logger.warning(f'Relation table {table_name} timed out or failed, continuing to next table')
            
            self.logger.info(f'Phase 2 complete: all relation tables extracted')
        
        await self._wait_for_all_batches_complete(context)
        await self._wait_for_all_tables_processing_complete(context)
        await self._signal_multi_table_verify(context)
        
        total_violations = sum(len(v) for v in context.all_violations.values())
        total_fixes = sum(len(f) for f in context.all_fixes.values())
        self.logger.info(f'All tables processed - snapshots: {len(context.all_snapshots)}, violations: {total_violations}, fixes: {total_fixes}')
        
        DataTransferUtils.transfer_processing_results(context)
        self._sync_snapshots_to_context(context)
        self._setup_result_context(context)
        context.current_state = Doc2DBProcessingState.COMPLETED
        completion_step = StepUtils.create_completion_step(context)
        context.step_outputs.append(completion_step)
        DataTransferUtils.save_final_snapshots(context)
        await self.broadcaster.emit_simple_signal(
            SignalType.PROCESSING_COMPLETE,
            data={'context': context.to_dict()},
            correlation_id=context.run_id
        )
    
    async def _signal_analyze_tables(self, context: Doc2DBContext):
        """Analyzing table structures through signals"""
        if isinstance(context.schema, str):
            context.schema = json.loads(context.schema)
        all_tables = self.schema_utils.extract_table_names_from_schema(context.schema)
        
        if context.table_name and context.table_name.strip() and context.table_name != 'orders':
            if context.table_name not in all_tables:
                self.logger.warning(f'Specified table {context.table_name} not in schema, will process all tables')
                target_tables = all_tables
            else:
                target_tables = [context.table_name]
                self.logger.info(f'Processing specified table only: {context.table_name}')
        else:
            target_tables = all_tables
            if len(all_tables) > 1:
                self.logger.info(f'Will process all {len(all_tables)} tables: {", ".join(all_tables)}')
        
        context.target_tables = target_tables
        
        table_classification = self.schema_utils.classify_tables_by_type(context.schema)
        
        all_entity_tables = table_classification['entity_tables']
        all_relation_tables = table_classification['relation_tables']
        
        context.entity_tables = [t for t in all_entity_tables if t in target_tables]
        context.relation_tables = [t for t in all_relation_tables if t in target_tables]
        
        for rel_table in context.relation_tables:
            rel_extraction_config = self._get_relation_extraction_config(context.schema, rel_table)
            if rel_extraction_config and rel_extraction_config.get('enabled'):
                ref_tables = rel_extraction_config.get('reference_tables', [])
                ref_table_names = [ref.get('table') for ref in ref_tables if ref.get('table')]
                if ref_table_names:
                    self.logger.info(f'Relation table {rel_table} will use reference tables: {", ".join(ref_table_names)}')
        
        self.logger.info(f'Table analysis complete: {len(target_tables)} tables (entity: {len(context.entity_tables)}, relation: {len(context.relation_tables)})')
        
        await self.broadcaster.emit_simple_signal(
            SignalType.ANALYSIS_COMPLETE,
            data={
                'target_tables': target_tables,
                'entity_tables': context.entity_tables,
                'relation_tables': context.relation_tables,
                'context': context
            },
            correlation_id=context.run_id
        )
    
    def _get_relation_extraction_config(self, schema: dict, table_name: str) -> dict:
        """Get the relation_extraction configuration of the specified table from the schema
        
        Args:
            schema: database schema
            table_name: table name
            
        Returns:
            relation_extraction configuration dictionary, returns None if it does not exist"""
        tables = schema.get('tables', [])
        for table in tables:
            if table.get('name') == table_name:
                return table.get('relation_extraction')
        return None
    
    async def _signal_extract_data(self, context: Doc2DBContext, table_name: str, is_relation_table: bool = False):
        """Request data extraction through signals (supports batch processing)
        
        Args:
            context: processing context
            table_name: table name
            is_relation_table: Whether it is a relational table. If True, all extracted entity table data will be included
            
        Process:
        1. Check whether it is multi-document mode
        2. If yes, divide into multiple batches
        3. Execute each batch in order: locate → extract → verify → fix
        4. Finally merge the results of all batches"""
        table_specific_schema = self.schema_utils.extract_table_specific_schema(context.schema, table_name)
        
        if not table_specific_schema:
            self.logger.warning(f'Schema not found for table {table_name}, using full schema')
            table_specific_schema = context.schema
        
        document_mode = context.document_mode if hasattr(context, 'document_mode') else "single"
        
        document_sources = self._get_document_sources_from_schema(context.schema, table_name)
        
        from .utils import DocumentUtils
        document_utils = DocumentUtils()
        
        if document_sources:
            self.logger.info('Table %s has %d configured document sources', table_name, len(document_sources))
            text_contents = self._load_documents_from_sources(document_sources, context)
            self.logger.info(f'Loaded {len(text_contents)} documents from document_sources')
        else:
            text_contents = document_utils.convert_documents_to_text(context.documents)
        
        self.logger.info(f'Table {table_name} - document_mode={document_mode}, document count={len(text_contents)}')
        
        if document_mode == "multi":
            await self._signal_extract_data_in_batches(
                context, table_name, table_specific_schema, text_contents, is_relation_table
            )
        else:
            await self._signal_extract_full_document(context, table_name, table_specific_schema, is_relation_table)
    
    async def _signal_extract_data_in_batches(self, context: Doc2DBContext, table_name: str, 
                                              table_specific_schema: dict, text_contents: List[str],
                                              is_relation_table: bool = False):
        """Process multiple document extraction in batches
        
        Args:
            context: processing context
            table_name: table name
            table_specific_schema: table schema
            text_contents: all document contents
            is_relation_table: whether it is a relational table"""
        self.logger.info(f'Table {table_name} - processing merged documents in chunks')
        
        document_names = []
        if context and hasattr(context, 'documents') and context.documents:
            import os
            document_names = [os.path.basename(doc) for doc in context.documents]
        
        merged_text = self._merge_documents_langchain_style(text_contents, document_names)
        chunks = self._split_text_into_chunks_langchain_style(merged_text)
        batches = []
        for chunk_index, chunk in enumerate(chunks):
            batches.append({
                'documents': [chunk],
                'document_indices': [0],
                'document_sub_indices': [chunk_index],
                'total_chars': len(chunk),
                'total_words': self._estimate_word_count(chunk)
            })
        
        
        self.logger.info(f'Table {table_name} split into {len(batches)} batches')
        
        tracker = self.coordinator.get_table_tracker(table_name)
        if tracker:
            tracker.total_batches = len(batches)
            self.logger.debug(f'Updated batch count for table {table_name}: {len(batches)}')
        
        for batch_index in range(1, len(batches) + 1):
            self.coordinator.init_batch_tracker(table_name, batch_index, len(batches))
        
        if not hasattr(context, 'batch_tracking'):
            context.batch_tracking = {}
        
        context.batch_tracking[table_name] = {
            'total_batches': len(batches),
            'completed_batches': 0,
            'snapshots': []
        }
        
        for batch_index, batch in enumerate(batches, 1):
            batch_document_indices = batch.get("document_indices", [])
            batch_document_sub_indices = batch.get("document_sub_indices", [0] * len(batch_document_indices))
            batch_document_names = []
            
            if context and hasattr(context, 'documents') and context.documents:
                import os
                for idx, sub_idx in zip(batch_document_indices, batch_document_sub_indices):
                    if idx < len(context.documents):
                        base_name = os.path.basename(context.documents[idx])
                        if sub_idx > 0:
                            name_parts = base_name.rsplit('.', 1)
                            if len(name_parts) == 2:
                                doc_name = f"{name_parts[0]} (part{sub_idx+1}).{name_parts[1]}"
                            else:
                                doc_name = f"{base_name} (part{sub_idx+1})"
                        else:
                            doc_name = base_name
                        batch_document_names.append(doc_name)
                    else:
                        batch_document_names.append(f"doc_{idx+1}")
            else:
                batch_document_names = [f"doc_{idx+1}" for idx in batch_document_indices]
            
            self.logger.info(
                f'Starting Batch {batch_index}/{len(batches)}: '
                f'{len(batch["documents"])} documents ({", ".join(batch_document_names)}), '
                f'{batch.get("total_words", 0)} words total'
            )
            
            await self._signal_extract_batch(
                context=context,
                table_name=table_name,
                table_specific_schema=table_specific_schema,
                batch_documents=batch["documents"],
                batch_document_names=batch_document_names,
                batch_index=batch_index,
                total_batches=len(batches),
                is_relation_table=is_relation_table
            )
            
            batch_timeout = 900.0
            batch_success = await self.coordinator.wait_batch_final(
                table_name, batch_index, timeout=batch_timeout
            )
            
            if not batch_success:
                self.logger.warning(
                    f'Batch {batch_index} timed out or failed, force marking final and continuing to next batch'
                )
                self.coordinator.mark_batch_final(table_name, batch_index)
            
            await asyncio.sleep(0.5)
    
    def _estimate_word_count(self, text_content: str) -> int:
        """Estimate the number of words in the text (number of Chinese characters + number of English words)
        
        Args:
            text_content: text content
            
        Returns:
            int: estimated number of words"""
        if not text_content:
            return 0
        
        import re
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text_content))
        english_words = len(re.findall(r'[a-zA-Z]+', text_content))
        return chinese_chars + english_words
    
    def _get_document_sources_from_schema(self, schema: dict, table_name: str) -> Optional[List[str]]:
        """Get the document_sources configuration of the table from the schema
        
        Args:
            schema: database schema definition
            table_name: table name
            
        Returns:
            document_sources list, returns None if not configured"""
        tables = schema.get('tables', [])
        for table in tables:
            if table.get('name') == table_name:
                relation_config = table.get('relation_extraction', {})
                if relation_config and relation_config.get('enabled', False):
                    document_sources = relation_config.get('document_sources', [])
                    if document_sources:
                        return document_sources
        return None
    
    def _load_documents_from_sources(self, document_sources: List[str], context: Doc2DBContext) -> List[str]:
        """Load document content from configured document_sources
        
        Args:
            document_sources: list of document paths
            context: processing context (used to resolve relative paths)
            
        Returns:
            Document content list"""
        from pathlib import Path
        text_contents = []
        
        project_root = self._find_project_root()
        
        for doc_source in document_sources:
            try:
                doc_path = Path(doc_source)
                
                if doc_path.is_absolute():
                    if doc_path.exists():
                        with open(doc_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                            text_contents.append(content)
                            self.logger.info(f'  Loaded document: {doc_path.name} ({len(content)} chars)')
                    else:
                        self.logger.warning(f'  Document not found: {doc_path}')
                else:
                    if project_root:
                        full_path = project_root / doc_source
                        if full_path.exists():
                            with open(full_path, 'r', encoding='utf-8') as f:
                                content = f.read()
                                text_contents.append(content)
                                self.logger.info(f'  Loaded document: {full_path.name} ({len(content)} chars)')
                        else:
                            self.logger.warning(f'  Document not found: {full_path}')
                    else:
                        self.logger.warning(f'  Cannot resolve relative path: {doc_source} (project root not found)')
            except Exception as e:
                self.logger.error(f'  Failed to load document {doc_source}: {e}')
        
        return text_contents
    
    def _find_project_root(self) -> Optional[Path]:
        """Find the project root directory
        
        Locate the project root directory by finding the parent directory containing feature directories such as backend/, dataset/, etc.
        
        Returns:
            Path object for the project root directory, or None if not found"""
        from pathlib import Path
        
        current = Path(__file__).resolve()
        
        for _ in range(10):
            parent = current.parent
            
            if (parent / 'backend').exists() and (parent / 'dataset').exists():
                return parent
            
            if parent == current:
                break
            
            current = parent
        
        return None
    
    def _split_text_into_chunks_langchain_style(self, text: str, 
                                                chunk_size: int = 100000, 
                                                chunk_overlap: int = 500) -> List[str]:
        """Split text into multiple chunks
        
        Strategy:
        1. If the text length <= chunk_size, do not divide into chunks
        2. Otherwise, divide it into chunks according to chunk_size, with overlap
        3. Break at paragraph boundaries first, then at sentence boundaries
        
        Args:
            text: text to be split
            chunk_size: The size of each chunk (number of characters, default 100000)
            chunk_overlap: overlap between chunks (number of characters, default 500)
            
        Returns:
            List[str]: split chunk list"""
        if len(text) <= chunk_size:
            self.logger.info(f"  Text length {len(text)} chars, no chunking needed")
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + chunk_size
            
            if end < len(text):
                paragraph_break = text.rfind('\n\n', start, end)
                if paragraph_break > start + chunk_size // 2:
                    end = paragraph_break + 2
                else:
                    sentence_break = max(
                        text.rfind('。', start, end),
                        text.rfind('！', start, end),
                        text.rfind('？', start, end),
                        text.rfind('.', start, end),
                        text.rfind('!', start, end),
                        text.rfind('?', start, end)
                    )
                    if sentence_break > start + chunk_size // 2:
                        end = sentence_break + 1
            
            chunk = text[start:end]
            chunks.append(chunk)
            
            start = end - chunk_overlap if end < len(text) else end
        
        self.logger.info(f"  Text split into {len(chunks)} chunks")
        for i, chunk in enumerate(chunks, 1):
            self.logger.info(f"   Chunk {i}: {len(chunk)} chars")
        
        return chunks
    
    def _merge_documents_langchain_style(self, text_contents: List[str], 
                                        document_names: List[str] = None) -> str:
        """Merge content from multiple documents
        
        Args:
            text_contents: document content list
            document_names: list of document names (optional)
            
        Returns:
            str: merged text"""
        if not document_names:
            document_names = [f"doc_{i+1}" for i in range(len(text_contents))]
        
        merged_content = []
        
        for i, (content, doc_name) in enumerate(zip(text_contents, document_names), 1):
            if content:
                merged_content.append(f"=== Document {i}: {doc_name} ===\n")
                merged_content.append(content)
                merged_content.append(f"\n=== End of Document {i} ===\n\n")
        
        final_content = "\n".join(merged_content)
        self.logger.info(f"  Merge complete: {len(text_contents)} documents -> {len(final_content)} chars")
        return final_content
    
    def _split_documents_into_batches(self, text_contents: List[str], context) -> List[dict]:
        """Split documents into multiple batches - smart batching strategy
        
        Core strategy:
        1. Prioritize document integrity: the same document will not be split into different batches
        2. Ultra-long document processing: When a single document exceeds the threshold, it will be treated as a batch alone (will be split and processed later)
        3. Optimal filling: Try to make each batch contain more complete documents without exceeding the limit.
        4. Double limit: consider both the number of words and the number of characters. If either exceeds the limit, the batch will be divided.
        
        Args:
            text_contents: document content list
            context: processing context
        
        Returns:
            List[dict]: Each dict contains {
                'documents': [...], # Text content list
                'document_indices': [...], # Corresponding original document index
                'total_chars': int,
                'total_words': int
            }"""
        MAX_BATCH_WORDS = 50000
        MAX_BATCH_CHARS = 100000
        MAX_SINGLE_DOC_WORDS = 50000
        MAX_SINGLE_DOC_CHARS = 100000
        
        batches = []
        current_batch = []
        current_batch_indices = []
        current_chars = 0
        current_words = 0
        
        self.logger.info(f'Starting smart batching: {len(text_contents)} documents total')
        
        processed_documents = []
        for i, doc_content in enumerate(text_contents):
            doc_chars = len(doc_content)
            doc_words = self._estimate_word_count(doc_content)
            
            self.logger.debug(f'Document {i+1}: {doc_chars} chars, {doc_words} words')
            
            if doc_words > MAX_SINGLE_DOC_WORDS or doc_chars > MAX_SINGLE_DOC_CHARS:
                self.logger.info(f'  Document {i+1} oversized ({doc_chars} chars, {doc_words} words), splitting required')
                sub_documents = self._split_long_document(doc_content, max_words=MAX_SINGLE_DOC_WORDS, max_chars=MAX_SINGLE_DOC_CHARS)
                self.logger.info(f'  Split into {len(sub_documents)} sub-documents')
                for sub_idx, sub_doc in enumerate(sub_documents):
                    processed_documents.append((sub_doc, i, sub_idx))
            else:
                processed_documents.append((doc_content, i, 0))
        
        self.logger.info(f'Document preprocessing complete: {len(text_contents)} original -> {len(processed_documents)} processed')
        
        current_batch_sub_indices = []
        
        for doc_content, original_index, sub_index in processed_documents:
            doc_chars = len(doc_content)
            doc_words = self._estimate_word_count(doc_content)
            
            if current_batch and (
                current_words + doc_words > MAX_BATCH_WORDS or
                current_chars + doc_chars > MAX_BATCH_CHARS
            ):
                self.logger.debug(f'Batch full ({current_chars} chars, {current_words} words), starting new batch')
                batches.append({
                    'documents': current_batch,
                    'document_indices': current_batch_indices,
                    'document_sub_indices': current_batch_sub_indices,
                    'total_chars': current_chars,
                    'total_words': current_words
                })
                current_batch = []
                current_batch_indices = []
                current_batch_sub_indices = []
                current_chars = 0
                current_words = 0
            
            current_batch.append(doc_content)
            current_batch_indices.append(original_index)
            current_batch_sub_indices.append(sub_index)
            current_chars += doc_chars
            current_words += doc_words
        
        if current_batch:
            batches.append({
                'documents': current_batch,
                'document_indices': current_batch_indices,
                'document_sub_indices': current_batch_sub_indices,
                'total_chars': current_chars,
                'total_words': current_words
            })
        self.logger.info(f'Batching complete: {len(batches)} batches total')
        for i, batch in enumerate(batches, 1):
            self.logger.info(
                f'  Batch {i}: {len(batch["documents"])} documents, '
                f'{batch["total_words"]} words, {batch["total_chars"]} chars'
            )
        
        return batches
    
    def _split_long_document(self, document: str, max_words: int = 40000, max_chars: int = 150000) -> List[str]:
        """Split extremely long documents into multiple subdocuments by paragraph boundaries
        
        Strategy:
        - Split by paragraph boundaries (maintain paragraph integrity)
        - There is a 10% overlap area between adjacent sub-documents to avoid loss of boundary information
        - Each subdocument does not exceed the specified number of words and characters (if any exceeds the limit, it will be split)
        
        Args:
            document: original long document
            max_words: Maximum number of words per subdocument (default 40000)
            max_chars: Maximum number of characters per subdocument (default 150000)
            
        Returns:
            List[str]: Split subdocument list"""
        import re
        
        paragraphs = re.split(r'\n\s*\n', document)
        
        sub_documents = []
        current_sub_doc = []
        current_words = 0
        current_chars = 0
        overlap_ratio = 0.1
        
        self.logger.debug(f'Splitting oversized document: {len(paragraphs)} paragraphs, target {max_words} words / {max_chars} chars per sub-document')
        
        for para in paragraphs:
            para_words = self._estimate_word_count(para)
            para_chars = len(para)
            
            if (current_words + para_words > max_words or current_chars + para_chars > max_chars) and current_sub_doc:
                sub_doc_text = '\n\n'.join(current_sub_doc)
                sub_documents.append(sub_doc_text)
                
                overlap_words = int(current_words * overlap_ratio)
                overlap_chars = int(current_chars * overlap_ratio)
                overlap_paras = []
                overlap_word_count = 0
                overlap_char_count = 0
                
                for j in range(len(current_sub_doc) - 1, -1, -1):
                    overlap_paras.insert(0, current_sub_doc[j])
                    overlap_word_count += self._estimate_word_count(current_sub_doc[j])
                    overlap_char_count += len(current_sub_doc[j])
                    if overlap_word_count >= overlap_words or overlap_char_count >= overlap_chars:
                        break
                
                current_sub_doc = overlap_paras + [para]
                current_words = overlap_word_count + para_words
                current_chars = overlap_char_count + para_chars
            else:
                current_sub_doc.append(para)
                current_words += para_words
                current_chars += para_chars
        if current_sub_doc:
            sub_doc_text = '\n\n'.join(current_sub_doc)
            sub_documents.append(sub_doc_text)
        
        self.logger.debug(f'Document split complete: {len(sub_documents)} sub-documents')
        for i, sub_doc in enumerate(sub_documents, 1):
            sub_words = self._estimate_word_count(sub_doc)
            sub_chars = len(sub_doc)
            self.logger.debug(f'  Sub-document {i}: {sub_chars} chars, {sub_words} words')
        
        return sub_documents
    
    async def _signal_extract_batch(self, context: Doc2DBContext, table_name: str,
                                    table_specific_schema: dict, batch_documents: List[str],
                                    batch_document_names: List[str],
                                    batch_index: int, total_batches: int,
                                    is_relation_table: bool = False):
        """Send extraction signal for a single batch
        
        The documents in this batch will be processed by the locate function of EntityExtractor
        
        Args:
            context: processing context
            table_name: table name
            table_specific_schema: table schema
            batch_documents: list of document contents in batch
            batch_document_names: list of document names in batch (one-to-one correspondence with batch_documents)
            batch_index: batch index
            total_batches: total number of batches
            is_relation_table: whether it is a relational table"""
        signal_data = {
            'context': {
                'run_id': context.run_id,
                'table_name': table_name,
                'schema': table_specific_schema,
                'full_schema': context.schema,
                'text_contents': batch_documents,
                'batch_document_names': batch_document_names,
                'document_mode': 'multi',
                'nl_prompt': context.nl_prompt or context.user_query,
                'processing_context': context
            }
        }
        
        signal_data['batch_info'] = {
            'batch_index': batch_index,
            'total_batches': total_batches,
            'documents_in_batch': len(batch_documents),
            'document_names': batch_document_names
        }
        
        if is_relation_table:
            entity_snapshots = {}
            for entity_table_name in context.entity_tables:
                if entity_table_name in context.all_snapshots:
                    entity_snapshots[entity_table_name] = context.all_snapshots[entity_table_name]
            signal_data['entity_snapshots'] = entity_snapshots
            signal_data['is_relation_table'] = True
        else:
            signal_data['is_relation_table'] = False
        
        correlation_id = SignalUtils.get_correlation_id(
            context.run_id, table_name, f"extract_batch{batch_index}"
        )
        
        self.coordinator.update_batch_state(table_name, batch_index, "extracting")
        await self.broadcaster.emit_simple_signal(
            signal_type=SignalType.EXTRACTION_REQUEST,
            data=signal_data,
            correlation_id=correlation_id
        )
        
        self.logger.info(f'Batch {batch_index} extraction request sent: {table_name}')
    
    async def _signal_extract_full_document(self, context: Doc2DBContext, table_name: str,
                                           table_specific_schema: dict, is_relation_table: bool = False):
        """Send complete document extraction signal (original logic)"""
        signal_data = SignalUtils.create_extraction_signal_data(context, table_name, table_specific_schema)
        
        if is_relation_table:
            entity_snapshots = {}
            for entity_table_name in context.entity_tables:
                if entity_table_name in context.all_snapshots:
                    entity_snapshots[entity_table_name] = context.all_snapshots[entity_table_name]
            signal_data['entity_snapshots'] = entity_snapshots
            signal_data['is_relation_table'] = True
            self.logger.debug(f'Relation table {table_name} - collected data from {len(entity_snapshots)} entity tables')
        else:
            signal_data['is_relation_table'] = False
        
        correlation_id = SignalUtils.get_correlation_id(context.run_id, table_name, "extract")
        self.coordinator.update_table_state(table_name, TableLifecycleState.EXTRACTING)
        response = await self.coordinator.send_and_wait(
            signal_type=SignalType.EXTRACTION_REQUEST,
            data=signal_data,
            correlation_id=correlation_id,
            timeout=600.0
        )
        
        if response:
            self.logger.info(f'Table extraction complete: {table_name}')
            self.coordinator.update_table_state(table_name, TableLifecycleState.EXTRACTED)
        else:
            self.logger.warning(f'Table extraction timed out: {table_name}')
            self.coordinator.update_table_state(table_name, TableLifecycleState.ERROR)
    
    async def _signal_verify_data(self, table_name: str, snapshots: List[TableSnapshot], context_data: dict = None):
        """Request data validation via signal
        
        Args:
            table_name: table name
            snapshots: List of snapshots to verify
            context_data: additional context data (such as batch information)"""
        actual_table_name = table_name
        if snapshots and len(snapshots) > 0 and hasattr(snapshots[0], 'table'):
            actual_table_name = snapshots[0].table
            if actual_table_name != table_name:
                self.logger.warning(f'Table name mismatch detected! param={table_name}, snapshot={actual_table_name}, using snapshot table name')
        
        table_specific_schema = self.schema_utils.extract_table_specific_schema(self.current_context.schema, actual_table_name)
        if not table_specific_schema:
            self.logger.warning(f'Schema not found for table {actual_table_name}, using full schema')
            table_specific_schema = self.current_context.schema
        
        signal_data = SignalUtils.create_verification_signal_data(
            self.current_context, actual_table_name, table_specific_schema, snapshots
        )
        
        if context_data:
            signal_data['context'].update(context_data)
        
        timestamp = int(time.time() * 1000)
        correlation_id = f"{self.current_context.run_id}_{actual_table_name}_verify_{timestamp}"
        self.coordinator.update_table_state(actual_table_name, TableLifecycleState.VERIFYING)
        response = await self.coordinator.send_and_wait(
            signal_type=SignalType.VERIFICATION_REQUEST,
            data=signal_data,
            correlation_id=correlation_id,
            timeout=300.0
        )
        
        if response:
            self.logger.info(f'Table verification complete: {actual_table_name}')
            self.coordinator.update_table_state(actual_table_name, TableLifecycleState.VERIFIED)
            return response
        else:
            self.logger.warning(f'Table verification timed out: {actual_table_name}')
            self.coordinator.update_table_state(actual_table_name, TableLifecycleState.ERROR)
            return None
    
    async def _signal_fix_data(self, table_name: str, violations: List[Violation], snapshot: TableSnapshot, 
                               context_data: dict = None):
        """Request data repair via signal
        
        Args:
            table_name: table name
            violations: list of violations
            snapshot: snapshot
            context_data: context data, including batch_index and other information"""
        self.logger.info(f'Preparing to send fix request signal - table: {table_name}, violations: {len(violations)}')
        
        actual_table_name = table_name
        if snapshot and hasattr(snapshot, 'table'):
            actual_table_name = snapshot.table
            if actual_table_name != table_name:
                self.logger.warning(f'Table name mismatch during fix! param={table_name}, snapshot={actual_table_name}, using snapshot table name')
        
        error_count = len([v for v in violations if getattr(v, 'severity', 'warn') == 'error'])
        warn_count = len([v for v in violations if getattr(v, 'severity', 'warn') == 'warn'])
        
        self.logger.info(f'Violation stats - errors: {error_count}, warnings: {warn_count}')
        
        table_specific_schema = self.schema_utils.extract_table_specific_schema(self.current_context.schema, actual_table_name)
        if not table_specific_schema:
            self.logger.warning(f'Schema not found for table {actual_table_name}, using full schema')
            table_specific_schema = self.current_context.schema
        
        signal_data = SignalUtils.create_fixing_signal_data(
            self.current_context, actual_table_name, table_specific_schema, violations, snapshot
        )
        
        if context_data:
            if 'context' not in signal_data:
                signal_data['context'] = {}
            if 'is_batch_verification' in context_data:
                signal_data['context']['is_batch_verification'] = context_data['is_batch_verification']
            if 'batch_index' in context_data:
                signal_data['context']['batch_index'] = context_data['batch_index']
            if 'batch_total' in context_data:
                signal_data['context']['batch_total'] = context_data['batch_total']
            if 'is_warm_start' in context_data:
                signal_data['context']['is_warm_start'] = context_data['is_warm_start']
            if 'warm_start' in context_data:
                signal_data['context']['warm_start'] = context_data['warm_start']
        
        timestamp = int(time.time() * 1000)
        correlation_id = f"{self.current_context.run_id}_{actual_table_name}_fix_{timestamp}"
        
        self.coordinator.update_table_state(actual_table_name, TableLifecycleState.FIXING)
        
        response = await self.coordinator.send_and_wait(
            signal_type=SignalType.FIXING_REQUEST,
            data=signal_data,
            correlation_id=correlation_id,
            timeout=300.0
        )
        
        if response:
            self.logger.info(f'Received fix complete response - table: {actual_table_name}')
            self.coordinator.update_table_state(actual_table_name, TableLifecycleState.FIXED)
            return response
        else:
            self.logger.error(f'Fix request timed out - table: {actual_table_name}')
            self.coordinator.update_table_state(actual_table_name, TableLifecycleState.ERROR)
            return None
    
    async def _wait_for_all_batches_complete(self, context: Doc2DBContext):
        """Wait for all batches to be completed and merged
        
        Use the coordinator's batch tracking mechanism to ensure that all batches for all tables have been completed"""
        if not hasattr(context, 'batch_tracking') or not context.batch_tracking:
            return
        
        max_wait_time = 2700
        start_time = time.time()
        last_log_time = 0
        
        tables_with_batches = list(context.batch_tracking.keys())
        
        self.logger.info(f'Waiting for all batches of {len(tables_with_batches)} tables to complete')
        
        while time.time() - start_time < max_wait_time:
            all_completed = True
            pending_tables = []
            
            for table_name in tables_with_batches:
                if not self.coordinator.all_batches_completed(table_name):
                    all_completed = False
                    pending_tables.append(table_name)
            
            if all_completed:
                self.logger.info('All table batches completed')
                return
            
            elapsed = time.time() - start_time
            if elapsed - last_log_time >= 10:
                self.logger.info(
                    f'Waiting for batches: {len(pending_tables)}/{len(tables_with_batches)} tables pending, '
                    f'elapsed {elapsed:.0f}s'
                )
                last_log_time = elapsed
            
            await asyncio.sleep(0.5)
        
        self.logger.warning(f'Batch wait timed out, some tables may be incomplete')
    
    async def _wait_for_all_tables_processing_complete(self, context: Doc2DBContext):
        """Wait for all table processing to complete (including verify-fix loop and warm start)
        
        Use coordinator's table life cycle state management to ensure that all tables reach the FINAL state"""
        if not context.target_tables:
            return
        
        max_wait_time = 1800
        
        self.logger.info(f'Waiting for all tables to complete: {len(context.target_tables)} tables total')
        
        success = await self.coordinator.wait_all_tables_final(timeout=max_wait_time)
        
        if success:
            self.logger.info('All tables processing complete')
        else:
            status = self.coordinator.get_all_tables_status()
            pending = {k: v for k, v in status.items() if v != 'final'}
            
            self.logger.warning(
                f'Table processing wait timed out: {len(pending)}/{len(status)} tables incomplete'
            )
            
            for table_name, state in pending.items():
                self.logger.warning(f'  - {table_name}: {state}')
                self.coordinator.update_table_state(
                    table_name, 
                    TableLifecycleState.FINAL,
                    force=True
                )
    
    async def _load_reference_tables_for_verification(self, context: Doc2DBContext):
        """Load relation_extraction configured reference table data for validation
        
        Load and convert reference table data from file to TableSnapshot format, add to context.all_snapshots
        This way the validator can use these reference data for foreign key validation"""
        import json
        from pathlib import Path
        from ...memory import TableSnapshot, TableRow, CellData
        from ...core.ids import IdGenerator
        
        for rel_table in context.relation_tables:
            rel_config = self._get_relation_extraction_config(context.schema, rel_table)
            
            if not rel_config or not rel_config.get('enabled'):
                continue
            
            ref_tables_config = rel_config.get('reference_tables', [])
            
            for ref_config in ref_tables_config:
                ref_table_name = ref_config.get('table')
                data_source = ref_config.get('data_source')
                key_fields = ref_config.get('key_fields', [])
                
                if not ref_table_name or not data_source:
                    continue
                
                if ref_table_name in context.all_snapshots:
                    continue
                
                try:
                    data_path = Path(data_source)
                    if not data_path.is_absolute():
                        if Path.cwd().name == 'backend':
                            data_path = Path.cwd().parent / data_source
                        else:
                            data_path = Path.cwd() / data_source
                    
                    if not data_path.exists():
                        self.logger.warning(f"Reference table data file not found: {data_path}")
                        continue
                    
                    with open(data_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    if ref_table_name not in data:
                        self.logger.warning(f"Table {ref_table_name} not found in data file")
                        continue
                    
                    table_data = data[ref_table_name]
                    
                    rows = []
                    for idx, row_data in enumerate(table_data):
                        tuple_id = IdGenerator.generate_tuple_id(ref_table_name, idx, row_data)
                        cells = {}
                        
                        for field_name, field_value in row_data.items():
                            if key_fields and field_name not in key_fields:
                                continue
                            
                            cells[field_name] = CellData(
                                value=field_value,
                                evidences=[]
                            )
                        
                        rows.append(TableRow(
                            tuple_id=tuple_id,
                            cells=cells
                        ))
                    
                    snapshot = TableSnapshot(
                        run_id=context.run_id,
                        table=ref_table_name,
                        table_id=f"{ref_table_name}_{datetime.now().isoformat()}",
                        rows=rows,
                        created_at=datetime.now().isoformat()
                    )
                    
                    snapshot.processing_stage = "reference_data"
                    snapshot.stage_description = f"Reference table data loaded from {data_source}"
                    
                    context.all_snapshots[ref_table_name] = snapshot
                    
                    self.logger.info(f"Loaded reference table {ref_table_name} for verification: {len(rows)} rows (from {data_source})")
                    
                except Exception as e:
                    self.logger.error(f"Failed to load reference table {ref_table_name}: {e}")
                    continue
    
    async def _signal_multi_table_verify(self, context: Doc2DBContext):
        """Request multi-table validation and repair via signals"""
        context.multi_table_violations = []
        
        await self._load_reference_tables_for_verification(context)
        
        if not context.all_snapshots or len(context.all_snapshots) < 2:
            self.logger.debug('Fewer than 2 tables, skipping multi-table verification')
            return
        
        try:
            from ..verifier.mcp_verifier import MCPBasedVerifier
            
            verifier = MCPBasedVerifier()
            
            multi_table_violations = verifier.verify_multi_table(
                all_snapshots=context.all_snapshots,
                schema=context.schema,
                context=context
            )
            
            context.multi_table_violations = multi_table_violations
            
            self.logger.info(f'Multi-table verification complete, found {len(multi_table_violations)} cross-table violations')
            
            if hasattr(context, 'step_outputs'):
                from ...core.io import IOManager
                
                violations_by_table = self._group_violations_by_table(multi_table_violations) if multi_table_violations else {}
                
                verification_details = {
                    'tables_verified': list(context.all_snapshots.keys()),
                    'total_tables': len(context.all_snapshots),
                    'total_violations': len(multi_table_violations),
                    'violations_by_table': violations_by_table,
                    'verification_status': 'passed' if len(multi_table_violations) == 0 else 'violations_found'
                }
                
                context.step_outputs.append({
                    'step': 'multi_table_verification',
                    'step_name': 'multi_table_verification_completed',
                    'status': 'completed',
                    'description': f'Multi-table verification complete, found {len(multi_table_violations)} cross-table quality issues',
                    'details': verification_details,
                    'timestamp': datetime.now().isoformat()
                })
                
            
            if multi_table_violations:
                self.logger.info(f'Starting fix for {len(multi_table_violations)} cross-table violations...')
                
                await self._fix_multi_table_violations(context, multi_table_violations)
            
        except Exception as e:
            self.logger.error(f"Multi-table verification exception: {e}", exc_info=True)
        
        await self.broadcaster.emit_simple_signal(
            SignalType.MULTI_TABLE_VERIFICATION_COMPLETE,
            data={
                'violations': context.multi_table_violations,
                'context': context
            },
            correlation_id=f"{context.run_id}_multi_table_verify"
        )
    
    def _group_violations_by_table(self, violations):
        """Violations grouped by table"""
        grouped = {}
        for v in violations:
            table = getattr(v, 'table', 'unknown')
            if table not in grouped:
                grouped[table] = 0
            grouped[table] += 1
        return grouped
    
    async def _fix_multi_table_violations(self, context: Doc2DBContext, violations: List[Violation]):
        """Fix cross-table violations
        
        Args:
            context: processing context
            violations: list of cross-table violations"""
        from ..fixer.mcp_fixer import MCPBasedFixer
        from ...core.io import IOManager
        
        violations_by_table = {}
        for violation in violations:
            table = getattr(violation, 'table', 'unknown')
            if table not in violations_by_table:
                violations_by_table[table] = []
            violations_by_table[table].append(violation)
        
        self.logger.info(f'Grouped by table: {len(violations_by_table)} tables have cross-table violations')
        
        fixer = MCPBasedFixer()
        total_fixes = 0
        
        for table_name, table_violations in violations_by_table.items():
            if table_name not in context.all_snapshots:
                self.logger.warning(f'Table {table_name} has no snapshot, skipping fix')
                continue
            
            snapshot = context.all_snapshots[table_name]
            
            self.logger.info(f'Fixing {len(table_violations)} cross-table violations for table {table_name}')
            
            try:
                fixes = fixer.fix_batch(table_violations, snapshot, context)
                
                if fixes:
                    updated_snapshot = self._apply_fixes_to_snapshot(snapshot, fixes)
                    
                    context.all_snapshots[table_name] = updated_snapshot
                    
                    if table_name not in context.all_fixes:
                        context.all_fixes[table_name] = []
                    context.all_fixes[table_name].extend(fixes)
                    
                    total_fixes += len(fixes)
                    
                    self.logger.info(f'Table {table_name} applied {len(fixes)} cross-table fixes')
                else:
                    self.logger.warning(f'Table {table_name} generated no cross-table fixes')
                    
            except Exception as e:
                self.logger.error(f'Failed to fix cross-table violations for table {table_name}: {e}', exc_info=True)
        
        if hasattr(context, 'step_outputs'):
            context.step_outputs.append({
                'step': 'multi_table_fixing',
                'status': 'completed',
                'description': f'Cross-table violation fixes complete',
                'details': {
                    'tables_fixed': list(violations_by_table.keys()),
                    'total_violations': len(violations),
                    'total_fixes': total_fixes,
                    'fixes_by_table': {
                        table: len([f for f in context.all_fixes.get(table, []) if 'CROSS_TABLE' in getattr(f, 'id', '')])
                        for table in violations_by_table.keys()
                    }
                },
                'timestamp': datetime.now().isoformat()
            })
        
        self.logger.info(f'Cross-table violation fixes complete, applied {total_fixes} fixes total')
        
        if total_fixes > 0:
            self.logger.info('Re-verifying after cross-table fixes')
            
            from ..verifier.mcp_verifier import MCPBasedVerifier
            verifier = MCPBasedVerifier()
            
            remaining_violations = verifier.verify_multi_table(
                all_snapshots=context.all_snapshots,
                schema=context.schema,
                context=context
            )
            
            context.multi_table_violations = remaining_violations
            
            if remaining_violations:
                self.logger.warning(f'{len(remaining_violations)} cross-table violations remain after fix')
            else:
                self.logger.info('All cross-table violations fixed successfully')
    
    def _apply_fixes_to_snapshot(self, snapshot: TableSnapshot, fixes: List[Fix]) -> TableSnapshot:
        """Apply fixes to snapshots
        
        Args:
            snapshot: original snapshot
            fixes: list of fixes
            
        Returns:
            Apply the new snapshot with the fix"""
        import copy
        updated_snapshot = copy.deepcopy(snapshot)
        
        for fix in fixes:
            tuple_id = getattr(fix, 'tuple_id', '')
            attr = getattr(fix, 'attr', '')
            new_value = getattr(fix, 'new', None)
            
            for row in updated_snapshot.rows:
                if row.tuple_id == tuple_id:
                    if attr in row.cells:
                        row.cells[attr].value = new_value
                        self.logger.debug('Applied fix to tuple %s attribute %s', tuple_id, attr)
                    break
        
        return updated_snapshot
    
    async def _trigger_batch_warm_start_extraction(self, table_name: str, violations_requiring_reextraction, 
                                                    snapshot, text_contents, document_names, 
                                                    batch_index, total_batches):
        """Warm start re-extraction for a single batch
        Directly use the documents of the current batch without performing global document recognition."""
        try:
            self.logger.info(
                f' Batch {batch_index}/{total_batches} warm start: '
                f'Re-extracting using current batch documents: {document_names}'
            )
            
            signal_data = {
                'context': {
                    'run_id': self.current_context.run_id,
                    'table_name': table_name,
                    'schema': self.schema_utils.extract_table_specific_schema(
                        self.current_context.schema, table_name
                    ),
                    'full_schema': self.current_context.schema,
                    'text_contents': text_contents,
                    'batch_document_names': document_names,
                    'document_mode': 'multi',
                    'nl_prompt': self.current_context.nl_prompt or self.current_context.user_query,
                    'processing_context': self.current_context,
                    'batch_index': batch_index,
                    'batch_total': total_batches,
                    'is_batch_verification': True,
                    'is_warm_start': True,
                    'warm_start': True,
                    'previous_snapshot': snapshot.to_dict() if snapshot else None,
                    'violations': [
                        {
                            'id': v.id,
                            'tuple_id': v.tuple_id,
                            'attr': v.attr,
                            'constraint_type': v.constraint_type,
                            'description': v.description,
                            'severity': v.severity
                        }
                        for v in violations_requiring_reextraction
                    ]
                }
            }
            
            correlation_id = f"{self.current_context.run_id}_{table_name}_batch_{batch_index}_warm_start_extract"
            
            await self.broadcaster.emit_simple_signal(
                SignalType.EXTRACTION_REQUEST,
                data=signal_data,
                correlation_id=correlation_id
            )
            
            self.logger.info(f'Batch {batch_index} warm start extraction request sent: {table_name}')
            
        except Exception as e:
            self.logger.error(f'Batch {batch_index} warm start request failed: {e}', exc_info=True)
    
    async def _trigger_smart_warm_start_extraction(self, table_name: str, violations_requiring_reextraction, snapshot):
        """Trigger smart warm start re-fetching (delegated to signal_handlers for processing)
        
        Note: The checking and marking of warm_start_attempted is the responsibility of the caller (signal_handlers).
        This method is just a delegate, the actual logic is in signal_handlers.
        
         Important: Warm start also needs to support batch processing to avoid LLM call failure caused by too long documents."""
        self.logger.info(f'Running warm start re-extraction - table: {table_name}, {len(violations_requiring_reextraction)} violations')
        
        if not hasattr(self.current_context, 'warm_start_tracking'):
            self.current_context.warm_start_tracking = set()
        self.current_context.warm_start_tracking.add(table_name)
        self.logger.info(f'Warm start tracking: added {table_name}, in progress: {list(self.current_context.warm_start_tracking)}')
        
        try:
            table_specific_schema = self.schema_utils.extract_table_specific_schema(
                self.current_context.schema, table_name
            )
            if not table_specific_schema:
                table_specific_schema = self.current_context.schema
            
            relevant_documents = self._extract_relevant_documents(violations_requiring_reextraction, snapshot)
            
            self.logger.info(f'Identified {len(relevant_documents)} relevant documents from violations: {relevant_documents}')
            
            document_utils = DocumentUtils()
            if relevant_documents:
                all_documents = self.current_context.documents
                relevant_text_contents = []
                relevant_doc_names = []
                
                import os
                for doc_path in all_documents:
                    doc_basename = os.path.basename(doc_path)
                    is_relevant = False
                    for rel_doc in relevant_documents:
                        if doc_basename == rel_doc or rel_doc in doc_basename or doc_basename in rel_doc:
                            is_relevant = True
                            break
                    
                    if is_relevant:
                        text_content = document_utils.convert_documents_to_text([doc_path])
                        if text_content:
                            relevant_text_contents.extend(text_content)
                            relevant_doc_names.append(doc_basename)
                            self.logger.info(f'  Matched relevant document: {doc_basename}')
                
                if not relevant_text_contents:
                    self.logger.warning(f'No relevant documents matched, falling back to all documents')
                    warm_start_text_contents = document_utils.convert_documents_to_text(self.current_context.documents)
                    warm_start_doc_names = [os.path.basename(d) for d in self.current_context.documents]
                else:
                    warm_start_text_contents = relevant_text_contents
                    warm_start_doc_names = relevant_doc_names
                    self.logger.info(f'Warm start will process only {len(warm_start_doc_names)} relevant documents (skipping {len(all_documents) - len(warm_start_doc_names)} others)')
            else:
                self.logger.warning(f'Could not identify relevant documents from evidences, using all documents')
                warm_start_text_contents = document_utils.convert_documents_to_text(self.current_context.documents)
                warm_start_doc_names = [os.path.basename(d) for d in self.current_context.documents]
            
            total_chars = sum(len(doc) for doc in warm_start_text_contents)
            total_words = sum(self._estimate_word_count(doc) for doc in warm_start_text_contents)
            
            self.logger.info(f'WARM START document stats - table: {table_name}, documents: {len(warm_start_text_contents)}, '
                           f'total chars: {total_chars}, total words: {total_words}')
            
            MAX_BATCH_WORDS = 50000
            MAX_BATCH_CHARS = 100000
            
            if total_words > MAX_BATCH_WORDS or total_chars > MAX_BATCH_CHARS or len(warm_start_text_contents) > 2:
                self.logger.info(f'WARM START documents exceed limits, enabling batch processing')
                
                batches = self._split_documents_into_batches(warm_start_text_contents, self.current_context)
                
                self.logger.info(f'WARM START split into {len(batches)} batches')
                
                for batch_index, batch in enumerate(batches, 1):
                    batch_document_indices = batch.get("document_indices", [])
                    batch_text_contents = batch["documents"]
                    
                    batch_doc_names = []
                    for idx in batch_document_indices:
                        if idx < len(warm_start_doc_names):
                            batch_doc_names.append(warm_start_doc_names[idx])
                        else:
                            batch_doc_names.append(f"doc_{idx+1}")
                    
                    self.logger.info(
                        f'Starting WARM START Batch {batch_index}/{len(batches)}: '
                        f'{len(batch_text_contents)} documents ({", ".join(batch_doc_names)}), '
                        f'{batch.get("total_words", 0)} words, {batch.get("total_chars", 0)} chars total'
                    )
                    
                    self.coordinator.init_batch_tracker(table_name, batch_index, len(batches), is_warm_start=True)
                    
                    signal_data = {
                        'context': {
                            'run_id': self.current_context.run_id,
                            'table_name': table_name,
                            'schema': table_specific_schema,
                            'full_schema': self.current_context.schema,
                            'text_contents': batch_text_contents,  # Contains only documents for the current batch
                            'batch_document_names': batch_doc_names,
                            'document_mode': 'multi',
                            'nl_prompt': self.current_context.nl_prompt or self.current_context.user_query,
                            'processing_context': self.current_context
                        }
                    }
                    
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
                                'severity': getattr(v, 'severity', 'error'),
                                'suggested_fix': v.suggested_fix.value if hasattr(v, 'suggested_fix') and v.suggested_fix else None,
                                'detector_id': getattr(v, 'detector_id', 'unknown'),
                                'timestamp': getattr(v, 'timestamp', None)
                            } 
                            for v in violations_requiring_reextraction
                        ],
                        'batch_info': {
                            'batch_index': batch_index,  # Use original batch_index
                            'is_warm_start': True,  # Add warm start flag
                            'total_batches': len(batches),
                            'documents_in_batch': len(batch_text_contents),
                            'document_names': batch_doc_names
                        }
                    })
                    
                    correlation_id = SignalUtils.get_correlation_id(
                        self.current_context.run_id, table_name, f"warm_start_batch{batch_index}"
                    )
                    
                    await self.broadcaster.emit_simple_signal(
                        SignalType.EXTRACTION_REQUEST,
                        data=signal_data,
                        correlation_id=correlation_id
                    )
                    
                    self.logger.info(f'WARM START Batch {batch_index} extraction request sent: {table_name}')
                    
                    batch_timeout = 60.0  # Each warm start batch waits for up to 1 minute and skips if it times out.
                    
                    batch_success = await self.coordinator.wait_batch_final(
                        table_name, batch_index, is_warm_start=True, timeout=batch_timeout
                    )
                    
                    if not batch_success:
                        self.logger.warning(
                            f'WARM START Batch {batch_index} timed out (>{batch_timeout}s), '
                            f'skipping batch, force marking final and continuing'
                        )
                        self.coordinator.mark_batch_final(table_name, batch_index, is_warm_start=True)
                    
                    await asyncio.sleep(0.5)
            else:
                self.logger.info(f'WARM START documents within limits, processing directly')
                
                signal_data = {
                    'context': {
                        'run_id': self.current_context.run_id,
                        'table_name': table_name,
                        'schema': table_specific_schema,
                        'full_schema': self.current_context.schema,
                        'text_contents': warm_start_text_contents,  # Include only relevant documents
                        'batch_document_names': warm_start_doc_names,
                        'document_mode': 'multi',
                        'nl_prompt': self.current_context.nl_prompt or self.current_context.user_query,
                        'processing_context': self.current_context
                    }
                }
                
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
                            'severity': getattr(v, 'severity', 'error'),
                            'suggested_fix': v.suggested_fix.value if hasattr(v, 'suggested_fix') and v.suggested_fix else None,
                            'detector_id': getattr(v, 'detector_id', 'unknown'),
                            'timestamp': getattr(v, 'timestamp', None)
                        } 
                        for v in violations_requiring_reextraction
                    ]
                })
                
                self.logger.info(f'WARM START signal data ready: {len(violations_requiring_reextraction)} violations pending re-extraction')
                
                await self.broadcaster.emit_simple_signal(
                    SignalType.EXTRACTION_REQUEST,
                    data=signal_data,
                    correlation_id=SignalUtils.get_correlation_id(
                        self.current_context.run_id, table_name, "warm_start_extract"
                    )
                )
                
                self.logger.info(f'WARM START extraction request sent: {table_name}')
            
        except Exception as e:
            self.logger.error(f"Smart warm start extraction failed: {e}", exc_info=True)
            await self._signal_fix_data(table_name, violations_requiring_reextraction, snapshot)
    
    def _extract_relevant_documents(self, violations: List, snapshot) -> List[str]:
        """Extract relevant documents from violations (via evidences)
        
         Key function: Identify the documents belonging to the batch from the illegal evidences
        - Only the source document name where the illegal data is located is returned
        - When used in warm start, only the documents of the relevant batch will be re-extracted, not all documents
        
        Args:
            violations: list of violations
            snapshot: table snapshot
            
        Returns:
            List of related document names (for example: ['doc1.txt', 'doc2.txt'])"""
        if not violations or not snapshot or not hasattr(snapshot, 'rows'):
            return []
        
        import os
        import re
        
        relevant_docs = set()
        violation_tuple_ids = set([v.tuple_id for v in violations])
        
        self.logger.debug(f'Extracting relevant documents from {len(violations)} violations, {len(violation_tuple_ids)} tuple_ids')
        
        for row in snapshot.rows:
            if row.tuple_id in violation_tuple_ids:
                for cell_name, cell_data in row.cells.items():
                    if hasattr(cell_data, 'evidences') and cell_data.evidences:
                        for evidence in cell_data.evidences:
                            
                            clean_evidence = re.sub(r'\[.*?\]\s*', '', evidence)
                            
                            doc_name = os.path.basename(clean_evidence.strip())
                            
                            if doc_name and len(doc_name) > 0 and not doc_name.startswith('['):
                                relevant_docs.add(doc_name)
                                self.logger.debug(f'  Extracted document from {row.tuple_id}.{cell_name}: {doc_name}')
        
        result = list(relevant_docs)
        self.logger.info(f'Identified {len(result)} relevant documents from violation evidences: {result}')
        return result
    
    async def handle_warm_start_request(self, signal):
        """Handling Warm Start refetch requests
        
        When Verifier finds a violation that cannot be fixed by the tool (such as null values, missing values),
        The WARM_START_REQUEST signal will be sent, and the Orchestrator schedules the Extractor to re-extract.
        
        Args:
            signal: WARM_START_REQUEST signal, including:
                - table_name: table name
                - violations: list of violations that need to be re-extracted
                - snapshot: current snapshot
                - run_id: run ID
                - schema: Schema definition"""
        data = signal.data
        table_name = data.get('table_name')
        violations = data.get('violations', [])
        snapshot = data.get('snapshot')
        
        self.logger.info(
            f"Received Warm Start request: {table_name}, "
            f"{len(violations)} violations require re-extraction"
        )
        
        try:
            relevant_docs = self._extract_relevant_documents(violations, snapshot)
            
            if not relevant_docs:
                self.logger.warning(f"Could not extract relevant documents, using all documents")
                text_contents = self.document_utils.convert_documents_to_text(
                    self.current_context.documents
                )
            else:
                text_contents = []
                import os
                for doc_path in self.current_context.documents:
                    doc_name = os.path.basename(doc_path)
                    if any(rel_doc in doc_name or doc_name in rel_doc for rel_doc in relevant_docs):
                        doc_text = self.document_utils.convert_documents_to_text([doc_path])
                        if doc_text:
                            text_contents.extend(doc_text)
            
            if not text_contents:
                self.logger.error(f"Warm Start: no document content available")
                return
            
            signal_data = {
                'context': {
                    'run_id': self.current_context.run_id,
                    'table_name': table_name,
                    'schema': self.schema_utils.extract_table_specific_schema(
                        self.current_context.schema, table_name
                    ),
                    'full_schema': self.current_context.schema,
                    'text_contents': text_contents,
                    'document_mode': 'single',  # Warm Start regardless of batch
                    'nl_prompt': self.current_context.nl_prompt or self.current_context.user_query,
                    'processing_context': self.current_context,
                    'is_warm_start': True,
                    'previous_snapshot': snapshot,
                    'violations': violations
                }
            }
            
            correlation_id = f"{self.current_context.run_id}_{table_name}_warmstart_extract"
            
            await self.broadcaster.emit_simple_signal(
                SignalType.EXTRACTION_REQUEST,
                data=signal_data,
                correlation_id=correlation_id
            )
            
            self.logger.info(f"Warm Start extraction request sent: {table_name}")
            
        except Exception as e:
            self.logger.error(f"Warm Start request handling failed: {e}", exc_info=True)
    
    def _set_table_force_completed(self, table_name: str):
        """Set table force completion mark"""
        if not hasattr(self.current_context, 'force_completed_tables'):
            self.current_context.force_completed_tables = set()
        
        self.current_context.force_completed_tables.add(table_name)
        
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
        
        self.logger.debug(f'Set force-complete flag for table {table_name}')
    
    def _setup_result_context(self, context: Doc2DBContext):
        """Set result_context to support front-end display of view result button
        
         Only the target table requested by the user is output, excluding reference tables (auxiliary tables used for relationship extraction verification)"""
        total_rows = 0
        table_summaries = {}
        
        target_snapshots = {}
        
        for table_name in context.target_tables:
            if table_name in context.all_snapshots:
                snapshot = context.all_snapshots[table_name]
                
                if hasattr(snapshot, 'processing_stage') and snapshot.processing_stage == 'reference_data':
                    self.logger.debug(f'Skipping reference table {table_name} (excluded from output)')
                    continue
                
                target_snapshots[table_name] = snapshot
                
                if snapshot and hasattr(snapshot, 'rows') and snapshot.rows:
                    row_count = len(snapshot.rows)
                    total_rows += row_count
                    table_summaries[table_name] = {
                        'rows': row_count,
                        'violations': len(context.all_violations.get(table_name, [])),
                        'fixes': len(context.all_fixes.get(table_name, []))
                    }
        
        context.result_context = {
            'summary': {
                'total_rows': total_rows,
                'total_tables': len(target_snapshots),
                'total_violations': sum(len(v) for v in context.all_violations.values()),
                'total_fixes': sum(len(f) for f in context.all_fixes.values()),
                'table_summaries': table_summaries
            },
            'snapshots': target_snapshots,  # Include only target tables
            'violations': context.all_violations,
            'fixes': context.all_fixes,
            'status': 'completed'
        }
        
        self.logger.info(
            f'result_context configured: {total_rows} total rows, {len(target_snapshots)} target tables'
        )
    
    def _sync_snapshots_to_context(self, context: Doc2DBContext):
        """Force synchronization of snapshot data to context to ensure that the service layer can read the data
        
        Note: Do not overwrite existing snapshots (which may be complete data after batch merging)"""
        self.logger.debug('Starting snapshot sync to context')
        
        try:
            for table_name in context.target_tables:
                if table_name in context.all_snapshots:
                    self.logger.debug(f'Snapshot for table {table_name} already in context.all_snapshots, skipping memory sync')
                    continue
                
                snapshot = self._sync_wrapper(self.memory_manager.get_snapshot(context.run_id, table_name))
                if snapshot:
                    context.all_snapshots[table_name] = snapshot
                    self.logger.debug(f'Synced snapshot for table {table_name} from memory_manager')
        except Exception as e:
            self.logger.error(f'Memory sync exception: {e}')
        
        if context.all_snapshots:
            context.snapshots = list(context.all_snapshots.values())

                
    def process(self, context: Doc2DBContext) -> Doc2DBContext:
        """How to handle synchronized versions - for compatibility with existing services"""
        DebugUtils.write_debug_log(context, f"Refactored orchestrator invoked: {context.run_id}")
            
        try:
            result = self._sync_wrapper(self.process_with_signals(context))
            
            if result.current_state == Doc2DBProcessingState.COMPLETED:
                DebugUtils.ensure_completion_step(result)
            
            DebugUtils.write_debug_log(context, f"Processing complete, state: {result.current_state}")
                
            return result
        except Exception as e:
            self.logger.error(f"Synchronous call exception: {e}", exc_info=True)
            
            error_step = StepUtils.create_error_step(context, e, 'orchestrator_sync_error')
            error_step['details']['sync_call'] = True
            context.step_outputs.append(error_step)
            
            DebugUtils.write_debug_log(context, f"Processing exception: {str(e)}")
                
            context.current_state = Doc2DBProcessingState.FAILED
            return context


def create_unified_orchestrator(max_iterations: int = 3) -> UnifiedSignalDrivenOrchestrator:
    """Create a unified signal-driven coordinator"""
    return UnifiedSignalDrivenOrchestrator(max_iterations=max_iterations)


async def run_unified_signal_orchestrator(context: Doc2DBContext) -> Doc2DBContext:
    """Run a unified signal-driven coordinator"""
    orchestrator = create_unified_orchestrator()
    return await orchestrator.process_with_signals(context)
