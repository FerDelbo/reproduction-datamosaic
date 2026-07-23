"""Coordinator tool module"""
import os
import json
import logging
from typing import List, Dict, Any, Optional

from .context import Doc2DBContext


class SchemaUtils:
    """Schema processing tool class"""
    
    @staticmethod
    def extract_table_names_from_schema(schema: Dict[str, Any]) -> List[str]:
        """Extract all table names from Schema and automatically process tables with the same name (add number suffix)"""
        table_names = []
        
        if 'tables' in schema and isinstance(schema['tables'], list):
            for table in schema['tables']:
                if isinstance(table, dict) and 'name' in table:
                    table_names.append(table['name'])
        
        elif 'table_name' in schema and 'columns' in schema:
            table_names.append(schema['table_name'])
        
        if table_names:
            name_counts = {}
            unique_names = []
            
            for name in table_names:
                if name not in name_counts:
                    name_counts[name] = 0
                name_counts[name] += 1
            
            name_indices = {}
            for name in table_names:
                if name_counts[name] > 1:
                    if name not in name_indices:
                        name_indices[name] = 1
                    unique_name = f"{name}_{name_indices[name]}"
                    name_indices[name] += 1
                    unique_names.append(unique_name)
                else:
                    unique_names.append(name)
            
            return unique_names
        
        return table_names
    
    @staticmethod
    def classify_tables_by_type(schema: Dict[str, Any]) -> Dict[str, List[str]]:
        """Classify tables into entity tables and relational tables
        
        New logic: directly read the "type" field of the table in the schema to classify
        - type: "entity" → entity table
        - type: "relationship" → relationship table
        - If there is no type field, it defaults to the entity table
        
        Returns:
            {
                'entity_tables': ['court', 'case', 'person', ...],
                'relation_tables': ['caseparty', ...]
            }"""
        if not isinstance(schema, dict):
            return {'entity_tables': [], 'relation_tables': []}
        
        entity_tables = []
        relation_tables = []
        
        if 'tables' in schema and isinstance(schema['tables'], list):
            for table in schema['tables']:
                if not isinstance(table, dict) or 'name' not in table:
                    continue
                
                table_name = table['name']
                table_type = table.get('type', 'entity')  # Default is entity table
                
                if table_type == 'relation':
                    relation_tables.append(table_name)
                else:
                    entity_tables.append(table_name)
        
        elif 'table_name' in schema:
            table_name = schema['table_name']
            table_type = schema.get('type', 'entity')
            
            if table_type == 'relation':
                relation_tables.append(table_name)
            else:
                entity_tables.append(table_name)
        
        return {
            'entity_tables': entity_tables,
            'relation_tables': relation_tables
        }
    
    @staticmethod
    def extract_table_specific_schema(schema: Dict[str, Any], table_name: str) -> Optional[Dict[str, Any]]:
        """Extract the schema definition of a specific table from the complete schema
        
        Supports numbered table names (such as tax_1, tax_2), which will automatically parse and find the corresponding original table definition."""
        if not isinstance(schema, dict):
            return None
        
        if 'tables' in schema and isinstance(schema['tables'], list):
            for table in schema['tables']:
                if isinstance(table, dict) and table.get('name') == table_name:
                    return {
                        'tables': [table],
                        'table_name': table_name
                    }
            
            if '_' in table_name and table_name.rsplit('_', 1)[-1].isdigit():
                base_name = table_name.rsplit('_', 1)[0]
                suffix_num = int(table_name.rsplit('_', 1)[1])
                
                matching_tables = [
                    table for table in schema['tables']
                    if isinstance(table, dict) and table.get('name') == base_name
                ]
                
                if matching_tables and 1 <= suffix_num <= len(matching_tables):
                    target_table = matching_tables[suffix_num - 1]
                    return {
                        'tables': [target_table],
                        'table_name': table_name  # Use numbered table name
                    }
        
        elif schema.get('table_name') == table_name and 'columns' in schema:
            return schema  # Already in single table format
        
        return None


