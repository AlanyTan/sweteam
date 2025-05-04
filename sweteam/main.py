# from alembic.config import Config
# from alembic import command
# from alembic.script import ScriptDirectory
# from alembic.runtime.environment import EnvironmentContext
from pathlib import Path
import sys


# def run_migrations() -> None:
#     # Add the parent directory to Python path to ensure imports work as expected
#     sys.path.append(str(Path(__file__).parent.parent))

#     # Configure alembic
#     alembic_ini_path = Path(__file__).parent.parent / 'alembic.ini'
#     alembic_cfg = Config(str(alembic_ini_path))

#     # Get the ScriptDirectory
#     script = ScriptDirectory.from_config(alembic_cfg)

#     # Let command.upgrade handle the configuration
#     command.upgrade(alembic_cfg, "head")


def main() -> None:
    # # Run database migrations
    # run_migrations()

    # Start the application
    from .bootstrap.fastapi_app import IssueManagementApp
    with IssueManagementApp() as app:
        app.run()


if __name__ == "__main__":
    main()
