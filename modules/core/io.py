"""Input/output read-write module."""
import json
import os
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime

from ..memory import TableSnapshot, Violation, Fix


class WerkzeugFilter(logging.Filter):
    """Filter werkzeug logs so they stay out of the file but remain in console output."""
    def filter(self, record):
        return not record.name.startswith('werkzeug')


class IOManager:
    """Input/output manager."""
    
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.base_path = self.output_dir
        
        self.logger = self._setup_logger()
    
    def _setup_logger(self) -> logging.Logger:
        """Set up the logger."""
        log_file = self.output_dir / 'run.log'
        file_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8')
        file_handler.setLevel(logging.INFO)
        file_handler.addFilter(WerkzeugFilter())
        
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)
        
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)
        root_logger.handlers.clear()
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
        
        logger = logging.getLogger('doc2db')
        logger.setLevel(logging.INFO)
        
        return logger
    
    @staticmethod
    def get_timestamp() -> str:
        """Return the current timestamp."""
        return datetime.now().isoformat()
    
    def read_schema(self, schema_path: str) -> Dict[str, Any]:
        """Read an ER schema file."""
        try:
            with open(schema_path, 'r', encoding='utf-8') as f:
                schema = json.load(f)
            return schema
        except Exception as e:
            self.logger.error(f"Failed to read schema file {schema_path}: {e}")
            raise
    
    def read_nl_prompt(self, prompt_path: str) -> str:
        """Read a natural language prompt file."""
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt = f.read().strip()
            return prompt
        except Exception as e:
            self.logger.error(f"Failed to read prompt file {prompt_path}: {e}")
            raise
    
    def list_documents(self, docs_path: str) -> List[str]:
        """List all files in the documents directory."""
        try:
            docs_dir = Path(docs_path)
            if not docs_dir.exists():
                raise FileNotFoundError(f"Documents directory not found: {docs_path}")
            
            supported_extensions = {'.pdf', '.txt', '.md', '.docx', '.doc'}
            
            doc_files = []
            for file_path in docs_dir.rglob('*'):
                if file_path.is_file() and file_path.suffix.lower() in supported_extensions:
                    doc_files.append(str(file_path))
            
            self.logger.info(f"Found {len(doc_files)} document files")
            return sorted(doc_files)
        except Exception as e:
            self.logger.error(f"Failed to list documents {docs_path}: {e}")
            raise
    
    def write_snapshots(self, snapshots: List[TableSnapshot]) -> None:
        """Write the snapshots file."""
        try:
            snapshots_file = self.output_dir / 'snapshots.jsonl'
            with open(snapshots_file, 'w', encoding='utf-8') as f:
                for snapshot in snapshots:
                    f.write(json.dumps(snapshot.to_dict(), ensure_ascii=False, sort_keys=False) + '\n')
        except Exception as e:
            self.logger.error(f"Failed to write snapshots: {e}")
            raise
            
    def append_snapshot(self, snapshot: TableSnapshot) -> None:
        """Append a single snapshot to the file to record each processing stage."""
        try:
            snapshots_file = self.output_dir / 'snapshots.jsonl'
            with open(snapshots_file, 'a', encoding='utf-8') as f:
                snapshot_dict = snapshot.to_dict()
                snapshot_dict['processing_stage'] = getattr(snapshot, 'processing_stage', 'unknown')
                snapshot_dict['stage_description'] = getattr(snapshot, 'stage_description', '')
                snapshot_dict['rows_count'] = len(snapshot.rows)
                f.write(json.dumps(snapshot_dict, ensure_ascii=False, sort_keys=False) + '\n')
        except Exception as e:
            self.logger.error(f"Failed to append snapshot: {e}")
            raise
    
    def write_violations(self, violations: List[Violation]) -> None:
        """Write the violations file."""
        try:
            violations_file = self.output_dir / 'violations.jsonl'
            with open(violations_file, 'w', encoding='utf-8') as f:
                for violation in violations:
                    f.write(json.dumps(violation.to_dict(), ensure_ascii=False, sort_keys=False) + '\n')
        except Exception as e:
            self.logger.error(f"Failed to write violations: {e}")
            raise
    
    def write_fixes(self, fixes: List[Fix]) -> None:
        """Write the fixes file."""
        try:
            fixes_file = self.output_dir / 'fixes.jsonl'
            with open(fixes_file, 'w', encoding='utf-8') as f:
                for fix in fixes:
                    f.write(json.dumps(fix.to_dict(), ensure_ascii=False, sort_keys=False) + '\n')
        except Exception as e:
            self.logger.error(f"Failed to write fixes: {e}")
            raise
    
    def read_snapshots(self) -> List[TableSnapshot]:
        """Read the snapshots file."""
        try:
            snapshots_file = self.output_dir / 'snapshots.jsonl'
            if not snapshots_file.exists():
                return []
            
            snapshots = []
            with open(snapshots_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        data = json.loads(line)
                        snapshots.append(TableSnapshot.from_dict(data))
            return snapshots
        except Exception as e:
            self.logger.error(f"Failed to read snapshots: {e}")
            raise

