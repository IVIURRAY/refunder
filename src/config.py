"""Configuration management for RefundAgent.

Loads all application configuration from environment variables using
pydantic-settings. This is the single source of truth for all config —
never use os.environ.get() directly elsewhere in the codebase.
"""

from typing import Optional

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file.

    All configuration is centralised here. In Lambda, values are injected as
    environment variables. Locally, values are loaded from a .env file.
    """

    # AWS
    aws_region: str = "eu-west-1"
    aws_access_key_id: Optional[str] = None  # None = use IAM role in Lambda
    aws_secret_access_key: Optional[str] = None

    # S3
    raw_emails_bucket: str = "refundagent-raw-emails"

    # SES
    inbound_email_domain: str = "refundagent.com"

    # RDS
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "refundagent"
    db_user: str = "refundagent"
    db_password: str = "changeme"
    db_pool_size: int = 5

    # Bedrock
    bedrock_model_id: str = "anthropic.claude-sonnet-4-20250514-v1:0"
    bedrock_region: str = "eu-west-1"

    # App
    app_name: str = "refundagent"
    log_level: str = "INFO"
    environment: str = "development"  # development | staging | production

    @property
    def database_url(self) -> str:
        """Construct the SQLAlchemy database URL from individual components.

        Returns:
            str: PostgreSQL connection URL.
        """
        return (
            f"postgresql+psycopg2://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


# Module-level singleton — import this throughout the codebase
settings = Settings()
