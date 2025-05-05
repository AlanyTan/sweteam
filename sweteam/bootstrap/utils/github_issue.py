"""
This module contains utility functions for working with GitHub issues.
"""

from github import Github
from github.Issue import Issue
from github.Repository import Repository
from .file_utils import dir_structure
from typing import Callable, Any
import os
import subprocess
from enum import Enum
import yaml
import json
from datetime import datetime
from .initialize_project import initialize_package, initialize_Dockerfile, initialize_startup_script
from .log import logger
from ..config import config


def get_dot_notation_value(dict_obj, dot_path, default=None):
    """
    Access nested dictionary values using dot notation

    Args:
        dict_obj (dict): The dictionary to search
        dot_path (str): Path to value using dot notation (e.g. "status.name")
        default (any): value to return if the key is not found, None if ommited
    Returns:
        The value if found, None if not found
    """
    try:
        parts = dot_path.split('.')
        value = dict_obj
        for part in parts:
            value = value[part]
        return value
    except (KeyError, TypeError):
        return default


class Action(Enum):
    """Action Enum for the agent to take."""
    LIST = "list"
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    ASSIGN = "assign"


def issue_manager(action: str, issue: str = '', only_in_state: list = [],
                  content: str | None = None, assignee: str | None = None, caller: str = "unknown") -> dict | list:
    """Manage GitHub issues: list, create, read, update, assign

    Args:
        action (str): The action to perform ('list', 'create', 'read', 'update', 'assign')
        issue (str, optional): Issue number. Defaults to ''.
        only_in_state (list, optional): Filter issues by state. Defaults to [].
        content (str | None, optional): Issue content in JSON/YAML format. Defaults to None.
        assignee (str | None, optional): GitHub username to assign. Defaults to None.
        caller (str, optional): Name of the calling agent. Defaults to "unknown".

    Returns:
        dict | list: Operation result or list of issues

    Examples:
        List all issues:
        >>> all_issues = issue_manager('list')  # doctest: +NORMALIZE_WHITESPACE
        >>> all_issues.sort(key=lambda x: x['issue'])
        >>> all_issues[0]['issue']
        '1'

        Read an issue:
        >>> result = issue_manager('read', '1')
        >>> sorted(result.keys())  # doctest: +NORMALIZE_WHITESPACE
        ['body', 'created_at', 'issue#', 'latest_assignee', 'latest_priority',
         'latest_status', 'latest_updated_by', 'title', 'updated_at']

        Update an issue:
        >>> content = '''{"status": "in progress", "priority": "2 - High"}'''
        >>> result = issue_manager('update', '1', content=content)
        >>> result['status']
        'success'

        Assign an issue:
        >>> result = issue_manager('assign', '1', assignee='AlanYTan')
        >>> result['status']
        'success'

        List issues with filters:
        >>> issues = issue_manager('list', only_in_state=['in progress'])
        >>> all(i['status'] == 'in progress' for i in issues)
        True

        Error handling:
        >>> result = issue_manager('invalid')
        >>> result['status']
        'error'
        >>> 'message' in result
        True

        Create issue with YAML content:
        >>> content = '''
        ... title: YAML Test Issue
        ... description: Test Description
        ... priority: 3 - Medium
        ... '''
        >>> result = issue_manager('create', content=content)
        >>> result['status']
        'success'

        Handle closed issues:
        >>> content = '''{"status": "in progress"}'''
        >>> result = issue_manager('update', '999', content=content)
        >>> result['status']
        'error'
    """
    content_obj: dict = {}
    logger.debug("entering...%s",
                 f"{action=}, {issue=}, {only_in_state=}, {content=}, {assignee=}, {caller=})")

    try:
        # Initialize GitHub connection
        g = Github(config.GITHUB_API_KEY)
        repo = g.get_repo(config.GITHUB_REPO)
    except Exception as e:
        logger.error("Failed to connect to GitHub: %s", e)
        return {"status": "error", "message": f"GitHub connection failed: {str(e)}"}

    if isinstance(content, str):
        try:
            content_obj = json.loads(content.replace("\n", "\\n"))
        except Exception as e:
            try:
                yaml_obj = yaml.safe_load(content)
                content_obj = {k.lower(): v for k, v in yaml_obj.items()}
            except Exception as e:
                if action == "create":
                    content_obj = {"title": f"{content:.24s}", "body": content}
                elif action == "update":
                    content_obj = {"body": content}

    match action:
        case 'list':
            try:
                results = []
                issues = repo.get_issues(state='all')
                for gh_issue in issues:
                    labels = [label.name for label in gh_issue.labels]
                    status = "closed" if gh_issue.state == "closed" else \
                        next((l.replace("status:", "") for l in labels if l.startswith("status:")), "new")
                    priority = next((l for l in labels if l.startswith("priority:")), "4 - Low")

                    if only_in_state and status not in only_in_state:
                        continue
                    if assignee and (not gh_issue.assignee or gh_issue.assignee.login != assignee):
                        continue

                    results.append({
                        'issue': str(gh_issue.number),
                        'priority': priority,
                        'status': status,
                        'assignee': gh_issue.assignee.login if gh_issue.assignee else "unassigned",
                        'title': gh_issue.title
                    })
                result = results
            except Exception as e:
                logger.error("List issues failed: %s", e)
                result = {"status": "error", "message": str(e)}

        case "create":
            try:
                title = content_obj.get('title', 'No title provided')
                body = content_obj.get('description', content_obj.get('body', ''))
                labels = []

                # Convert priority to label
                priority = content_obj.get('priority', '4 - Low')
                labels.append(f"priority:{priority}")

                # Convert status to label
                status = content_obj.get('status', 'new')
                labels.append(f"status:{status}")

                # Handle sub-issue creation if parent issue number is provided
                if issue:
                    try:
                        # Validate parent issue exists
                        parent_issue = repo.get_issue(int(issue))
                        # Add parent reference to body
                        parent_ref = f"\n\n_Sub-issue of #{parent_issue.number}_"
                        body = f"{body}{parent_ref}"
                        # Add parent issue reference as label
                        labels.append(f"parent:#{parent_issue.number}")
                    except Exception as e:
                        return {"status": "error", "message": f"Failed to create sub-issue: Parent issue #{issue} not found"}

                # Create issue with or without assignee
                if assignee:
                    new_issue = repo.create_issue(
                        title=title,
                        body=body,
                        assignee=assignee,
                        labels=labels
                    )
                else:
                    new_issue = repo.create_issue(
                        title=title,
                        body=body,
                        labels=labels
                    )

                # If this is a sub-issue, add reference comment to parent issue
                if issue:
                    parent_issue.create_comment(f"Sub-issue created: #{new_issue.number}")

                result = {"issue": str(new_issue.number), "status": "success"}
                if issue:
                    result["parent_issue"] = issue
            except Exception as e:
                logger.error("Create issue failed: %s", e, exc_info=e)
                result = {"status": "error", "message": str(e)}

        case "read":
            try:
                issue_number = int(issue)
                gh_issue = repo.get_issue(issue_number)
                labels = [label.name for label in gh_issue.labels]

                result = {
                    'issue#': str(gh_issue.number),
                    'title': gh_issue.title,
                    'body': gh_issue.body,
                    'latest_status': next((l.replace("status:", "") for l in labels if l.startswith("status:")), "new"),
                    'latest_priority': next((l.replace("priority:", "") for l in labels if l.startswith("priority:")), "4 - Low"),
                    'latest_assignee': gh_issue.assignee.login if gh_issue.assignee else "unassigned",
                    'latest_updated_by': gh_issue.user.login,
                    'created_at': gh_issue.created_at.isoformat(),
                    'updated_at': gh_issue.updated_at.isoformat()
                }
            except Exception as e:
                logger.error("Read issue failed: %s", e)
                result = {"status": "error", "message": str(e)}

        case "update":
            try:
                issue_number = int(issue)
                gh_issue = repo.get_issue(issue_number)

                if gh_issue.state == "closed":
                    return {"issue": issue, "status": "error",
                            "message": "This issue is already closed."}

                # Update labels
                current_labels = [l.name for l in gh_issue.labels]
                new_labels = [l for l in current_labels if not (l.startswith("status:") or l.startswith("priority:"))]

                if 'status' in content_obj:
                    new_labels.append(f"status:{content_obj['status']}")
                if 'priority' in content_obj:
                    new_labels.append(f"priority:{content_obj['priority']}")

                update_kwargs = {}
                if 'title' in content_obj:
                    update_kwargs['title'] = content_obj['title']
                if 'body' in content_obj:
                    update_kwargs['body'] = content_obj['body']

                gh_issue.edit(**update_kwargs, labels=new_labels)
                result = {"issue": issue, "status": "success"}
            except Exception as e:
                logger.error("Update issue failed: %s", e, exc_info=e)
                result = {"status": "error", "message": str(e)}

        case "assign":
            try:
                issue_number = int(issue)
                gh_issue = repo.get_issue(issue_number)

                # Validate assignee first
                try:
                    # Try to get the user to validate they exist
                    if assignee:
                        user = g.get_user(assignee)
                        gh_issue.edit(assignee=user.login)
                    else:
                        gh_issue.edit(assignee=None)  # Clear assignee if None

                    result = {"issue": issue, "status": "success",
                              "message": f"{'Unassigned' if not assignee else f'Assigned to {assignee}'} successfully."}
                except Exception as user_error:
                    result = {"issue": issue, "status": "error",
                              "message": f"Invalid assignee '{assignee}'. User must exist and have access to the repository."}
            except Exception as e:
                logger.error("Assign issue failed: %s", e, exc_info=e)
                result = {"status": "error", "message": str(e)}

        case _:
            result = {"status": "error",
                      "message": f"{action} is not a valid action. Only 'list', 'create', 'read', 'update', 'assign' are valid actions"}

    logger.debug("exiting %s %s - result: %s", action, issue, result)
    return result


if __name__ == "__main__":
    import doctest
    doctest.testmod()
