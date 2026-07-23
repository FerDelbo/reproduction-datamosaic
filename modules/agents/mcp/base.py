"""MCP (Model Context Protocol) base interfaces - data quality processing framework."""
import logging
import json
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass, asdict
from enum import Enum
from ...memory import TableSnapshot, Violation, Fix, ConstraintType


class MCPMessageType(Enum):
    """MCP message type."""
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"


class MCPCapability(Enum):
    """MCP server capability."""
    RESOURCES = "resources"
    PROMPTS = "prompts"
    TOOLS = "tools"


@dataclass
class MCPMessage:
    """Base MCP message."""
    jsonrpc: str = "2.0"
    id: Optional[str] = None
    method: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict."""
        return {k: v for k, v in asdict(self).items() if v is not None}


@dataclass
class MCPResource:
    """MCP resource definition."""
    uri: str
    name: str
    description: str
    mimeType: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MCPPrompt:
    """MCP prompt definition."""
    name: str
    description: str
    arguments: List[Dict[str, Any]]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class MCPTool:
    """MCP tool definition."""
    name: str
    description: str
    inputSchema: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class MCPServer(ABC):
    """Base MCP server providing context and tools for data quality processing."""
    
    def __init__(self, name: str, version: str, capabilities: List[MCPCapability]):
        self.name = name
        self.version = version
        self.capabilities = {cap.value: {} for cap in capabilities}
        self.logger = logging.getLogger(f'doc2db.mcp.{name}')
        
        self.resources: Dict[str, MCPResource] = {}
        self.prompts: Dict[str, MCPPrompt] = {}
        self.tools: Dict[str, MCPTool] = {}
    
    def get_server_info(self) -> Dict[str, Any]:
        """Return server info."""
        return {
            "name": self.name,
            "version": self.version,
            "capabilities": self.capabilities
        }
    
    def register_resource(self, resource: MCPResource):
        """Register a resource."""
        self.resources[resource.uri] = resource
    
    def register_prompt(self, prompt: MCPPrompt):
        """Register a prompt."""
        self.prompts[prompt.name] = prompt
    
    def register_tool(self, tool: MCPTool):
        """Register a tool."""
        self.tools[tool.name] = tool
    
    @abstractmethod
    async def handle_request(self, message: MCPMessage) -> MCPMessage:
        """Handle an MCP request."""
        pass
    
    def list_resources(self) -> List[MCPResource]:
        """List all resources."""
        return list(self.resources.values())
    
    def list_prompts(self) -> List[MCPPrompt]:
        """List all prompts."""
        return list(self.prompts.values())
    
    def list_tools(self) -> List[MCPTool]:
        """List all tools."""
        return list(self.tools.values())


class MCPClient:
    """MCP client for communicating with MCP servers."""
    
    def __init__(self, client_name: str):
        self.client_name = client_name
        self.logger = logging.getLogger(f'doc2db.mcp.client.{client_name}')
        self.connected_servers: Dict[str, MCPServer] = {}
    
    def connect_server(self, server: MCPServer):
        """Connect to an MCP server."""
        self.connected_servers[server.name] = server
        self.logger.info(f"Connected to MCP server: {server.name}")
    
    async def send_request(self, server_name: str, method: str, 
                          params: Optional[Dict[str, Any]] = None) -> MCPMessage:
        """Send a request to the specified server."""
        if server_name not in self.connected_servers:
            raise ValueError(f"Not connected to server: {server_name}")
        
        server = self.connected_servers[server_name]
        request = MCPMessage(
            id=f"{self.client_name}_{method}_{id(params)}",
            method=method,
            params=params
        )
        
        return await server.handle_request(request)
    
    async def list_server_resources(self, server_name: str) -> List[MCPResource]:
        """List server resources."""
        response = await self.send_request(server_name, "resources/list")
        if response.result:
            return [MCPResource(**res) for res in response.result.get("resources", [])]
        return []
    
    async def get_resource(self, server_name: str, uri: str) -> Optional[Dict[str, Any]]:
        """Get the specified resource."""
        response = await self.send_request(server_name, "resources/read", {"uri": uri})
        return response.result
    
    async def call_tool(self, server_name: str, tool_name: str, 
                       arguments: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Call a tool."""
        response = await self.send_request(server_name, "tools/call", {
            "name": tool_name,
            "arguments": arguments
        })
        return response.result


