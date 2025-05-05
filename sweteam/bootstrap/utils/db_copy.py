import sqlite3
from pathlib import Path
from .log import logger
from .decorators import timing_context


def copy_evaluation_criteria_table(
    source_db_path: str = "evaluation_criteria.db",
    target_db_path: str = "issue_evaluator.db"
):
    """Copy evaluation_criteria table from source to target database.

    Args:
        source_db_path (str): Path to source database
        target_db_path (str): Path to target database
    """
    with timing_context("db_table_copy"):
        try:
            # Connect to both databases
            source = sqlite3.connect(source_db_path)
            target = sqlite3.connect(target_db_path)

            # Copy table structure and data
            source.backup(target)
            logger.info("Successfully copied evaluation_criteria table")

        except sqlite3.Error as e:
            logger.error("Failed to copy table: %s", str(e))
            raise
        finally:
            source.close()
            target.close()


if __name__ == "__main__":
    # Assuming script is run from project root
    src_path = Path("evaluation_criteria.db").absolute()
    dst_path = Path("issue_evaluator.db").absolute()

    copy_evaluation_criteria_table(str(src_path), str(dst_path))
