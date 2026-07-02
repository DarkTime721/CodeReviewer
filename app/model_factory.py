import os
from dotenv import load_dotenv

load_dotenv()

def get_model(role: str = "default"):
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()

    if provider == "ollama":
        from langchain_ollama import ChatOllama
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

        model_map = {
            "classifier": os.getenv("OLLAMA_CLASSIFIER", "qwen2.5-coder"),
            "judge": os.getenv("OLLAMA_JUDGE_MODEL", "qwen3.5:9b"),
            "specialist": os.getenv("OLLAMA_SPECIALIST_MODEL", "qwen2.5-coder:14b"),
            "default": os.getenv("OLLAMA_DEFAULT_MODEL", "qwen2.5-coder:14b"),
        }
        return ChatOllama(model=model_map.get(role, model_map["default"]), temperature=0, base_url=base_url)
    
    elif provider == "openai":
        from langchain_openai import ChatOpenAI
        model_map = {
            "classifier": os.getenv("OPENAI_CLASSIFIER", "gpt-4o-mini"),
            "judge": os.getenv("OPENAI_JUDGE_MODEL", "gpt-4o"),
            "specialist": os.getenv("OPENAI_SPECIALIST_MODEL", "gpt-4o-mini"),
            "default": os.getenv("OPENAI_DEFAULT_MODEL", "gpt-4o-mini"),
        }
        return ChatOpenAI(
            model=model_map.get(role, model_map['default']),
            api_key=os.getenv("OPENAI_API_KEY"),
            temperature=0
        )
    
    elif provider == "groq":
        from langchain_groq import ChatGroq
        model_map = {
            "classifier": os.getenv("GROQ_CLASSIFIER", "llama-3.1-8b-instant"),
            "judge": os.getenv("GROQ_JUDGE_MODEL", "llama-3.1-70b-versatile"),
            "specialist": os.getenv("GROQ_SPECIALIST_MODEL", "llama-3.1-70b-versatile"),
            "default": os.getenv("GROQ_DEFAULT_MODEL", "llama-3.1-8b-instant"),
        }
        return ChatGroq(
            model=model_map.get(role, model_map['default']),
            api_key=os.getenv("GROQ_API_KEY"),
            temperature=0
        )
    
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER: '{provider}'. Choose from: ollama, openai, groq")