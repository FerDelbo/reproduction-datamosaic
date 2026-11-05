import os
import re
import json
import logging
from typing import List, Dict, Any, Optional, Type
from pathlib import Path
from abc import ABC, abstractmethod
from datetime import datetime

from ...memory import TableRow, CellData, Fix
from ...core.ids import IdGenerator

from llm.main import get_answer
from llm.utils import load_env_config

from .entity_extractor import EntityExtractor
from .relation_extractor import RelationExtractor

from .utils import ExtractorUtils

try:
    from pydantic import BaseModel, Field, create_model
    from langchain_core.output_parsers import PydanticOutputParser
    from langchain_openai import ChatOpenAI
    from langchain_google_genai import ChatGoogleGenerativeAI
    # from langchain.output_parsers import OutputFixingParser
    from langchain_core.output_parsers import StrOutputParser   
    STRUCTURED_OUTPUT_AVAILABLE = True
except ImportError:
    STRUCTURED_OUTPUT_AVAILABLE = False
    BaseModel = None
    Field = None
    create_model = None


class BaseExtractor:
    
    def __init__(self, extractor_id: str = "BaseExtractor.v1", enable_eae: bool = True):
        """
        Initialize the extractor.

        Args:
            extractor_id: Extractor identifier.
            enable_eae: Enable the EAE strategy (entity-first scan tip appended to
                the entity cold-start prompt). Can be overridden per run via
                `context.enable_eae`.
        """
        self.extractor_id = extractor_id
        self.enable_eae = enable_eae
        self.logger = logging.getLogger('doc2db.extractor')
        
        self.entity_extractor = EntityExtractor(logger=self.logger)
        self.relation_extractor = RelationExtractor(logger=self.logger)
        
        self.utils = ExtractorUtils(logger=self.logger)

    def _get_model_api_config(self, model: str) -> Dict[str, Optional[str]]:
        """Get the API configuration for a given model name.
 
        Args:
            model: Model name.
 
        Returns:
            Dict containing api_base and api_key.
        """
        def _normalize_base_url(url: Optional[str]) -> Optional[str]:
            """Remove trailing /chat/completions - o ChatOpenAI ja adiciona isso sozinho."""
            if not url:
                return None
            url = url.rstrip('/')
            suffix = '/chat/completions'
            if url.endswith(suffix):
                url = url[:-len(suffix)]
            return url
 
        model_lower = model.lower()
        
        if 'deepseek' in model_lower:
            print("DEEPSEEK")
            return {
                'api_base': _normalize_base_url(os.getenv("DEEPSEEK_URL")),
                'api_key': os.getenv("DEEPSEEK_KEY")
            }
        
        elif 'qwen' in model_lower:
            print("qwen")
            return {
                'api_base': _normalize_base_url(os.getenv("QWEN_URL")),
                'api_key': os.getenv("QWEN_KEY")
            }
        
        else:
            env_config = load_env_config()
            raw_base = env_config.get("API_URL") or os.getenv("API_URL") or os.getenv("OPENAI_API_BASE")
            return {
                'api_base': _normalize_base_url(raw_base),
                'api_key': env_config.get("API_KEY") or os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
            }

    
    # def _get_model_api_config(self, model: str) -> Dict[str, Optional[str]]:
    #     """Get the API configuration for a given model name.

    #     Args:
    #         model: Model name.

    #     Returns:
    #         Dict containing api_base and api_key.
    #     """
    #     model_lower = model.lower()
        
    #     if 'deepseek' in model_lower:
    #         print("DEEPSEEK")
    #         return {
    #             'api_base': os.getenv("DEEPSEEK_URL"),
    #             'api_key': os.getenv("DEEPSEEK_KEY")
    #         }
        
    #     elif 'qwen' in model_lower:
    #         print("qwen")
    #         return {
    #             'api_base': os.getenv("QWEN_URL"),
    #             'api_key': os.getenv("QWEN_KEY")
    #         }
        
    #     else:
    #         env_config = load_env_config()
    #         # return {
    #         #     'api_base': os.getenv("API_URL") or os.getenv("OPENAI_API_BASE"),
    #         #     'api_key': os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
    #         # }
    #         return {
    #                 'api_base': env_config.get("API_URL") or os.getenv("API_URL") or os.getenv("OPENAI_API_BASE"),
    #                 'api_key': env_config.get("API_KEY") or os.getenv("API_KEY") or os.getenv("OPENAI_API_KEY")
    #         # }
    #         }
    
    def extract(self, text_contents: List[str], schema: Dict[str, Any], 
                table_name: str, nl_prompt: str = "", context=None, 
                warm_start: bool = False, previous_snapshot=None, 
                violations: List = None, full_schema: Dict[str, Any] = None) -> List[TableRow]:
        """Extract table data from text content.

        Args:
            text_contents: List of text contents (already chunked by the Orchestrator).
            schema: Database schema definition (usually the table-specific schema).
            table_name: Target table name.
            nl_prompt: Natural-language prompt.
            context: Processing context.
            warm_start: Whether to run in warm-start mode.
            previous_snapshot: Previous data snapshot.
            violations: Violations that require re-extraction.
            full_schema: Full database schema definition (all tables and relations).

        Returns:
            List of extracted table rows.
        """
        self.logger.info(f"Starting extraction for table {table_name} (EAE={'on' if self._is_eae_enabled(context) else 'off'})")
        
        if isinstance(schema, str):
            if not schema.strip():
                actual_schema = self.utils.generate_default_schema_from_prompt(table_name, nl_prompt)
            else:
                try:
                    actual_schema = json.loads(schema)
                except Exception as e:
                    raise ValueError(f"Invalid schema format: {e}")
        else:
            actual_schema = schema
        
        table_def = self._get_table_definition(actual_schema, table_name)
        if not table_def:
            raise ValueError(f"Table definition not found: {table_name}")
        
        document_names = []
        if context and hasattr(context, 'documents'):
            document_names = [os.path.basename(doc_path) for doc_path in context.documents]
        
        all_rows = []
        
        if warm_start and violations and previous_snapshot and len(text_contents) > 1:
            self.logger.info(f"[Warm Start batch] Processing fixes for {len(text_contents)} documents at once")
            
            try:
                all_rows = self._batch_warm_start_fix(
                    text_contents, table_def, nl_prompt, document_names,
                    context, previous_snapshot, violations
                )
                self.logger.info(f"[Warm Start batch] Done, fixed {len(all_rows)} rows")
                return all_rows
            except Exception as e:
                self.logger.error(f"[Warm Start batch] Failed: {e}, falling back to per-document processing")
        
        current_snapshot = previous_snapshot
        
        for i, text_content in enumerate(text_contents):
            doc_name = document_names[i] if i < len(document_names) else f"doc{i+1}"
            
            if not text_content or not text_content.strip():
                self.logger.warning(f"Text content {i} ({doc_name}) is empty, skipping")
                continue
            
            try:
                if warm_start and violations and current_snapshot:
                    doc_rows = self._extract_with_warm_start(
                        text_content, table_def, nl_prompt, doc_name, context, i,
                        current_snapshot, violations
                    )
                else:
                    doc_rows = self._extract_with_cold_start(
                        text_content, table_def, nl_prompt, doc_name, context, i, full_schema
                    )
                
                all_rows.extend(doc_rows)
                
                if warm_start and doc_rows:
                    from ...memory.snapshot import TableSnapshot
                    from ...core.io import IOManager
                    current_snapshot = TableSnapshot(
                        run_id=f"temp_fix_{i}",
                        table=table_name,
                        rows=all_rows,
                        created_at=IOManager.get_timestamp(),
                        table_id=previous_snapshot.table_id if hasattr(previous_snapshot, 'table_id') else table_name
                    )
                
            except Exception as e:
                self.logger.error(f"Failed to process text content {i} ({doc_name}): {e}")
                continue
        
        all_rows = self.utils.deduplicate_rows(all_rows)
        
        self.logger.info(f"Extracted {len(all_rows)} rows in total")
        return all_rows
    
    def _is_eae_enabled(self, context=None) -> bool:
        """Resolve whether EAE is on: context.enable_eae overrides the constructor default."""
        if context is not None and getattr(context, 'enable_eae', None) is not None:
            return bool(context.enable_eae)
        return self.enable_eae

    def _extract_with_cold_start(self, text_content: str, table_def: Dict[str, Any],
                               nl_prompt: str, doc_source: str, context=None, 
                               doc_index: int = 0, full_schema: Dict[str, Any] = None) -> List[TableRow]:
        """
        Cold Start extraction entry point - dispatches to entity or relation extraction by table type.

        Args:
            text_content: Text content.
            table_def: Table definition.
            nl_prompt: Natural-language prompt.
            doc_source: Document source.
            context: Processing context.
            doc_index: Document index.
            full_schema: Full schema.

        Returns:
            List of extracted table rows.
        """
        table_type = table_def.get('type', 'entity').lower()
        table_name = table_def.get('name', 'data_table')
        
        relation_extraction_config = table_def.get('relation_extraction', {})
        is_relation_table = (table_type in ['relation', 'relationship'] or 
                            relation_extraction_config.get('enabled', False))
        
        if is_relation_table:
            self.logger.info(f"[Cold Start] Relation table extraction: {table_name}")
            return self.relation_extractor.extract_cold_start(
                text_content, table_def, nl_prompt, doc_source, 
                context, doc_index, full_schema,
                get_model_api_config_func=self._get_model_api_config,
                create_list_model_func=self._create_list_model_from_schema,
                build_schema_context_func=self._build_schema_context,
                parse_structured_response_func=self._parse_structured_response,
                record_extraction_step_func=self._record_extraction_step,
                fallback_func=self._extract_with_fallback
            )
        else:
            eae = self._is_eae_enabled(context)
            self.logger.info(f"[Cold Start] EAE {'ENABLED' if eae else 'DISABLED'} for table {table_name}")
            self.logger.info(f"[Cold Start] Entity table extraction: {table_name}")
            return self.entity_extractor.extract_cold_start(
                text_content, table_def, nl_prompt, doc_source, 
                context, doc_index, full_schema,
                get_model_api_config_func=self._get_model_api_config,
                create_list_model_func=self._create_list_model_from_schema,
                build_schema_context_func=self._build_schema_context,
                parse_structured_response_func=self._parse_structured_response,
                record_extraction_step_func=self._record_extraction_step,
                enable_strategy=eae,
                fallback_func=self._extract_with_fallback
            )
    
    def _extract_with_warm_start(self, text_content: str, table_def: Dict[str, Any],
                                nl_prompt: str, doc_source: str, context=None, 
                                doc_index: int = 0, previous_snapshot=None, 
                                violations: List = None) -> List[TableRow]:
        """
        Warm Start extraction entry point - dispatches to entity or relation warm-start extraction by table type.

        Args:
            text_content: Text content.
            table_def: Table definition.
            nl_prompt: Natural-language prompt.
            doc_source: Document source.
            context: Processing context.
            doc_index: Document index.
            previous_snapshot: Previous data snapshot.
            violations: Violations to fix.

        Returns:
            List of fixed table rows.
        """
        table_type = table_def.get('type', 'entity').lower()
        table_name = table_def.get('name') or table_def.get('table_name', 'unknown')
        
        relation_extraction_config = table_def.get('relation_extraction', {})
        is_relation_table = (table_type in ['relation', 'relationship'] or 
                            relation_extraction_config.get('enabled', False))
        
        if is_relation_table:
            self.logger.info(f"[Warm Start] Relation table fix: {table_name}")
            return self.relation_extractor.extract_warm_start(
                text_content, table_def, nl_prompt, doc_source, 
                context, doc_index, previous_snapshot, violations,
                check_warm_start_limit_func=self._check_warm_start_limit,
                identify_cells_from_violations_func=self._identify_cells_from_violations,
                build_cell_fix_prompt_func=self._build_cell_fix_prompt,
                parse_cell_fix_json_func=self.utils.parse_cell_fix_json,
                apply_cell_fixes_func=self._apply_cell_fixes
            )
        else:
            self.logger.info(f"[Warm Start] Entity table fix: {table_name}")
            return self.entity_extractor.extract_warm_start(
                text_content, table_def, nl_prompt, doc_source, 
                context, doc_index, previous_snapshot, violations,
                check_warm_start_limit_func=self._check_warm_start_limit,
                identify_cells_from_violations_func=self._identify_cells_from_violations,
                build_cell_fix_prompt_func=self._build_cell_fix_prompt,
                parse_cell_fix_json_func=self.utils.parse_cell_fix_json,
                apply_cell_fixes_func=self._apply_cell_fixes
            )
    
    def _extract_with_fallback(self, text_content: str, table_def: Dict[str, Any],
                              nl_prompt: str, doc_source: str, context=None,
                              doc_index: int = 0) -> List[TableRow]:
        """Fallback extraction strategy - uses a simple Markdown table format."""
        self.logger.info(f"[Fallback extraction] Using Markdown table format")
        
        rows = []
        attributes = table_def.get('attributes', [])
        
        schema_info = self.utils.build_simple_schema_prompt(table_def)
        
        system_prompt = """You are a professional data extraction expert. 
Your role is to read documents carefully and extract structured data with high accuracy and recall."""
        
        prompt = f"""Extract structured data from the following document according to the schema.

{schema_info}

Return the data in a Markdown table format:

<TABLE BEGIN>
| {attributes[0]['name'] if attributes else 'field1'} | {attributes[1]['name'] if len(attributes) > 1 else 'field2'} | ... |
|---|---|---|
| value1 | value2 | ... |
<TABLE END>

Document Content:
{text_content}

Additional Instructions: {nl_prompt if nl_prompt else 'No special requirements'}
"""
        
        try:
            model = context.model if context and hasattr(context, 'model') else "gpt-4o"
            llm_response = get_answer(prompt, system_prompt=system_prompt, model=model)
            
            extracted_data = self.utils.parse_markdown_table_response(llm_response, table_def, doc_source)
            rows.extend(extracted_data)
            
            self.logger.info(f"[Fallback extraction] Obtained {len(extracted_data)} rows")
            
        except Exception as e:
            self.logger.error(f"[Fallback extraction] Failed: {e}")
        
        return rows
    
    def _parse_structured_response(self, llm_response: str, fixing_parser, 
                                   table_name: str, doc_source: str) -> List[TableRow]:
        """Parse the LLM's structured response and convert it to TableRow format."""
        try:
            result = fixing_parser.parse(llm_response)
            
            rows_data = []
            if hasattr(result, 'rows'):
                for row in result.rows:
                    if hasattr(row, 'model_dump'):
                        row_dict = row.model_dump()
                    elif hasattr(row, 'dict'):
                        row_dict = row.dict()
                    else:
                        row_dict = dict(row)
                    rows_data.append(row_dict)
            
            self.logger.info(f"Successfully parsed {len(rows_data)} rows")
            
            rows = []
            for i, row_dict in enumerate(rows_data):
                tuple_id = IdGenerator.generate_tuple_id(table_name, i, row_dict)
                
                cells = {}
                for field_name, value in row_dict.items():
                    if value is not None:
                        cells[field_name] = CellData(
                            value=value,
                            evidences=[doc_source]
                        )
                
                if cells:
                    table_row = TableRow(tuple_id=tuple_id, cells=cells)
                    rows.append(table_row)
            
            return rows
            
        except Exception as parse_error:
            self.logger.error(f"Parsing failed: {parse_error}")
            return []
    
    def _record_extraction_step(self, context, table_name: str, doc_index: int, 
                                doc_source: str, extraction_mode: str, model: str,
                                prompt: str, llm_response: str, row_count: int):
        """Record the extraction step to context."""
        if context and hasattr(context, 'step_outputs'):
            from ...core.io import IOManager
            context.step_outputs.append({
                'step': f'extractor_{table_name}_{doc_index}',
                'status': 'completed',
                'description': f"Document {doc_index+1} ({os.path.basename(doc_source)}) [table: {table_name}]",
                'details': {
                    'document': os.path.basename(doc_source),
                    'table_name': table_name,
                    'extraction_mode': extraction_mode,
                    'extracted_rows': row_count,
                    'model_used': model,
                    'eae_enabled': self._is_eae_enabled(context),
                    'llm_input': prompt[:1000] + '...' if len(prompt) > 1000 else prompt,
                    'llm_output': llm_response[:1000] + '...' if len(llm_response) > 1000 else llm_response,
                },
                'timestamp': IOManager.get_timestamp()
            })
    
    def _check_warm_start_limit(self, context, table_name: str) -> bool:
        """Check the warm-start limit and return whether processing can continue."""
        if context and hasattr(context, 'coordinator'):
            coordinator = context.coordinator
            current_batch_index = getattr(context, 'current_batch_index', 1)
            
            if not coordinator.get_table_tracker(table_name):
                coordinator.init_table_tracker(table_name, total_batches=1)
            
            table_tracker = coordinator.get_table_tracker(table_name)
            if current_batch_index not in table_tracker.batch_trackers:
                coordinator.init_batch_tracker(table_name, current_batch_index, 1)
            
            if not coordinator.can_batch_warm_start(table_name, current_batch_index):
                self.logger.warning(f'Table {table_name} batch {current_batch_index} reached the maximum warm-start attempts')
                return False
            
            coordinator.increment_batch_warm_start_count(table_name, current_batch_index)
        
        return True
    
    def _batch_warm_start_fix(self, text_contents: List[str], table_def: Dict[str, Any],
                             nl_prompt: str, document_names: List[str],
                             context=None, previous_snapshot=None, 
                             violations: List = None) -> List[TableRow]:
        """Batch warm-start fix - processes multiple documents at once."""
        table_name = table_def.get('name') or table_def.get('table_name', 'unknown')
        
        if context and hasattr(context, 'coordinator'):
            coordinator = context.coordinator
            current_batch_index = getattr(context, 'current_batch_index', 1)
            
            if not coordinator.get_table_tracker(table_name):
                coordinator.init_table_tracker(table_name, total_batches=1)
            
            table_tracker = coordinator.get_table_tracker(table_name)
            if current_batch_index not in table_tracker.batch_trackers:
                coordinator.init_batch_tracker(table_name, current_batch_index, 1)
            
            if not coordinator.can_batch_warm_start(table_name, current_batch_index):
                self.logger.warning(f'Table {table_name} batch {current_batch_index} reached the maximum warm-start attempts')
                return previous_snapshot.rows if previous_snapshot else []
            
            coordinator.increment_batch_warm_start_count(table_name, current_batch_index)
        
        cells_to_fix = self._identify_cells_from_violations(violations, previous_snapshot)
        
        if not cells_to_fix:
            return previous_snapshot.rows if previous_snapshot else []
        
        extraction_prompt = self._build_batch_cell_fix_prompt(
            cells_to_fix, table_def, previous_snapshot, nl_prompt, len(text_contents)
        )
        
        system_prompt = """You are a data extraction expert specializing in fixing data quality issues across multiple documents.
Your task is to analyze ALL documents and extract ONLY the specified field values that need correction.
Output in strict JSON format with the structure: {"fixes": [{"tuple_id": "...", "field": "...", "new_value": "..."}]}
"""
        
        try:
            model = context.model if context and hasattr(context, 'model') else "gpt-4o"
            
            documents_section = "\n\nDocuments Content:\n"
            for i, (text_content, doc_name) in enumerate(zip(text_contents, document_names)):
                if text_content and text_content.strip():
                    documents_section += f"\n=== Document {i+1}: {doc_name} ===\n{text_content}\n"
            
            full_prompt = f"""{extraction_prompt}
{documents_section}

Remember: 
- Analyze ALL {len(text_contents)} documents
- Output ONLY in JSON format with the structure shown above
- Extract accurate values for each field that needs correction
"""
            
            llm_response = get_answer(full_prompt, system_prompt=system_prompt, model=model)
            
            fixes_data = self.utils.parse_cell_fix_json(llm_response)
            
            if not fixes_data:
                return previous_snapshot.rows if previous_snapshot else []
            
            doc_sources = ", ".join(document_names)
            updated_rows, fix_records = self._apply_cell_fixes(
                previous_snapshot.rows if previous_snapshot else [],
                fixes_data,
                f"[Batch: {doc_sources}]",
                table_name
            )
            
            if context and hasattr(context, 'step_outputs'):
                from ...core.io import IOManager
                context.step_outputs.append({
                    'step': f'extractor_batch_warm_start_{table_name}',
                    'status': 'completed',
                    'description': f"[Batch Warm Start] Processed {len(text_contents)} documents at once [table: {table_name}]",
                    'details': {
                        'documents_count': len(text_contents),
                        'documents': document_names,
                        'table_name': table_name,
                        'mode': 'batch_warm_start',
                        'cells_identified': len(cells_to_fix),
                        'cells_fixed': len(fixes_data),
                        'total_rows': len(updated_rows),
                        'model_used': model,
                    },
                    'timestamp': IOManager.get_timestamp()
                })
            
            return updated_rows
            
        except Exception as e:
            self.logger.error(f"[Batch Warm Start] Failed: {e}")
            raise
    
    
    def _get_table_definition(self, schema: Dict[str, Any], table_name: str) -> Optional[Dict[str, Any]]:
        """Get the table definition."""
        tables = schema.get('tables', [])
        
        for table in tables:
            if table.get('name') == table_name:
                result = table.copy()
                if 'fields' in result and 'attributes' not in result:
                    result['attributes'] = result.pop('fields')
                return result
        
        if '_' in table_name and table_name.rsplit('_', 1)[-1].isdigit():
            base_name = table_name.rsplit('_', 1)[0]
            suffix_num = int(table_name.rsplit('_', 1)[1])
            
            matching_tables = [t for t in tables if isinstance(t, dict) and t.get('name') == base_name]
            
            if matching_tables and 1 <= suffix_num <= len(matching_tables):
                target_table = matching_tables[suffix_num - 1]
                result = target_table.copy()
                if 'fields' in result and 'attributes' not in result:
                    result['attributes'] = result.pop('fields')
                return result
        
        return None
    
    def _create_pydantic_model_from_schema(self, schema: Dict[str, Any], 
                                          table_name: str) -> Optional[Type]:
        """Dynamically create a Pydantic model from the schema."""
        if not STRUCTURED_OUTPUT_AVAILABLE:
            return None
        
        try:
            table_def = self._get_table_definition(schema, table_name)
            if not table_def:
                return None
            
            attributes = table_def.get('attributes', [])
            field_definitions = {}
            
            for attr in attributes:
                field_name = attr['name']
                field_type = attr.get('type', 'VARCHAR')
                field_desc = attr.get('description', '')
                
                if 'VARCHAR' in field_type or 'TEXT' in field_type or 'ENUM' in field_type or 'string' in field_type.lower():
                    python_type = str
                elif 'INT' in field_type or 'integer' in field_type.lower():
                    python_type = int
                elif 'DECIMAL' in field_type or 'FLOAT' in field_type or 'number' in field_type.lower():
                    python_type = float
                elif 'BOOLEAN' in field_type or 'boolean' in field_type.lower():
                    python_type = bool
                elif 'DATE' in field_type or 'date' in field_type.lower():
                    python_type = str
                else:
                    python_type = str
                
                if not attr.get('required', False):
                    python_type = Optional[python_type]
                
                field_definitions[field_name] = (python_type, Field(description=field_desc, default=None))
            
            model_class = create_model(table_name, **field_definitions)
            return model_class
            
        except Exception as e:
            self.logger.error(f"Failed to create Pydantic model: {e}")
            return None
    
    def _create_list_model_from_schema(self, schema: Dict[str, Any], 
                                      table_name: str) -> Optional[Type]:
        """Create a list model containing multiple rows of data."""
        if not STRUCTURED_OUTPUT_AVAILABLE:
            return None
        
        try:
            row_model = self._create_pydantic_model_from_schema(schema, table_name)
            if not row_model:
                return None
            
            list_model = create_model(
                f"{table_name}List",
                rows=(List[row_model], Field(description=f"List of {table_name} records"))
            )
            
            return list_model
            
        except Exception as e:
            self.logger.error(f"Failed to create list model: {e}")
            return None
    
    def _build_schema_context(self, table_def: Dict[str, Any], nl_prompt: str = "", full_schema: Dict[str, Any] = None) -> str:
        """Build the schema context."""
        table_name = table_def.get('name', 'data_table')
        attributes = table_def.get('attributes', [])
        
        context_parts = []
        
        context_parts.append(f"Target Table: {table_name}")
        
        table_type = table_def.get('type', '')
        if table_type:
            context_parts.append(f"Type: {table_type}")
        
        table_desc = table_def.get('description', '')
        if table_desc:
            context_parts.append(f"Description: {table_desc}")
        
        if attributes:
            context_parts.append(f"Fields ({len(attributes)}):")
            for attr in attributes:
                field_name = attr.get('name', 'unknown')
                field_type = attr.get('type', 'VARCHAR')
                field_desc = attr.get('description', '')
                constraints = attr.get('constraints', {})
                
                constraint_info = []
                
                if constraints.get('primary_key'):
                    constraint_info.append('PK')
                if constraints.get('foreign_key'):
                    constraint_info.append('FK')
                if constraints.get('unique'):
                    constraint_info.append('UNIQUE')
                if not constraints.get('nullable', True):
                    constraint_info.append('NOT NULL')
                
                if attr.get('required', False) and 'NOT NULL' not in constraint_info:
                    constraint_info.append('REQUIRED')
                if attr.get('unique', False) and 'UNIQUE' not in constraint_info:
                    constraint_info.append('UNIQUE')
                
                if 'domain' in attr:
                    domain_values = attr['domain']
                    if isinstance(domain_values, list):
                        constraint_info.append(f"domain={domain_values}")
                    else:
                        constraint_info.append(f"domain={domain_values}")
                
                if 'format' in attr:
                    constraint_info.append(f"format='{attr['format']}'")
                
                if 'min' in attr:
                    constraint_info.append(f"min={attr['min']}")
                if 'max' in attr:
                    constraint_info.append(f"max={attr['max']}")
                
                constraint_str = f" [{', '.join(constraint_info)}]" if constraint_info else ""
                context_parts.append(f"  - {field_name} ({field_type}){constraint_str}: {field_desc}")
        
        if table_type and table_type.lower() == 'relationship' and full_schema:
            relations_info = self._build_relations_context(table_name, full_schema)
            if relations_info:
                context_parts.append("\nTable Relationships:")
                context_parts.append(relations_info)
        
        return "\n".join(context_parts)
    
    def _build_relations_context(self, table_name: str, full_schema: Dict[str, Any]) -> str:
        """Build table relationship context (mirrors the relation_extractor.py implementation).

        Extracts relations relevant to the current table from the schema's relations
        section to help the LLM understand which entity tables this relation table connects.
        """
        if not full_schema:
            return ""
        
        relations = full_schema.get('relations', [])
        if not relations:
            return ""
        
        relevant_relations = []
        for relation in relations:
            if not isinstance(relation, dict):
                continue
            
            from_info = relation.get('from', {})
            to_info = relation.get('to', {})
            
            if (from_info.get('table') == table_name or 
                to_info.get('table') == table_name):
                relevant_relations.append(relation)
        
        if not relevant_relations:
            return ""
        
        relation_lines = []
        for relation in relevant_relations:
            from_info = relation.get('from', {})
            to_info = relation.get('to', {})
            relation_type = relation.get('type', 'unknown')
            relation_id = relation.get('id', '')
            
            from_table = from_info.get('table', '')
            from_field = from_info.get('field', '')
            to_table = to_info.get('table', '')
            to_field = to_info.get('field', '')
            
            if from_table and from_field and to_table and to_field:
                relation_desc = f"  - {from_table}.{from_field} → {to_table}.{to_field} ({relation_type})"
                if relation_id:
                    relation_desc += f" [ID: {relation_id}]"
                relation_lines.append(relation_desc)
        
        return "\n".join(relation_lines)
    
    
    
    def _identify_cells_from_violations(self, violations: List, 
                                       previous_snapshot) -> List[Dict[str, Any]]:
        """Identify the cells that need fixing from violations."""
        cells_to_fix = []
        
        if not violations or not previous_snapshot:
            return cells_to_fix
        
        rows_map = {row.tuple_id: row for row in previous_snapshot.rows}
        
        for violation in violations:
            tuple_id = getattr(violation, 'tuple_id', '')
            field = getattr(violation, 'attr', '')
            constraint_type = getattr(violation, 'constraint_type', '').upper()
            description = getattr(violation, 'description', '')
            
            current_value = None
            if tuple_id in rows_map and field in rows_map[tuple_id].cells:
                current_value = rows_map[tuple_id].cells[field].value
            
            cells_to_fix.append({
                'tuple_id': tuple_id,
                'field': field,
                'current_value': current_value,
                'violation_id': getattr(violation, 'id', ''),
                'violation_desc': description,
                'constraint_type': constraint_type
            })
        
        return cells_to_fix
    
    def _build_cell_fix_prompt(self, cells_to_fix: List[Dict[str, Any]], 
                              table_def: Dict[str, Any],
                              previous_snapshot, nl_prompt: str) -> str:
        """Build the cell-level fix prompt."""
        table_name = table_def.get('name', 'unknown_table')
        
        rows_map = {}
        if previous_snapshot and previous_snapshot.rows:
            rows_map = {row.tuple_id: row for row in previous_snapshot.rows}
        
        cell_list = []
        for i, cell in enumerate(cells_to_fix[:20]):
            tuple_id = cell['tuple_id']
            field = cell['field']
            current_value = cell['current_value']
            issue = cell['violation_desc'][:100]
            
            row_context = ""
            if tuple_id in rows_map:
                row = rows_map[tuple_id]
                context_values = []
                for field_name, cell_data in row.cells.items():
                    if field_name != field:
                        context_values.append(f"{field_name}='{cell_data.value}'")
                if context_values:
                    row_context = f" | Row Context: {', '.join(context_values[:5])}"
            
            cell_list.append(
                f"  {i+1}. tuple_id: {tuple_id}, field: {field}, "
                f"current_value: {current_value}{row_context}\n"
                f"      Issue: {issue}"
            )
        
        if len(cells_to_fix) > 20:
            cell_list.append(f"  ... {len(cells_to_fix) - 20} more cells need to be fixed")
        
        attributes = table_def.get('attributes', [])
        field_definitions = []
        for attr in attributes:
            field_definitions.append(
                f"  - {attr['name']} ({attr.get('type', 'TEXT')}): {attr.get('description', 'N/A')}"
            )
        
        prompt = f"""Task: Fix problematic cell values in table [{table_name}]

[Field Definitions]
{chr(10).join(field_definitions)}

[Cells to Fix] Total: {len(cells_to_fix)} cells
{chr(10).join(cell_list)}

[Task Requirements]
1. Carefully read the document content to find clues related to the cells above
2. Locate cells to fix based on tuple_id + field
3. Use "row context" information to accurately match the corresponding data
4. Extract accurate corrected values from the document
5. If the information is not found in the document, output null

Output strictly in the following JSON format:
{{
  "fixes": [
    {{
      "tuple_id": "Original tuple_id from the data",
      "field": "Field name",
      "new_value": "Corrected value extracted from document (or null)"
    }}
  ]
}}

[Important Notes]
- Output ONLY JSON, do not add any other text
- tuple_id must exactly match those listed above
- field must exist in the field definitions
- Prevent mismatches: Use "row context" to accurately locate the data
"""
        
        if nl_prompt and nl_prompt.strip():
            prompt += f"\n\n[Additional User Requirements]\n{nl_prompt}\n"
        
        return prompt
    
    def _build_batch_cell_fix_prompt(self, cells_to_fix: List[Dict[str, Any]], 
                                    table_def: Dict[str, Any],
                                    previous_snapshot, nl_prompt: str,
                                    document_count: int) -> str:
        """Build the batch cell-fix prompt."""
        table_name = table_def.get('name', 'unknown_table')
        
        rows_map = {}
        if previous_snapshot and previous_snapshot.rows:
            rows_map = {row.tuple_id: row for row in previous_snapshot.rows}
        
        cell_list = []
        for i, cell in enumerate(cells_to_fix[:50]):
            tuple_id = cell['tuple_id']
            field = cell['field']
            current_value = cell['current_value']
            issue = cell['violation_desc'][:100]
            
            row_context = ""
            if tuple_id in rows_map:
                row = rows_map[tuple_id]
                context_values = []
                for field_name, cell_data in row.cells.items():
                    if field_name != field:
                        context_values.append(f"{field_name}='{cell_data.value}'")
                if context_values:
                    row_context = f" | Row Context: {', '.join(context_values[:5])}"
            
            cell_list.append(
                f"  {i+1}. tuple_id: {tuple_id}, field: {field}, "
                f"current_value: {current_value}{row_context}\n"
                f"      Issue: {issue}"
            )
        
        if len(cells_to_fix) > 50:
            cell_list.append(f"  ... {len(cells_to_fix) - 50} more cells need to be fixed")
        
        attributes = table_def.get('attributes', [])
        field_definitions = []
        for attr in attributes:
            field_definitions.append(
                f"  - {attr['name']} ({attr.get('type', 'TEXT')}): {attr.get('description', 'N/A')}"
            )
        
        prompt = f"""Task: Batch fix problematic cell values in table [{table_name}]

Document Count: {document_count} documents will be analyzed together

[Field Definitions]
{chr(10).join(field_definitions)}

[Cells to Fix] Total: {len(cells_to_fix)} cells
{chr(10).join(cell_list)}

[Task Requirements]
1. Carefully read the content of **ALL {document_count} documents**
2. Accurately locate cells to fix based on tuple_id + field
3. Use "row context" information to extract corresponding data from the correct document
4. If the information is not found in any document, output null

Output strictly in the following JSON format:
{{
  "fixes": [
    {{
      "tuple_id": "Original tuple_id from the data",
      "field": "Field name",
      "new_value": "Corrected value extracted from document (or null)"
    }}
  ]
}}

[Important Notes]
- Output ONLY JSON
- tuple_id must exactly match
- field must exist in the field definitions
- Prevent mismatches: Must use "row context" to accurately locate the data
"""
        
        if nl_prompt and nl_prompt.strip():
            prompt += f"\n\n[Additional User Requirements]\n{nl_prompt}\n"
        
        return prompt
    
    
    def _apply_cell_fixes(self, original_rows: List[TableRow], 
                         fixes_data: List[Dict[str, Any]],
                         doc_source: str,
                         table_name: str = None) -> tuple[List[TableRow], List]:
        """Apply fixes at the cell level."""
        rows_map = {row.tuple_id: row for row in original_rows}
        
        applied_count = 0
        skipped_count = 0
        fix_records = []
        
        for fix_data in fixes_data:
            tuple_id = fix_data.get('tuple_id', '')
            field = fix_data.get('field', '')
            new_value = fix_data.get('new_value')
            
            if new_value is None or new_value == 'null':
                skipped_count += 1
                continue
            
            if tuple_id not in rows_map:
                skipped_count += 1
                continue
            
            row = rows_map[tuple_id]
            old_value = None
            
            if field in row.cells:
                old_value = row.cells[field].value
                row.cells[field].value = new_value
                if hasattr(row.cells[field], 'evidences'):
                    row.cells[field].evidences.append(f"[Warm Start Fix] {doc_source}")
            else:
                old_value = None
                row.cells[field] = CellData(
                    value=new_value,
                    evidences=[f"[Warm Start Fix] {doc_source}"]
                )
            
            fix_record = Fix(
                id=IdGenerator.generate_fix_id(
                    table=table_name or 'unknown',
                    tuple_id=tuple_id,
                    attr=field,
                    fix_type='warm_start_extraction',
                    old_value=old_value
                ),
                table=table_name or 'unknown',
                tuple_id=tuple_id,
                attr=field,
                old=old_value,
                new=new_value,
                fix_type='warm_start_extraction',
                applied_by='BaseExtractor',
                timestamp=datetime.now().isoformat(),
                fix_success=True,
                failure_reason=''
            )
            fix_records.append(fix_record)
            
            applied_count += 1
        
        self.logger.info(f"Applied fixes: {applied_count} succeeded, {skipped_count} skipped")
        
        return list(rows_map.values()), fix_records
    
    
    def _apply_document_filter(self, text_contents: List[str], document_names: List[str], 
                               table_def: Dict[str, Any]) -> tuple:
        """Filter the document list based on the document-filter config in the table definition.

        Args:
            text_contents: List of document contents.
            document_names: List of document names.
            table_def: Table definition.

        Returns:
            (filtered text_contents, filtered document_names).
        """
        doc_filter = None
        
        if 'relation_extraction' in table_def:
            relation_config = table_def['relation_extraction']
            if isinstance(relation_config, dict) and 'document_filter' in relation_config:
                doc_filter = relation_config['document_filter']
        
        if not doc_filter and 'document_filter' in table_def:
            doc_filter = table_def['document_filter']
        
        if not doc_filter:
            return text_contents, document_names
        
        mode = doc_filter.get('mode', 'include')  # include or exclude
        patterns = doc_filter.get('patterns', [])
        
        if not patterns:
            return text_contents, document_names
        
        self.logger.info(f"Applying document filter: mode={mode}, patterns={patterns}")
        self.logger.info(f"   Input document counts: text_contents={len(text_contents)}, document_names={len(document_names)}")
        
        filtered_contents = []
        filtered_names = []
        
        for i, doc_name in enumerate(document_names):
            matches = any(pattern in doc_name for pattern in patterns)
            
            self.logger.debug(f"  Document: {doc_name}, matches: {matches}")
            for pattern in patterns:
                self.logger.debug(f"    Checking pattern '{pattern}' in '{doc_name}': {pattern in doc_name}")
            
            should_keep = (mode == 'include' and matches) or (mode == 'exclude' and not matches)
            
            if should_keep:
                if i < len(text_contents):
                    filtered_contents.append(text_contents[i])
                    filtered_names.append(doc_name)
                    self.logger.info(f"  Kept document: {doc_name}")
                else:
                    self.logger.warning(f"  Document index out of range: i={i}, len(text_contents)={len(text_contents)}")
            else:
                self.logger.info(f"  Filtered out document: {doc_name}")
        
        self.logger.info(f"Document filtering complete: {len(document_names)} -> {len(filtered_names)} documents")
        
        return filtered_contents, filtered_names
    
    def supports_format(self, file_path: str) -> bool:
        """Check whether the given file format is supported."""
        supported_extensions = {'.txt', '.md', '.csv', '.json'}
        file_ext = Path(file_path).suffix.lower()
        return file_ext in supported_extensions