def get_table_definition(schema: Dict[str, Any], table_name: str) -> Optional[Dict[str, Any]]:
    """Get a table definition (shared helper)."""
    if not isinstance(schema, dict):
        return None
        
    tables = schema.get('tables', [])
    
    if isinstance(tables, list):
        for table in tables:
            if table.get('name') == table_name:
                result = table.copy()
                if 'fields' in result and 'attributes' not in result:
                    result['attributes'] = result.pop('fields')
                
                if 'attributes' in result:
                    flattened_attributes = []
                    for attr in result['attributes']:
                        attr_copy = attr.copy()
                        if 'constraints' in attr_copy:
                            constraints = attr_copy.pop('constraints')
                            for key, value in constraints.items():
                                if key not in attr_copy:  # do not overwrite existing fields
                                    attr_copy[key] = value
                        flattened_attributes.append(attr_copy)
                    result['attributes'] = flattened_attributes
                
                return result
        
        if '_' in table_name and table_name.rsplit('_', 1)[-1].isdigit():
            base_name = table_name.rsplit('_', 1)[0]
            suffix_num = int(table_name.rsplit('_', 1)[1])
            
            matching_tables = [
                table for table in tables
                if isinstance(table, dict) and table.get('name') == base_name
            ]
            
            if matching_tables and 1 <= suffix_num <= len(matching_tables):
                target_table = matching_tables[suffix_num - 1]
                result = target_table.copy()
                if 'fields' in result and 'attributes' not in result:
                    result['attributes'] = result.pop('fields')
                
                if 'attributes' in result:
                    flattened_attributes = []
                    for attr in result['attributes']:
                        attr_copy = attr.copy()
                        if 'constraints' in attr_copy:
                            constraints = attr_copy.pop('constraints')
                            for key, value in constraints.items():
                                if key not in attr_copy:  # do not overwrite existing fields
                                    attr_copy[key] = value
                        flattened_attributes.append(attr_copy)
                    result['attributes'] = flattened_attributes
                
                return result
    elif isinstance(tables, dict):
        if table_name in tables:
            table_def = tables[table_name].copy()
            if 'name' not in table_def:
                table_def['name'] = table_name
            if 'fields' in table_def and 'attributes' not in table_def:
                table_def['attributes'] = table_def.pop('fields')
            
            if 'attributes' in table_def:
                flattened_attributes = []
                for attr in table_def['attributes']:
                    attr_copy = attr.copy()
                    if 'constraints' in attr_copy:
                        constraints = attr_copy.pop('constraints')
                        for key, value in constraints.items():
                            if key not in attr_copy:  # do not overwrite existing fields
                                attr_copy[key] = value
                    flattened_attributes.append(attr_copy)
                table_def['attributes'] = flattened_attributes
            
            return table_def
    
    if schema.get('table_name') == table_name and 'columns' in schema:
        columns = schema.get('columns', {})
        attributes = []
        
        if isinstance(columns, dict):
            for col_name, col_def in columns.items():
                attr = {'name': col_name}
                attr.update(col_def)  # add type, constraints, etc.
                attributes.append(attr)
        elif isinstance(columns, list):
            attributes = columns
            
        return {
            'name': schema['table_name'],
            'attributes': attributes
        }
    
    return None


def get_cell_value(violation: Violation, snapshot: TableSnapshot) -> Optional[Any]:
    """Get a cell value (shared helper; tolerant of tuple_id formatting)."""
    import logging
    logger = logging.getLogger('doc2db.mcp')
    
    target_tuple_id = violation.tuple_id.strip('[]').strip()
    
    for row in snapshot.rows:
        row_tuple_id = row.tuple_id.strip('[]').strip()
        if row_tuple_id == target_tuple_id:
            cell_data = row.cells.get(violation.attr)
            if cell_data:
                return cell_data.value
    
    logger.debug(f"tuple_id={violation.tuple_id} not found in current snapshot ({len(snapshot.rows)} rows)")
    logger.debug("This can happen in an intermediate processing stage and is usually safe to ignore")
    
    if logger.isEnabledFor(logging.DEBUG):
        sample_ids = [row.tuple_id for row in snapshot.rows[:5]]
        logger.debug(f"First 5 tuple_id samples in snapshot: {sample_ids}")
        logger.debug(f"tuple_id being matched: '{target_tuple_id}'")
    
    return None



