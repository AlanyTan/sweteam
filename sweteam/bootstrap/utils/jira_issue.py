"""
This module contains utility functions for working with Jira issues through REST API.
"""

import os
import yaml
import json
from enum import Enum
from datetime import datetime
import aiohttp
import asyncio
from typing import Optional, Dict, List, Any

from ..utils.decorators import timed_execution
from .log import logger
from ..config import config


def get_dot_notation_value(dict_obj, dot_path, default=None):
    """
    Access nested dictionary values using dot notation

    Args:
        dict_obj (dict): The dictionary to search
        dot_path (str): Path to value using dot notation (e.g. "status.name")
        default (any): value to return if the key is not found, None if omitted
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


class JIRABase:
    """Base JIRA class that handles REST API communication"""

    def __init__(self, namespace: str = "", field_mapping: dict = {}, default_jql: str = ""):
        self.logger = logger
        self.namespace = namespace or f"{config.PROJECT_NAME}"
        self.auth = aiohttp.BasicAuth(config.JIRA_USERNAME, config.JIRA_API_KEY)
        self.base_url = config.JIRA_BASE_URL
        self.issues_to_reconcile = []
        self.default_jql = default_jql or 'created >= startOfDay("-3d") ORDER BY created DESC'
        self.field_mapping = field_mapping or {
            "id": "id",
            "key": "key",
            "issue_type": "issuetype.name",
            "status": "status.name",
            "title": "summary",
            "priority": "priority.name",
            "created_at": "created",
            "updated_at": "updated",
            "resolved_at": "resolutiondate",
            "created_by": "reporter.displayName",
            "reported_by": "reporter.displayName",
            "assignee": "assignee.displayName",
        }
        self.session = None

    async def _get_session(self):
        if self.session is None:
            self.session = aiohttp.ClientSession(auth=self.auth, timeout=aiohttp.ClientTimeout(total=120))
        return self.session

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def __aenter__(self):
        await self._get_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    def get_issue_metadata(self, issue: dict) -> dict:
        key_prefix = f"{self.namespace}"
        metadata = {}
        for k, v in self.field_mapping.items():
            metadata[key_prefix + k] = get_dot_notation_value(issue, v, 'n/a')
        return metadata

    async def list_issues(self, jql: str = "", force: bool = False) -> List[Dict[str, Any]]:
        """Return list of issues by JQL query"""
        if not jql:
            jql = self.default_jql

        if force:
            reconcileIssues = self.issues_to_reconcile
        else:
            reconcileIssues = []

        returned_issues = []
        session = await self._get_session()

        url = f"{self.base_url}/search/jql"
        headers = {"Accept": "application/json"}

        maxResults = 500
        fields = ",".join([f.split(".")[0] for f in self.field_mapping.values()])  # "*navigable"
        nextPageToken = "Not Yet Known"

        while nextPageToken:
            query = {
                'jql': jql,
                # 'id,key,updated,status,summary,priority,created,reporter',
                'fields': fields,
                'maxResults': maxResults,
                'reconcileIssues': reconcileIssues
            }
            if nextPageToken != "Not Yet Known":
                query["nextPageToken"] = nextPageToken

            async with session.get(url, headers=headers, params=query) as response:
                try:
                    result = await response.json()
                except Exception as e:
                    self.logger.warning("Jira jql response run into %s converting to JSON: %s", e, await response.text())
                    result = {}

                issues = result.get('issues', [])
                for issue in issues:
                    for k, v in issue.get("fields", {}).items():
                        issue[k] = v
                    del issue['fields']
                returned_issues.extend(issues)
                if (nextPageToken := result.get("nextPageToken", None)) is None:
                    break

        return returned_issues

    async def get_issue(self, issue_key: str) -> Dict[str, Any]:
        """Get a single issue by key"""
        session = await self._get_session()
        url = f"{self.base_url}/issue/{issue_key}"
        headers = {"Accept": "application/json"}

        query = {'fields': "all"}
        async with session.get(url, headers=headers, params=query) as response:
            if response.status == 404:
                raise ValueError(f"Issue {issue_key} not found")
            result = await response.json()

            # Flatten fields
            for k, v in result.get("fields", {}).items():
                result[k] = v
            del result['fields']

            return result

    async def create_issue(self, fields: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new issue"""
        session = await self._get_session()
        url = f"{self.base_url}/issue"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        async with session.post(url, headers=headers, json={"fields": fields}) as response:
            if response.status >= 400:
                error_text = await response.text()
                raise ValueError(f"Failed to create issue: {error_text}")
            return await response.json()

    async def update_issue(self, issue_key: str, fields: Dict[str, Any]) -> None:
        """Update an existing issue"""
        session = await self._get_session()
        url = f"{self.base_url}/issue/{issue_key}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        async with session.put(url, headers=headers, json={"fields": fields}) as response:
            if response.status >= 400:
                error_text = await response.text()
                raise ValueError(f"Failed to update issue: {error_text}")

    async def assign_issue(self, issue_key: str, assignee: Optional[str]) -> None:
        """Assign an issue to a user"""
        session = await self._get_session()
        url = f"{self.base_url}/issue/{issue_key}/assignee"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json"
        }
        data = {"name": assignee} if assignee else {"name": None}

        async with session.put(url, headers=headers, json=data) as response:
            if response.status >= 400:
                error_text = await response.text()
                raise ValueError(f"Failed to assign issue: {error_text}")

    async def transition_issue(self, issue_key: str, status: str) -> None:
        """Transition an issue to a new status"""
        session = await self._get_session()

        # First get available transitions
        url = f"{self.base_url}/issue/{issue_key}/transitions"
        headers = {"Accept": "application/json"}

        async with session.get(url, headers=headers) as response:
            transitions = await response.json()

        # Find matching transition
        transition_id = None
        for t in transitions.get('transitions', []):
            if t['to']['name'].lower() == status.lower():
                transition_id = t['id']
                break

        if not transition_id:
            raise ValueError(f"No transition found to status: {status}")

        # Perform transition
        headers["Content-Type"] = "application/json"
        data = {"transition": {"id": transition_id}}

        async with session.post(url, headers=headers, json=data) as response:
            if response.status >= 400:
                error_text = await response.text()
                raise ValueError(f"Failed to transition issue: {error_text}")


