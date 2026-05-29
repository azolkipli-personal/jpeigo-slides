"""
PPTX Translator - Backend Configuration
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(extra='ignore', env_file=".env")
    
    # Server settings
    app_name: str = "PPTX Translator"
    debug: bool = False
    cors_origins: list[str] = ["http://localhost:3002"]
    
    # File upload settings
    max_file_size: int = 100 * 1024 * 1024  # 100MB
    upload_dir: str = "uploads"
    output_dir: str = "outputs"

    # Default model
    default_model: str = "gemini"

    # Translation API settings
    glm_api_key: Optional[str] = None
    glm_api_url: str = "https://open.bigmodel.cn/api/paas/v4"
    
    kimi_api_key: Optional[str] = None
    kimi_api_url: str = "https://api.moonshot.cn/v1"
    
    minimax_api_key: Optional[str] = None
    minimax_group_id: Optional[str] = None
    minimax_api_url: str = "https://api.minimax.chat/v1"
    
    qwen_api_key: Optional[str] = None
    qwen_api_url: str = "https://dashscope.aliyuncs.com/api/v1"
    
    # Google Cloud API settings (for Vision OCR and Translation)
    google_cloud_api_key: Optional[str] = None
    
    # Google Gemini settings (free tier available)
    gemini_api_key: Optional[str] = None
    gemini_api_url: str = "https://generativelanguage.googleapis.com/v1beta"
    
    # OpenCode Zen/Go settings (unified API for curated models)
    opencode_api_key: Optional[str] = None
    opencode_api_url: str = "https://api.opencode.ai/v1"
    
    # Ollama settings (for local models)
    ollama_url: Optional[str] = None  # e.g., "http://localhost:11434"
    
    # Google Slides OAuth
    google_slides_redirect_uri: str = "http://localhost:3002/api/slides/auth/callback"
    
    # Translation memory
    translation_cache_ttl: int = 86400  # 24 hours
    use_redis: bool = False
    redis_url: str = "redis://localhost:6379"


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
