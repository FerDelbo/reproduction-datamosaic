"""Relationship extractor module
Responsible for extracting relational table data from documents (Cold Start and Warm Start)"""
import os
import json
import logging
from typing import List, Dict, Any, Optional
from pathlib import Path

from ...memory import TableRow, CellData
from ...core.ids import IdGenerator

from llm.main import get_answer
from llm.utils import get_llm_request_timeout

try:
    from pydantic import BaseModel, Field
    from langchain_core.output_parsers import PydanticOutputParser
    from langchain_openai import ChatOpenAI
    from langchain.output_parsers import OutputFixingParser
    STRUCTURED_OUTPUT_AVAILABLE = True
except ImportError:
    STRUCTURED_OUTPUT_AVAILABLE = False


class RelationExtractor:
    """Relational Extractor - handles data extraction of relational tables"""
    
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger('doc2db.extractor.relation')
        self.entity_mention_log_file = None
        self._mention_handler = None
    
    def _setup_entity_mention_logging(self, output_dir: str):
        """Set entity mention logging to file"""
        if not output_dir or self._mention_handler:
            return  # output_dir has been set or does not exist
        
        from pathlib import Path
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        self.entity_mention_log_file = output_path / 'entity_mentions.log'
        
        self._mention_handler = logging.FileHandler(self.entity_mention_log_file, mode='a', encoding='utf-8')
        self._mention_handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        self._mention_handler.setFormatter(formatter)
        
        if not any(isinstance(h, logging.FileHandler) and 
                  hasattr(h, 'baseFilename') and 
                  'entity_mentions.log' in h.baseFilename 
                  for h in self.logger.handlers):
            self.logger.addHandler(self._mention_handler)
            self.logger.setLevel(logging.DEBUG)
            self.logger.info(f"Entity mention log file created: {self.entity_mention_log_file}")
    
    def extract_cold_start(self, text_content: str, table_def: Dict[str, Any],
                          nl_prompt: str, doc_source: str, context=None,
                          doc_index: int = 0, full_schema: Dict[str, Any] = None,
                          get_model_api_config_func=None,
                          create_list_model_func=None,
                          build_schema_context_func=None,
                          parse_structured_response_func=None,
                          record_extraction_step_func=None,
                          fallback_func=None,
                          extraction_strategy: str = 'entity_anchored',
                          use_batch_processing: bool = True,
                          batch_size: int = 20) -> List[TableRow]:
        """Cold Start extraction of relational tables - supports multiple extraction strategies
        
        Args:
            extraction_strategy: extraction strategy selection
                - "entity_anchored": Entity-anchored blocked extraction
                - "global": traditional global extraction
                Priority: method parameters > table_def['relation_extraction']['strategy'] > default value 'global'
            use_batch_processing: whether to use batch mode (only valid for entity_anchored strategy)
                - True: Process multiple entities in batches to reduce the number of LLM calls (recommended)
                - False: Process entities one by one (compatibility mode)
            batch_size: The number of entities in each batch during batch processing (default 20)
        
        Entity-anchored strategy:
        1. Use the first reference table as anchor (such as Student table)
        2. For each anchor entity, call LLM to find the sentence that mentions it in the document.
        3. Extract the relationships related to the entity in these sentences
        4. The complexity is reduced from O(m×n) to O(m) LLM calls
        5. Batch processing mode is further reduced to O(m/batch_size) LLM calls
        
        Global strategy:
        1. Extract all relationships from the entire document at once
        2. Suitable for scenarios where documents are short or have few relationships."""
        if not STRUCTURED_OUTPUT_AVAILABLE:
            return fallback_func(text_content, table_def, nl_prompt, doc_source, context, doc_index)
        
        try:
            table_name = table_def.get('name', 'data_table')
            
            relation_extraction_config = table_def.get('relation_extraction', {})
            
            self.logger.debug(f"Starting relation table processing: {table_name}")
            self.logger.debug(f"Original text_content length: {len(text_content)} characters")
            self.logger.debug(f"relation_extraction config: {relation_extraction_config.keys() if relation_extraction_config else 'None'}")
            
            text_content = self._load_document_sources(relation_extraction_config, text_content, context)
            
            self.logger.debug(f"Loaded text_content length: {len(text_content)} characters")
            
            reference_tables_data = None
            
            if relation_extraction_config.get('enabled', False):
                self.logger.info(f"[Entity-Anchored] Loading reference table data...")
                reference_tables_data = self._load_reference_tables(relation_extraction_config, context)
                if reference_tables_data:
                    self.logger.info(f"[Entity-Anchored] Successfully loaded {len(reference_tables_data)} reference tables")
            
            if not reference_tables_data and context:
                reference_tables_data = self._get_entity_snapshots_as_reference(context, table_def)
                if reference_tables_data:
                    self.logger.info(f"[Entity-Anchored] Retrieved {len(reference_tables_data)} entity tables from context")
            
            strategy = extraction_strategy

            
            if strategy == 'entity_anchored':
                if not reference_tables_data:
                    self.logger.warning(f"Configuration requires entity_anchored strategy but no reference table data is available; falling back to global extraction")
                    strategy = 'global'
                else:
                    self.logger.info(f"[Strategy] Using Entity-Anchored strategy (configured strategy: {strategy})")
            
            if strategy == 'global':
                self.logger.info(f"[Strategy] Using global extraction strategy (configured strategy: {strategy})")
                return self._extract_global(
                    text_content, table_def, nl_prompt, doc_source, context, doc_index,
                    full_schema, reference_tables_data, get_model_api_config_func, 
                    create_list_model_func, build_schema_context_func, 
                    parse_structured_response_func, record_extraction_step_func, fallback_func
                )
            
            anchor_table_name = list(reference_tables_data.keys())[0]
            anchor_entities = reference_tables_data[anchor_table_name]
            
            self.logger.info(
                f"[Entity-Anchored] Using anchor table: {anchor_table_name}, "
                f"{len(anchor_entities)} anchor entities total"
            )
            
            model = context.model if context and hasattr(context, 'model') else "gpt-4o"
            api_config = get_model_api_config_func(model)
            
            all_relation_rows = []
            
            if use_batch_processing:

                anchor_entities_with_mentions = self._find_entity_mentions_via_llm_batch(
                    text_content, anchor_entities, anchor_table_name, 
                    model, api_config, context, batch_size=batch_size
                )
                
                all_relation_rows = self._extract_relations_for_anchors_batch(
                    anchor_entities_with_mentions, table_def,
                    reference_tables_data, relation_extraction_config,
                    model, api_config, doc_source,
                    create_list_model_func, build_schema_context_func,
                    parse_structured_response_func, full_schema,
                    batch_size=batch_size
                )
                
            else:
                self.logger.info(f"[Sequential mode] Using traditional serial processing")
                
                for i, anchor_entity in enumerate(anchor_entities):
                    self.logger.info(
                        f"  [{i+1}/{len(anchor_entities)}] Processing anchor: {anchor_entity}"
                    )
                    
                    relevant_sentences = self._find_entity_mentions_via_llm(
                        text_content, anchor_entity, anchor_table_name, model, api_config, context
                    )
                    
                    if not relevant_sentences:
                        self.logger.debug(f"    No sentences mentioning this entity were found; skipping")
                        continue
                    
                    self.logger.info(f"    Found {len(relevant_sentences)} relevant sentences")
                    
                    rows = self._extract_relations_for_anchor(
                        anchor_entity, relevant_sentences, table_def, 
                        reference_tables_data, relation_extraction_config,
                        model, api_config, doc_source,
                        create_list_model_func, build_schema_context_func,
                        parse_structured_response_func, full_schema
                    )
                    
                    all_relation_rows.extend(rows)
                    self.logger.info(f"    Extracted {len(rows)} relation records")
            
            unique_rows = self._deduplicate_relation_rows(all_relation_rows)
            
            self.logger.info(
                f"[Entity-Anchored] Complete: {len(all_relation_rows)} raw records "
                f"-> {len(unique_rows)} deduplicated records"
            )
            
            record_extraction_step_func(
                context, table_name, doc_index, doc_source, 
                'entity_anchored_relation_extraction', model, 
                f"Entity-Anchored extraction with {len(anchor_entities)} anchors",
                f"Extracted {len(unique_rows)} unique relations", 
                len(unique_rows)
            )
            
            return unique_rows
            
        except Exception as e:
            self.logger.error(f"[Entity-Anchored] Exception: {e}")
            import traceback
            traceback.print_exc()
            return fallback_func(text_content, table_def, nl_prompt, doc_source, context, doc_index)
    
    def extract_warm_start(self, text_content: str, table_def: Dict[str, Any],
                          nl_prompt: str, doc_source: str, context=None,
                          doc_index: int = 0, previous_snapshot=None,
                          violations: List = None,
                          check_warm_start_limit_func=None,
                          get_model_api_config_func=None,
                          create_list_model_func=None,
                          build_schema_context_func=None,
                          parse_structured_response_func=None,
                          record_extraction_step_func=None,
                          full_schema: Dict[str, Any] = None) -> List[TableRow]:
        """Warm Start extraction of relational tables - Entity-Anchored incremental re-extraction
        
        Thesis logic:
        1. Identify the anchor entities involved from the violation
        2. Rerun the entity-anchored extraction for only these entities
        3. Remove affected old records, add new records, and retain irrelevant records
        
        Args:
            text_content: document content
            table_def: table definition
            nl_prompt: natural language prompt
            doc_source: Document source
            context: processing context
            doc_index: document index
            previous_snapshot: the last snapshot
            violations: list of violations
            check_warm_start_limit_func: function to check warm start limit
            get_model_api_config_func: Get the model API configuration function
            create_list_model_func: Create list model function
            build_schema_context_func: build schema context function
            parse_structured_response_func: Parse structured response function
            record_extraction_step_func: record extraction step function
            full_schema: complete schema definition
            
        Returns:
            Updated TableRow list"""
        table_name = table_def.get('name') or table_def.get('table_name', 'unknown')
        
        if not check_warm_start_limit_func(context, table_name):
            return previous_snapshot.rows if previous_snapshot else []
        
        self.logger.info(f"[Relation Warm Start] Starting Entity-Anchored incremental re-extraction - table: {table_name}")
        
        affected_anchor_entities = self._identify_affected_anchors(
            violations, previous_snapshot, table_def, context
        )
        
        if not affected_anchor_entities:
            self.logger.info(f"[Relation Warm Start] No affected anchor entities identified; keeping original snapshot")
            return previous_snapshot.rows if previous_snapshot else []
        
        self.logger.info(
            f"[Relation Warm Start] Identified {len(affected_anchor_entities)} affected anchor entities"
        )
        
        relation_extraction_config = table_def.get('relation_extraction', {})
        text_content = self._load_document_sources(relation_extraction_config, text_content, context)
        
        reference_tables_data = None
        if relation_extraction_config.get('enabled', False):
            reference_tables_data = self._load_reference_tables(relation_extraction_config, context)
        
        if not reference_tables_data and context:
            reference_tables_data = self._get_entity_snapshots_as_reference(context, table_def)
        
        if not reference_tables_data:
            self.logger.warning(f"[Relation Warm Start] No reference table data available; cannot run entity-anchored re-extraction; keeping original snapshot")
            return previous_snapshot.rows if previous_snapshot else []
        
        model = context.model if context and hasattr(context, 'model') else "gpt-4o"
        api_config = get_model_api_config_func(model)
        
        re_extracted_rows = []
        anchor_table_name = list(reference_tables_data.keys())[0]
        
        for i, anchor_entity in enumerate(affected_anchor_entities):
            anchor_desc = ", ".join([f"{k}={v}" for k, v in anchor_entity.items()])
            self.logger.info(f"  [{i+1}/{len(affected_anchor_entities)}] Re-extracting anchor: {anchor_desc}")
            
            relevant_sentences = self._find_entity_mentions_via_llm(
                text_content, anchor_entity, anchor_table_name,
                model, api_config, context
            )
            
            if relevant_sentences:
                rows = self._extract_relations_for_anchor(
                    anchor_entity, relevant_sentences, table_def,
                    reference_tables_data, relation_extraction_config,
                    model, api_config, doc_source,
                    create_list_model_func, build_schema_context_func,
                    parse_structured_response_func, full_schema
                )
                re_extracted_rows.extend(rows)
                self.logger.info(f"    Extracted {len(rows)} relations")
            else:
                self.logger.info(f"    No relevant text found; this anchor has no relation records")
        
        updated_rows = self._merge_warm_start_results(
            previous_snapshot.rows if previous_snapshot else [],
            re_extracted_rows,
            affected_anchor_entities,
            table_def
        )
        
        self.logger.info(
            f"[Relation Warm Start] Complete: original {len(previous_snapshot.rows if previous_snapshot else [])} records "
            f"-> re-extracted {len(re_extracted_rows)} -> final {len(updated_rows)} records"
        )
        
        if record_extraction_step_func:
            record_extraction_step_func(
                context, table_name, doc_index, doc_source,
                'entity_anchored_warm_start', model,
                f"Re-extracted {len(affected_anchor_entities)} affected anchors",
                f"Updated to {len(updated_rows)} rows (re-extracted {len(re_extracted_rows)})",
                len(updated_rows)
            )
        
        return updated_rows
    
    def _get_entity_snapshots_as_reference(self, context, table_def: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """Obtain the extracted entity table data from context as a reference
        
        When used for relationship extraction, convert the extracted entity table data into a reference format"""
        reference_data = {}
        
        if not hasattr(context, 'all_snapshots') or not context.all_snapshots:
            return reference_data
        
        attributes = table_def.get('attributes', table_def.get('fields', []))
        referenced_tables = set()
        
        for attr in attributes:
            constraints = attr.get('constraints', {})
            if constraints.get('foreign_key'):
                field_name = attr.get('name', '')
                if field_name.endswith('ID') or field_name.endswith('_id'):
                    ref_table = field_name[:-2] if field_name.endswith('ID') else field_name[:-3]
                    if ref_table:
                        referenced_tables.add(ref_table)
        
        for table_name, snapshot in context.all_snapshots.items():
            if any(table_name.lower() == ref.lower() for ref in referenced_tables):
                rows_data = []
                if hasattr(snapshot, 'rows') and snapshot.rows:
                    for row in snapshot.rows:
                        row_dict = {}
                        for field_name, cell_data in row.cells.items():
                            if hasattr(cell_data, 'value'):
                                row_dict[field_name] = cell_data.value
                        if row_dict:
                            rows_data.append(row_dict)
                
                if rows_data:
                    reference_data[table_name] = rows_data
                    self.logger.info(f"Retrieved reference table {table_name} from context: {len(rows_data)} rows")
        
        return reference_data
    
    def _find_project_root(self) -> Optional[Path]:
        """Find the project root directory (the directory containing the dataset directory)
        
        Search upwards from the current directory until you find the directory containing the dataset directory"""
        current = Path.cwd()
        max_depth = 5  # Search up to 5 levels upward
        
        for _ in range(max_depth):
            if (current / 'dataset').exists():
                return current
            
            parent = current.parent
            if parent == current:  # Reached root directory
                break
            current = parent
        
        return None
    
    def _load_document_sources(self, relation_config: Dict[str, Any], 
                               default_text_content: str, context=None) -> str:
        """Load dedicated relation documents configured in ``document_sources``.

        Configured sources replace ``default_text_content``. This allows a relation
        table to use a documented, table-specific input set; callers that require the
        orchestrator-provided batch should leave ``document_sources`` unset.

        Args:
            relation_config: relation_extraction configuration
            default_text_content: Default text content (used if document_sources is not configured)
            context: processing context
            
        Returns:
            Document content (may be loaded from document_sources, may be the default)"""
        
        if not relation_config:
            return default_text_content
        
        document_sources = relation_config.get('document_sources', [])
        
        if not document_sources:
            return default_text_content
        
        self.logger.debug("Loading configured relation document sources")
        
        merged_content = []
        
        for doc_source in document_sources:
            try:
                doc_path = Path(doc_source)
                
                if not doc_path.is_absolute():
                    if context and hasattr(context, 'workspace_path'):
                        doc_path = Path(context.workspace_path) / doc_source
                    else:
                        candidate1 = Path.cwd() / doc_source
                        candidate2 = Path.cwd().parent / doc_source if Path.cwd().name == 'backend' else None
                        project_root = self._find_project_root()
                        candidate3 = project_root / doc_source if project_root else None
                        
                        if candidate1.exists():
                            doc_path = candidate1
                        elif candidate2 and candidate2.exists():
                            doc_path = candidate2
                            self.logger.info(f"Using project root path: {doc_path}")
                        elif candidate3 and candidate3.exists():
                            doc_path = candidate3
                            self.logger.info(f"Found project root: {doc_path}")
                        else:
                            doc_path = candidate1  # The first candidate is used by default
                
                if not doc_path.exists():
                    self.logger.error(f"Document source does not exist: {doc_path}")
                    continue
                
                with open(doc_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if content:
                    merged_content.append(f"=== Document: {doc_path.name} ===\n")
                    merged_content.append(content)
                    merged_content.append(f"\n=== End of {doc_path.name} ===\n\n")
                    self.logger.info(f"Successfully loaded document: {doc_path.name} ({len(content)} characters)")
                
            except Exception as e:
                self.logger.error(f"Failed to load document {doc_source}: {e}")
                continue
        
        if merged_content:
            result = "\n".join(merged_content)
            self.logger.info(f"Loaded {len(document_sources)} documents from document_sources; total {len(result)} characters")
            return result
        else:
            self.logger.warning(f"All documents configured in document_sources failed to load; falling back to provided text_content")
            return default_text_content
    
    def _load_reference_tables(self, relation_config: Dict[str, Any], 
                              context=None) -> Dict[str, List[Dict[str, Any]]]:
        """Load reference table data required for relational extraction
        
        Args:
            relation_config: relation_extraction configuration
            context: Extract context (may include workspace path and other information)
            
        Returns:
            Dictionary, key is the table name, value is the data list of the table"""
        reference_tables = {}
        
        reference_configs = relation_config.get('reference_tables', [])
        if not reference_configs:
            return reference_tables
        
        for ref_config in reference_configs:
            table_name = ref_config.get('table')
            data_source = ref_config.get('data_source')
            key_fields = ref_config.get('key_fields', [])
            
            if not table_name or not data_source:
                self.logger.warning(f"Incomplete reference table configuration; skipping: {ref_config}")
                continue
            
            try:
                data_path = Path(data_source)
                if not data_path.is_absolute():
                    if context and hasattr(context, 'workspace_path'):
                        data_path = Path(context.workspace_path) / data_source
                    else:
                        candidate1 = Path.cwd() / data_source
                        candidate2 = Path.cwd().parent / data_source if Path.cwd().name == 'backend' else None
                        candidate3 = self._find_project_root() / data_source if self._find_project_root() else None
                        
                        if candidate1.exists():
                            data_path = candidate1
                        elif candidate2 and candidate2.exists():
                            data_path = candidate2
                            self.logger.info(f"Using project root path: {data_path}")
                        elif candidate3 and candidate3.exists():
                            data_path = candidate3
                            self.logger.info(f"Found project root: {data_path}")
                        else:
                            data_path = candidate1  # The first candidate is used by default
                
                if not data_path.exists():
                    self.logger.error(f"Reference table data file does not exist: {data_path}")
                    if not data_path.is_absolute():
                        self.logger.error(f"   Hint: current working directory is {Path.cwd()}")
                    continue
                
                with open(data_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if table_name in data:
                    table_data = data[table_name]
                    
                    reference_tables[table_name] = table_data
                    
                    fields_info = f" (key_fields: {key_fields})" if key_fields else ""
                    self.logger.info(f"Loaded reference table {table_name}: {len(table_data)} rows{fields_info}")
                else:
                    self.logger.warning(f"Table {table_name} not found in data file")
                
            except Exception as e:
                self.logger.error(f"Failed to load reference table {table_name}: {e}")
                continue
        
        return reference_tables
    
    def _build_reference_tables_prompt(self, reference_tables_data: Dict[str, List[Dict[str, Any]]], 
                                       relation_config: Dict[str, Any]) -> str:
        """Build prompt section containing reference table data
        
        Args:
            reference_tables_data: reference table data dictionary
            relation_config: relation_extraction configuration
            
        Returns:
            Formatted prompt string"""
        if not reference_tables_data:
            return ""
        
        prompt_parts = ["\n【Reference Tables for Relationship Extraction】"]
        
        extraction_hint = relation_config.get('extraction_hint', '')
        if extraction_hint:
            prompt_parts.append(f"\nTask: {extraction_hint}\n")
        
        for table_name, table_data in reference_tables_data.items():
            if not table_data:
                continue
            
            table_config = None
            for ref_config in relation_config.get('reference_tables', []):
                if ref_config.get('table') == table_name:
                    table_config = ref_config
                    break
            
            prompt_parts.append(f"\n{table_name} Table:")
            
            if table_config and table_config.get('description'):
                prompt_parts.append(f"  Description: {table_config['description']}")
            
            if table_data:
                fields = list(table_data[0].keys())
                
                header = "  | " + " | ".join(fields) + " |"
                separator = "  |" + "|".join(["-" * (len(f) + 2) for f in fields]) + "|"
                prompt_parts.append(header)
                prompt_parts.append(separator)
                
                max_rows = min(50, len(table_data))
                for row in table_data[:max_rows]:
                    values = [str(row.get(f, '')) for f in fields]
                    data_row = "  | " + " | ".join(values) + " |"
                    prompt_parts.append(data_row)
                
                if len(table_data) > max_rows:
                    prompt_parts.append(f"  ... (total {len(table_data)} rows)")
            
            prompt_parts.append("")  # Blank line separated
        
        prompt_parts.append("IMPORTANT Instructions for Relationship Extraction:")
        prompt_parts.append("- Use the reference tables above to match entity names/descriptions to their IDs")
        prompt_parts.append("- For foreign key fields, MUST use the exact ID values from the reference tables")
        
        matching_instructions = []
        for table_name, table_data in reference_tables_data.items():
            if table_data:
                sample_row = table_data[0]
                id_field = None
                name_field = None
                
                for field in sample_row.keys():
                    if 'id' in field.lower():
                        id_field = field
                    elif 'name' in field.lower():
                        name_field = field
                
                if id_field and name_field:
                    matching_instructions.append(
                        f"- Match {table_name} entities by their {name_field} to {table_name}.{id_field}"
                    )
        
        if matching_instructions:
            prompt_parts.extend(matching_instructions)
        
        prompt_parts.append("- Extract ONLY the relationships (ID pairs) that are explicitly mentioned in the document")
        prompt_parts.append("")
        
        return "\n".join(prompt_parts)
    
    def _extract_global(self, text_content: str, table_def: Dict[str, Any],
                       nl_prompt: str, doc_source: str, context=None,
                       doc_index: int = 0, full_schema: Dict[str, Any] = None,
                       reference_tables_data: Dict[str, List[Dict]] = None,
                       get_model_api_config_func=None,
                       create_list_model_func=None,
                       build_schema_context_func=None,
                       parse_structured_response_func=None,
                       record_extraction_step_func=None,
                       fallback_func=None) -> List[TableRow]:
        """Traditional global relationship extraction"""
        relation_extraction_config = table_def.get('relation_extraction', {})
        
        self.logger.info(f"[_extract_global] Starting global relation extraction")
        self.logger.info(f"   Original text_content length: {len(text_content)} characters")
        
        text_content = self._load_document_sources(relation_extraction_config, text_content, context)
        
        self.logger.info(f"   Loaded text_content length: {len(text_content)} characters")
        
        temp_schema = {'tables': [table_def]}
        table_name = table_def.get('name', 'data_table')
        
        list_model = create_list_model_func(temp_schema, table_name)
        if not list_model:
            return fallback_func(text_content, table_def, nl_prompt, doc_source, context, doc_index)
        
        model = context.model if context and hasattr(context, 'model') else "gpt-4o"
        api_config = get_model_api_config_func(model)
        api_base = api_config['api_base']
        api_key = api_config['api_key']
        
        llm_kwargs = {"model": model, "temperature": 0, "timeout": get_llm_request_timeout()}
        if api_base:
            llm_kwargs["base_url"] = api_base
        if api_key:
            llm_kwargs["api_key"] = api_key
        
        llm = ChatOpenAI(**llm_kwargs)
        
        parser = PydanticOutputParser(pydantic_object=list_model)
        fixing_parser = OutputFixingParser.from_llm(parser=parser, llm=llm)
        
        schema_context = build_schema_context_func(table_def, full_schema=full_schema)
        
        reference_tables_prompt = self._build_reference_tables_prompt(
            reference_tables_data or {}, relation_extraction_config
        )
        
        prompt = f"""Please extract structured data from the following text according to the schema for table "{table_name}".

{schema_context}

{reference_tables_prompt}

Extract ALL relevant records for the "{table_name}" table from the document. Each record should be a separate item in the list.

Text content:
{text_content}

{parser.get_format_instructions()}

IMPORTANT: 
- Return a JSON object with a "rows" field containing a list of all extracted records for "{table_name}".
- Extract EVERY occurrence of relevant data for this table, even if mentioned multiple times.
- For foreign key fields, use exact values from the reference tables provided above.
"""

        if nl_prompt and nl_prompt.strip():
            prompt += f"\nAdditional Instructions: {nl_prompt}\n"
        
        response = llm.invoke(prompt)
        llm_response = response.content
        
        rows = parse_structured_response_func(
            llm_response, fixing_parser, table_name, doc_source
        )
        
        record_extraction_step_func(
            context, table_name, doc_index, doc_source, 
            'global_relation_extraction', model, prompt, llm_response, len(rows)
        )
        
        return rows
    
    def _find_entity_mentions_via_llm_batch(self, text_content: str, 
                                           anchor_entities: List[Dict[str, Any]],
                                           anchor_table_name: str, model: str,
                                           api_config: Dict[str, str], 
                                           context=None,
                                           batch_size: int = 20) -> Dict[str, List[str]]:
        """Use LLM in batches to find text chunks (chunks) that mention multiple anchor entities in documents
        
        Advantages of batch processing compared to single processing:
        1. Reduce the number of network round-trips (N times -> N/batch_size times)
        2. Higher throughput
        3. Reduce total latency
        
        Args:
            text_content: complete document content
            anchor_entities: list of anchor entities
            anchor_table_name: anchor table name
            model: model used
            api_config: API configuration
            context: processing context
            batch_size: Number of entities processed in each batch
            
        Returns:
            Dictionary, key is entity description, value is a list of text blocks containing the entity
            For example: {"StudentID=s1, StudentName=Alice": ["chunk1", "chunk2"], ...}"""
        if context:
            output_dir = None
            if hasattr(context, 'io_manager') and hasattr(context.io_manager, 'output_dir'):
                output_dir = context.io_manager.output_dir
            elif hasattr(context, 'output_dir'):
                output_dir = context.output_dir
            if output_dir:
                self._setup_entity_mention_logging(output_dir)
        
        self.logger.info(f"[Batch] Starting batch mention lookup for {len(anchor_entities)} entities")
        
        all_results = {}
        
        for batch_idx in range(0, len(anchor_entities), batch_size):
            batch = anchor_entities[batch_idx:batch_idx + batch_size]
            self.logger.info(f"  Batch {batch_idx//batch_size + 1}: processing {len(batch)} entities")
            
            entities_list = []
            entity_keys = []  # Used to map return results
            for entity in batch:
                entity_desc = ", ".join([f"{k}={v}" for k, v in entity.items()])
                entities_list.append(entity_desc)
                entity_keys.append(entity_desc)
            
            system_prompt = """You are a document analysis expert. Your task is to find all relevant text chunks 
that mention specific entities and provide sufficient context for understanding relationships."""
            
            prompt = f"""Find all text chunks in the document that mention ANY of the following entities from the {anchor_table_name} table.

TARGET ENTITIES:
{chr(10).join([f"{i+1}. {desc}" for i, desc in enumerate(entities_list)])}

DOCUMENT TO SEARCH:
{text_content}

TASK:
- For EACH entity (by its ID or name), find ALL text passages that mention it
- Extract complete sentences with context (2-5 sentences per chunk)
- Include surrounding text to help understand relationships

OUTPUT FORMAT (STRICTLY FOLLOW):
<entity id="1">
<chunk>Text passage mentioning entity 1...</chunk>
<chunk>Another passage mentioning entity 1...</chunk>
</entity>
<entity id="2">
<chunk>Text passage mentioning entity 2...</chunk>
</entity>

IMPORTANT:
- You MUST process ALL {len(entities_list)} entities listed above
- If an entity is not mentioned in the document, write: <entity id="X">NO_MENTION</entity>
- Do NOT skip any entity
- Use the exact entity ID numbers (1, 2, 3, etc.)
"""
            
            try:
                llm_response = get_answer(prompt, system_prompt=system_prompt, model=model)
                
                self.logger.debug(f"Raw LLM response length: {len(llm_response)} characters")
                
                self.logger.info(f"[Batch {batch_idx//batch_size + 1}] Finding mentions for {len(batch)} entities")

                import re
                
                for i, entity_key in enumerate(entity_keys):
                    entity_num = i + 1
                    
                    entity_pattern = rf'<entity\s+id\s*=\s*["\']?{entity_num}["\']?\s*>(.*?)</entity>'
                    entity_match = re.search(entity_pattern, llm_response, re.DOTALL | re.IGNORECASE)
                    
                    chunks = []
                    if entity_match:
                        entity_content = entity_match.group(1)
                        self.logger.debug(f"Entity {entity_num} matched successfully; content length: {len(entity_content)}")
                        
                        if "NO_MENTION" not in entity_content:
                            chunk_matches = re.findall(r'<chunk>(.*?)</chunk>', entity_content, re.DOTALL)
                            
                            for chunk in chunk_matches:
                                chunk = chunk.strip()
                                if chunk and len(chunk) > 20:
                                    if len(chunk) > 800:
                                        chunk = chunk[:800] + "..."
                                    chunks.append(chunk)
                            
                            if not chunks:
                                self.logger.debug(f"Entity {entity_num} has no <chunk> tags; attempting fallback parsing")
                                potential_chunks = entity_content.strip().split('\n\n')
                                for chunk in potential_chunks:
                                    chunk = chunk.strip()
                                    if chunk and len(chunk) > 30:
                                        if len(chunk) > 800:
                                            chunk = chunk[:800] + "..."
                                        chunks.append(chunk)
                    else:
                        self.logger.debug(f"Entity {entity_num} did not match an <entity> tag")
                    
                    chunks = chunks[:10]
                    all_results[entity_key] = chunks
                    
                    if chunks:
                        self.logger.info("Entity %d matched %d chunks", entity_num, len(chunks))
                    else:
                        self.logger.info("Entity %d was not found", entity_num)
                
            except Exception as e:
                self.logger.error(f"Batch entity mention lookup failed (batch {batch_idx//batch_size + 1}): {e}")
                import traceback
                self.logger.error(traceback.format_exc())
                for entity_key in entity_keys:
                    all_results[entity_key] = []
        
        successful_count = sum(1 for chunks in all_results.values() if chunks)
        self.logger.info(f"[Batch] Complete: found mentions for {successful_count} of {len(anchor_entities)} entities")
        
        return all_results
    
    def _find_entity_mentions_via_llm(self, text_content: str, anchor_entity: Dict[str, Any],
                                     anchor_table_name: str, model: str,
                                     api_config: Dict[str, str], context=None) -> List[str]:
        """Use LLM to find the text chunk (chunk) in the document that mentions the anchor entity
        
        Note: This method is for single entity processing. For batch processing, use _find_entity_mentions_via_llm_batch
        
        Args:
            text_content: complete document content
            anchor_entity: anchor entity, for example {'StudentID': 's1', 'StudentName': 'Alice'}
            anchor_table_name: anchor table name
            model: model used
            api_config: API configuration
            context: processing context, used to obtain output_dir
            
        Returns:
            List of text blocks containing this entity"""
        if context:
            output_dir = None
            if hasattr(context, 'io_manager') and hasattr(context.io_manager, 'output_dir'):
                output_dir = context.io_manager.output_dir
            elif hasattr(context, 'output_dir'):
                output_dir = context.output_dir
            
            if output_dir:
                self._setup_entity_mention_logging(output_dir)
        
        entity_desc = ", ".join([f"{k}={v}" for k, v in anchor_entity.items()])
        
        self.logger.info("Starting entity mention lookup for table %s", anchor_table_name)
        
        system_prompt = """You are a document analysis expert. Your task is to find all relevant text chunks 
that mention a specific entity and provide sufficient context for understanding relationships."""
        
        prompt = f"""Find all text chunks in the document that mention the following entity from the {anchor_table_name} table:

Entity: {entity_desc}

Document:
{text_content}

Instructions:
1. Identify the entity by any of its attributes (ID, name, etc.)
2. Extract complete text chunks (not just single sentences) that mention this entity
3. A chunk should be 2-5 sentences long to provide sufficient context
4. Include surrounding context that helps understand relationships and attributes
5. If a mention is very brief, include the surrounding sentences for context
6. Return ONLY the text chunks, no explanations
7. If no mention found, return "NO_MENTION"

Output format:
<chunk>First text chunk mentioning the entity with context.</chunk>
<chunk>Second text chunk mentioning the entity with context.</chunk>
"""
        
        try:
            llm_response = get_answer(prompt, system_prompt=system_prompt, model=model)
            
            chunks = []
            if "NO_MENTION" in llm_response:
                return chunks
            
            import re
            chunk_matches = re.findall(r'<chunk>(.*?)</chunk>', llm_response, re.DOTALL)
            
            for chunk in chunk_matches:
                chunk = chunk.strip()
                if chunk and len(chunk) > 20:  # Make sure the chunk has substance
                    if len(chunk) > 800:
                        chunk = chunk[:800] + "..."
                    chunks.append(chunk)
            
            if not chunks:
                potential_chunks = llm_response.strip().split('\n\n')
                for chunk in potential_chunks:
                    chunk = chunk.strip()
                    if chunk and not chunk.startswith('#') and len(chunk) > 30:
                        if len(chunk) > 800:
                            chunk = chunk[:800] + "..."
                        chunks.append(chunk)
            
            final_chunks = chunks[:15]  # Limit to 15 chunks
            if final_chunks:
                self.logger.info("Found %d matching text chunks", len(final_chunks))
            else:
                self.logger.info("No matching text chunks found")
            
            return final_chunks
            
        except Exception as e:
            self.logger.error("LLM entity mention lookup failed for table %s: %s", anchor_table_name, e)
            return []
    
    def _extract_relations_for_anchors_batch(self, 
                                            anchor_entities_with_context: Dict[str, List[str]],
                                            table_def: Dict[str, Any],
                                            reference_tables_data: Dict[str, List[Dict]],
                                            relation_config: Dict[str, Any],
                                            model: str,
                                            api_config: Dict[str, str],
                                            doc_source: str,
                                            create_list_model_func=None,
                                            build_schema_context_func=None,
                                            parse_structured_response_func=None,
                                            full_schema: Dict[str, Any] = None,
                                            batch_size: int = 10) -> List[TableRow]:
        """Extract relationships for multiple anchor entities in batches
        
        Advantages compared to individual processing:
        1. Reduce the number of LLM calls (N times -> N/batch_size times)
        2. Sharing the context of schema and reference tables
        3. Significantly reduce total latency
        
        Args:
            anchor_entities_with_context: dictionary, key is entity description, value is list of related text blocks
                For example: {"StudentID=s1, StudentName=Alice": ["chunk1", "chunk2"], ...}
            table_def: relational table definition
            reference_tables_data: all reference table data
            relation_config: relation extraction configuration
            model: model name
            api_config: API configuration
            doc_source: Document source
            batch_size: Number of entities processed in each batch
            
        Returns:
            List of relationship rows for all entities (merged)"""
        self.logger.info(f"[Batch] Starting batch relation extraction for {len(anchor_entities_with_context)} entities")
        
        temp_schema = {'tables': [table_def]}
        table_name = table_def.get('name', 'data_table')
        
        list_model = create_list_model_func(temp_schema, table_name)
        if not list_model:
            return []
        
        api_base = api_config['api_base']
        api_key = api_config['api_key']
        
        llm_kwargs = {"model": model, "temperature": 0, "timeout": get_llm_request_timeout()}
        if api_base:
            llm_kwargs["base_url"] = api_base
        if api_key:
            llm_kwargs["api_key"] = api_key
        
        from langchain_openai import ChatOpenAI
        from langchain_core.output_parsers import PydanticOutputParser
        from langchain.output_parsers import OutputFixingParser
        
        llm = ChatOpenAI(**llm_kwargs)
        parser = PydanticOutputParser(pydantic_object=list_model)
        fixing_parser = OutputFixingParser.from_llm(parser=parser, llm=llm)
        
        schema_context = build_schema_context_func(table_def, full_schema=full_schema)
        reference_tables_prompt = self._build_reference_tables_prompt(
            reference_tables_data, relation_config
        )
        
        all_rows = []
        
        entities_with_text = {k: v for k, v in anchor_entities_with_context.items() if v}
        
        entity_items = list(entities_with_text.items())
        for batch_idx in range(0, len(entity_items), batch_size):
            batch = entity_items[batch_idx:batch_idx + batch_size]
            self.logger.info(f"  Batch {batch_idx//batch_size + 1}: extracting relations for {len(batch)} entities")
            
            entities_context_parts = []
            for i, (entity_desc, relevant_texts) in enumerate(batch, 1):
                context_text = "\n".join(relevant_texts)
                entities_context_parts.append(
                    f"=== Entity {i}: {entity_desc} ===\n{context_text}\n"
                )
            
            combined_context = "\n".join(entities_context_parts)
            
            prompt = f"""Extract relationship records for ALL the following anchor entities:

{schema_context}

{reference_tables_prompt}

Relevant Text for Multiple Entities:
{combined_context}

{parser.get_format_instructions()}

IMPORTANT:
- Extract relationships for ALL {len(batch)} entities listed above
- For each entity, extract ONLY relationships involving that specific entity
- For foreign key fields, use exact values from the reference tables
- Return a JSON object with a "rows" field containing ALL extracted records
- Each record should be properly linked to its anchor entity

TIPS: Process each entity section separately and combine all results.
"""
            
            try:
                response = llm.invoke(prompt)
                llm_response = response.content
                
                self.logger.debug(f"Relation extraction LLM response length: {len(llm_response)} characters")
                
                batch_rows = parse_structured_response_func(
                    llm_response, fixing_parser, table_name, doc_source
                )
                
                all_rows.extend(batch_rows)
                self.logger.info(f"    Extracted {len(batch_rows)} relation records")
                
                
            except Exception as e:
                self.logger.error(f"Batch relation extraction failed (batch {batch_idx//batch_size + 1}): {e}")
                import traceback
                self.logger.error(traceback.format_exc())
        
        self.logger.info(f"[Batch] Complete: extracted {len(all_rows)} relation records in total")
        
        return all_rows
    
    def _extract_relations_for_anchor(self, anchor_entity: Dict[str, Any],
                                     relevant_sentences: List[str],
                                     table_def: Dict[str, Any],
                                     reference_tables_data: Dict[str, List[Dict]],
                                     relation_config: Dict[str, Any],
                                     model: str,
                                     api_config: Dict[str, str],
                                     doc_source: str,
                                     create_list_model_func=None,
                                     build_schema_context_func=None,
                                     parse_structured_response_func=None,
                                     full_schema: Dict[str, Any] = None) -> List[TableRow]:
        """Extract relationships in related sentences for a single anchor entity
        
        Note: This method is for single entity processing. For batch processing, use _extract_relations_for_anchors_batch
        
        Args:
            anchor_entity: anchor entity
            relevant_sentences: list of sentences containing this entity
            table_def: relational table definition
            reference_tables_data: all reference table data
            relation_config: relation extraction configuration
            model: model name
            api_config: API configuration
            doc_source: Document source
            
        Returns:
            List of extracted relationship rows"""
        temp_schema = {'tables': [table_def]}
        table_name = table_def.get('name', 'data_table')
        
        list_model = create_list_model_func(temp_schema, table_name)
        if not list_model:
            return []
        
        api_base = api_config['api_base']
        api_key = api_config['api_key']
        
        llm_kwargs = {"model": model, "temperature": 0, "timeout": get_llm_request_timeout()}
        if api_base:
            llm_kwargs["base_url"] = api_base
        if api_key:
            llm_kwargs["api_key"] = api_key
        
        llm = ChatOpenAI(**llm_kwargs)
        
        parser = PydanticOutputParser(pydantic_object=list_model)
        fixing_parser = OutputFixingParser.from_llm(parser=parser, llm=llm)
        
        schema_context = build_schema_context_func(table_def, full_schema=full_schema)
        
        reference_tables_prompt = self._build_reference_tables_prompt(
            reference_tables_data, relation_config
        )
        
        anchor_desc = ", ".join([f"{k}={v}" for k, v in anchor_entity.items()])
        
        context_text = "\n".join(relevant_sentences)
        
        prompt = f"""Extract relationship records involving the following anchor entity:

Anchor Entity: {anchor_desc}

{schema_context}

{reference_tables_prompt}

Relevant Text (sentences mentioning this entity):
{context_text}

{parser.get_format_instructions()}

IMPORTANT:
- Extract ONLY relationships involving the anchor entity specified above
- For foreign key fields, use exact values from the reference tables
- Return a JSON object with a "rows" field
- If no relationships found, return {{"rows": []}}

TIPS: Focus on relationships explicitly stated in the relevant text.
"""
        
        try:
            response = llm.invoke(prompt)
            llm_response = response.content
            
            rows = parse_structured_response_func(
                llm_response, fixing_parser, table_name, doc_source
            )
            
            return rows
            
        except Exception as e:
            self.logger.error(f"Failed to extract relations for anchor: {e}")
            return []
    
    def _deduplicate_relation_rows(self, rows: List[TableRow]) -> List[TableRow]:
        """Remove duplicate relationships
        
        Deduplication based on tuple_id or cell content"""
        if not rows:
            return []
        
        seen_tuples = set()
        unique_rows = []
        
        for row in rows:
            cell_values = tuple(sorted([
                (field_name, str(cell_data.value)) 
                for field_name, cell_data in row.cells.items()
            ]))
            
            if cell_values not in seen_tuples:
                seen_tuples.add(cell_values)
                unique_rows.append(row)
        
        return unique_rows
    
    def _identify_affected_anchors(self, violations: List, previous_snapshot,
                                   table_def: Dict[str, Any], context) -> List[Dict[str, Any]]:
        """Identify affected anchor entities from violations
        
        Thesis logic: "identifies the involved entities"
        
        Args:
            violations: list of violations
            previous_snapshot: the last snapshot
            table_def: table definition
            context: processing context
            
        Returns:
            List of affected anchor entities, in the format [{'StudentID': 's1', 'StudentName': 'Alice'}, ...]"""
        if not violations or not previous_snapshot:
            return []
        
        attributes = table_def.get('attributes', table_def.get('fields', []))
        anchor_fk_field = None
        for attr in attributes:
            constraints = attr.get('constraints', {})
            if constraints.get('foreign_key'):
                anchor_fk_field = attr.get('name')
                break  # Take the first foreign key as anchor
        
        if not anchor_fk_field:
            self.logger.warning("Anchor foreign key field not found")
            return []
        
        self.logger.info(f"Using anchor field: {anchor_fk_field}")
        
        affected_anchor_ids = set()
        for violation in violations:
            
            tuple_ids = []
            
            if hasattr(violation, 'affected_tuple_ids') and violation.affected_tuple_ids:
                tuple_ids = violation.affected_tuple_ids
                self.logger.debug(f"  Detected aggregation-type violation; affected tuple count: {len(tuple_ids)}")
            elif hasattr(violation, 'tuple_id') and violation.tuple_id:
                tuple_ids = [violation.tuple_id]
            elif isinstance(violation, dict):
                tuple_ids = violation.get('tuple_ids', [])
            
            for tuple_id in tuple_ids:
                for row in previous_snapshot.rows:
                    if row.tuple_id == tuple_id:
                        if anchor_fk_field in row.cells:
                            anchor_value = row.cells[anchor_fk_field].value
                            affected_anchor_ids.add(anchor_value)
                            self.logger.debug(f"  Identified anchor ID from violation: {anchor_value}")
        
        self.logger.info(f"Identified {len(affected_anchor_ids)} affected anchor IDs: {affected_anchor_ids}")
        
        relation_config = table_def.get('relation_extraction', {})
        reference_tables_data = self._load_reference_tables(relation_config, context)
        
        if not reference_tables_data:
            reference_tables_data = self._get_entity_snapshots_as_reference(context, table_def)
        
        if not reference_tables_data:
            self.logger.warning("Unable to retrieve reference table data")
            return []
        
        anchor_table_name = list(reference_tables_data.keys())[0]
        anchor_entities = reference_tables_data[anchor_table_name]
        
        self.logger.info(f"Retrieved {len(anchor_entities)} entities from reference table {anchor_table_name}")
        
        affected_entities = []
        for entity in anchor_entities:
            entity_id = (entity.get(anchor_fk_field) or 
                        entity.get('ID') or 
                        entity.get('id') or
                        entity.get(f'{anchor_table_name}ID'))
            
            if entity_id in affected_anchor_ids:
                affected_entities.append(entity)
                self.logger.debug(f"  Matched affected entity: {entity}")
        
        self.logger.info(f"Final count: {len(affected_entities)} affected anchor entities identified")
        
        return affected_entities
    
    def _merge_warm_start_results(self, old_rows: List[TableRow], 
                                   new_rows: List[TableRow],
                                   affected_anchors: List[Dict[str, Any]],
                                   table_def: Dict[str, Any]) -> List[TableRow]:
        """Merge warm start results: remove old records involving affected_anchors, add new records, keep irrelevant records
        
        Thesis logic: "Relationship tuples unrelated to the violation are left unchanged"
        
        Args:
            old_rows: old relationship rows
            new_rows: newly extracted relationship rows
            affected_anchors: Affected anchor entities
            table_def: table definition
            
        Returns:
            Merged row list"""
        attributes = table_def.get('attributes', table_def.get('fields', []))
        anchor_fk_field = None
        for attr in attributes:
            constraints = attr.get('constraints', {})
            if constraints.get('foreign_key'):
                anchor_fk_field = attr.get('name')
                break
        
        if not anchor_fk_field:
            self.logger.warning("Anchor field not found; cannot merge precisely; returning deduplicated new records")
            return self._deduplicate_relation_rows(new_rows)
        
        affected_ids = set()
        for anchor in affected_anchors:
            anchor_id = (anchor.get(anchor_fk_field) or 
                        anchor.get('ID') or 
                        anchor.get('id'))
            if anchor_id:
                affected_ids.add(anchor_id)
        
        self.logger.info(f"Starting result merge - affected anchor IDs: {affected_ids}")
        
        unaffected_rows = []
        removed_count = 0
        for row in old_rows:
            if anchor_fk_field in row.cells:
                row_anchor_id = row.cells[anchor_fk_field].value
                if row_anchor_id not in affected_ids:
                    unaffected_rows.append(row)
                else:
                    removed_count += 1
        
        self.logger.info(f"  Kept {len(unaffected_rows)} unaffected records; removed {removed_count} affected records")
        
        merged_rows = unaffected_rows + new_rows
        
        self.logger.info(f"  Added {len(new_rows)} newly extracted records")
        
        unique_rows = self._deduplicate_relation_rows(merged_rows)
        
        self.logger.info(f"Merge complete: {len(old_rows)} original -> {len(unique_rows)} final records (deduplicated)")
        
        return unique_rows