async def issue_manager(action: str, issue: str = '', only_in_state: list = [],
                        content: str | None = None, assignee: str | None = None, caller: str = "unknown") -> dict | list:
    """Manage Jira issues: list, create, read, update, assign

    Args:
        action (str): The action to perform ('list', 'create', 'read', 'update', 'assign')
        issue (str, optional): Issue key (e.g., 'PROJ-123'). Defaults to ''.
        only_in_state (list, optional): Filter issues by state. Defaults to [].
        content (str | None, optional): Issue content in JSON/YAML format. Defaults to None.
        assignee (str | None, optional): Jira username to assign. Defaults to None.
        caller (str, optional): Name of the calling agent. Defaults to "unknown".

    Returns:
        dict | list: Operation result or list of issues
    """
    content_obj: dict = {}
    logger.debug("entering...%s",
                 f"{action=}, {issue=}, {only_in_state=}, {content=}, {assignee=}, {caller=})")

    jira = JIRABase()
    try:
        await jira._get_session()

        if isinstance(content, str):
            try:
                content_obj = json.loads(content.replace("\n", "\\n"))
            except Exception:
                try:
                    yaml_obj = yaml.safe_load(content)
                    content_obj = {k.lower(): v for k, v in yaml_obj.items()}
                except Exception:
                    if action == "create":
                        content_obj = {"summary": f"{content:.24s}", "description": content}
                    elif action == "update":
                        content_obj = {"description": content}

        match action:
            case 'list':
                try:
                    jql = 'created >= startOfDay("-3d")'
                    if only_in_state:
                        states = "','".join(only_in_state)
                        jql += f" AND status IN ('{states}')"
                    if assignee:
                        jql += f" AND assignee = '{assignee}'"

                    issues = await jira.list_issues(jql)
                    results = []
                    for jira_issue in issues:
                        results.append({
                            'issue': jira_issue['key'],
                            'priority': get_dot_notation_value(jira_issue, 'priority.name', 'n/a'),
                            'status': get_dot_notation_value(jira_issue, 'status.name', 'n/a'),
                            'assignee': get_dot_notation_value(jira_issue, 'assignee.displayName', 'unassigned'),
                            'title': jira_issue.get('summary', 'No title')
                        })
                    result = results
                except Exception as e:
                    logger.error("List issues failed: %s", e)
                    result = {"status": "error", "message": str(e)}

            case "create":
                try:
                    issue_dict = {
                        'project': {'key': config.PROJECT_NAME},
                        'summary': content_obj.get('title', content_obj.get('summary', 'No title provided')),
                        'description': content_obj.get('description', content_obj.get('body', '')),
                        'issuetype': {'name': "incident"},
                    }

                    if assignee:
                        issue_dict['assignee'] = {'name': assignee}

                    if 'priority' in content_obj:
                        issue_dict['priority'] = {'name': content_obj['priority']}

                    new_issue = await jira.create_issue(issue_dict)
                    result = {"issue": new_issue['key'], "status": "success"}
                except Exception as e:
                    logger.error("Create issue failed: %s", e)
                    result = {"status": "error", "message": str(e)}

            case "read":
                try:
                    jira_issue = await jira.get_issue(issue)
                    result = {
                        'issue#': jira_issue['key'],
                        'title': jira_issue.get('summary'),
                        'body': jira_issue.get('description'),
                        'latest_status': get_dot_notation_value(jira_issue, 'status.name', 'n/a'),
                        'latest_priority': get_dot_notation_value(jira_issue, 'priority.name', 'n/a'),
                        'latest_assignee': get_dot_notation_value(jira_issue, 'assignee.displayName', 'unassigned'),
                        'latest_updated_by': get_dot_notation_value(jira_issue, 'reporter.displayName', 'unknown'),
                        'created_at': jira_issue.get('created'),
                        'updated_at': jira_issue.get('updated')
                    }
                except Exception as e:
                    logger.error("Read issue failed: %s", e)
                    result = {"status": "error", "message": str(e)}

            case "update":
                try:
                    update_fields = {}

                    if 'status' in content_obj:
                        await jira.transition_issue(issue, content_obj['status'])

                    if 'priority' in content_obj:
                        update_fields['priority'] = {'name': content_obj['priority']}
                    if 'title' in content_obj:
                        update_fields['summary'] = content_obj['title']
                    if 'body' in content_obj:
                        update_fields['description'] = content_obj['body']

                    if update_fields:
                        await jira.update_issue(issue, update_fields)

                    result = {"issue": issue, "status": "success"}
                except Exception as e:
                    logger.error("Update issue failed: %s", e)
                    result = {"status": "error", "message": str(e)}

            case "assign":
                try:
                    await jira.assign_issue(issue, assignee)
                    result = {"issue": issue, "status": "success",
                              "message": f"{'Unassigned' if not assignee else f'Assigned to {assignee}'} successfully."}
                except Exception as e:
                    logger.error("Assign issue failed: %s", e)
                    result = {"status": "error", "message": str(e)}

            case _:
                result = {"status": "error",
                          "message": f"{action} is not a valid action. Only 'list', 'create', 'read', 'update', 'assign' are valid actions"}

    except Exception as e:
        return {"status": "error", "message": f"Jira connection failed: {str(e)}"}
    finally:
        await jira.close()

    logger.debug("exiting %s %s - result: %s", action, issue, result)
    return result
