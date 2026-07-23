"""
Global configuration management for the LLM module.
Manages the default model name.
"""

import json
import os
from pathlib import Path
from typing import Optional

_model = 'gpt'


def _load_config_from_file() -> None:
    """
    Load configuration from known config.json locations.
    Searches in priority order and uses the first valid config found.
    """
    global _model
    
    config_locations = [
        Path(__file__).parent.parent / "document_chat_app" / "backend" / "config.json",
        Path(__file__).parent.parent / "refer_code" / "backend" / "config.json",
        Path(__file__).parent / "config.json",
        Path(__file__).parent.parent / "config.json"
    ]
    
    for config_path in config_locations:
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    if 'model' in config:
                        _model = config['model']
                        print(f"Loaded model config from {config_path}: {_model}")
                        return
            except Exception as e:
                print(f"Failed to load config from {config_path}: {e}")
                continue


def set_model(new_model: str) -> None:
    """
    Set the global model name.
    
    Args:
        new_model: New model name
    """
    global _model
    _model = new_model


def get_model() -> str:
    """
    Get the current global model name.
    
    Returns:
        str: Current global model name
    """
    return _model


def reload_config() -> None:
    """
    Reload model configuration from the config file.
    """
    _load_config_from_file()


_load_config_from_file()
