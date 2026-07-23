"""
Qwen series model API.
Supports Qwen-Long, Qwen2.5, and related models.
"""

import requests
import time
import json
import logging
from typing import Optional, List, Dict
import llm.global_config as global_config
from llm.utils import load_env_config, build_messages, get_llm_request_timeout, get_llm_max_retries, get_llm_retry_delay

logger = logging.getLogger('llm.qwen')

config = load_env_config()


def get_answer(
    text: str,
    image: Optional[str] = None,
    system_prompt: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
    model: Optional[str] = None
) -> str:
    """
    Call a Qwen series model to get an answer.
    
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
        'qwen2.5-7b-instruct',
        'qwen2.5-14b-instruct',
        'qwen2.5-32b-instruct',
        'qwen2.5-72b-instruct',
        'qwen2.5-14b-instruct-1m',
        'qwen2-72b-instruct',
        'qwen-long',
        'qwen-turbo'
    ]
    
    if model not in model_list:
        logger.warning(f"Model {model} is not supported, using default qwen-long")
        model = 'qwen-long'
    
    logger.debug(f"Using Qwen model: {model}")
    
    messages = build_messages(text, image, system_prompt, history)
    
    api_url = config.get("QWEN_URL")
    api_key = config.get("QWEN_KEY")
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    
    data = {
        'model': model,
        'messages': messages,
    }
    
    max_retries = get_llm_max_retries()
    retry_delay = get_llm_retry_delay()
    request_timeout = get_llm_request_timeout()
    for i in range(max_retries):
        try:
            logger.debug("=" * 50)
            logger.debug("Qwen input:")
            logger.debug("Message count: %d", len(messages))
            logger.debug("=" * 50)
            
            response = requests.post(api_url, headers=headers, json=data, timeout=request_timeout)
            response_json = response.json()
            output = response_json['choices'][0]['message']['content']
            
            logger.debug("=" * 50)
            logger.debug("Qwen output length: %d", len(output))
            logger.debug("=" * 50)
            
            logger.info(f"Qwen call succeeded (model={model}, output length={len(output)})")
            return output
            
        except Exception as e:
            logger.warning(f"Qwen call failed (attempt {i+1}/{max_retries}): {str(e)}")
            if i < max_retries - 1:
                time.sleep(retry_delay)
    
    logger.error(f"Qwen call failed after {max_retries} attempts")
    return output


if __name__ == '__main__':
    test_input = """
What is the FY2022 unadjusted EBITDA less capex for PepsiCo? 
Define unadjusted EBITDA as unadjusted operating income + depreciation and amortization.
Answer in USD millions.
"""
    
    answer = get_answer(test_input, model="qwen-long")
    print(answer)
