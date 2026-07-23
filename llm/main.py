"""
Unified entry point for the LLM module.
Automatically selects the appropriate model based on configuration.
"""

import logging
from typing import Optional, List, Dict
from pathlib import Path
import llm.gpt as gpt
import llm.qwen as qwen
import llm.deepseek as deepseek
import llm.global_config as config

logger = logging.getLogger('llm.main')


def get_answer(
    question: str,
    image: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
    system_prompt: Optional[str] = None,
    model: Optional[str] = None
) -> Optional[str]:
    """
    Unified LLM call interface that routes to the appropriate implementation based on model name.
    
    Args:
        question: User input question or content
        image: Image path or URL (optional)
        history: Conversation history (optional)
        system_prompt: System prompt (optional)
        model: Model name (optional); uses global config if None
    
    Returns:
        str: Model response text, or None on failure
    """
    if model is None:
        model = config.get_model().lower()
    else:
        model = model.lower()
    
    logger.debug(f"Calling LLM: model={model}, input length={len(question)}")
    
    try:
        if 'qwen' in model:
            output = qwen.get_answer(
                text=question,
                image=image,
                system_prompt=system_prompt,
                history=history,
                model=model
            )
        elif 'deepseek' in model:
            output = deepseek.get_answer(
                content=question,
                system_prompt=system_prompt,
                history=history,
                model=model
            )
        else:
            output = gpt.get_answer(
                text=question,
                image=image,
                system_prompt=system_prompt,
                history=history,
                model=model
            )
        
        if output:
            logger.info(f"LLM call succeeded (model={model}, output length={len(str(output))})")
        else:
            logger.warning(f"LLM call failed (model={model})")
        
        return output
        
    except Exception as e:
        logger.error(f"LLM call error (model={model}): {str(e)}")
        return None


if __name__ == '__main__':
    test_question = "What is the capital of France?"
    answer = get_answer(test_question)
    print(f"Answer: {answer}")
