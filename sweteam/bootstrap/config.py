from typing import ClassVar
from pydantic import ValidationError, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "issue_evaluator"
    ISSUE_BOARD_DIR: str = "issue_board"
    HOST: str = "localhost"
    PORT: int = 8000
    JIRA_BASE_URL: str = ""
    JIRA_USERNAME: str = ""
    JIRA_API_KEY: str = ""
    LOG_LEVEL: str = "INFO"
    LOG_LEVEL_CONSOLE: str = "WARNING"
    LOG_LEVEL_REDIS: str = ""
    RETRY_COUNT: int = 3
    DIR_STRUCTURE_YAML: str = PROJECT_NAME + "/dir_structure.yaml"
    OLLAMA_URL: str = "http://localhost:11434"
    OLLAMA_DEFAULT_BASE_MODEL: str = "deepseek-r1:14b"
    OLLAMA_EMBEDDING_MODEL: str = "bge-m3"
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_USERNAME: str = ""
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    GITHUB_API_KEY: str = ""
    GITHUB_REPO: str = ""

    AZURE_OPENAI_DEPLOYMENT_NAME: str = ''
    OPENAI_MODEL: str = ''
    USE_AZURE: bool = True
    AZURE_OPENAI_API_KEY: str = ''
    OPENAI_API_KEY: str = ''

    LOWER_CASE_LETTERS: ClassVar[str] = 'abcdefghijklmnopqrstuvwxyz'
    UPPER_CASE_LETTERS: ClassVar[str] = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    DIGITS: ClassVar[str] = '0123456789'
    SPECIAL_CHARS: ClassVar[str] = '~!@#$%^&*()-=_+[]{}|;:,.<>?`'

    @classmethod
    def allowed_chars(cls, value: str, field: str, char_sets: list = []) -> str:
        """Generic validator for checking allowed characters in a string.

        Args:
            value: The string to validate
            field: The field name being validated
            char_sets: list of character sets to check against

        Returns:
            The validated string

        Raises:
            ValueError: If the string contains invalid characters

        Examples:
            >>> Settings.allowed_chars('test123', 'test_field', 
            ...     [set('abcdefghijklmnopqrstuvwxyz0123456789')])
            'test123'

            >>> Settings.allowed_chars('', 'empty_field', [set('abc')])
            ''

            >>> Settings.allowed_chars('hello_world', 'test_field',
            ...     [set('abcdefghijklmnopqrstuvwxyz'), set('_')])
            'hello_world'

            >>> Settings.allowed_chars('Test123!', 'test_field',
            ...     [set('abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')])
            Traceback (most recent call last):
            ...
            ValueError: test_field contains invalid characters: ['!'].

            >>> Settings.allowed_chars('mixed@case', 'test_field',
            ...     [Settings.LOWER_CASE_LETTERS, Settings.UPPER_CASE_LETTERS])
            Traceback (most recent call last):
            ...
            ValueError: test_field contains invalid characters: ['@'].

            >>> Settings.allowed_chars('api-key_123', 'test_field',
            ...     [Settings.LOWER_CASE_LETTERS, set('_-'), Settings.DIGITS])
            'api-key_123'
        """
        if not value:  # Handle empty strings based on your requirements
            return value

        invalid_chars = set(value)
        for allowed in char_sets:
            invalid_chars -= set(allowed)

        if invalid_chars:
            raise ValueError(
                f'{field} contains invalid characters: {sorted(invalid_chars)}.'
                # f'Allowed characters are: {sorted(allowed)}'
            )
        return value

    @field_validator('PROJECT_NAME', 'ISSUE_BOARD_DIR', 'AZURE_OPENAI_DEPLOYMENT_NAME', 'OPENAI_MODEL', 'AZURE_OPENAI_API_KEY', 'OPENAI_API_KEY')
    def validate_alphanumeric_and_underscore(cls, v, field):
        return cls.allowed_chars(v, field.field_name, [cls.LOWER_CASE_LETTERS, cls.UPPER_CASE_LETTERS, cls.DIGITS, cls.SPECIAL_CHARS])

    @field_validator('HOST', 'REDIS_HOST', 'POSTGRES_HOST')
    def validate_hostname(cls, v, field):
        return cls.allowed_chars(v, field.field_name, [cls.LOWER_CASE_LETTERS, cls.UPPER_CASE_LETTERS, cls.DIGITS, set('.-')])

    @field_validator('OLLAMA_URL')
    def validate_ollama_url(cls, v, field):
        return cls.allowed_chars(v, field.field_name, [cls.LOWER_CASE_LETTERS, cls.UPPER_CASE_LETTERS, cls.DIGITS, set(':/.-')])

    @field_validator('RETRY_COUNT', 'PORT', 'REDIS_PORT', 'POSTGRES_PORT')
    def check_int_values(cls, value, field):
        if not isinstance(value, int):
            raise ValueError(f'{field.field_name} must be an integer')
        return value


try:
    config = Settings()
except ValidationError as e:
    print(f'Environment variable validation error: {e}')
    config = BaseSettings()
    exit()


def test():
    """
    >>> import os
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
    >>> Settings() # doctest: +ELLIPSIS
    Traceback (most recent call last):
    ...
    pydantic_core._pydantic_core.ValidationError: 3 validation errors for Settings...

    # Test default values
    >>> del os.environ['PROJECT_NAME']
    >>> del os.environ['ISSUE_BOARD_DIR']
    >>> del os.environ['RETRY_COUNT']
    >>> config = Settings()
    >>> config.ISSUE_BOARD_DIR
    'issue_board'
    >>> config.PROJECT_NAME
    'issue_evaluator'

    """


if __name__ == '__main__':
    import doctest
    doctest.testmod()