class DocumentUtils:
    """Document processing tools"""
    
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger('document_utils')
    
    def convert_documents_to_text(self, documents: List[str]) -> List[str]:
        """Convert document path to text content"""
        text_contents = []
        
        for doc_path in documents:
            try:
                file_ext = os.path.splitext(doc_path.lower())[1]
                
                if file_ext in ['.txt', '.md']:
                    try:
                        with open(doc_path, 'r', encoding='utf-8') as f:
                            text_content = f.read()
                    except UnicodeDecodeError:
                        with open(doc_path, 'r', encoding='gbk') as f:
                            text_content = f.read()
                    text_contents.append(text_content)
                    
                elif file_ext in ['.pdf', '.docx', '.doc']:
                    from ...utils.textin_parser import TextinParser
                    parser = TextinParser()
                    
                    parse_result = parser.parse_pdf_with_textin(doc_path, main_content_only=True)
                    markdown_content = parse_result.get('markdown_content', '')
                    
                    if markdown_content:
                        text_contents.append(markdown_content)
                    else:
                        self.logger.warning(f"Failed to extract content from document {doc_path}")
                        text_contents.append("")
                        
                else:
                    self.logger.warning(f"Unsupported file format: {doc_path}")
                    text_contents.append("")
                    
            except Exception as e:
                self.logger.error(f"Failed to process document {doc_path}: {e}")
                text_contents.append("")
        
        return text_contents


