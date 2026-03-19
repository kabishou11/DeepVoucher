from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    modelscope_api_key: str = ""
    modelscope_base_url: str = "https://api-inference.modelscope.cn/v1"
    modelscope_chat_model: str = "Qwen/Qwen3.5-35B-A3B"
    embedding_model_path: str = r"F:\models\modelscope\models\Xorbits\bge-m3"
    lancedb_uri: str = "./knowledge/lancedb"
    sqlite_path: str = "./data/app.db"
    data_dir: str = "./data"
    knowledge_dir: str = "./knowledge"
    reference_dir: str = "./reference"
    test_input_dir: str = "./test_input"
    ground_truth_dir: str = "./ground_truth"
    default_lb: int = 1
    default_orgnow: str = "320282105231000"
    default_menu: int = 21
    default_sys: int = 3
    web_origin: str = "http://localhost:3000"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    llm_timeout_seconds: int = 120

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
