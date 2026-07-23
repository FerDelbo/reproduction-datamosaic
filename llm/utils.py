"""
Shared utility functions for the LLM module.
"""

import re
import base64
import os
from pathlib import Path
from dotenv import dotenv_values
from typing import Optional


def load_env_config(env_filename: str = ".env") -> dict:
    """
    Load environment configuration file.
    
    Args:
        env_filename: Environment config filename, defaults to ".env"
    
    Returns:
        dict: Configuration dictionary
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    env_path = os.path.join(current_dir, env_filename)
    return dotenv_values(env_path)


def _read_env_number(name: str, default: float, as_int: bool = False):
    config = load_env_config()
    raw = os.environ.get(name) or config.get(name)
    if raw is None or str(raw).strip() == "":
        return int(default) if as_int else default
    try:
        return int(raw) if as_int else float(raw)
    except (TypeError, ValueError):
        return int(default) if as_int else default


def get_llm_request_timeout(default: float = 30.0) -> float:
    return _read_env_number("LLM_REQUEST_TIMEOUT", default)


def get_llm_max_retries(default: int = 3) -> int:
    return _read_env_number("LLM_MAX_RETRIES", default, as_int=True)


def get_llm_retry_delay(default: float = 3.0) -> float:
    return _read_env_number("LLM_RETRY_DELAY", default)


def count_len(text: str) -> int:
    """
    Compute text length (Chinese character count + English word count).
    
    Args:
        text: Text to measure
    
    Returns:
        int: Text length
    """
    chinese_count = len(re.findall(r'[\u4e00-\u9fa5]', text))
    word_count = len(re.findall(r'[a-zA-Z]+', text))
    total_count = chinese_count + word_count
    return total_count


def encode_image(image_path: str) -> str:
    """
    Encode an image file as a base64 string.
    
    Args:
        image_path: Image file path
    
    Returns:
        str: Base64-encoded image string
    """
    with open(image_path, "rb") as image_file:
        image_bytes = image_file.read()
    base64_image = base64.b64encode(image_bytes).decode('utf-8')
    return base64_image


def build_messages(
    content: str,
    image: Optional[str] = None,
    system_prompt: Optional[str] = None,
    history: Optional[list] = None
) -> list:
    """
    Build the message list for an LLM call.
    
    Args:
        content: User input content
        image: Image path (optional)
        system_prompt: System prompt (optional)
        history: Conversation history (optional)
    
    Returns:
        list: Message list
    """
    default_system = {"role": "system", "content": "You are a helpful assistant."}
    
    if image is None:
        user_message = {"role": "user", "content": content}
    else:
        base64_image = encode_image(image)
        user_message = {
            "role": "user",
            "content": [
                {"type": "text", "text": content},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
            ]
        }
    
    if history is None:
        if system_prompt is None:
            messages = [default_system, user_message]
        else:
            messages = [{"role": "system", "content": system_prompt}, user_message]
    else:
        if system_prompt is not None:
            messages = [{"role": "system", "content": system_prompt}] + history + [user_message]
        else:
            messages = history + [user_message]
    
    return messages
