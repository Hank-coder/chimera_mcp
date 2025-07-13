from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict
from typing import Optional, List
import os
from pathlib import Path


class Settings(BaseSettings):
    """
    Application settings using Pydantic Settings.
    Loads from environment variables with fallback to .env file.
    """
    
    # Application Configuration
    app_name: str = "personal-ai-memory"
    app_version: str = "0.1.0"
    app_environment: str = "development"
    debug: bool = True
    
    # Neo4j Configuration
    neo4j_uri: str = Field(default="neo4j://127.0.0.1:7687", description="Neo4j database URI")
    neo4j_username: str = Field(default="neo4j", description="Neo4j username")
    neo4j_password: str = Field(..., description="Neo4j password - MUST be set via environment variable")
    neo4j_database: str = Field(default="neo4j", description="Neo4j database name")
    
    # Notion Configuration
    notion_token: str = Field(..., description="Notion API token - MUST be set via environment variable")
    notion_base_url: str = Field(default="https://www.notion.so", description="Notion base URL")
    
    # Gemini Configuration
    gemini_api_key: str = Field(..., description="Gemini API key - MUST be set via environment variable")
    gemini_model: str = Field(default="models/text-embedding-004", description="Gemini embedding model")
    gemini_dimension: int = Field(default=768, description="Gemini embedding dimension")
    
    @property
    def GEMINI_API_KEY(self) -> str:
        """Compatibility property for GEMINI_API_KEY"""
        return self.gemini_api_key
    
    # Authentication Configuration
    chimera_api_key: Optional[str] = Field(default=None, description="Chimera API key for Bearer authentication")
    enable_auth: bool = Field(default=True, description="Enable Bearer token authentication")
    
    # MCP Server Configuration
    mcp_server_host: str = "localhost"
    mcp_server_port: int = 8080
    mcp_server_log_level: str = "INFO"
    max_concurrent_requests: int = 10
    request_timeout_seconds: int = 30
    
    # Sync Service Configuration
    sync_interval_minutes: int = 30
    sync_batch_size: int = 100
    sync_max_retries: int = 3
    sync_retry_delay: int = 5
    
    # Logging Configuration
    log_level: str = "INFO"
    log_file_path: str = "logs/chimera.log"
    log_format: str = "json"
    log_rotation: str = "1 day"
    log_retention: str = "30 days"
    
    # Graph Configuration
    graph_max_depth: int = 3
    graph_max_results: int = 50
    embedding_dimension: int = 768
    similarity_threshold: float = 0.7
    
    # Rate Limiting
    notion_rate_limit_per_second: int = 3
    openai_rate_limit_per_minute: int = 60
    
    model_config = ConfigDict(
        # 使用绝对路径确保能找到.env文件
        env_file=str(Path(__file__).parent.parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"  # 忽略额外字段，避免validation错误
    )
        
    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.app_environment.lower() == "development"
        
    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.app_environment.lower() == "production"
        
    def get_log_file_path(self) -> str:
        """Get the full log file path, creating directory if needed."""
        import os
        os.makedirs(os.path.dirname(self.log_file_path), exist_ok=True)
        return self.log_file_path


# Global settings instance
settings = Settings()
"""
 1. 当创建Settings()实例时，Pydantic会：
    - 首先读取系统环境变量
    - 然后读取.env文件中的变量
    - 系统环境变量优先级更高（会覆盖.env中的值）
  2. 变量映射：
    - .env中的NOTION_TOKEN → settings.notion_token
    - .env中的GEMINI_API_KEY → settings.gemini_api_key
    - .env中的NEO4J_PASSWORD → settings.neo4j_password

"""

def get_settings() -> Settings:
    """Get the global settings instance."""
    return settings


def reload_settings():
    """Reload settings from environment."""
    global settings
    settings = Settings()