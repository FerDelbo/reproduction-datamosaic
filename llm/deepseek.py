"""
Deepseek model API.
Supports Deepseek-Chat (V3) and Deepseek-Reasoner (R1) models.
"""

import time
import logging
from typing import Optional, List, Dict
from openai import OpenAI
import llm.global_config as global_config
from llm.utils import load_env_config, get_llm_request_timeout, get_llm_max_retries, get_llm_retry_delay

logger = logging.getLogger('llm.deepseek')

config = load_env_config()


def get_answer(
    content: str,
    system_prompt: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
    model: Optional[str] = None
) -> str:
    """
    Call a Deepseek model to get an answer.
    
    Args:
        content: user input content
        system_prompt: system prompt (optional)
        history: conversation history (optional)
        model: model name (optional); uses the global config if None
    
    Returns:
        str: the model's answer text
    """
    output = ''
    
    if model is None:
        model = global_config.get_model()
    
    if model.lower() == 'deepseek-v3':
        model = 'deepseek-chat'
    elif 'deepseek' in model.lower():
        if 'r1' in model.lower():
            model = 'deepseek-reasoner'
        else:
            model = 'deepseek-chat'
    else:
        model = 'deepseek-chat'
    
    logger.debug(f"Using Deepseek model: {model}")
    
    if history is None:
        if system_prompt is None:
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": content}
            ]
        else:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content},
            ]
    else:
        if system_prompt is None:
            messages = history + [{"role": "user", "content": content}]
        else:
            messages = [
                {"role": "system", "content": system_prompt}
            ] + history + [
                {"role": "user", "content": content}
            ]
    
    api_key = config.get("DEEPSEEK_KEY")
    base_url = config.get("DEEPSEEK_URL")
    
    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=get_llm_request_timeout(),
    )
    
    max_retries = get_llm_max_retries()
    retry_delay = get_llm_retry_delay()
    for i in range(max_retries):
        try:
            logger.debug("=" * 50)
            logger.debug("Deepseek input:")
            logger.debug(f"Model: {model}")
            logger.debug("Message count: %d", len(messages))
            logger.debug("=" * 50)
            
            response = client.chat.completions.create(
                model=model,
                messages=messages,
                stream=False
            )
            
            output = response.choices[0].message.content
            
            logger.debug("=" * 50)
            logger.debug("Deepseek output length: %d", len(output))
            logger.debug("=" * 50)
            
            logger.info(f"Deepseek call succeeded (model={model}, output length={len(output)})")
            return output
            
        except Exception as e:
            logger.warning(f"Deepseek call failed (attempt {i+1}/{max_retries}): {str(e)}")
            if i < max_retries - 1:
                time.sleep(retry_delay)
    
    logger.error(f"Deepseek call failed after {max_retries} retries")
    return output


if __name__ == '__main__':
    test_input = """
What is the FY2022 unadjusted EBITDA less capex for PepsiCo? 
Define unadjusted EBITDA as unadjusted operating income + depreciation and amortization.
Answer in USD millions.
"""
    
    ans = get_answer(test_input)
    print(ans)