class MCPVerifier(ABC):
    """Base MCP verifier (legacy architecture)."""
    
    def __init__(self, verifier_id: str):
        self.verifier_id = verifier_id
        self.mcp_id = verifier_id  # mcp_id kept for compatibility
        self.logger = logging.getLogger(f'doc2db.mcp.verifier.{verifier_id}')
    
    @abstractmethod
    def verify(self, snapshot: TableSnapshot, schema: Dict[str, Any], table_name: str) -> List[Violation]:
        """Verify a data snapshot."""
        pass


class MCPFixer(ABC):
    """Base MCP fixer (legacy architecture)."""
    
    def __init__(self, fixer_id: str):
        self.fixer_id = fixer_id
        self.mcp_id = fixer_id  # mcp_id kept for compatibility
        self.logger = logging.getLogger(f'doc2db.mcp.fixer.{fixer_id}')
    
    @abstractmethod
    def fix(self, violation: Violation, snapshot: TableSnapshot, context=None) -> List[Fix]:
        """Fix a violation."""
        pass
    
    def fix_batch(self, violations: List[Violation], snapshot: TableSnapshot, 
                  context=None) -> List[Fix]:
        """
        Batch-fix violations - default implementation (subclasses may override for efficiency).

        Default behavior: call fix() for each violation one by one.
        Subclasses should override to implement true batch fixing (a single LLM call for all violations).

        Args:
            violations: violations to fix
            snapshot: table snapshot
            context: context information

        Returns:
            List[Fix]: list of fix objects
        """
        all_fixes = []
        for violation in violations:
            try:
                fixes = self.fix(violation, snapshot, context)
                all_fixes.extend(fixes)
            except Exception as e:
                self.logger.error(f"Failed to fix violation {getattr(violation, 'id', 'unknown')}: {e}")
        return all_fixes
    
    def get_unfixable_violations(self, fixes: List[Fix]) -> List[Fix]:
        """
        Return the list of unfixable violations - base default implementation.

        Args:
            fixes: list of fix results

        Returns:
            List[Fix]: list of Fix objects that failed to fix
        """
        unfixable_fixes = []
        for fix in fixes:
            if not getattr(fix, 'fix_success', True):  # default True for backward compatibility
                unfixable_fixes.append(fix)
                self.logger.warning(f"Found unfixable violation: {getattr(fix, 'id', 'unknown')}, reason: {getattr(fix, 'failure_reason', 'unknown')}")
        
        self.logger.info(f"Filtered {len(unfixable_fixes)} unfixable violations")
        return unfixable_fixes


class BaseMCP:
    """Base MCP component (legacy architecture)."""
    
    def __init__(self, mcp_id: str, verifier: MCPVerifier, fixer: MCPFixer):
        self.mcp_id = mcp_id
        self.verifier = verifier
        self.fixer = fixer
        self.logger = logging.getLogger(f'doc2db.mcp.{mcp_id}')
        
    
    def verify(self, snapshot: TableSnapshot, schema: Dict[str, Any], table_name: str) -> List[Violation]:
        """Verify data."""
        self.logger.info(f"Verifying table {table_name}")
        try:
            violations = self.verifier.verify(snapshot, schema, table_name)
            self.logger.info(f"Verification complete, found {len(violations)} violations")
            return violations
        except Exception as e:
            self.logger.error(f"Verification failed: {e}")
            return []
    
    def fix(self, violation: Violation, snapshot: TableSnapshot) -> List[Fix]:
        """Fix a violation."""
        try:
            fixes = self.fixer.fix(violation, snapshot)
            return fixes
        except Exception as e:
            self.logger.error(f"Fix failed: {e}")
            return []


def is_valid_fix_value(value: str) -> bool:
    """Check whether a suggested fix value is a real data value (not prompt-like text).

    Shared helper used by all fixers.

    Args:
        value: suggested fix value

    Returns:
        True if it is a valid data value, False if it looks like prompt text
    """
    if not value or not isinstance(value, str):
        return False
    
    prompt_keywords = [
        "确认", "检查", "建议", "请", "是否", "或者", "可能", "需要",
        "应该", "必须", "注意", "提示", "警告", "说明", "参考",
        "数据源", "采集逻辑", "业务逻辑", "特定需求", "合理的",
        "问题", "错误", "修改", "更正", "调整"
    ]
    
    if len(value) > 100:
        return False
    
    keyword_count = sum(1 for keyword in prompt_keywords if keyword in value)
    if keyword_count >= 2:
        return False
    
    if any(char in value for char in ['。', '？', '！', '?', '!']):
        return False
    
    return True