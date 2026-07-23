"""Repairer implementation based on MCP (Model Context Protocol)"""
import logging
import asyncio
from typing import List, Dict, Any, Optional
from ..mcp.base import MCPClient
from ..mcp.data_quality_server import DataQualityMCPServer
from ...memory import TableSnapshot, Violation, Fix, ConstraintType


class MCPBasedFixer:
    """Fixer based on Model Context Protocol"""
    
    def __init__(self):
        self.fixer_id = "MCPBasedFixer.v2.0"
        self.logger = logging.getLogger('doc2db.fixer')
        
        self.mcp_client = MCPClient("doc2db-fixer-client")
        self.data_quality_server = DataQualityMCPServer()
        
        self.mcp_client.connect_server(self.data_quality_server)
        
        self.constraint_type_mapping = {
            ConstraintType.TYPE.value: "TYPE",
            ConstraintType.VALUE.value: "VALUE",
            ConstraintType.STRUCTURE.value: "STRUCTURE",
            ConstraintType.LOGIC.value: "LOGIC",
            ConstraintType.TEMPORAL.value: "TEMPORAL",
            ConstraintType.FORMAT.value: "FORMAT",
            ConstraintType.REFERENCE.value: "REFERENCE",
            ConstraintType.AGGREGATION.value: "AGGREGATION",
        }
        
        self.logger.info(f"Initialized MCP fixer with support for {len(self.constraint_type_mapping)} constraint types")
    
    def fix_table(self, table, violations: List[Violation], context=None) -> List[Fix]:
        """Directly repair Table objects (new interface)
        
        Args:
            table: Table object
            violations: list of violations that need to be fixed
            context: processing context
            
        Returns:
            List of fixes applied"""
        try:
            return table.fix(self, violations, context)
        except Exception as e:
            self.logger.error(f"Failed to fix Table object: {e}")
            return []
    
    def fix(self, violation: Violation, snapshot: TableSnapshot, context=None) -> List[Fix]:
        """Fix violations using MCP"""
        if not self.can_fix(violation):
            return []
        
        try:
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self._async_fix(violation, snapshot, context))
                    return future.result()
            except RuntimeError:
                return asyncio.run(self._async_fix(violation, snapshot, context))
        except Exception as e:
            self.logger.error(f"Async fix failed: {e}")
            return []
    
    async def _async_fix(self, violation: Violation, snapshot: TableSnapshot, context=None) -> List[Fix]:
        """Asynchronous repair implementation"""
        fixes = []
        
        if hasattr(violation, 'business_rule_id') and violation.business_rule_id:
            self.logger.info(f"[MCPFixer] Detected business rule violation: {violation.business_rule_id}")
            business_rule_fixes = await self._fix_business_rule_violation(
                violation, snapshot, context
            )
            if business_rule_fixes:
                return business_rule_fixes
        
        try:
            violation_data = {
                "id": getattr(violation, 'id', ''),
                "constraint_type": getattr(violation, 'constraint_type', ''),
                "table_name": getattr(violation, 'table', ''),
                "tuple_id": getattr(violation, 'tuple_id', ''),
                "attr": getattr(violation, 'attr', ''),
                "description": getattr(violation, 'description', ''),
                "current_value": getattr(violation, 'current_value', None)
            }
            
            snapshot_data = {
                "table_id": snapshot.table_id,
                "rows": [
                    {
                        "tuple_id": row.tuple_id,
                        "cells": {
                            attr: cell.value
                            for attr, cell in row.cells.items()
                        }
                    }
                    for row in snapshot.rows
                ]
            }
            
            response = await self.mcp_client.call_tool(
                server_name="doc2db-data-quality",
                tool_name="fix_violation",
                arguments={
                    "violation": violation_data,
                    "snapshot": snapshot_data
                }
            )
            
            if response and response.get("status") == "success":
                self.logger.info(f"MCP fix succeeded; violation ID: {violation_data.get('id')}")
                
                fixes_data = response.get("fixes", [])
                for fix_data in fixes_data:
                    pass
            
        except Exception as e:
            self.logger.error(f"MCP tool call failed: {e}")
        
        if not fixes:
            fixes = await self._fallback_fix(violation, snapshot, context)
        
        if fixes:
            self.logger.info(f"Generated {len(fixes)} fixes for violation {getattr(violation, 'id', 'unknown')}")
        else:
            self.logger.warning(f"Violation {getattr(violation, 'id', 'unknown')} could not be fixed; attempting to mark as unfixable")
            await self._mark_violation_unfixable(violation, context)
        
        return fixes
    
    async def _mark_violation_unfixable(self, violation: Violation, context):
        """Mark violation as unfixable"""
        try:
            memory_manager = None
            run_id = None
            
            if context:
                if isinstance(context, dict):
                    memory_manager = context.get('memory_manager')
                    run_id = context.get('run_id')
                else:
                    memory_manager = getattr(context, 'memory_manager', None)
                    run_id = getattr(context, 'run_id', None)
            
            if memory_manager and run_id:
                await memory_manager.mark_violation_unfixable(violation.id, run_id)
                self.logger.debug(f"Marked violation {violation.id} as unfixable")
            else:
                self.logger.debug(f"Unable to mark violation {violation.id} as unfixable: context is missing memory_manager or run_id")
        except Exception as e:
            self.logger.error(f"Failed to mark violation {violation.id} as unfixable: {e}")
    
    async def _fallback_fix(self, violation: Violation, snapshot: TableSnapshot, context=None) -> List[Fix]:
        """Fallback fix - use specific MCP components directly"""
        self.logger.info("Fixing directly with individual MCP components")
        
        fixes = []
        
        try:
            from ..mcp import (
                TypeMCP, ValueMCP, StructureMCP, FormatMCP,
                LogicMCP, TemporalMCP, ReferenceMCP, AggregationMCP
            )
            
            constraint_type = getattr(violation, 'constraint_type', '').lower()  # Change to lowercase comparison
            violation_attr = getattr(violation, 'attr', 'unknown')
            
            
            mcp_instance = None
            mcp_name = ""
            
            if constraint_type == 'type':
                mcp_instance = TypeMCP()
                mcp_name = "TypeMCP"
            elif constraint_type == 'value' or constraint_type == 'domain':
                mcp_instance = ValueMCP()
                mcp_name = "ValueMCP"
            elif constraint_type == 'structure' or constraint_type == 'null':
                mcp_instance = StructureMCP()
                mcp_name = "StructureMCP"
            elif constraint_type == 'format':  # Exact match format type
                mcp_instance = FormatMCP()
                mcp_name = "FormatMCP"
            elif constraint_type == 'logic' or constraint_type == 'business':
                mcp_instance = LogicMCP()
                mcp_name = "LogicMCP"
            elif constraint_type == 'temporal' or constraint_type == 'time' or constraint_type == 'date':
                mcp_instance = TemporalMCP()
                mcp_name = "TemporalMCP"
            elif constraint_type == 'reference' or constraint_type == 'foreign':
                mcp_instance = ReferenceMCP()
                mcp_name = "ReferenceMCP"
            elif constraint_type == 'aggregation' or constraint_type == 'sum' or constraint_type == 'count':
                mcp_instance = AggregationMCP()
                mcp_name = "AggregationMCP"
            else:
                mcps = [
                    ("TypeMCP", TypeMCP()),
                    ("ValueMCP", ValueMCP()),
                    ("StructureMCP", StructureMCP()),
                    ("FormatMCP", FormatMCP()),
                    ("LogicMCP", LogicMCP()),
                    ("TemporalMCP", TemporalMCP()),
                    ("ReferenceMCP", ReferenceMCP()),
                    ("AggregationMCP", AggregationMCP())
                ]
                
                for name, mcp in mcps:
                    try:
                        mcp_fixes = mcp.fix(violation, snapshot)
                        if mcp_fixes:
                            fixes.extend(mcp_fixes)
                            self.logger.info(f"{name} generated {len(mcp_fixes)} fixes")
                    except Exception as e:
                        self.logger.error(f"{name} fix failed: {e}")
            
            if mcp_instance:
                try:
                    mcp_fixes = mcp_instance.fix(violation, snapshot)
                    fixes.extend(mcp_fixes)
                    
                    
                except Exception as e:
                    error_msg = f"{mcp_name} fix failed: {e}"
                    self.logger.error(error_msg)
            
        except ImportError as e:
            self.logger.error(f"Failed to import MCP components: {e}")
        
        
        
        return fixes
    
    def _generate_simple_fix(self, violation: Violation, snapshot: TableSnapshot) -> List[Fix]:
        """Generate simple default value fixes"""
        fixes = []
        
        try:
            from ...memory import Fix, FixType
            
            attr = getattr(violation, 'attr', '')
            tuple_id = getattr(violation, 'tuple_id', '')
            old_value = getattr(violation, 'current_value', None)
            
            if attr and tuple_id:
                new_value = self._get_default_value_for_attr(attr, snapshot)
                
                if new_value is not None:
                    fix = Fix(
                        id=f"simple_fix_{tuple_id}_{attr}",
                        table=violation.table if hasattr(violation, 'table') else snapshot.table,
                        tuple_id=tuple_id,
                        attr=attr,
                        old=old_value,
                        new=new_value,

                        fix_type=FixType.VALUE_CORRECTION.value,
                        applied_by=self.fixer_id,
                        timestamp=""
                    )
                    fixes.append(fix)
        
        except ImportError:
            self.logger.error("Failed to import Fix class; skipping simple fix")
        except Exception as e:
            self.logger.error(f"Failed to generate simple fix: {e}")
        
        return fixes
    
    def _get_default_value_for_attr(self, attr: str, snapshot: TableSnapshot) -> Any:
        """Generate default values ​​for properties"""
        if 'id' in attr.lower():
            return 0
        elif 'name' in attr.lower():
            return "Unknown"
        elif 'date' in attr.lower():
            return "1900-01-01"
        elif 'time' in attr.lower():
            return "00:00:00"
        else:
            return ""
    
    def can_fix(self, violation: Violation) -> bool:
        """Checks whether the specified violation can be fixed"""
        constraint_type = getattr(violation, 'constraint_type', '')
        return constraint_type in self.constraint_type_mapping
    
    def get_supported_fix_types(self) -> List[str]:
        """Get a list of supported repair types"""
        return [
            "DOMAIN_MAPPING",      # Domain mapping fix
            "VALUE_CORRECTION",    # value correction repair
            "STRUCTURE_FIX",       # structural repair
            "LENGTH_ADJUST",       # Length adjustment fix
            "TEMPORAL_FIX",        # Time to fix
            "LOGIC_FIX",           # logic fix
            "BUSINESS_RULE_FIX",   # Business rules fixes
            "CALCULATION_FIX",     # Compute repair
            "AGGREGATION_FIX",     # aggregate repair
            "FOREIGN_KEY_FIX",     # Foreign key repair
            "FORMAT_FIX",          # Format repair
            "TYPE_CONVERSION"      # Type conversion fix
        ]
    
    async def get_mcp_fix_strategies(self) -> Optional[Dict[str, Any]]:
        """Get MCP repair strategy information"""
        try:
            resource_data = await self.mcp_client.get_resource("doc2db-data-quality", "fix://strategies")
            return resource_data
        except Exception as e:
            self.logger.error(f"Failed to get fix strategy information: {e}")
            return None
    
    def get_unfixable_violations(self, fixes: List[Fix]) -> List[Fix]:
        """Get a list of violations that cannot be repaired
        
        Args:
            fixes: list of fix results
            
        Returns:
            List[Fix]: List of Fix objects that failed to be repaired"""
        unfixable_fixes = []
        for fix in fixes:
            if not fix.fix_success:
                unfixable_fixes.append(fix)
                self.logger.warning(f"Found unfixable violation: {fix.id}, reason: {fix.failure_reason}")
        
        self.logger.info(f"Filtered {len(unfixable_fixes)} unfixable violations")
        return unfixable_fixes
    
    def fix_batch(self, violations: List[Violation], snapshot: TableSnapshot, 
                  context=None) -> List[Fix]:
        """Fix violations in batches"""
        try:
            try:
                loop = asyncio.get_running_loop()
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self._async_fix_batch(violations, snapshot, context))
                    return future.result()
            except RuntimeError:
                return asyncio.run(self._async_fix_batch(violations, snapshot, context))
        except Exception as e:
            self.logger.error(f"Async batch fix failed: {e}")
            return []
    
    async def _async_fix_batch(self, violations: List[Violation], snapshot: TableSnapshot, 
                              context=None) -> List[Fix]:
        """Asynchronous batch repair implementation"""
        all_fixes = []
        
        violations_by_type = self._group_violations(violations)
        
        for (constraint_type, attr), grouped_violations in violations_by_type.items():
            try:
                mcp_fixes = await self._batch_fix_by_mcp(
                    grouped_violations, snapshot, constraint_type, context
                )
                all_fixes.extend(mcp_fixes)
            except Exception as e:
                self.logger.error(f"Batch fix for {constraint_type}/{attr} failed: {e}")
        
        return all_fixes
    
    def _group_violations(self, violations: List[Violation]) -> Dict[tuple, List[Violation]]:
        """Group violations by constraint type and attribute"""
        groups = {}
        for violation in violations:
            constraint_type = getattr(violation, 'constraint_type', '')
            attr = getattr(violation, 'attr', '')
            key = (constraint_type, attr)
            
            if key not in groups:
                groups[key] = []
            groups[key].append(violation)
        
        return groups
    
    async def _batch_fix_by_mcp(self, violations: List[Violation], 
                               snapshot: TableSnapshot, 
                               constraint_type: str,
                               context=None) -> List[Fix]:
        """Use the corresponding MCP to perform batch repairs"""
        all_fixes = []
        
        try:
            from ..mcp import (
                TypeMCP, ValueMCP, StructureMCP, FormatMCP,
                LogicMCP, TemporalMCP, ReferenceMCP, AggregationMCP
            )
            
            constraint_type_lower = constraint_type.lower()
            
            mcp_instance = None
            if constraint_type_lower == 'type':
                mcp_instance = TypeMCP()
            elif constraint_type_lower in ['value', 'domain']:
                mcp_instance = ValueMCP()
            elif constraint_type_lower in ['structure', 'null']:
                mcp_instance = StructureMCP()
            elif constraint_type_lower == 'format':
                mcp_instance = FormatMCP()
            elif constraint_type_lower in ['logic', 'business']:
                mcp_instance = LogicMCP()
            elif constraint_type_lower in ['temporal', 'time', 'date']:
                mcp_instance = TemporalMCP()
            elif constraint_type_lower in ['reference', 'foreign']:
                mcp_instance = ReferenceMCP()
            elif constraint_type_lower in ['aggregation', 'sum', 'count']:
                mcp_instance = AggregationMCP()
            
            if mcp_instance and hasattr(mcp_instance.fixer, 'fix_batch'):
                all_fixes = mcp_instance.fixer.fix_batch(violations, snapshot, context)
                if all_fixes:
                    mcp_name = mcp_instance.mcp_id if hasattr(mcp_instance, 'mcp_id') else constraint_type
                    self.logger.info(f"{mcp_name}: batch-fixed {len(violations)} violations and generated {len(all_fixes)} fixes")
            elif mcp_instance:
                for violation in violations:
                    fixes = mcp_instance.fix(violation, snapshot)
                    all_fixes.extend(fixes)
                if all_fixes:
                    mcp_name = mcp_instance.mcp_id if hasattr(mcp_instance, 'mcp_id') else constraint_type
                    self.logger.info(f"{mcp_name}: fixed {len(violations)} violations and generated {len(all_fixes)} fixes")
            else:
                for violation in violations:
                    fixes = await self._async_fix(violation, snapshot, context)
                    all_fixes.extend(fixes)
                    
        except ImportError as e:
            self.logger.error(f"Failed to import MCP components: {e}")
        
        return all_fixes
    
    async def _fix_business_rule_violation(self, violation: Violation,
                                          snapshot: TableSnapshot,
                                          context=None) -> List[Fix]:
        """Fix business rule violations defined by schema
        
        This method will only be triggered when the rules field is defined in the schema"""
        from ...memory import Fix, FixType, SuggestedFix
        from ...core.ids import IdGenerator
        
        fixes = []
        rule_id = getattr(violation, 'business_rule_id', '')
        
        self.logger.info(f"[MCPFixer] Fixing business rule violation: {rule_id}")
        
        if rule_id == 'phi_1':
            fixes = await self._fix_mutual_investment_violation(violation, snapshot, context)
        
        elif rule_id == 'phi_2':
            fixes = await self._fix_cash_sanity_violation(violation, snapshot, context)
        
        elif rule_id == 'phi_3':
            fixes = await self._fix_recursive_investment_violation(violation, snapshot, context)
        
        else:
            self.logger.debug(f"  Using generic MCP fix for unknown business rule: {rule_id}")
            fixes = await self._fallback_fix(violation, snapshot, context)
        
        return fixes
    
    async def _fix_mutual_investment_violation(self, violation: Violation,
                                              snapshot: TableSnapshot,
                                              context=None) -> List[Fix]:
        """Fix phi_1: Mutual investment prohibition violation
        
        Strategy: Flags require manual review because it is necessary to determine which investment relationship is more trustworthy"""
        from ...memory import Fix, FixType
        from ...core.ids import IdGenerator
        
        fixes = []
        
        self.logger.info("  [phi_1] Mutual investment violation requires manual review")
        
        try:
            fix_id = IdGenerator.generate_fix_id(
                violation.table, violation.tuple_id, violation.attr,
                FixType.BUSINESS_RULE_FIX.value, "manual_review"
            )
            
            fix = Fix(
                id=fix_id,
                table=violation.table,
                tuple_id=violation.tuple_id,
                attr=violation.attr,
                old=getattr(violation, 'current_value', None),
                new="[Manual review required: determine which investment relationship is more credible]",
                fix_type=FixType.BUSINESS_RULE_FIX.value,
                applied_by=f"{self.fixer_id}_phi1",
                timestamp=""
            )
            fix.needs_manual_review = True
            fix.fix_strategy = "manual_decision_on_investment_credibility"
            fix.business_rule_id = "phi_1"
            
            fixes.append(fix)
            
        except Exception as e:
            self.logger.error(f"Failed to generate phi_1 fix marker: {e}")
        
        return fixes
    
    async def _fix_cash_sanity_violation(self, violation: Violation,
                                        snapshot: TableSnapshot,
                                        context=None) -> List[Fix]:
        """Fix phi_2: Cash rationality boundary violation
        
        Policy: Markup needs to be revalidated from source document"""
        from ...memory import Fix, FixType
        from ...core.ids import IdGenerator
        
        fixes = []
        
        self.logger.info("  [phi_2] Cash sanity violation: recommend re-verifying source document")
        
        try:
            fix_id = IdGenerator.generate_fix_id(
                violation.table, violation.tuple_id, violation.attr,
                FixType.BUSINESS_RULE_FIX.value, "verify_source"
            )
            
            fix = Fix(
                id=fix_id,
                table=violation.table,
                tuple_id=violation.tuple_id,
                attr=violation.attr,
                old=getattr(violation, 'current_value', None),
                new="[Source document re-verification required]",
                fix_type=FixType.BUSINESS_RULE_FIX.value,
                applied_by=f"{self.fixer_id}_phi2",
                timestamp=""
            )
            fix.needs_manual_review = True
            fix.fix_strategy = "verify_source_document"
            fix.business_rule_id = "phi_2"
            
            fixes.append(fix)
            
        except Exception as e:
            self.logger.error(f"Failed to generate phi_2 fix marker: {e}")
        
        return fixes
    
    async def _fix_recursive_investment_violation(self, violation: Violation,
                                                 snapshot: TableSnapshot,
                                                 context=None) -> List[Fix]:
        """Fix phi_3: recursive investment violation (transitive closure)
        
        Strategy: Add missing indirect investment relationships based on suggested_fix"""
        from ...memory import Fix, FixType
        from ...core.ids import IdGenerator
        
        fixes = []
        
        self.logger.info("  [phi_3] Adding missing transitive investment relationship")
        
        if hasattr(violation, 'suggested_fix') and violation.suggested_fix:
            suggested_value = violation.suggested_fix.value
            
            try:
                fix_id = IdGenerator.generate_fix_id(
                    violation.table, "NEW_ROW", "transitive_investment",
                    FixType.BUSINESS_RULE_FIX.value, "add_relation"
                )
                
                fix = Fix(
                    id=fix_id,
                    table=violation.table,
                    tuple_id="NEW_ROW",
                    attr="transitive_investment",
                    old=None,
                    new=suggested_value,
                    fix_type=FixType.BUSINESS_RULE_FIX.value,
                    applied_by=f"{self.fixer_id}_phi3",
                    timestamp=""
                )
                fix.fix_action = "insert_row"
                fix.suggested_relation = suggested_value
                fix.business_rule_id = "phi_3"
                
                fixes.append(fix)
                
            except Exception as e:
                self.logger.error(f"Failed to generate phi_3 fix: {e}")
        else:
            self.logger.warning("  [phi_3] Missing fix suggestion; skipping")
        
        return fixes
