"""
Entity extractor module.
Extracts entity-table data from documents (Cold Start and Warm Start).
"""
import os
import logging
from typing import List, Dict, Any, Optional

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


class EntityExtractor:
    """Entity extractor - handles data extraction for entity tables."""
    
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger('doc2db.extractor.entity')
    
    def extract_cold_start(self, text_content: str, table_def: Dict[str, Any],
                          nl_prompt: str, doc_source: str, context=None,
                          doc_index: int = 0, full_schema: Dict[str, Any] = None,
                          get_model_api_config_func=None,
                          create_list_model_func=None,
                          build_schema_context_func=None,
                          parse_structured_response_func=None,
                          record_extraction_step_func=None,
                          enable_strategy = True,
                          fallback_func=None) -> List[TableRow]:
        """
        Cold Start extraction for entity tables.

        Uses LangChain structured output for entity extraction:
        - PydanticOutputParser ensures a correct output format.
        - OutputFixingParser automatically repairs format errors.
        - Higher precision and recall.
        """
        if not STRUCTURED_OUTPUT_AVAILABLE:
            return fallback_func(text_content, table_def, nl_prompt, doc_source, context, doc_index)
        
        try:
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
            
            prompt = f"""Please extract structured data from the following text according to the schema for table "{table_name}".

{schema_context}

Extract ALL relevant records for the "{table_name}" table from the document. Each record should be a separate item in the list.

Text content:
{text_content}

{parser.get_format_instructions()}

IMPORTANT: 
- Return a JSON object with a "rows" field containing a list of all extracted records for "{table_name}".
- Extract EVERY occurrence of relevant data for this table, even if mentioned multiple times.
"""

            if enable_strategy:
                prompt += """
                
TIPS: Scan the document to find all entities first, then extract their complete details.

"""
            if nl_prompt and nl_prompt.strip():
                prompt += f"\nAdditional Instructions: {nl_prompt}\n"
            
            response = llm.invoke(prompt)
            llm_response = response.content
            
            self.logger.info(f"[Entity extraction] LLM response length: {len(llm_response)}")
            
            rows = parse_structured_response_func(
                llm_response, fixing_parser, table_name, doc_source
            )
            
            record_extraction_step_func(
                context, table_name, doc_index, doc_source, 
                'entity_extraction', model, prompt, llm_response, len(rows)
            )
            
            return rows
            
        except Exception as e:
            self.logger.error(f"[Entity extraction] Exception: {e}")
            import traceback
            traceback.print_exc()
            return fallback_func(text_content, table_def, nl_prompt, doc_source, context, doc_index)
    
    def extract_warm_start(self, text_content: str, table_def: Dict[str, Any],
                          nl_prompt: str, doc_source: str, context=None,
                          doc_index: int = 0, previous_snapshot=None,
                          violations: List = None,
                          check_warm_start_limit_func=None,
                          identify_cells_from_violations_func=None,
                          build_cell_fix_prompt_func=None,
                          parse_cell_fix_json_func=None,
                          apply_cell_fixes_func=None) -> List[TableRow]:
        """
        Warm Start extraction for entity tables - precise cell-level fixes.
        """
        table_name = table_def.get('name') or table_def.get('table_name', 'unknown')
        
        if not check_warm_start_limit_func(context, table_name):
            return previous_snapshot.rows if previous_snapshot else []
        
        cells_to_fix = identify_cells_from_violations_func(violations, previous_snapshot)
        
        if not cells_to_fix:
            return previous_snapshot.rows if previous_snapshot else []
        
        extraction_prompt = build_cell_fix_prompt_func(
            cells_to_fix, table_def, previous_snapshot, nl_prompt
        )
        
        system_prompt = """You are a data extraction expert specializing in fixing data quality issues.
Your task is to analyze the document and extract ONLY the specified field values that need correction.
Output in strict JSON format with the structure: {"fixes": [{"tuple_id": "...", "field": "...", "new_value": "..."}]}
"""
        
        try:
            model = context.model if context and hasattr(context, 'model') else "gpt-4o"
            
            full_prompt = f"""{extraction_prompt}

Document Content:
{text_content}

Remember: Output ONLY in JSON format with the structure shown above.
"""
            
            llm_response = get_answer(full_prompt, system_prompt=system_prompt, model=model)
            
            fixes_data = parse_cell_fix_json_func(llm_response)
            
            if not fixes_data:
                return previous_snapshot.rows if previous_snapshot else []
            
            updated_rows, fix_records = apply_cell_fixes_func(
                previous_snapshot.rows if previous_snapshot else [],
                fixes_data,
                doc_source,
                table_name
            )
            
            if context and hasattr(context, 'step_outputs'):
                from ...core.io import IOManager
                context.step_outputs.append({
                    'step': f'extractor_warm_start_{doc_index+1}_{table_name}',
                    'status': 'completed',
                    'description': f"[Entity Warm Start] Document {doc_index+1} precise cell-level fix [table: {table_name}]",
                    'details': {
                        'document': os.path.basename(doc_source),
                        'table_name': table_name,
                        'mode': 'entity_warm_start_cell_fix',
                        'cells_identified': len(cells_to_fix),
                        'cells_fixed': len(fixes_data),
                        'total_rows': len(updated_rows),
                        'model_used': model,
                        'output_text': f"Entity Warm Start complete: identified {len(cells_to_fix)} problematic cells, fixed {len(fixes_data)}",
                    },
                    'timestamp': IOManager.get_timestamp()
                })
            
            return updated_rows
            
        except Exception as e:
            self.logger.error(f"[Entity Warm Start] Failed: {e}")
            return previous_snapshot.rows if previous_snapshot else []

