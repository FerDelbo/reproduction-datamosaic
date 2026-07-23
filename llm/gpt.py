"""
GPT series model API.
Supports GPT-4o, Claude, Gemini, and other models via OpenAI-compatible endpoints.
"""

import requests
import time
import json
import logging
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
import llm.global_config as global_config
from llm.utils import load_env_config, build_messages, get_llm_request_timeout, get_llm_max_retries, get_llm_retry_delay

logger = logging.getLogger('llm.gpt')

config = load_env_config()

current_dir = os.path.dirname(os.path.abspath(__file__))
LLM_LOG_DIR = os.path.join(current_dir, "..", "llm_logs")
os.makedirs(LLM_LOG_DIR, exist_ok=True)


def save_llm_call_log(
    model: str,
    input_data: Dict[str, Any],
    output_data: Any,
    error: Optional[str] = None
) -> Optional[str]:
    """
    Save LLM call input and output to a file.
    
    Args:
        model: Model name used
        input_data: LLM input data (dict)
        output_data: LLM output data (string or dict)
        error: Error message if any
    
    Returns:
        str: Log file path, or None if save failed
    """
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        log_filename = f"llm_call_{timestamp}.json"
        log_filepath = os.path.join(LLM_LOG_DIR, log_filename)
        
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "input": input_data,
            "output": output_data,
            "error": error,
            "success": error is None
        }
        
        with open(log_filepath, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"LLM call log saved: {log_filepath}")
        return log_filepath
    except Exception as e:
        logger.error(f"Failed to save LLM call log: {str(e)}")
        return None


def get_answer(
    text: str,
    image: Optional[str] = None,
    system_prompt: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
    model: Optional[str] = None
) -> str:
    """
    Call a GPT series model to get an answer.
    
    Args:
        text: User input text
        image: Image path (optional)
        system_prompt: System prompt (optional)
        history: Conversation history (optional)
        model: Model name (optional); uses global config if None
    
    Returns:
        str: Model response text
    """
    output = ''
    
    if model is None:
        model = global_config.get_model()
    
    model_list = [
        'gpt-4o', 'gpt-4o-mini', 'o1',
        'claude-3-5-sonnet-20240620', 'claude-sonnet-4-20250514',
        'deepseek-r1', 'deepseek-v3',
        'gpt-5', 'gemini-2.5-pro'
    ]
    
    if model not in model_list:
        logger.warning(f"Model {model} is not supported, using default gpt-4o")
        model = 'gpt-4o'
    
    messages = build_messages(text, image, system_prompt, history)
    
    api_url = config.get("API_URL")
    api_key = config.get("API_KEY")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    data = {
        'model': model,
        'messages': messages,
    }
    
    last_error = None
    max_retries = get_llm_max_retries()
    retry_delay = get_llm_retry_delay()
    request_timeout = get_llm_request_timeout()
    for i in range(max_retries):
        try:
            logger.debug("=" * 50)
            logger.debug("GPT input:")
            logger.debug("Message count: %d", len(messages))
            logger.debug("=" * 50)
            
            response = requests.post(api_url, headers=headers, json=data, timeout=request_timeout)
            
            logger.debug("=" * 50)
            logger.debug("GPT response received")
            logger.debug("HTTP status: %s", response.status_code)
            logger.debug("=" * 50)
            
            response_json = response.json()
            output = response_json['choices'][0]['message']['content']
            
            logger.info(f"GPT call succeeded (model={model}, output length={len(output)})")
            return output
            
        except Exception as e:
            last_error = str(e)
            logger.warning(f"GPT call failed (attempt {i+1}/{max_retries}): {last_error}")
            if i < max_retries - 1:
                time.sleep(retry_delay)
    
    logger.error(f"GPT call failed after {max_retries} attempts: {last_error}")
    return output


if __name__ == '__main__':
    test_input = """
What is the FY2022 unadjusted EBITDA less capex for PepsiCo? 
Define unadjusted EBITDA as unadjusted operating income + depreciation and amortization.
Answer in USD millions.
"""
    
    answer = get_answer(test_input, model="gpt-4o-mini")
    print(answer)
