"""
Extractor utility module.
Utility functions for data parsing, deduplication, and format conversion.
"""

import re
import json
import logging
from typing import List, Dict, Any

from ...memory import TableRow, CellData
from ...core.ids import IdGenerator


class ExtractorUtils:
    """Extractor utility class."""
    
    def __init__(self, logger: logging.Logger = None):
        self.logger = logger or logging.getLogger('doc2db.extractor.utils')
    
    
    def parse_markdown_table_response(self, llm_response: str, 
                                     table_def: Dict[str, Any], 
                                     doc_source: str) -> List[TableRow]:
        """Parse a response containing a Markdown table.

        Args:
            llm_response: LLM response containing a Markdown table.
            table_def: Table definition.
            doc_source: Data source.

        Returns:
            List of parsed TableRow objects.
        """
        rows = []
        
        try:
            table_match = re.search(r'<TABLE BEGIN>(.*?)<TABLE END>', llm_response, re.DOTALL)
            if not table_match:
                return rows
            
            table_markdown = table_match.group(1).strip()
            lines = [line.strip() for line in table_markdown.strip().split('\n') if line.strip()]
            
            if len(lines) < 3:
                return rows
            
            header_line = lines[0]
            column_names = [col.strip() for col in header_line.split('|')[1:-1]]
            
            data_lines = lines[2:]
            attributes = table_def.get('attributes', [])
            schema_fields = {attr['name']: attr for attr in attributes}
            
            for row_index, data_line in enumerate(data_lines):
                if not data_line.startswith('|') or not data_line.endswith('|'):
                    continue
                
                cells_data = [cell.strip() for cell in data_line.split('|')[1:-1]]
                if not cells_data:
                    continue
                
                tuple_id = IdGenerator.generate_tuple_id(
                    table_def.get('name', 'table'), row_index, cells_data
                )
                
                cells = {}
                for col_index, cell_value in enumerate(cells_data):
                    if col_index < len(column_names):
                        column_name = column_names[col_index].strip()
                        
                        if column_name in schema_fields:
                            clean_value = cell_value.strip()
                            cells[column_name] = CellData(
                                value=clean_value,
                                evidences=[doc_source]
                            )
                
                if cells:
                    row = TableRow(tuple_id=tuple_id, cells=cells)
                    rows.append(row)
            
        except Exception as e:
            self.logger.error(f"Failed to parse Markdown table: {e}")
        
        return rows
    
    
    def parse_cell_fix_json(self, llm_response: str) -> List[Dict[str, Any]]:
        """Parse the cell-fix JSON returned by the LLM.

        Args:
            llm_response: JSON response returned by the LLM.

        Returns:
            List of fix data, each containing tuple_id, field, and new_value.
        """
        json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', llm_response, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_str = llm_response.strip()
        
        try:
            data = json.loads(json_str)
            
            if isinstance(data, dict) and 'fixes' in data:
                fixes = data['fixes']
            elif isinstance(data, list):
                fixes = data
            else:
                return []
            
            valid_fixes = []
            for fix in fixes:
                if isinstance(fix, dict) and all(k in fix for k in ['tuple_id', 'field', 'new_value']):
                    valid_fixes.append(fix)
            
            return valid_fixes
            
        except json.JSONDecodeError as e:
            self.logger.error(f"JSON parsing failed: {e}")
            return []
    
    
    def deduplicate_rows(self, rows: List[TableRow]) -> List[TableRow]:
        """Deduplicate rows based on a field-value signature.

        Args:
            rows: Original list of rows.

        Returns:
            Deduplicated list of rows.
        """
        if not rows:
            return rows
        
        seen_signatures = set()
        deduplicated_rows = []
        
        for row in rows:
            signature = self.create_row_signature(row)
            
            if signature not in seen_signatures:
                seen_signatures.add(signature)
                deduplicated_rows.append(row)
        
        if len(deduplicated_rows) < len(rows):
            self.logger.info(f"Deduplicated: {len(rows)} rows -> {len(deduplicated_rows)} rows")
        
        return deduplicated_rows
    
    def create_row_signature(self, row: TableRow) -> str:
        """Create a row signature for deduplication.

        Args:
            row: Table row.

        Returns:
            Unique signature string for the row.
        """
        values = []
        
        sorted_cells = sorted(row.cells.items(), key=lambda x: x[0])
        
        for field_name, cell_data in sorted_cells:
            if hasattr(cell_data, 'value'):
                value = cell_data.value
            else:
                value = str(cell_data)
            
            normalized = self.normalize_value_for_dedup(value)
            if normalized:
                values.append(f"{field_name}:{normalized}")
        
        return "||".join(values)
    
    def normalize_value_for_dedup(self, value) -> str:
        """Normalize a value for deduplication.

        Args:
            value: Original value.

        Returns:
            Normalized string.
        """
        if value is None:
            return ""
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, (int, float)):
            return str(value)
        return str(value).strip().lower()
    
    
    def generate_default_schema_from_prompt(self, table_name: str, 
                                           nl_prompt: str) -> Dict[str, Any]:
        """Generate a default schema from a natural-language prompt.

        Args:
            table_name: Table name.
            nl_prompt: Natural-language prompt.

        Returns:
            Generated schema dict.
        """
        default_attributes = [
            {'name': 'id', 'type': 'TEXT', 'description': 'Unique record identifier'}
        ]
        
        if nl_prompt and nl_prompt.strip():
            prompt_lower = nl_prompt.lower()
            
            if any(word in prompt_lower for word in ['订单编号', 'order_id', '编号', 'id']):
                default_attributes.append({'name': 'order_id', 'type': 'TEXT', 'description': 'Order number'})
            if any(word in prompt_lower for word in ['客户', '姓名', 'customer', 'name']):
                default_attributes.append({'name': 'customer_name', 'type': 'TEXT', 'description': 'Customer name'})
            if any(word in prompt_lower for word in ['金额', 'amount', '价格', 'price', '费用']):
                default_attributes.append({'name': 'amount', 'type': 'DECIMAL', 'description': 'Amount'})
            if any(word in prompt_lower for word in ['日期', 'date', '时间', 'time']):
                default_attributes.append({'name': 'date', 'type': 'DATE', 'description': 'Date'})
            if any(word in prompt_lower for word in ['商品', 'product', '产品', 'item']):
                default_attributes.append({'name': 'product', 'type': 'TEXT', 'description': 'Product information'})
        
        if len(default_attributes) == 1:
            default_attributes.extend([
                {'name': 'content', 'type': 'TEXT', 'description': 'Extracted content'},
                {'name': 'category', 'type': 'TEXT', 'description': 'Category information'}
            ])
        
        return {
            'tables': [{
                'name': table_name,
                'attributes': default_attributes
            }]
        }
    
    
    def build_simple_schema_prompt(self, table_def: Dict[str, Any]) -> str:
        """Build a simple schema prompt.

        Args:
            table_def: Table definition.

        Returns:
            Schema prompt string.
        """
        table_name = table_def.get('name', 'data_table')
        attributes = table_def.get('attributes', [])
        
        prompt = f"Target Table: {table_name}\n\nFields:\n"
        for attr in attributes:
            prompt += f"- {attr['name']} ({attr.get('type', 'TEXT')}): {attr.get('description', 'N/A')}\n"
        
        return prompt

