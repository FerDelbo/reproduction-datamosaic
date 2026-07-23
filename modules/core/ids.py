"""Idempotent ID generation rules."""
import hashlib
import uuid
from typing import Any, Dict, List
import json


class IdGenerator:
    """ID generator ensuring identical inputs produce identical IDs."""
    
    @staticmethod
    def generate_run_id(schema_path: str, docs_path: str, nl_prompt: str, table_name: str) -> str:
        """Generate a run ID from a hash of the input parameters."""
        content = f"{schema_path}:{docs_path}:{nl_prompt}:{table_name}"
        return f"run-{hashlib.sha256(content.encode()).hexdigest()[:16]}"
    
    @staticmethod
    def generate_tuple_id(table_name: str, row_index: int, row_content: Dict[str, Any]) -> str:
        """Generate a tuple ID."""
        content_str = json.dumps(row_content, sort_keys=True, ensure_ascii=False)
        content_hash = hashlib.md5(content_str.encode()).hexdigest()[:8]
        return f"t-{table_name}-{row_index:03d}-{content_hash}"
    
    @staticmethod
    def generate_violation_id(table: str, tuple_id: str, attr: str, constraint_type: str) -> str:
        """Generate a violation ID."""
        content = f"{table}:{tuple_id}:{attr}:{constraint_type}"
        hash_val = hashlib.md5(content.encode()).hexdigest()[:8]
        return f"v-{hash_val}"
    
    @staticmethod
    def generate_fix_id(table: str, tuple_id: str, attr: str, fix_type: str, old_value: Any) -> str:
        """Generate a fix ID."""
        content = f"{table}:{tuple_id}:{attr}:{fix_type}:{str(old_value)}"
        hash_val = hashlib.md5(content.encode()).hexdigest()[:8]
        return f"f-{hash_val}"
    
    @staticmethod
    def generate_detector_id(detector_class: str, version: str = "v1") -> str:
        """Generate a detector ID."""
        return f"{detector_class}.{version}"
    
    @staticmethod
    def generate_fixer_id(fixer_class: str, version: str = "v1") -> str:
        """Generate a fixer ID."""
        return f"{fixer_class}.{version}"
    
    @staticmethod
    def generate_table_id(table_name: str, schema_hash: str = None) -> str:
        """Generate a table ID."""
        if schema_hash:
            return f"table-{table_name}-{schema_hash[:8]}"
        else:
            unique_suffix = str(uuid.uuid4())[:8]
            return f"table-{table_name}-{unique_suffix}"