class SignalUtils:
    """Signal processing tools"""
    
    @staticmethod
    def create_extraction_signal_data(context: Doc2DBContext, table_name: str, table_specific_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Create extracted signal data"""
        document_utils = DocumentUtils()
        
        return {
            'context': {
                'run_id': context.run_id,
                'table_name': table_name,
                'schema': table_specific_schema,
                'full_schema': context.schema,
                'text_contents': document_utils.convert_documents_to_text(context.documents),
                'nl_prompt': context.nl_prompt or context.user_query,
                'processing_context': context
            }
        }
    
    @staticmethod
    def create_verification_signal_data(context: Doc2DBContext, table_name: str, 
                                      table_specific_schema: Dict[str, Any], snapshots: List) -> Dict[str, Any]:
        """Create verification signal data"""
        return {
            'context': {
                'run_id': context.run_id,
                'table_name': table_name,
                'schema': table_specific_schema,
                'full_schema': context.schema,
                'processing_context': context
            },
            'snapshots': snapshots
        }
    
    @staticmethod
    def create_fixing_signal_data(context: Doc2DBContext, table_name: str, 
                                table_specific_schema: Dict[str, Any], violations: List, snapshot) -> Dict[str, Any]:
        """Create repair signal data"""
        return {
            'context': {
                'run_id': context.run_id,
                'table_name': table_name,
                'schema': table_specific_schema,
                'full_schema': context.schema,
                'processing_context': context
            },
            'violations': violations,
            'snapshot': snapshot
        }
    
    @staticmethod
    def get_correlation_id(run_id: str, table_name: str, operation: str, timestamp: Optional[int] = None) -> str:
        """Generate association ID"""
        if timestamp is None:
            import time
            timestamp = int(time.time() * 1000)
        return f"{run_id}_{table_name}_{operation}_{timestamp}"


class StepUtils:
    """Step processing tools"""
    
    @staticmethod
    def create_start_step(context: Doc2DBContext) -> Dict[str, Any]:
        """Create a start processing step"""
        return {
            'step': 'orchestrator_start',
            'description': 'Orchestrator started processing',
            'status': 'completed',
            'timestamp': context.io_manager.get_timestamp(),
            'details': {
                'run_id': context.run_id,
                'target_tables': getattr(context, 'target_tables', []),
                'signal_mode': True
            }
        }
    
    @staticmethod
    def create_completion_step(context: Doc2DBContext) -> Dict[str, Any]:
        """Create completion steps"""
        return {
            'step': 'orchestrator_completion',
            'step_name': 'orchestrator_completion',
            'description': 'Data processing complete - all tables extracted, verified, and fixed',
            'status': 'completed',
            'timestamp': context.io_manager.get_timestamp(),
            'details': {
                'total_tables_processed': len(context.all_snapshots),
                'total_snapshots': len(context.all_snapshots),
                'total_violations': sum(len(v) for v in context.all_violations.values()),
                'total_fixes': sum(len(f) for f in context.all_fixes.values()),
                'processing_state': context.current_state.value,
                'processing_summary': {
                    'extraction_completed': True,
                    'verification_completed': True,
                    'fixing_completed': True,
                    'quality_issues_resolved': sum(len(f) for f in context.all_fixes.values())
                }
            },
            'final_stats': {
                'tables': list(context.all_snapshots.keys()),
                'success': True,
                'completion_time': context.io_manager.get_timestamp()
            }
        }
    
    @staticmethod
    def create_error_step(context: Doc2DBContext, error: Exception, step_name: str = 'orchestrator_error') -> Dict[str, Any]:
        """Create error steps"""
        return {
            'step': step_name,
            'description': f'Orchestrator processing exception: {str(error)}',
            'status': 'failed',
            'timestamp': context.io_manager.get_timestamp(),
            'error': str(error),
            'details': {
                'exception_type': type(error).__name__,
                'processing_state': context.current_state.value
            }
        }


class DataTransferUtils:
    """Data transfer tools"""
    
    @staticmethod
    def transfer_processing_results(context: Doc2DBContext):
        """Transfer multi-table processing results to the context main field"""
        if context.all_snapshots:
            context.snapshots = list(context.all_snapshots.values())
        
        if context.all_violations:
            context.violations = []
            for table_name, table_violations in context.all_violations.items():
                context.violations.extend(table_violations)
        
        if context.all_fixes:
            context.fixes = []
            for table_name, table_fixes in context.all_fixes.items():
                context.fixes.extend(table_fixes)
    
    @staticmethod
    def save_final_snapshots(context: Doc2DBContext):
        """Save final completed state snapshot"""
        for table_name, snapshot in context.all_snapshots.items():
            if snapshot and hasattr(snapshot, 'rows') and snapshot.rows:
                original_row_count = len(snapshot.rows)
                snapshot.rows = [
                    row for row in snapshot.rows
                    if not any(
                        (hasattr(cell, 'value') and (cell.value == "__DELETED__" or str(cell.value) == "__DELETED__"))
                        for cell in row.cells.values()
                    )
                ]
                deleted_row_count = original_row_count - len(snapshot.rows)
                if deleted_row_count > 0:
                    context.io_manager.logger.info(f'[Final cleanup] Table {table_name}: cleaned {deleted_row_count} rows marked __DELETED__')
            
            final_snapshot = snapshot
            final_snapshot.processing_stage = 'final'
            final_snapshot.stage_description = f'Final completed state - table {table_name}'
            context.io_manager.append_snapshot(final_snapshot)
        
        DataTransferUtils.save_result_json(context)
    
    @staticmethod
    def save_result_json(context: Doc2DBContext):
        """Generate result.json file
        
        Only output the target table requested by the user, excluding the reference table (auxiliary table used for relationship extraction verification)"""
        try:
            import json
            from pathlib import Path
            
            best_snapshots = {}
            for table_name in context.target_tables:
                if table_name in context.all_snapshots:
                    snapshot = context.all_snapshots[table_name]
                    
                    if hasattr(snapshot, 'processing_stage') and snapshot.processing_stage == 'reference_data':
                        context.io_manager.logger.debug(f'Skipping reference table {table_name} (not included in result.json)')
                        continue
                    
                    best_snapshots[table_name] = snapshot
            
            if not best_snapshots:
                context.io_manager.logger.warning("target_tables snapshots are empty, attempting to read final snapshots from file")
                best_snapshots = DataTransferUtils._find_final_snapshots_from_file(context)
            
            tables_data = {}
            
            schema_field_orders = {}
            if hasattr(context, 'schema') and context.schema:
                schema = context.schema
                if isinstance(schema, str):
                    import json as json_module
                    schema = json_module.loads(schema)
                
                if 'tables' in schema and isinstance(schema['tables'], list):
                    for table in schema['tables']:
                        table_name_key = table.get('name')
                        fields_list = table.get('attributes') or table.get('fields', [])
                        if table_name_key and fields_list:
                            field_order = [f.get('name') or f.get('field_name') for f in fields_list if f.get('name') or f.get('field_name')]
                            schema_field_orders[table_name_key] = field_order
            
            for table_name, snapshot in best_snapshots.items():
                if not snapshot or not hasattr(snapshot, 'rows') or not snapshot.rows:
                    continue
                
                first_row = snapshot.rows[0]
                if not hasattr(first_row, 'cells') or not first_row.cells:
                    continue
                
                if table_name in schema_field_orders:
                    headers = [field for field in schema_field_orders[table_name] if field in first_row.cells]
                    for field in first_row.cells.keys():
                        if field not in headers:
                            headers.append(field)
                else:
                    headers = list(first_row.cells.keys())
                    context.io_manager.logger.warning(f"Table {table_name} not found in schema, using order inferred from cells")
                
                table_rows = []
                skipped_deleted_rows = 0  # Count skipped delete marked rows
                
                for row in snapshot.rows:
                    has_deleted_marker = False
                    for header in headers:
                        cell = row.cells.get(header)
                        if cell:
                            cell_value = None
                            if hasattr(cell, 'value'):
                                cell_value = cell.value
                            elif hasattr(cell, 'best') and hasattr(cell.best, 'value'):
                                cell_value = cell.best.value
                            
                            if cell_value == "__DELETED__" or str(cell_value) == "__DELETED__":
                                has_deleted_marker = True
                                break
                    
                    if has_deleted_marker:
                        skipped_deleted_rows += 1
                        context.io_manager.logger.debug(f"Skipping row marked for deletion: {row.tuple_id}")
                        continue
                    
                    row_data = {}
                    for header in headers:
                        cell = row.cells.get(header)
                        if cell:
                            if hasattr(cell, 'value'):
                                row_data[header] = cell.value
                            elif hasattr(cell, 'best') and hasattr(cell.best, 'value'):
                                row_data[header] = cell.best.value
                            else:
                                row_data[header] = ''
                        else:
                            row_data[header] = ''
                    table_rows.append(row_data)
                
                if skipped_deleted_rows > 0:
                    context.io_manager.logger.info(f"Table {table_name}: filtered {skipped_deleted_rows} rows marked for deletion")
                
                tables_data[table_name] = table_rows
            
            result_data = {
                'run_id': context.run_id,
                'tables': tables_data
            }
            
            result_file = context.io_manager.output_dir / 'result.json'
            with open(result_file, 'w', encoding='utf-8') as f:
                json.dump(result_data, f, ensure_ascii=False, indent=2, sort_keys=False)
            
            import os
            if not (os.path.exists(result_file) and os.path.getsize(result_file) > 0):
                context.io_manager.logger.warning(f"result.json write may not have completed: {result_file}")
            
        except Exception as e:
            context.io_manager.logger.error(f"Failed to generate result.json: {e}")
    
    @staticmethod
    def _find_final_snapshots_from_file(context: Doc2DBContext):
        """Read the final stage snapshot from the snapshots.jsonl file
        
        The snapshots in the final stage are saved in save_final_snapshots.
        Represents the content of context.all_snapshots (already contains the complete data after all batch merges)"""
        try:
            import json
            from ...memory.snapshot import TableSnapshot
            
            snapshots_file = context.io_manager.output_dir / 'snapshots.jsonl'
            if not snapshots_file.exists():
                context.io_manager.logger.warning(f"snapshots.jsonl file does not exist: {snapshots_file}")
                return None
            
            final_snapshots = {}
            with open(snapshots_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        snapshot_dict = json.loads(line)
                        table_name = snapshot_dict.get('table')
                        stage = snapshot_dict.get('processing_stage', '')
                        
                        if stage == 'final' and table_name:
                            try:
                                snapshot_obj = TableSnapshot.from_dict(snapshot_dict)
                                final_snapshots[table_name] = snapshot_obj
                                context.io_manager.logger.info(
                                    f"Read final snapshot for table {table_name} from file: {len(snapshot_obj.rows)} rows"
                                )
                            except Exception as e:
                                context.io_manager.logger.error(f"Failed to convert snapshot: {e}")
                    except Exception as e:
                        continue
            
            return final_snapshots if final_snapshots else None
                
        except Exception as e:
            context.io_manager.logger.error(f"Failed to read final snapshots from file: {e}")
            return None


class DebugUtils:
    """Debugging tool class"""
    
    @staticmethod
    def write_debug_log(context: Doc2DBContext, message: str):
        """Write debug log"""
        try:
            with open(f"{context.io_manager.base_path}/debug_orchestrator.log", "a", encoding="utf-8") as f:
                f.write(f"[{context.io_manager.get_timestamp()}] {message}\n")
        except:
            pass  # Ignore log writing errors
    
    @staticmethod
    def ensure_completion_step(context: Doc2DBContext) -> bool:
        """Make sure there is a record of the completed steps (do it all)"""
        has_completion_step = any(
            ('Orchestrator完成所有处理流程' in step.get('description', '') or 'Orchestrator completed all processing' in step.get('description', ''))
            for step in context.step_outputs
        )
        
        if not has_completion_step:
            completion_step = {
                'step': 'orchestrator_completion_fallback',
                'description': 'Orchestrator completed all processing',
                'status': 'completed',
                'timestamp': context.io_manager.get_timestamp(),
                'details': {'fallback': True, 'sync_call': True}
            }
            context.step_outputs.append(completion_step)
            return True
        
        return False
