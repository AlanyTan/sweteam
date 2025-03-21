from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "default_project"
    ISSUE_BOARD_DIR: str = "issue_board"
    JIRA_BASE_URL: str = ""
    JIRA_USERNAME: str = ""
    JIRA_API_KEY: str = ""
    INDEX_STORE_PERSIST_DIR: str = "index.store"
    LOG_LEVEL: str = "INFO"
    LOG_LEVEL_CONSOLE: str = "WARNING"
    AZURE_OPENAI_DEPLOYMENT_NAME: str = ''
    OPENAI_MODEL: str = ''
    USE_AZURE: bool = True
    AZURE_OPENAI_API_KEY: str = ''
    OPENAI_API_KEY: str = ''
    RETRY_COUNT: int = 3
    DIR_STRUCTURE_YAML: str = PROJECT_NAME + "/dir_structure.yaml"
    OLLAMA_HOST: str = "http://172.17.0.1:11434"  # "http://localhost:11434"
    OLLAMA_DEFAULT_BASE_MODEL: str = "deepseek-r1:14b"
    OLLAMA_EMBEDDING_MODEL: str = "bge-m3"
    REDIS_HOST: str = "172.17.0.1"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_USERNAME: str = ""

    @field_validator('PROJECT_NAME', 'ISSUE_BOARD_DIR', 'AZURE_OPENAI_DEPLOYMENT_NAME', 'OPENAI_MODEL', 'AZURE_OPENAI_API_KEY', 'OPENAI_API_KEY')
    def validate_alphanumeric_and_underscore(cls, v, field):
        if not all(char.isalnum() or char in '_-' for char in v):
            raise ValueError(
                f'{field.field_name} must contain only alphanumeric characters and underscores')
        return v

    @field_validator('RETRY_COUNT')
    def check_app_port(cls, value):
        if not isinstance(value, int):
            raise ValueError('app_port must be an integer')
        return value


try:
    config = Settings()
except ValidationError as e:
    print(f'Environment variable validation error: {e}')
    config = BaseSettings()
    exit()


def test():
    """
    >>> os.environ['PROJECT_NAME'] = 'Valid_Project_Name_123'
    >>> os.environ['ISSUE_BOARD_DIR'] = 'Valid_Dir_123'
    >>> os.environ['AZURE_OPENAI_DEPLOYMENT_NAME'] = 'Valid_Deployment_Name'
    >>> os.environ['OPENAI_MODEL'] = 'Valid_Model'
    >>> os.environ['AZURE_OPENAI_API_KEY'] = 'Valid_API_Key'
    >>> os.environ['OPENAI_API_KEY'] = 'Valid_API_Key'
    >>> os.environ['RETRY_COUNT'] = '12'
    >>> os.environ['USE_AZURE'] = 'False'
    >>> config = Settings()
    >>> config.PROJECT_NAME
    'Valid_Project_Name_123'
    >>> config.ISSUE_BOARD_DIR
    'Valid_Dir_123'
    >>> config.AZURE_OPENAI_DEPLOYMENT_NAME
    'Valid_Deployment_Name'
    >>> config.OPENAI_MODEL
    'Valid_Model'
    >>> config.AZURE_OPENAI_API_KEY
    'Valid_API_Key'
    >>> config.OPENAI_API_KEY
    'Valid_API_Key'
    >>> config.RETRY_COUNT
    12
    >>> config.USE_AZURE
    False

    >>> os.environ['PROJECT_NAME'] = 'Invalid Project Name!'
    >>> os.environ['ISSUE_BOARD_DIR'] = 'Invalid Dir Name!'
    >>> os.environ['RETRY_COUNT'] = 'Invalid Retry Count'
    >>> Settings()
    Traceback (most recent call last):
    ...
    pydantic.error_wrappers.ValidationError: 3 validation errors for Settings
    PROJECT_NAME
      PROJECT_NAME must contain only alphanumeric characters and underscores (type=value_error)
    ISSUE_BOARD_DIR
      ISSUE_BOARD_DIR must contain only alphanumeric characters and underscores (type=value_error)
    RETRY_COUNT
      value is not a valid integer (type=type_error.integer)

    >>> del os.environ['PROJECT_NAME']
    >>> del os.environ['ISSUE_BOARD_DIR']
    >>> del os.environ['RETRY_COUNT']
    >>> config = Settings()
    >>> config.ISSUE_BOARD_DIR
    'issue_board'
    >>> config.PROJECT_NAME
    'default_project'

    """


if __name__ == '__main__':
    import doctest
    doctest.testmod()
