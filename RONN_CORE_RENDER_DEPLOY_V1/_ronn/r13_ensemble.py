"""RONN R13 Adaptive Free-Model Ensemble.

Uses four free OpenRouter model endpoints as complementary specialists:
- Nemotron 3 Ultra: hard reasoning/planning
- DeepSeek V4 Flash: coding/debugging
- Qwen3.8 27B: general/vision
- GPT-OSS 120B: critic/fallback

The ensemble is adaptive: it does not call every model for every request.
"""
from __future__ import annotations

NEMOTRON_MODEL = "nvidia/nemotron-3-ultra-550b-a55b:free"
DEEPSEEK_MODEL = "deepseek/deepseek-v4-flash:free"
QWEN_MODEL = "qwen/qwen3.8-27b:free"
CRITIC_MODEL = "openai/gpt-oss-120b:free"

ENSEMBLE_MODELS = {
    NEMOTRON_MODEL,
    DEEPSEEK_MODEL,
    QWEN_MODEL,
    CRITIC_MODEL,
}

def choose_primary(profile: str, difficulty: int, has_images: bool=False, current_fact: bool=False):
    """Return (model, route) for the strongest matching free specialist."""
    profile=(profile or "chat").lower()
    difficulty=int(difficulty or 0)
    if has_images:
        return QWEN_MODEL, "ensemble-vision"
    if profile in {"coding","roblox"}:
        return DEEPSEEK_MODEL, "ensemble-code"
    if profile in {"analysis","mathscience","knowledge","research"} or difficulty >= 3:
        return NEMOTRON_MODEL, "ensemble-reasoning"
    if profile in {"creative","writing","chat"}:
        return QWEN_MODEL, "ensemble-general"
    return QWEN_MODEL, "ensemble-general"

def critic_model():
    return CRITIC_MODEL

def council_models(profile: str):
    """Two diverse candidate solvers for very hard work."""
    profile=(profile or "chat").lower()
    second = DEEPSEEK_MODEL if profile in {"coding","roblox"} else QWEN_MODEL
    return [NEMOTRON_MODEL, second]

def fallback_models(profile: str="chat"):
    profile=(profile or "chat").lower()
    if profile in {"coding","roblox"}:
        return [DEEPSEEK_MODEL, NEMOTRON_MODEL, CRITIC_MODEL, QWEN_MODEL]
    return [QWEN_MODEL, NEMOTRON_MODEL, CRITIC_MODEL, DEEPSEEK_MODEL]

def status():
    return {
        "enabled_models": 4,
        "models": {
            "reasoning": NEMOTRON_MODEL,
            "coding": DEEPSEEK_MODEL,
            "general_vision": QWEN_MODEL,
            "critic_fallback": CRITIC_MODEL,
        },
        "strategy": "adaptive specialist + independent critic; council only for very hard work",
    }
