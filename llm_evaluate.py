#!/usr/bin/env python3
"""
LLM extraction capability evaluation script.
Tests a single LLM's document extraction directly, without the full Doc2DB pipeline.
"""

import os
import sys
import json
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional

project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from dotenv import load_dotenv
env_file = Path(__file__).parent.parent / "llm" / ".env"
if env_file.exists():
    load_dotenv(env_file)
    for url_var in ['API_URL', 'API_URL1', 'API_URL2', 'DEEPSEEK_URL', 'QWEN_URL']:
        url_value = os.getenv(url_var)
        if url_value and url_value.endswith('/chat/completions'):
            base_url = url_value.replace('/chat/completions', '')
            os.environ[url_var] = base_url
else:
    print(f"Warning: Environment file not found: {env_file}")

from llm.main import get_answer

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

DATASET_DIR = Path(__file__).parent.parent / "dataset"
OUTPUT_DIR = Path(__file__).parent.parent / "dataset_output"
DEFAULT_MODEL = "gpt-4o"
DEFAULT_CHUNK_SIZE = 100000
DEFAULT_CHUNK_OVERLAP = 500


class LLMExtractorEvaluator:
    """Evaluator for LLM extraction capability."""
    
    def __init__(self, model: str = DEFAULT_MODEL, dataset_dir: Path = DATASET_DIR,
                 output_dir: Path = OUTPUT_DIR, run_name: Optional[str] = None,
                 chunk_size: int = DEFAULT_CHUNK_SIZE, chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
                 force_rerun: bool = False):
        self.model = model
        self.dataset_dir = dataset_dir
        self.output_dir = output_dir
        self.run_name = run_name
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.force_rerun = force_rerun
        self.results = []
        
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Output directory: {self.output_dir}")
        logger.info(f"Model: {model}")
        if run_name:
            logger.info(f"Run name: {run_name}")
        logger.info(f"Chunk size: {chunk_size} chars, overlap: {chunk_overlap} chars")
        if force_rerun:
            logger.info("Force rerun mode: will reprocess all cases")
        else:
            logger.info("Skip mode: processed cases will be skipped")
    
    def scan_datasets(self) -> List[Dict[str, Any]]:
        """Scan all datasets and cases."""
        cases = []
        
        if not self.dataset_dir.exists():
            logger.error(f"Dataset directory does not exist: {self.dataset_dir}")
            return cases
        
        for db_dir in self.dataset_dir.iterdir():
            if not db_dir.is_dir():
                continue
            
            db_name = db_dir.name
            logger.info(f"Scanning database: {db_name}")
            
            for case_dir in db_dir.iterdir():
                if not case_dir.is_dir() or not case_dir.name.startswith("case"):
                    continue
                
                case_name = case_dir.name
                
                docs_dir = case_dir / "docs"
                schema_file = case_dir / "schema.json"
                answer_file = case_dir / "answer.json"
                
                if not docs_dir.exists():
                    logger.warning(f"{db_name}/{case_name}: docs directory not found, skipping")
                    continue
                
                if not schema_file.exists():
                    logger.warning(f"{db_name}/{case_name}: schema.json not found, skipping")
                    continue
                
                if not answer_file.exists():
                    logger.warning(f"{db_name}/{case_name}: answer.json not found, skipping")
                    continue
                
                doc_files = []
                for ext in ['*.txt', '*.pdf', '*.md', '*.docx', '*.doc']:
                    doc_files.extend(list(docs_dir.glob(ext)))
                
                if not doc_files:
                    logger.warning(f"{db_name}/{case_name}: docs directory is empty, skipping")
                    continue
                
                cases.append({
                    'db_name': db_name,
                    'case_name': case_name,
                    'case_dir': case_dir,
                    'docs_dir': docs_dir,
                    'schema_file': schema_file,
                    'answer_file': answer_file,
                    'doc_files': [str(f) for f in doc_files]
                })
                
                logger.info(f"  Found {len(doc_files)} document files in {db_name}/{case_name}")
        
        logger.info(f"\nFound {len(cases)} valid test cases\n")
        return cases
    
    def read_document_content(self, file_path: str) -> str:
        """Read document content (supports txt files)."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            logger.info(f"  Read document: {os.path.basename(file_path)} ({len(content)} chars)")
            return content
        except Exception as e:
            logger.error(f"  Failed to read document: {os.path.basename(file_path)} - {e}")
            return ""
    
    def merge_documents(self, doc_files: List[str]) -> str:
        """Merge content from multiple documents."""
        merged_content = []
        
        for i, doc_file in enumerate(doc_files, 1):
            content = self.read_document_content(doc_file)
            if content:
                merged_content.append(f"=== Document {i}: {os.path.basename(doc_file)} ===\n")
                merged_content.append(content)
                merged_content.append(f"\n=== End of Document {i} ===\n\n")
        
        final_content = "\n".join(merged_content)
        logger.info(f"  Merged documents, total length: {len(final_content)} chars")
        return final_content
    
    def is_case_processed(self, case_info: Dict[str, Any]) -> bool:
        """Check whether a case has already been processed."""
        case_dir = self.output_dir / case_info['db_name'] / case_info['case_name']
        safe_model = self.model.replace('/', '_').replace('\\', '_').replace('-', '_')
        folder_name = f"{case_info['db_name']}_{case_info['case_name']}_{safe_model}_only"
        
        model_dir = case_dir / folder_name
        metadata_file = model_dir / "metadata.json"
        extracted_file = model_dir / "extracted_data.json"
        
        if metadata_file.exists() and extracted_file.exists():
            try:
                with open(metadata_file, 'r', encoding='utf-8') as f:
                    metadata = json.load(f)
                with open(extracted_file, 'r', encoding='utf-8') as f:
                    extracted_data = json.load(f)
                
                if metadata.get('model') == self.model:
                    logger.info(f"  Case already processed, skipping: {case_info['db_name']}/{case_info['case_name']}")
                    return True
            except Exception as e:
                logger.warning(f"  Failed to read existing result, will reprocess: {e}")
                return False
        
        return False
    
    def load_existing_result(self, case_info: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Load results for an already-processed case."""
        case_dir = self.output_dir / case_info['db_name'] / case_info['case_name']
        safe_model = self.model.replace('/', '_').replace('\\', '_').replace('-', '_')
        folder_name = f"{case_info['db_name']}_{case_info['case_name']}_{safe_model}_only"
        model_dir = case_dir / folder_name
        
        try:
            with open(model_dir / "metadata.json", 'r', encoding='utf-8') as f:
                metadata = json.load(f)
            
            with open(model_dir / "extracted_data.json", 'r', encoding='utf-8') as f:
                extracted_data = json.load(f)
            
            with open(case_info['answer_file'], 'r', encoding='utf-8') as f:
                expected_answer = json.load(f)
            
            cell_metrics = self.calculate_cell_metrics(extracted_data, expected_answer)
            
            result = {
                "cell_recall": cell_metrics['cell_recall'],
                "cell_precision": cell_metrics['cell_precision'],
                "cell_f1": cell_metrics['cell_f1'],
                "total_expected_cells": cell_metrics['total_expected_cells'],
                "total_generated_cells": cell_metrics['total_generated_cells'],
                "total_correct_cells": cell_metrics['total_correct_cells'],
            }
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to load existing result: {e}")
            return None
    
    def split_text_into_chunks(self, text: str) -> List[str]:
        """Split text into chunks."""
        if len(text) <= self.chunk_size:
            logger.info(f"Document length {len(text)} chars, no need to split")
            return [text]
        
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + self.chunk_size
            
            if end < len(text):
                paragraph_break = text.rfind('\n\n', start, end)
                if paragraph_break > start + self.chunk_size // 2:
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
                    if sentence_break > start + self.chunk_size // 2:
                        end = sentence_break + 1
            
            chunk = text[start:end]
            chunks.append(chunk)
            
            start = end - self.chunk_overlap if end < len(text) else end
        
        logger.info(f"Document split into {len(chunks)} chunks, each ~{self.chunk_size} chars")
        return chunks
    
    def _create_row_signature(self, row: Dict[str, Any]) -> str:
        """Create a unique row signature for deduplication."""
        values = []
        for key in sorted(row.keys()):
            value = row[key]
            normalized = self.normalize_value(value)
            if normalized:
                values.append(f"{key}:{normalized}")
        return "||".join(values)
    
    def merge_extraction_results(self, all_results: List[Dict[str, List[Dict[str, Any]]]]) -> Dict[str, List[Dict[str, Any]]]:
        """Merge extraction results from multiple chunks, removing duplicate records."""
        table_rows = {}
        
        for result in all_results:
            for table_name, rows in result.items():
                if table_name not in table_rows:
                    table_rows[table_name] = []
                table_rows[table_name].extend(rows)
        
        merged_result = {}
        for table_name, rows in table_rows.items():
            seen_records = set()
            unique_rows = []
            
            for row in rows:
                row_signature = self._create_row_signature(row)
                if row_signature not in seen_records:
                    seen_records.add(row_signature)
                    unique_rows.append(row)
            
            merged_result[table_name] = unique_rows
            logger.info(f"Table {table_name}: {len(rows)} rows -> {len(unique_rows)} rows after deduplication")
        
        return merged_result
    
    def build_extraction_prompt(self, schema: Dict[str, Any], table_name: str, 
                                merged_content: str, nl_prompt: str = "") -> tuple[str, str]:
        """Build the extraction prompt."""
        table_def = self._get_table_definition(schema, table_name)
        if not table_def:
            raise ValueError(f"Table definition not found: {table_name}")
        
        attributes = table_def.get('attributes', [])
        schema_info = self._build_detailed_schema_prompt(table_def, nl_prompt)
        
        system_prompt = """You are a professional data extraction expert. 
Your role is to read documents carefully and extract structured data with high accuracy and recall. 
Always follow the user instructions strictly and produce only the requested output format.

This is a COLD START extraction - extract all relevant data from scratch."""
        
        user_prompt = f"""

Your task: Extract structured data from the following document according to the schema.

{schema_info}


Extraction Requirements:
1. Carefully read the document content and identify all relevant data records
2. For each record, extract all available attribute values according to the schema constraints
3. If an attribute value is not found, set it to null
4. Maintain data accuracy and completeness
5. Pay strict attention to data types, formats, and domain constraints defined in the schema
6. Follow all validation rules and constraints specified in the schema
7. Extract as many relevant records as possible for high recall
8. Ensure extracted values comply with the schema requirements

CRITICAL: You MUST respond with a Markdown table format marked with <TABLE BEGIN> and <TABLE END> tags.

Format Example:
<TABLE BEGIN>
| {attributes[0]['name'] if attributes else 'field1'} | {attributes[1]['name'] if len(attributes) > 1 else 'field2'} | {attributes[2]['name'] if len(attributes) > 2 else 'field3'} |
|---|---|---|
| extracted_value1 | extracted_value2 | extracted_value3 |
| extracted_value4 | extracted_value5 | extracted_value6 |
<TABLE END>

IMPORTANT NOTES:
- Use ONLY the column names from the schema: {[attr['name'] for attr in attributes]}
- Each row should represent one data record (e.g., one quarter's data for one company)
- Create separate rows for different quarters/time periods
- Always include all schema fields as columns, even if the value is null
- Use simple text values in table cells, no complex structures
- Follow standard Markdown table format with proper alignment
- Include the header separator row with dashes

Additional Instructions: {nl_prompt if nl_prompt else 'No special requirements'}

Document Content:
{merged_content}

Please return the Markdown table result in the format specified in the system instructions. Remember to respond with the complete table wrapped in <TABLE BEGIN> and <TABLE END> tags."""
        
        return system_prompt, user_prompt
    
    def _get_table_definition(self, schema: Dict[str, Any], table_name: str) -> Optional[Dict[str, Any]]:
        """Get the table definition (compatible with multiple schema formats)."""
        
        tables = schema.get('tables', [])
        for table in tables:
            if table.get('name') == table_name:
                result = table.copy()
                if 'fields' in result and 'attributes' not in result:
                    result['attributes'] = result.pop('fields')
                return result
        
        if schema.get('table_name') == table_name and 'columns' in schema:
            return {
                'name': table_name,
                'attributes': schema['columns']
            }
    
    def classify_tables_by_type(self, schema: Dict[str, Any]) -> Dict[str, List[str]]:
        """Classify tables into entity tables and relation tables.
        
        Classification is based on the table "type" field in the schema:
        - type: "entity" -> entity table
        - type: "relation" / "relationship" -> relation table
        - If no type field is present, default to entity table
        
        Returns:
            {'entity_tables': [...], 'relation_tables': [...]}
        """
        if not isinstance(schema, dict):
            return {'entity_tables': [], 'relation_tables': []}
        
        entity_tables = []
        relation_tables = []
        
        if 'tables' in schema and isinstance(schema['tables'], list):
            for table in schema['tables']:
                if not isinstance(table, dict) or 'name' not in table:
                    continue
                
                table_name = table['name']
                table_type = table.get('type', 'entity').lower()
                
                relation_config = table.get('relation_extraction', {})
                has_relation_config = relation_config.get('enabled', False)
                
                if table_type in ['relation', 'relationship'] or has_relation_config:
                    relation_tables.append(table_name)
                else:
                    entity_tables.append(table_name)
        
        elif 'table_name' in schema:
            table_name = schema['table_name']
            table_type = schema.get('type', 'entity').lower()
            
            if table_type in ['relation', 'relationship']:
                relation_tables.append(table_name)
            else:
                entity_tables.append(table_name)
        
        return {
            'entity_tables': entity_tables,
            'relation_tables': relation_tables
        }
    
    def _load_document_sources_for_relation(self, relation_config: Dict[str, Any], case_dir: Path) -> str:
        """Load dedicated documents for relation tables from configured document_sources.
        
        Args:
            relation_config: relation_extraction configuration
            case_dir: Case directory (used to resolve relative paths)
            
        Returns:
            Document content loaded from document_sources
        """
        document_sources = relation_config.get('document_sources', [])
        if not document_sources:
            logger.warning(f"document_sources is empty")
            return ""
        
        logger.info(f"Loading {len(document_sources)} documents from document_sources")
        
        merged_content = []
        
        for doc_source in document_sources:
            try:
                doc_path = Path(doc_source)
                
                if not doc_path.is_absolute():
                    candidate1 = case_dir / doc_source
                    candidate2 = case_dir.parent.parent / doc_source  # dataset/xxx/case1 -> dataset
                    candidate3 = Path(__file__).parent.parent / doc_source  # From evaluate directory
                    
                    if candidate1.exists():
                        doc_path = candidate1
                    elif candidate2.exists():
                        doc_path = candidate2
                    elif candidate3.exists():
                        doc_path = candidate3
                    else:
                        doc_path = Path(__file__).parent.parent / doc_source
                
                if not doc_path.exists():
                    logger.error(f"Document source does not exist: {doc_path}")
                    continue
                
                with open(doc_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if content:
                    merged_content.append(f"=== Document: {doc_path.name} ===\n")
                    merged_content.append(content)
                    merged_content.append(f"\n=== End of {doc_path.name} ===\n\n")
                    logger.info(f"   Successfully loaded document: {doc_path.name} ({len(content)} chars)")
                
            except Exception as e:
                logger.error(f"Failed to load document {doc_source}: {e}")
                continue
        
        if merged_content:
            result = "\n".join(merged_content)
            logger.info(f"   Loaded {len(document_sources)} documents from document_sources, {len(result)} chars total")
            return result
        else:
            logger.warning(f"Failed to load all documents configured in document_sources")
            return ""
    
    def _load_reference_tables(self, table_def: Dict[str, Any], case_dir: Path) -> Dict[str, List[Dict[str, Any]]]:
        """Load reference table data required for relation extraction.
        
        Args:
            table_def: Table definition (includes relation_extraction configuration)
            case_dir: Case directory (used to resolve relative paths)
            
        Returns:
            Dict mapping table names to lists of row data
        """
        reference_tables = {}
        
        relation_config = table_def.get('relation_extraction', {})
        if not relation_config.get('enabled', False):
            return reference_tables
        
        reference_configs = relation_config.get('reference_tables', [])
        
        for ref_config in reference_configs:
            table_name = ref_config.get('table')
            data_source = ref_config.get('data_source')
            key_fields = ref_config.get('key_fields', [])
            
            if not table_name or not data_source:
                logger.warning(f"Incomplete reference table config, skipping: {ref_config}")
                continue
            
            try:
                data_path = Path(data_source)
                if not data_path.is_absolute():
                    candidate1 = case_dir / data_source
                    candidate2 = case_dir.parent.parent / data_source  # dataset/xxx/case1 -> dataset
                    candidate3 = Path(__file__).parent.parent / data_source  # From evaluate directory
                    
                    if candidate1.exists():
                        data_path = candidate1
                    elif candidate2.exists():
                        data_path = candidate2
                    elif candidate3.exists():
                        data_path = candidate3
                    else:
                        data_path = Path(__file__).parent.parent / data_source
                
                if not data_path.exists():
                    logger.warning(f"Reference table data file does not exist: {data_path}")
                    continue
                
                with open(data_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if table_name in data:
                    table_data = data[table_name]
                    
                    if key_fields:
                        filtered_data = []
                        for row in table_data:
                            filtered_row = {k: v for k, v in row.items() if k in key_fields}
                            filtered_data.append(filtered_row)
                        reference_tables[table_name] = filtered_data
                    else:
                        reference_tables[table_name] = table_data
                    
                    logger.info(f"   Loaded reference table {table_name}: {len(table_data)} rows")
                else:
                    logger.warning(f"Table {table_name} not found in data file")
                    
            except Exception as e:
                logger.error(f"Failed to load reference table {table_name}: {e}")
                continue
        
        return reference_tables
    
    def _build_reference_tables_prompt(self, reference_tables_data: Dict[str, List[Dict[str, Any]]], 
                                       relation_config: Dict[str, Any]) -> str:
        """Build the prompt section containing reference table data.
        
        Args:
            reference_tables_data: Reference table data dictionary
            relation_config: relation_extraction configuration
            
        Returns:
            Formatted prompt string
        """
        if not reference_tables_data:
            return ""
        
        prompt_parts = ["\n【Reference Tables for Relationship Extraction】"]
        
        extraction_hint = relation_config.get('extraction_hint', '')
        if extraction_hint:
            prompt_parts.append(f"\nTask: {extraction_hint}\n")
        
        for table_name, table_data in reference_tables_data.items():
            if not table_data:
                continue
            
            prompt_parts.append(f"\n{table_name} Table:")
            
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
            
            prompt_parts.append("")
        
        prompt_parts.append("IMPORTANT Instructions for Relationship Extraction:")
        prompt_parts.append("- Use the reference tables above to match entity names/descriptions to their IDs")
        prompt_parts.append("- For foreign key fields, MUST use the exact ID values from the reference tables")
        prompt_parts.append("- Extract ONLY the relationships that are explicitly mentioned in the document")
        prompt_parts.append("")
        
        return "\n".join(prompt_parts)
    
    def build_relation_extraction_prompt(self, schema: Dict[str, Any], table_name: str, 
                                         merged_content: str, reference_tables_data: Dict[str, List[Dict[str, Any]]],
                                         nl_prompt: str = "") -> tuple[str, str]:
        """Build the relation extraction prompt (including reference table data)."""
        
        table_def = self._get_table_definition(schema, table_name)
        if not table_def:
            raise ValueError(f"Table definition not found: {table_name}")
        
        attributes = table_def.get('attributes', [])
        relation_config = table_def.get('relation_extraction', {})
        
        schema_info = self._build_detailed_schema_prompt(table_def, nl_prompt)
        
        reference_tables_prompt = self._build_reference_tables_prompt(reference_tables_data, relation_config)
        
        system_prompt = """You are a professional data extraction expert specializing in relationship extraction.
Your role is to read documents carefully and extract relationships between entities with high accuracy and recall.
You must use the reference tables provided to correctly map entity names to their IDs.
Always follow the user instructions strictly and produce only the requested output format.

This is a RELATIONSHIP EXTRACTION task - extract relationships between entities using the reference tables."""
        
        user_prompt = f"""
Your task: Extract relationship data from the following document according to the schema.

{schema_info}

{reference_tables_prompt}

Extraction Requirements:
1. Carefully read the document content and identify all relationships between entities
2. Use the reference tables to map entity names/descriptions to their correct IDs
3. For each relationship, extract all required foreign key fields
4. Only extract relationships that are explicitly mentioned in the document
5. For foreign key fields, use the EXACT ID values from the reference tables

CRITICAL: You MUST respond with a Markdown table format marked with <TABLE BEGIN> and <TABLE END> tags.

Format Example:
<TABLE BEGIN>
| {attributes[0]['name'] if attributes else 'field1'} | {attributes[1]['name'] if len(attributes) > 1 else 'field2'} |
|---|---|
| id_value1 | id_value2 |
| id_value3 | id_value4 |
<TABLE END>

IMPORTANT NOTES:
- Use ONLY the column names from the schema: {[attr['name'] for attr in attributes]}
- Each row represents ONE relationship between entities
- Use the ID values from the reference tables, NOT the entity names
- Follow standard Markdown table format with proper alignment

Additional Instructions: {nl_prompt if nl_prompt else 'No special requirements'}

Document Content:
{merged_content}

Please return the Markdown table result. Remember to use ID values from reference tables for foreign key fields."""
        
        return system_prompt, user_prompt
    
    def _extract_entity_table(self, schema: Dict[str, Any], table_name: str, 
                               merged_content: str) -> tuple[Dict[str, List[Dict]], List[str]]:
        """Extract entity table data.
        
        Args:
            schema: Full schema
            table_name: Table name
            merged_content: Merged document content
            
        Returns:
            (Extraction result dict, list of responses)
        """
        all_results = []
        all_responses = []
        table_def = self._get_table_definition(schema, table_name)
        
        chunks = self.split_text_into_chunks(merged_content)
        
        for i, chunk in enumerate(chunks, 1):
            logger.info(f"Processing Chunk {i}/{len(chunks)}...")
            
            chunk_info = f" (Chunk {i}/{len(chunks)})" if len(chunks) > 1 else ""
            system_prompt, user_prompt = self.build_extraction_prompt(
                schema, table_name, chunk, nl_prompt=""
            )
            
            logger.info(f"Calling LLM ({self.model}){chunk_info}...")
            llm_response = get_answer(user_prompt, system_prompt=system_prompt, model=self.model)
            
            if not llm_response:
                logger.warning(f"Chunk {i} LLM returned empty response")
                continue
            
            logger.info(f"LLM response length: {len(llm_response)} chars")
            
            chunk_result = self.parse_llm_response(llm_response, table_def)
            all_results.append(chunk_result)
            all_responses.append(f"=== Entity Table {table_name} - Chunk {i} Response ===\n{llm_response}\n")
            
            if i < len(chunks):
                time.sleep(0.5)
        
        if not all_results:
            logger.warning(f"Table {table_name} did not extract any data")
            return {table_name: []}, all_responses
        
        logger.info(f"Merging results from {len(all_results)} chunks...")
        table_data = self.merge_extraction_results(all_results)
        
        table_rows = sum(len(rows) for rows in table_data.values())
        logger.info(f"   Entity table {table_name} extraction complete: {table_rows} rows")
        
        return table_data, all_responses
    
    def _extract_relation_table(self, schema: Dict[str, Any], table_name: str, 
                                 merged_content: str, extracted_entity_data: Dict[str, List[Dict]],
                                 case_dir: Path) -> tuple[Dict[str, List[Dict]], List[str]]:
        """Extract relation table data (with reference tables).
        
        Args:
            schema: Full schema
            table_name: Table name
            merged_content: Merged document content
            extracted_entity_data: Already extracted entity table data
            case_dir: Case directory
            
        Returns:
            (Extraction result dict, list of responses)
        """
        all_results = []
        all_responses = []
        table_def = self._get_table_definition(schema, table_name)
        
        relation_config = table_def.get('relation_extraction', {}) if table_def else {}
        if relation_config.get('enabled') and relation_config.get('document_sources'):
            logger.info(f"Detected document_sources config, reading specified documents directly")
            merged_content = self._load_document_sources_for_relation(relation_config, case_dir)
        
        reference_tables_data = self._load_reference_tables(table_def, case_dir)
        
        if not reference_tables_data and extracted_entity_data:
            logger.info(f"Using already-extracted entity table data as reference...")
            attributes = table_def.get('attributes', [])
            for attr in attributes:
                constraints = attr.get('constraints', {})
                if constraints.get('foreign_key'):
                    field_name = attr.get('name', '')
                    if field_name.endswith('ID') or field_name.endswith('_id'):
                        ref_table = field_name[:-2] if field_name.endswith('ID') else field_name[:-3]
                        for entity_name, entity_data in extracted_entity_data.items():
                            if entity_name.lower() == ref_table.lower():
                                reference_tables_data[entity_name] = entity_data
                                logger.info(f"Using extracted {entity_name} as reference")
        
        if reference_tables_data:
            logger.info(f"   Loaded {len(reference_tables_data)} reference tables")
        else:
            logger.warning(f"No reference table data found, performing relation extraction without references")
        
        chunks = self.split_text_into_chunks(merged_content)
        
        for i, chunk in enumerate(chunks, 1):
            logger.info(f"Processing Chunk {i}/{len(chunks)}...")
            
            chunk_info = f" (Chunk {i}/{len(chunks)})" if len(chunks) > 1 else ""
            
            if reference_tables_data:
                system_prompt, user_prompt = self.build_relation_extraction_prompt(
                    schema, table_name, chunk, reference_tables_data, nl_prompt=""
                )
            else:
                system_prompt, user_prompt = self.build_extraction_prompt(
                    schema, table_name, chunk, nl_prompt=""
                )
            
            logger.info(f"Calling LLM ({self.model}){chunk_info}...")
            llm_response = get_answer(user_prompt, system_prompt=system_prompt, model=self.model)
            
            if not llm_response:
                logger.warning(f"Chunk {i} LLM returned empty response")
                continue
            
            logger.info(f"LLM response length: {len(llm_response)} chars")
            
            chunk_result = self.parse_llm_response(llm_response, table_def)
            all_results.append(chunk_result)
            all_responses.append(f"=== Relation Table {table_name} - Chunk {i} Response ===\n{llm_response}\n")
            
            if i < len(chunks):
                time.sleep(0.5)
        
        if not all_results:
            logger.warning(f"Table {table_name} did not extract any data")
            return {table_name: []}, all_responses
        
        logger.info(f"Merging results from {len(all_results)} chunks...")
        table_data = self.merge_extraction_results(all_results)
        
        table_rows = sum(len(rows) for rows in table_data.values())
        logger.info(f"   Relation table {table_name} extraction complete: {table_rows} rows")
        
        return table_data, all_responses
    
    def _build_detailed_schema_prompt(self, table_def: Dict[str, Any], nl_prompt: str) -> str:
        """Build detailed schema information as the core part of the prompt."""
        table_name = table_def.get('name', 'data_table')
        attributes = table_def.get('attributes', [])
        
        schema_parts = [
            f"=== TABLE SCHEMA DEFINITION ===",
            f"Table Name: {table_name}",
            f"Fields ({len(attributes)} total):"
        ]
        
        for i, attr in enumerate(attributes):
            field_info = [f"\n{i+1}. Field: {attr['name']}"]
            
            if 'type' in attr:
                field_info.append(f"   - Type: {attr['type']}")
            
            if 'description' in attr:
                field_info.append(f"   - Description: {attr['description']}")
            
            constraints = []
            
            constraint_dict = attr.get('constraints', {})
            if constraint_dict.get('primary_key', False):
                constraints.append("PRIMARY KEY")
            if constraint_dict.get('foreign_key', False):
                constraints.append("FOREIGN KEY")
            if constraint_dict.get('unique', False):
                constraints.append("UNIQUE")
            if not constraint_dict.get('nullable', True):
                constraints.append("NOT NULL (required)")
            
            if attr.get('required', False) and "NOT NULL" not in ' '.join(constraints):
                constraints.append("REQUIRED (must not be null)")
            if 'domain' in attr:
                constraints.append(f"Domain values: {attr['domain']}")
            if 'format' in attr:
                constraints.append(f"Format pattern: {attr['format']}")
            if 'min' in attr:
                constraints.append(f"Minimum value: {attr['min']}")
            if 'max' in attr:
                constraints.append(f"Maximum value: {attr['max']}")
            if attr.get('unique', False) and "UNIQUE" not in ' '.join(constraints):
                constraints.append("Must be unique")
            
            if constraints:
                field_info.append(f"   - Constraints: {' | '.join(constraints)}")
            
            schema_parts.extend(field_info)
        
        if nl_prompt:
            schema_parts.extend([
                f"\n=== BUSINESS REQUIREMENTS ===",
                f"Additional Requirements: {nl_prompt}",
                f"Please ensure the extracted data aligns with these business requirements while strictly following the schema definition."
            ])
        
        schema_parts.append(f"\n=== CRITICAL SCHEMA COMPLIANCE ===")
        schema_parts.append(f"- ALL extracted values MUST match the specified data types")
        schema_parts.append(f"- REQUIRED fields cannot be empty or null")
        schema_parts.append(f"- Values must comply with domain constraints if specified")
        schema_parts.append(f"- Follow format patterns exactly as defined")
        schema_parts.append(f"- Respect min/max value constraints")
        
        return "\n".join(schema_parts)
    
    def parse_llm_response(self, llm_response: str, table_def: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """Parse LLM response and extract table data."""
        
        table_name = table_def.get('name', 'data_table')
        attributes = table_def.get('attributes', [])
        
        try:
            import re
            table_pattern = r'<TABLE BEGIN>(.*?)<TABLE END>'
            matches = re.findall(table_pattern, llm_response, re.DOTALL)
            
            if not matches:
                logger.warning("  No table markers found, trying to find Markdown table...")
                lines = llm_response.split('\n')
                table_lines = [line for line in lines if line.strip().startswith('|')]
                if len(table_lines) >= 3:  # At least header, separator, and one data row
                    table_content = '\n'.join(table_lines)
                else:
                    raise ValueError("No valid table content found")
            else:
                table_content = matches[0].strip()
            
            lines = [line.strip() for line in table_content.split('\n') if line.strip()]
            
            if len(lines) < 3:
                raise ValueError(f"Not enough table rows: {len(lines)}")
            
            header_line = lines[0]
            headers = [h.strip() for h in header_line.split('|') if h.strip()]
            
            
            rows = []
            for line in lines[2:]:
                if not line.strip() or line.startswith('---'):
                    continue
                
                cells = [c.strip() for c in line.split('|') if c.strip()]
                
                while len(cells) < len(headers):
                    cells.append('')
                
                row_dict = {}
                for i, header in enumerate(headers):
                    if i < len(cells):
                        cell_value = cells[i].strip()
                        if cell_value.lower() in ['null', 'none', 'n/a', '']:
                            row_dict[header] = None
                        else:
                            row_dict[header] = cell_value
                    else:
                        row_dict[header] = None
                
                if any(v is not None for v in row_dict.values()):
                    rows.append(row_dict)
            
            logger.info(f"Parsing complete, extracted {len(rows)} rows")
            return {table_name: rows}
            
        except Exception as e:
            logger.error(f"  Failed to parse LLM response: {e}")
            logger.debug(f"LLM response content:\n{llm_response[:500]}...")
            return {table_name: []}
    
    def normalize_value(self, value: Any) -> str:
        """Normalize cell values for comparison."""
        if value is None:
            return ""
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, (int, float)):
            return str(value)
        return str(value).strip().lower()
    
    def calculate_cell_metrics(self, generated: Dict[str, Any], expected: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate cell-level recall and precision (uses lists instead of sets to handle duplicates and empty values)."""
        try:
            expected_cells = []
            generated_cells = []
            
            for table_name, expected_rows in expected.items():
                if not isinstance(expected_rows, list):
                    continue
                
                table_name_lower = table_name.lower()
                
                for row_idx, row in enumerate(expected_rows):
                    if isinstance(row, dict):
                        for attr, value in row.items():
                            attr_lower = attr.lower()
                            norm_value = self.normalize_value(value)
                            expected_cells.append((table_name_lower, attr_lower, norm_value))
            
            for table_name, generated_rows in generated.items():
                if not isinstance(generated_rows, list):
                    continue
                
                table_name_lower = table_name.lower()
                
                for row_idx, row in enumerate(generated_rows):
                    if isinstance(row, dict):
                        for attr, value in row.items():
                            attr_lower = attr.lower()
                            norm_value = self.normalize_value(value)
                            generated_cells.append((table_name_lower, attr_lower, norm_value))
            
            expected_cells_remaining = expected_cells.copy()
            correct_count = 0
            
            for gen_cell in generated_cells:
                if gen_cell in expected_cells_remaining:
                    expected_cells_remaining.remove(gen_cell)
                    correct_count += 1
            total_expected = len(expected_cells)
            total_generated = len(generated_cells)
            total_correct = correct_count
            
            recall = (total_correct / total_expected * 100) if total_expected > 0 else 0
            precision = (total_correct / total_generated * 100) if total_generated > 0 else 0
            f1_score = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0
            
            logger.info(f"Cell metrics: expected {total_expected}, generated {total_generated}, correct {total_correct}")
            
            return {
                "cell_recall": recall,
                "cell_precision": precision,
                "cell_f1": f1_score,
                "total_expected_cells": total_expected,
                "total_generated_cells": total_generated,
                "total_correct_cells": total_correct
            }
            
        except Exception as e:
            logger.error(f"Failed to calculate cell metrics: {e}")
            import traceback
            traceback.print_exc()
            return {
                "cell_recall": 0.0,
                "cell_precision": 0.0,
                "cell_f1": 0.0,
                "total_expected_cells": 0,
                "total_generated_cells": 0,
                "total_correct_cells": 0
            }
    
    def evaluate_with_llm(self, generated: Dict[str, Any], expected: Dict[str, Any], 
                          case_info: Dict[str, Any]) -> Dict[str, Any]:
        """Perform fine-grained evaluation using an LLM."""
        try:
            schema = {}
            try:
                with open(case_info['schema_file'], 'r', encoding='utf-8') as f:
                    schema = json.load(f)
            except Exception as e:
                logger.warning(f"Failed to read schema file: {e}")
            
            evaluation_prompt = f"""
You are a database evaluation expert. Please evaluate the quality of database tables extracted from documents.

Database Name: {case_info['db_name']}
Test Case: {case_info['case_name']}

[Database Schema]:
{json.dumps(schema, ensure_ascii=False, indent=2)}

[Generated Results]:
{json.dumps(generated, ensure_ascii=False, indent=2)}

[Standard Answer]:
{json.dumps(expected, ensure_ascii=False, indent=2)}


Please evaluate the quality of the generated results from the following dimensions:

- Whether the generated results are semantically consistent with the standard answer
- Whether numeric data is accurate (values must be exactly equal to be considered correct)
- Whether the decimal places of numeric values match the standard answer
- Whether string data is accurate (similarity needs to reach 90% or above)
- Whether there are hallucinations or erroneous information

- Whether the generated results contain all key information from the standard answer
- Whether there are important data omissions
- Whether the table structure and fields are complete
- Further explanations of these key points can be omitted, but the core content must be complete

- Whether the data format complies with the Schema definition
- Whether the data types are correct (numeric, string, date, etc.)
- Whether the formats are consistent (e.g., date format, number format, etc.)

1. Numeric values must be exactly equal to be considered correct, including decimal places
2. String similarity below 90% is not considered a match
3. Type mismatches are serious errors
4. If the generated results fully comply with all key points of the standard answer, the total score should be 100 points
5. Please note: The standard answer may be considered the correct answer to the question

The assistant will receive a total score from 0 to 100 points, with higher scores indicating better overall performance. Please note that if the assistant's answer fully complies with the above standards and matches the standard answer, the total score should be 100 points.

Please first provide a comprehensive evaluation explanation (no more than 100 words), avoiding any potential bias. Then output the score in strict format.

Please output in the following format:
<Start Output>
Evaluation evidence: Your evaluation explanation (no more than 100 words)
Rating: [[score]]
<End Output>

Where score is an integer between 0-100.

Now begin the evaluation:
"""
            
            logger.info(f"Using {self.model} for fine-grained evaluation")
            
            response = get_answer(evaluation_prompt, model=self.model)
            
            if not response:
                raise Exception("LLM returned empty response")
            
            import re
            overall_score = 0
            evaluation_details = ""
            
            score_match = re.search(r'Rating:\s*\[\[(\d+(?:\.\d+)?)\]\]', response)
            if score_match:
                overall_score = float(score_match.group(1))
            else:
                score_match = re.search(r'"overall_score":\s*(\d+(?:\.\d+)?)', response)
                if score_match:
                    overall_score = float(score_match.group(1))
                else:
                    # Also match Chinese LLM score suffix (分 = points)
                    score_match = re.search(r'(\d+(?:\.\d+)?)\s*分', response)
                    if score_match:
                        overall_score = float(score_match.group(1))
            
            evidence_match = re.search(r'Evaluation evidence:\s*([^\n]+)', response)
            if evidence_match:
                evaluation_details = evidence_match.group(1).strip()
            else:
                evaluation_details = response[:500]
            
            overall_score = max(0, min(100, overall_score))
            
            llm_evaluation = {
                "overall": overall_score,
                "completeness": overall_score,
                "accuracy": overall_score,
                "consistency": overall_score,
                "coverage": overall_score,
                "comments": evaluation_details
            }
            
            logger.info(f"LLM fine-grained evaluation completed, total score: {overall_score:.1f}")
            return llm_evaluation
                
        except Exception as e:
            logger.warning(f"LLM evaluation failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                "completeness": 0.0,
                "accuracy": 0.0,
                "consistency": 0.0,
                "coverage": 0.0,
                "overall": 0.0,
                "comments": f"LLM evaluation failed: {str(e)}"
            }
    
    def save_output(self, case_info: Dict[str, Any], extracted_data: Dict[str, Any], 
                    llm_response: str, prompt_info: Dict[str, str]) -> Path:
        """Save processing results to the output directory."""
        case_dir = self.output_dir / case_info['db_name'] / case_info['case_name']
        case_dir.mkdir(parents=True, exist_ok=True)
        
        safe_model = self.model.replace('/', '_').replace('\\', '_').replace('-', '_')
        folder_name = f"{case_info['db_name']}_{case_info['case_name']}_{safe_model}_only"
        
        model_dir = case_dir / folder_name
        model_dir.mkdir(parents=True, exist_ok=True)
        
        metadata = {
            'model': self.model,
            'run_name': self.run_name,
            'method': 'llm_only',
            'db_name': case_info['db_name'],
            'case_name': case_info['case_name'],
            'timestamp': datetime.now().isoformat()
        }
        
        with open(model_dir / "metadata.json", 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        
        with open(model_dir / "extracted_data.json", 'w', encoding='utf-8') as f:
            json.dump(extracted_data, f, ensure_ascii=False, indent=2)
        
        with open(model_dir / "llm_response.txt", 'w', encoding='utf-8') as f:
            f.write(llm_response)
        
        with open(model_dir / "prompt.txt", 'w', encoding='utf-8') as f:
            f.write("=== SYSTEM PROMPT ===\n\n")
            f.write(prompt_info['system_prompt'])
            f.write("\n\n=== USER PROMPT ===\n\n")
            f.write(prompt_info['user_prompt'])
        
        logger.info(f"Results saved to: {model_dir}")
        return model_dir
    
    def process_case(self, case_info: Dict[str, Any]) -> Dict[str, Any]:
        """Process a single test case."""
        case_id = f"{case_info['db_name']}/{case_info['case_name']}"
        logger.info(f"\n{'='*80}")
        logger.info(f"Processing: {case_id}")
        logger.info(f"{'='*80}")
        
        if not self.force_rerun and self.is_case_processed(case_info):
            existing_result = self.load_existing_result(case_info)
            if existing_result:
                logger.info(f"Using cached result: {case_id}")
                return existing_result
            else:
                logger.warning(f"Failed to load cached result, reprocessing: {case_id}")
        
        result = {
            'case_id': case_id,
            'db_name': case_info['db_name'],
            'case_name': case_info['case_name'],
            'model': self.model,
            'run_name': self.run_name,
            'status': 'failed',
            'start_time': datetime.now().isoformat(),
            'end_time': None,
            'duration': 0,
            'evaluation': None,
            'error': None,
            'from_cache': False
        }
        
        start_time = time.time()
        
        try:
            logger.info("Reading schema...")
            with open(case_info['schema_file'], 'r', encoding='utf-8') as f:
                schema = json.load(f)
            
            logger.info("Reading standard answer...")
            with open(case_info['answer_file'], 'r', encoding='utf-8') as f:
                expected_answer = json.load(f)
            
            logger.info(f"Merging {len(case_info['doc_files'])} documents...")
            merged_content = self.merge_documents(case_info['doc_files'])
            
            if not merged_content:
                raise Exception("Document content is empty")
            
            table_classification = self.classify_tables_by_type(schema)
            entity_tables = table_classification['entity_tables']
            relation_tables = table_classification['relation_tables']
            
            all_table_names = entity_tables + relation_tables
            logger.info(f"Need to extract {len(all_table_names)} tables")
            logger.info(f"Entity tables ({len(entity_tables)}): {', '.join(entity_tables) if entity_tables else 'none'}")
            logger.info(f"Relation tables ({len(relation_tables)}): {', '.join(relation_tables) if relation_tables else 'none'}")
            
            extracted_data = {}
            all_combined_responses = []
            table_idx = 0
            total_tables = len(all_table_names)
            
            if entity_tables:
                logger.info(f"\n{'='*60}")
                logger.info(f"Stage 1: extracting {len(entity_tables)} entity tables")
                logger.info(f"{'='*60}")
                
                for table_name in entity_tables:
                    table_idx += 1
                    logger.info(f"\n [{table_idx}/{total_tables}] Entity table: {table_name}")
                    
                    table_results, table_responses = self._extract_entity_table(
                        schema, table_name, merged_content
                    )
                    
                    extracted_data.update(table_results)
                    all_combined_responses.extend(table_responses)
                    
                    if table_idx < total_tables:
                        time.sleep(1)
            
            if relation_tables:
                logger.info(f"\n{'='*60}")
                logger.info(f"Stage 2: extracting {len(relation_tables)} relation tables")
                logger.info(f"{'='*60}")
                
                for table_name in relation_tables:
                    table_idx += 1
                    logger.info(f"\n [{table_idx}/{total_tables}] Relation table: {table_name}")
                    
                    table_results, table_responses = self._extract_relation_table(
                        schema, table_name, merged_content, 
                        extracted_data, case_info['case_dir']
                    )
                    
                    extracted_data.update(table_results)
                    all_combined_responses.extend(table_responses)
                    
                    if table_idx < total_tables:
                        time.sleep(1)
            
            combined_response = "\n".join(all_combined_responses)
            
            logger.info(f"\n{'='*60}")
            total_rows = sum(len(rows) for rows in extracted_data.values())
            logger.info(f"Completed extraction for all tables: {len(extracted_data)} tables, {total_rows} rows total")
            logger.info(f"Entity tables: {', '.join(entity_tables) if entity_tables else 'none'}")
            logger.info(f"Relation tables: {', '.join(relation_tables) if relation_tables else 'none'}")
            logger.info(f"{'='*60}")
            
            logger.info("Saving results...")
            first_table = all_table_names[0] if all_table_names else 'data_table'
            last_system_prompt, last_user_prompt = self.build_extraction_prompt(
                schema, first_table, "...(document content processed in chunks)...", nl_prompt=""
            )
            output_dir = self.save_output(
                case_info, 
                extracted_data, 
                combined_response,
                {'system_prompt': last_system_prompt, 'user_prompt': last_user_prompt}
            )
            result['output_dir'] = str(output_dir)
            
            logger.info("Calculating cell-level recall and precision...")
            cell_metrics = self.calculate_cell_metrics(extracted_data, expected_answer)
            logger.info(f"Cell recall: {cell_metrics['cell_recall']:.2f}%")
            logger.info(f"Cell precision: {cell_metrics['cell_precision']:.2f}%")
            logger.info(f"Cell F1: {cell_metrics['cell_f1']:.2f}")
            
            logger.info("Running LLM evaluation...")
            llm_evaluation = self.evaluate_with_llm(
                extracted_data, 
                expected_answer, 
                case_info
            )
            
            evaluation = {
                "cell_recall": cell_metrics['cell_recall'],
                "cell_precision": cell_metrics['cell_precision'],
                "cell_f1": cell_metrics['cell_f1'],
                "total_expected_cells": cell_metrics['total_expected_cells'],
                "total_generated_cells": cell_metrics['total_generated_cells'],
                "total_correct_cells": cell_metrics['total_correct_cells'],
                
                "llm_score": llm_evaluation.get('overall', 0),
                "llm_completeness": llm_evaluation.get('completeness', 0),
                "llm_accuracy": llm_evaluation.get('accuracy', 0),
                "llm_consistency": llm_evaluation.get('consistency', 0),
                "llm_coverage": llm_evaluation.get('coverage', 0),
                "llm_comments": llm_evaluation.get('comments', 'N/A')
            }
            result['evaluation'] = evaluation
            
            result['status'] = 'success'
            result['duration'] = time.time() - start_time
            result['end_time'] = datetime.now().isoformat()
            
            logger.info(f"\n{case_id} completed successfully")
            logger.info(f"Duration: {int(result['duration'])}s")
            logger.info("Evaluation results:")
            logger.info(f"   - Cell recall: {evaluation['cell_recall']:.2f}%")
            logger.info(f"   - Cell precision: {evaluation['cell_precision']:.2f}%")
            logger.info(f"   - LLM score: {evaluation['llm_score']:.1f}/100")
            logger.info(f"Comments: {evaluation['llm_comments']}")
            
        except Exception as e:
            result['status'] = 'failed'
            result['error'] = str(e)
            result['duration'] = time.time() - start_time
            result['end_time'] = datetime.now().isoformat()
            logger.error(f"\nFailed to process {case_id}: {e}")
            import traceback
            traceback.print_exc()
        
        return result
    
    def run_evaluation(self):
        """Run the full evaluation workflow."""
        logger.info("Starting LLM extraction evaluation")
        
        cases = self.scan_datasets()
        
        if not cases:
            logger.error("No valid test cases found")
            return
        
        for i, case_info in enumerate(cases, 1):
            logger.info(f"Progress: {i}/{len(cases)}")
            
            result = self.process_case(case_info)
            self.results.append(result)
            
            time.sleep(1)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='LLM extraction capability evaluation system',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Example usage:
  python llm_evaluate.py
  
  python llm_evaluate.py --model gpt-4o
  
  python llm_evaluate.py --force-rerun
  
  python llm_evaluate.py --model gpt-4o --run-name exp_001
  
  python llm_evaluate.py --chunk-size 15000 --chunk-overlap 800
  
  python llm_evaluate.py --model qwen-long --run-name test_001 --chunk-size 20000 --force-rerun
        '''
    )
    
    parser.add_argument('--model', type=str, default=DEFAULT_MODEL,
                        help=f'Model name to use (default: {DEFAULT_MODEL})')
    parser.add_argument('--run-name', type=str, default=None,
                        help='Run name to distinguish different experiments (optional)')
    parser.add_argument('--chunk-size', type=int, default=DEFAULT_CHUNK_SIZE,
                        help=f'Document chunk size in characters (default: {DEFAULT_CHUNK_SIZE})')
    parser.add_argument('--chunk-overlap', type=int, default=DEFAULT_CHUNK_OVERLAP,
                        help=f'Overlap between chunks in characters (default: {DEFAULT_CHUNK_OVERLAP})')
    parser.add_argument('--force-rerun', action='store_true',
                        help='Force rerun of all cases, even if already processed (default: False, skips processed cases)')
    
    args = parser.parse_args()
    
    evaluator = LLMExtractorEvaluator(
        model=args.model,
        run_name=args.run_name,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        force_rerun=args.force_rerun
    )
    
    try:
        evaluator.run_evaluation()
    except KeyboardInterrupt:
        logger.warning("Evaluation interrupted by user")
    except Exception as e:
        logger.error(f"Evaluation failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()


