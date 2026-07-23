"""Smart MCP Router - Choose the right authentication components using LLM Agent"""
import json
import re
import logging
from typing import List, Dict, Any, Tuple
from ...memory import TableSnapshot

from llm.main import get_answer


class MCPRouter:
    """Smart MCP Router - LLM-Based Verified Component Selection"""
    
    def __init__(self):
        self.logger = logging.getLogger('doc2db.mcp_router')
        
        self.mandatory_mcps = [
            "TypeMCP",       # Type verification
            "StructureMCP"   # Structure verification (non-null, uniqueness, etc.)
        ]
        
        self.optional_mcps = {
            "ValueMCP": {
                "description": "Value domain constraint verifier",
                "scenarios": "Verifies numeric ranges, enum values, string length, and other value-domain constraints. Suitable for fields with explicit allowed ranges."
            },
            "FormatMCP": {
                "description": "Format constraint verifier",
                "scenarios": "Verifies phone numbers, email addresses, IDs, codes, and other formats. Suitable for fields with fixed format requirements."
            },
            "TemporalMCP": {
                "description": "Temporal constraint verifier",
                "scenarios": "Verifies date/time validity and logical relationships. Suitable for tables containing date or time fields."
            },
            "ReferenceMCP": {
                "description": "Reference constraint verifier",
                "scenarios": "Verifies foreign key referential integrity. Suitable for tables with foreign key relationships."
            },
            "AggregationMCP": {
                "description": "Aggregation constraint verifier",
                "scenarios": "Verifies calculated fields (for example, total = unit price x quantity). Suitable for tables with computed relationships."
            },
            "LogicMCP": {
                "description": "Business logic verifier (uses LLM; higher cost)",
                "scenarios": "Verifies complex business rules and logical consistency. Suitable for finance, contracts, transactions, and other complex business scenarios."
            }
        }
        
        self.logger.info(f"Initialized MCP router: {len(self.mandatory_mcps)} mandatory MCPs, {len(self.optional_mcps)} optional MCPs")
    
    def select_mcps(self, snapshot: TableSnapshot, schema: Dict[str, Any], 
                   table_name: str) -> Tuple[List[str], Dict[str, Any]]:
        """Select the MCP component that needs to be executed
        
        Args:
            snapshot: table snapshot
            schema: table structure definition
            table_name: table name
            
        Returns:
            (selected_mcps, routing_info): Selected MCP list and routing decision information"""
        table_schema_str = self._format_table_schema(schema, table_name)
        data_sample_str = self._format_data_sample(snapshot, max_rows=5)
        available_mcps_str = self._format_available_mcps()
        
        try:
            selected_optional = self._llm_select_mcps(
                table_name=table_name,
                table_schema=table_schema_str,
                data_sample=data_sample_str,
                available_mcps=available_mcps_str,
            )
            
            valid_optional_set = set(self.optional_mcps.keys())
            selected_optional = [m for m in selected_optional if m in valid_optional_set]
            
            all_selected = self.mandatory_mcps + selected_optional
            
            skipped = list(valid_optional_set - set(selected_optional))
            
            routing_info = {
                "mandatory_mcps": self.mandatory_mcps,
                "optional_mcps_selected": selected_optional,
                "optional_mcps_skipped": skipped
            }
            
            return all_selected, routing_info
            
        except Exception as e:
            self.logger.error(f"LLM routing decision failed: {e}")
            
            all_mcps = self.mandatory_mcps + list(self.optional_mcps.keys())
            routing_info = {
                "mandatory_mcps": self.mandatory_mcps,
                "optional_mcps_selected": list(self.optional_mcps.keys()),
                "optional_mcps_skipped": []
            }
            
            return all_mcps, routing_info
    
    def _llm_select_mcps(self, table_name: str, table_schema: str,
                         data_sample: str, available_mcps: str) -> List[str]:
        """Call LLM to select the MCP component and return the selected MCP name list"""
        system_prompt = (
            "You are a data validation routing assistant."
            "Based on the table schema and sample data, select the necessary optional verification components (MCPs) from the candidates."
            "Return strict JSON only with no explanation or Markdown fences."
            'JSON format: {"selected_mcps": ["MCPName1", "MCPName2"]}'
        )
        
        user_prompt = f"""Select the verification components (MCPs) to run based on the table characteristics.

Table name: {table_name}

Table schema:
{table_schema}

Data sample:
{data_sample}

Optional verification components:
{available_mcps}

Selection rules:
- ValueMCP: value-domain constraints (min/max/enum) or numeric fields
- FormatMCP: fields with format requirements (phone/email/id/code)
- TemporalMCP: date or time fields
- ReferenceMCP: foreign key fields
- AggregationMCP: fields with computed relationships
- LogicMCP: complex business logic (finance/contract/transaction, etc.; higher cost, choose carefully)

Return JSON only: {{"selected_mcps": ["MCPName", ...]}}
"""
        
        llm_response = get_answer(user_prompt, system_prompt=system_prompt)
        
        return self._parse_selected_mcps(llm_response)
    
    @staticmethod
    def _parse_selected_mcps(llm_response: str) -> List[str]:
        """Parse the selected_mcps list from the LLM response"""
        if not llm_response:
            return []
        
        json_str = None
        match = re.search(r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```', llm_response, re.DOTALL)
        if match:
            json_str = match.group(1)
        else:
            match = re.search(r'\{.*?\}', llm_response, re.DOTALL)
            if match:
                json_str = match.group(0)
        
        if not json_str:
            json_str = llm_response.strip()
        
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            return []
        
        if isinstance(data, dict):
            selected = data.get('selected_mcps', [])
        elif isinstance(data, list):
            selected = data
        else:
            return []
        
        return [str(m).strip() for m in selected if m]
    
    def _format_table_schema(self, schema: Dict[str, Any], table_name: str) -> str:
        """Format table structure definition"""
        try:
            tables = schema.get('tables', [])
            table_def = None
            
            for table in tables:
                if table.get('name') == table_name:
                    table_def = table
                    break
            
            if not table_def:
                return f"Schema definition for table {table_name} not found"
            
            attributes = table_def.get('attributes', [])
            schema_lines = [f"Table name: {table_name}"]
            schema_lines.append(f"Field count: {len(attributes)}")
            schema_lines.append("\nField list:")
            
            for attr in attributes:
                attr_name = attr.get('name', 'unknown')
                attr_type = attr.get('type', 'unknown')
                constraints = attr.get('constraints', {})
                
                constraint_strs = []
                if constraints.get('not_null'):
                    constraint_strs.append("NOT NULL")
                if constraints.get('unique'):
                    constraint_strs.append("UNIQUE")
                if 'min' in constraints or 'max' in constraints:
                    constraint_strs.append(f"range constraint")
                if 'enum' in constraints:
                    constraint_strs.append(f"enum values")
                if 'format' in constraints:
                    constraint_strs.append(f"format: {constraints['format']}")
                
                constraint_str = f" [{', '.join(constraint_strs)}]" if constraint_strs else ""
                schema_lines.append(f"  - {attr_name}: {attr_type}{constraint_str}")
            
            return "\n".join(schema_lines)
            
        except Exception as e:
            self.logger.error(f"Failed to format table schema: {e}")
            return f"Failed to format table schema: {str(e)}"
    
    def _format_data_sample(self, snapshot: TableSnapshot, max_rows: int = 5) -> str:
        """Formatted data sample"""
        try:
            if not snapshot.rows:
                return "Data is empty"
            
            sample_rows = snapshot.rows[:max_rows]
            
            if sample_rows:
                field_names = list(sample_rows[0].cells.keys())
            else:
                return "Data is empty"
            
            lines = [f"Row count: {len(snapshot.rows)} (showing first {len(sample_rows)} rows)"]
            lines.append("")
            
            header = "| " + " | ".join(field_names) + " |"
            separator = "|" + "|".join(["---" for _ in field_names]) + "|"
            lines.append(header)
            lines.append(separator)
            
            for row in sample_rows:
                values = []
                for field_name in field_names:
                    cell = row.cells.get(field_name)
                    value = str(cell.value) if cell and cell.value is not None else ""
                    if len(value) > 30:
                        value = value[:27] + "..."
                    values.append(value)
                
                line = "| " + " | ".join(values) + " |"
                lines.append(line)
            
            return "\n".join(lines)
            
        except Exception as e:
            self.logger.error(f"Failed to format data sample: {e}")
            return f"Failed to format data sample: {str(e)}"
    
    def _format_available_mcps(self) -> str:
        """Format available MCP list"""
        lines = []
        for mcp_name, mcp_info in self.optional_mcps.items():
            lines.append(f"- {mcp_name}: {mcp_info['scenarios']}")
        return "\n".join(lines)
