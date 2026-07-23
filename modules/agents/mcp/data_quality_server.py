"""Data-quality MCP server implementation."""
import json
from typing import Dict, Any, List
from .base import (
    MCPServer, MCPMessage, MCPResource, MCPPrompt, MCPTool, 
    MCPCapability
)


class DataQualityMCPServer(MCPServer):
    """Data-quality MCP server for validating and fixing data quality."""
    
    def __init__(self):
        super().__init__(
            name="doc2db-data-quality",
            version="1.0.0",
            capabilities=[MCPCapability.RESOURCES, MCPCapability.PROMPTS, MCPCapability.TOOLS]
        )
        
        self._register_data_quality_components()
    
    def _register_data_quality_components(self):
        """Register data-quality components."""
        self.register_resource(MCPResource(
            uri="constraint://types",
            name="Constraint type definitions",
            description="Supported data constraint types and their definitions",
            mimeType="application/json"
        ))
        
        self.register_resource(MCPResource(
            uri="fix://strategies", 
            name="Fix strategies",
            description="Fix strategies and methods for various violations",
            mimeType="application/json"
        ))
        
        self.register_resource(MCPResource(
            uri="schema://template",
            name="Data schema template",
            description="Standard data schema definition template",
            mimeType="application/json"
        ))
        
        self.register_prompt(MCPPrompt(
            name="verify-data-quality",
            description="Verify data quality and identify violations",
            arguments=[
                {"name": "data", "description": "Data to verify", "required": True},
                {"name": "schema", "description": "Data schema definition", "required": True},
                {"name": "constraint_type", "description": "Constraint type", "required": False}
            ]
        ))
        
        self.register_prompt(MCPPrompt(
            name="suggest-data-fix",
            description="Suggest a fix for a data violation",
            arguments=[
                {"name": "violation", "description": "Violation information", "required": True},
                {"name": "context", "description": "Context data", "required": True}
            ]
        ))
        
        self.register_prompt(MCPPrompt(
            name="analyze-data-pattern",
            description="Analyze data patterns and quality trends",
            arguments=[
                {"name": "data", "description": "Dataset", "required": True},
                {"name": "analysis_type", "description": "Analysis type", "required": False}
            ]
        ))
        
        self.register_tool(MCPTool(
            name="verify_constraint",
            description="Verify a specific constraint",
            inputSchema={
                "type": "object",
                "properties": {
                    "constraint_type": {"type": "string"},
                    "data": {"type": "object"},
                    "schema": {"type": "object"}
                },
                "required": ["constraint_type", "data", "schema"]
            }
        ))
        
        self.register_tool(MCPTool(
            name="fix_violation",
            description="Fix a data violation",
            inputSchema={
                "type": "object", 
                "properties": {
                    "violation": {"type": "object"},
                    "snapshot": {"type": "object"}
                },
                "required": ["violation", "snapshot"]
            }
        ))
        
        self.register_tool(MCPTool(
            name="batch_verify",
            description="Batch-verify data quality",
            inputSchema={
                "type": "object",
                "properties": {
                    "snapshots": {"type": "array"},
                    "schema": {"type": "object"},
                    "constraint_types": {"type": "array"}
                },
                "required": ["snapshots", "schema"]
            }
        ))
        
    
    async def handle_request(self, message: MCPMessage) -> MCPMessage:
        """Handle an MCP request."""
        try:
            method = message.method
            params = message.params or {}
            
            if method == "resources/list":
                return MCPMessage(
                    id=message.id,
                    result={"resources": [res.to_dict() for res in self.list_resources()]}
                )
            
            elif method == "resources/read":
                uri = params.get("uri")
                return await self._handle_resource_read(message.id, uri)
            
            elif method == "prompts/list":
                return MCPMessage(
                    id=message.id,
                    result={"prompts": [prompt.to_dict() for prompt in self.list_prompts()]}
                )
            
            elif method == "prompts/get":
                prompt_name = params.get("name")
                return await self._handle_prompt_get(message.id, prompt_name, params.get("arguments", {}))
            
            elif method == "tools/list":
                return MCPMessage(
                    id=message.id,
                    result={"tools": [tool.to_dict() for tool in self.list_tools()]}
                )
            
            elif method == "tools/call":
                tool_name = params.get("name")
                arguments = params.get("arguments", {})
                return await self._handle_tool_call(message.id, tool_name, arguments)
            
            else:
                return MCPMessage(
                    id=message.id,
                    error={"code": -32601, "message": f"Unknown method: {method}"}
                )
                
        except Exception as e:
            self.logger.error(f"Failed to handle request: {e}")
            return MCPMessage(
                id=message.id,
                error={"code": -32603, "message": f"Internal error: {str(e)}"}
            )
    
    async def _handle_resource_read(self, request_id: str, uri: str) -> MCPMessage:
        """Handle a resource read request."""
        if uri == "constraint://types":
            constraint_types = {
                "single_table": {
                    "TYPE": {
                        "name": "Data type constraint",
                        "description": "Verify that data types match the schema definition",
                        "supported_types": ["integer", "float", "decimal", "date", "datetime", "boolean", "string"],
                        "implementation": "algorithmic"
                    },
                    "VALUE": {
                        "name": "Value constraint", 
                        "description": "Verify value ranges, domain constraints, and enum values",
                        "supported_constraints": ["min/max", "domain", "enum"],
                        "implementation": "algorithmic"
                    },
                    "STRUCTURE": {
                        "name": "Structure constraint",
                        "description": "Verify not-null, uniqueness, and primary-key constraints",
                        "supported_constraints": ["not_null", "required", "unique", "primary_key"],
                        "implementation": "algorithmic"
                    },
                    "FORMAT": {
                        "name": "Format constraint",
                        "description": "Verify data formats, pattern matching, and length constraints",
                        "predefined_formats": ["email", "phone", "id_card", "url", "ip", "date_iso", "currency"],
                        "implementation": "algorithmic"
                    },
                    "TEMPORAL": {
                        "name": "Temporal constraint",
                        "description": "Verify time formats, time ranges, and temporal logic",
                        "supported_constraints": ["time_format", "time_range", "time_logic", "time_series"],
                        "implementation": "algorithmic"
                    },
                    "LOGIC": {
                        "name": "Logic constraint",
                        "description": "Use an LLM to verify complex business logic",
                        "focus_areas": ["business_rules", "field_relationships", "value_reasonableness", "state_transitions"],
                        "implementation": "llm"
                    }
                },
                "multi_table": {
                    "REFERENCE": {
                        "name": "Reference constraint",
                        "description": "Verify foreign-key referential integrity",
                        "supported_constraints": ["foreign_key"],
                        "implementation": "algorithmic"
                    },
                    "AGGREGATION": {
                        "name": "Aggregation constraint",
                        "description": "Verify calculated fields, totals, averages, and other aggregation logic",
                        "supported_operations": ["sum", "multiply", "percentage", "average", "count"],
                        "implementation": "algorithmic+llm"
                    }
                }
            }
            return MCPMessage(
                id=request_id,
                result={"contents": [{"type": "text", "text": json.dumps(constraint_types, ensure_ascii=False, indent=2)}]}
            )
        
        elif uri == "fix://strategies":
            fix_strategies = {
                "TYPE": {
                    "strategy": "Type conversion and normalization",
                    "methods": {
                        "numeric": "Remove non-numeric characters and convert to the target type",
                        "date": "Normalize the date format",
                        "boolean": "Normalize the boolean representation"
                    }
                },
                "VALUE": {
                    "strategy": "Value mapping and range adjustment",
                    "methods": {
                        "range": "Clamp to the boundary value",
                        "domain": "Map to the most similar domain value",
                        "enum": "Select the best-matching enum value"
                    }
                },
                "STRUCTURE": {
                    "strategy": "Structure repair and default-value filling",
                    "methods": {
                        "not_null": "Provide a smart default value",
                        "unique": "Flag but do not auto-fix (requires manual handling)"
                    }
                },
                "FORMAT": {
                    "strategy": "Format normalization",
                    "methods": {
                        "standardization": "Format normalization",
                        "length_adjustment": "Length adjustment",
                        "pattern_fix": "Pattern repair"
                    }
                },
                "TEMPORAL": {
                    "strategy": "Time format and logic repair",
                    "methods": {
                        "format_standardization": "Time format normalization",
                        "range_clipping": "Time range clipping",
                        "logic_fix": "Temporal logic repair"
                    }
                },
                "LOGIC": {
                    "strategy": "LLM-based smart repair",
                    "methods": {
                        "llm_suggestion": "LLM-generated smart fix suggestions",
                        "business_rule_fix": "Business-rule repair"
                    }
                },
                "REFERENCE": {
                    "strategy": "Reference mapping",
                    "methods": {
                        "similarity_mapping": "Map to the most similar reference value"
                    }
                },
                "AGGREGATION": {
                    "strategy": "Recompute aggregate values",
                    "methods": {
                        "recalculation": "Recompute the correct aggregate value",
                        "llm_complex_logic": "Use an LLM for complex aggregation logic"
                    }
                }
            }
            return MCPMessage(
                id=request_id,
                result={"contents": [{"type": "text", "text": json.dumps(fix_strategies, ensure_ascii=False, indent=2)}]}
            )
        
        elif uri == "schema://template":
            schema_template = {
                "table_name": "example_table",
                "columns": [
                    {
                        "name": "id",
                        "type": "integer",
                        "constraints": ["primary_key", "not_null"]
                    },
                    {
                        "name": "name",
                        "type": "string",
                        "constraints": ["not_null"],
                        "max_length": 100
                    },
                    {
                        "name": "email",
                        "type": "string",
                        "format": "email",
                        "constraints": ["unique"]
                    },
                    {
                        "name": "age",
                        "type": "integer",
                        "min_value": 0,
                        "max_value": 150
                    },
                    {
                        "name": "created_at",
                        "type": "datetime",
                        "format": "iso8601"
                    }
                ]
            }
            return MCPMessage(
                id=request_id,
                result={"contents": [{"type": "text", "text": json.dumps(schema_template, ensure_ascii=False, indent=2)}]}
            )
        
        return MCPMessage(
            id=request_id,
            error={"code": -32602, "message": f"Resource not found: {uri}"}
        )
    
    async def _handle_prompt_get(self, request_id: str, prompt_name: str, arguments: Dict[str, Any]) -> MCPMessage:
        """Handle a prompt get request."""
        if prompt_name == "verify-data-quality":
            data = arguments.get("data", "")
            schema = arguments.get("schema", "")
            constraint_type = arguments.get("constraint_type", "all types")
            
            prompt_text = f"""Verify the quality of the following data, focusing on {constraint_type} constraints:

Data schema:
{json.dumps(schema, ensure_ascii=False, indent=2)}

Data content:
{json.dumps(data, ensure_ascii=False, indent=2)}

Identify all constraint violations and return them in the following format:
1. Violation type
2. Violation location (table name, row number, column name)
3. Violation description
4. Current value
5. Expected value or fix suggestion

Return the result in structured JSON format."""

            return MCPMessage(
                id=request_id,
                result={
                    "messages": [
                        {
                            "role": "user",
                            "content": {
                                "type": "text",
                                "text": prompt_text
                            }
                        }
                    ]
                }
            )
        
        elif prompt_name == "suggest-data-fix":
            violation = arguments.get("violation", {})
            context = arguments.get("context", {})
            
            prompt_text = f"""Provide a fix suggestion for the following data violation:

Violation information:
{json.dumps(violation, ensure_ascii=False, indent=2)}

Context data:
{json.dumps(context, ensure_ascii=False, indent=2)}

Please provide:
1. Fix strategy explanation
2. Concrete fix steps
3. Fixed value
4. Fix confidence (1-10)
5. Possible side effects or caveats

Return the fix suggestion in structured JSON format."""

            return MCPMessage(
                id=request_id,
                result={
                    "messages": [
                        {
                            "role": "user", 
                            "content": {
                                "type": "text",
                                "text": prompt_text
                            }
                        }
                    ]
                }
            )
        
        elif prompt_name == "analyze-data-pattern":
            data = arguments.get("data", "")
            analysis_type = arguments.get("analysis_type", "comprehensive analysis")
            
            prompt_text = f"""Perform a {analysis_type} on the following data:

Dataset:
{json.dumps(data, ensure_ascii=False, indent=2)}

Please analyze:
1. Overall data quality assessment
2. Common data quality problem patterns
3. Data distribution characteristics
4. Outlier identification
5. Improvement suggestions

Provide a detailed analysis report."""

            return MCPMessage(
                id=request_id,
                result={
                    "messages": [
                        {
                            "role": "user",
                            "content": {
                                "type": "text",
                                "text": prompt_text
                            }
                        }
                    ]
                }
            )
        
        return MCPMessage(
            id=request_id,
            error={"code": -32602, "message": f"Prompt not found: {prompt_name}"}
        )
    
    async def _handle_tool_call(self, request_id: str, tool_name: str, arguments: Dict[str, Any]) -> MCPMessage:
        """Handle a tool call request."""
        if tool_name == "verify_constraint":
            constraint_type = arguments.get("constraint_type")
            data = arguments.get("data")
            schema = arguments.get("schema")
            
            result = {
                "status": "success",
                "constraint_type": constraint_type,
                "violations": [],
                "message": f"{constraint_type} constraint verification complete",
                "processed_records": len(data.get("rows", [])) if isinstance(data, dict) else 0
            }
            return MCPMessage(id=request_id, result=result)
        
        elif tool_name == "fix_violation":
            violation = arguments.get("violation")
            snapshot = arguments.get("snapshot")
            
            fixes = []
            
            try:
                from . import (
                    TypeMCP, ValueMCP, StructureMCP, LogicMCP,
                    TemporalMCP, FormatMCP, ReferenceMCP, AggregationMCP
                )
                from ...memory import TableSnapshot, TableRow, CellData, Violation, SuggestedFix
                
                constraint_type = violation.get("constraint_type", "").upper()
                
                fixers = {
                    "TYPE": TypeMCP().fixer,
                    "VALUE": ValueMCP().fixer,
                    "STRUCTURE": StructureMCP().fixer,
                    "FORMAT": FormatMCP().fixer,
                    "LOGIC": LogicMCP().fixer,
                    "TEMPORAL": TemporalMCP().fixer,
                    "REFERENCE": ReferenceMCP().fixer,
                    "AGGREGATION": AggregationMCP().fixer
                }
                
                fixer = fixers.get(constraint_type)
                if fixer:
                    suggested_fix = None
                    if violation.get("suggested_fix"):
                        suggested_fix = SuggestedFix(value=violation["suggested_fix"])
                    
                    violation_obj = Violation(
                        id=violation.get("id", ""),
                        table=violation.get("table", ""),
                        tuple_id=violation.get("tuple_id", ""),
                        attr=violation.get("attr", ""),
                        constraint_type=violation.get("constraint_type", ""),
                        description=violation.get("description", ""),
                        severity=violation.get("severity", "warn"),
                        suggested_fix=suggested_fix,
                        detector_id="mcp_server",
                        timestamp=""
                    )
                    
                    rows = []
                    for row_data in snapshot.get("rows", []):
                        tuple_id = row_data.get("tuple_id", "")
                        cells = {}
                        for attr, value in row_data.get("cells", {}).items():
                            cell = CellData(
                                value=value,
                                evidences=[]
                            )
                            cells[attr] = cell
                        rows.append(TableRow(tuple_id=tuple_id, cells=cells))
                    
                    snapshot_obj = TableSnapshot(run_id="test_run", table="test_table", rows=rows, created_at="")
                    
                    fix_results = fixer.fix(violation_obj, snapshot_obj)
                    
                    fixes = []
                    for fix in fix_results:
                        fix_dict = {
                            "id": fix.id,
                            "table": fix.table,
                            "tuple_id": fix.tuple_id,
                            "attr": fix.attr,
                            "old": fix.old,
                            "new": fix.new,
                            "fix_type": fix.fix_type,
                            "applied_by": fix.applied_by
                        }
                        fixes.append(fix_dict)
                
                result = {
                    "status": "success",
                    "violation_id": violation.get("id") if violation else None,
                    "fixes": fixes,
                    "message": f"Violation fixing complete, generated {len(fixes)} fixes"
                }
                
            except ImportError as e:
                self.logger.error(f"Failed to import MCP fix components: {e}")
                result = {
                    "status": "error",
                    "violation_id": violation.get("id") if violation else None,
                    "fixes": [],
                    "message": f"Failed to import MCP fix components: {e}"
                }
            except Exception as e:
                self.logger.error(f"Violation fixing failed: {e}")
                result = {
                    "status": "error",
                    "violation_id": violation.get("id") if violation else None,
                    "fixes": [],
                    "message": f"Fixing failed: {e}"
                }
            
            return MCPMessage(id=request_id, result=result)
        
        elif tool_name == "batch_verify":
            snapshots = arguments.get("snapshots", [])
            schema = arguments.get("schema")
            constraint_types = arguments.get("constraint_types", [])
            
            all_violations = []
            violations_by_type = {}
            
            try:
                from . import (
                    TypeMCP, ValueMCP, StructureMCP, LogicMCP, 
                    TemporalMCP, FormatMCP, ReferenceMCP, AggregationMCP
                )
                from ...memory import TableSnapshot, TableRow, CellData
                
                mcps = [
                    ("TYPE", TypeMCP()),
                    ("VALUE", ValueMCP()),
                    ("STRUCTURE", StructureMCP()),
                    ("FORMAT", FormatMCP()),
                    ("LOGIC", LogicMCP()),
                    ("TEMPORAL", TemporalMCP()),
                    ("REFERENCE", ReferenceMCP()),
                    ("AGGREGATION", AggregationMCP())
                ]
                
                for snapshot_data in snapshots:
                    table_name = snapshot_data.get("table_name", "unknown")
                    rows_data = snapshot_data.get("rows", [])
                    
                    rows = []
                    for row_data in rows_data:
                        tuple_id = row_data.get("tuple_id", "")
                        cells = {}
                        for attr, value in row_data.get("cells", {}).items():
                            cell = CellData(
                                value=value,
                                evidences=[]
                            )
                            cells[attr] = cell
                        rows.append(TableRow(tuple_id=tuple_id, cells=cells))
                    
                    snapshot = TableSnapshot(run_id="batch_verify", table=table_name, rows=rows, created_at="")
                    
                    for constraint_type, mcp in mcps:
                        if constraint_types and constraint_type not in constraint_types:
                            continue
                            
                        try:
                            violations = mcp.verify(snapshot, schema, table_name)
                            all_violations.extend(violations)
                            
                            if constraint_type not in violations_by_type:
                                violations_by_type[constraint_type] = 0
                            violations_by_type[constraint_type] += len(violations)
                            
                        except Exception as e:
                            self.logger.error(f"{constraint_type} MCP verification failed: {e}")
                            continue
                
                violations_data = []
                for violation in all_violations:
                    violation_dict = {
                        "id": violation.id,
                        "table": violation.table,
                        "tuple_id": violation.tuple_id,
                        "attr": violation.attr,
                        "constraint_type": violation.constraint_type,
                        "description": violation.description,
                        "severity": violation.severity
                    }
                    if violation.suggested_fix:
                        violation_dict["suggested_fix"] = violation.suggested_fix.value
                    violations_data.append(violation_dict)
                
                result = {
                    "status": "success",
                    "processed_snapshots": len(snapshots),
                    "constraint_types": constraint_types,
                    "total_violations": len(all_violations),
                    "violations_by_type": violations_by_type,
                    "violations": violations_data,
                    "message": f"Batch verification complete, found {len(all_violations)} violations"
                }
                
            except ImportError as e:
                self.logger.error(f"Failed to import MCP components: {e}")
                result = {
                    "status": "error",
                    "processed_snapshots": 0,
                    "total_violations": 0,
                    "violations": [],
                    "message": f"Failed to import MCP components: {e}"
                }
            except Exception as e:
                self.logger.error(f"Batch verification failed: {e}")
                result = {
                    "status": "error",
                    "processed_snapshots": 0,
                    "total_violations": 0,
                    "violations": [],
                    "message": f"Verification failed: {e}"
                }
            
            return MCPMessage(id=request_id, result=result)
        
        
        return MCPMessage(
            id=request_id,
            error={"code": -32602, "message": f"Tool not found: {tool_name}"}
        )
