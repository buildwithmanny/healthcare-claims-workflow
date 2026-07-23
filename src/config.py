import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = PROJECT_ROOT / ".env"

load_dotenv(ENV_FILE)


def get_required_env(variable_name: str) -> str:
    """
    Return a required environment variable.

    Raises:
        RuntimeError: If the environment variable is missing or empty.
    """
    value = os.getenv(variable_name)

    if not value:
        raise RuntimeError(
            f"Required environment variable '{variable_name}' is not configured."
        )

    return value


DB_CONFIG = {
    "host": get_required_env("DB_HOST"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": get_required_env("DB_NAME"),
    "user": get_required_env("DB_USER"),
    "password": get_required_env("DB_PASSWORD"),
}