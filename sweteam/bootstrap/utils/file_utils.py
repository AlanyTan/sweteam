"""File related utils for agents"""
import os
import re
import yaml
from ..config import config
from .log import logger


def dir_tree(path_: str, return_yaml: bool = False) -> str:
    """Print the directory tree

    Args:
        path - to list
        return_yaml - if True, retrun YAML format

    >>> import yaml
    >>> dir_obj = yaml.load(dir_tree("issue_board", True))
    >>> dir_obj['issue_board']['type']
    'directory'

    """
    def extract_desc(file_path: str) -> str:
        """Extract the description from the file
        """
        READLINES_HINT = 128
        EXTRACT_RULES = [{"type": "README.md", "filename_pattern": r"README.md$", "comment_prefix": ""},
                         {"type": "Python", "filename_pattern": r".*\.py$",
                             "comment_prefix": "\"\"\""},
                         {"type": "Python", "filename_pattern": r".*\.py$",
                             "comment_prefix": "#"},
                         {"type": "Dockerfile", "filename_pattern": r"Dockerfile$",
                          "comment_prefix": "#"},
                         {"type": "Docker-compose",
                          "filename_pattern": r"docker-compose.ya?ml$", "comment_prefix": ""},
                         {"type": "TOML",
                          "filename_pattern": r".*to?ml$", "comment_prefix": "description"},
                         {"type": "Javascript",
                          "filename_pattern": r".*\.(js|ts)$", "comment_prefix": "/**"},
                         ]
        comment = ""
        file_name = os.path.basename(file_path)
        for rule in EXTRACT_RULES:
            rule_re = re.compile(rule["filename_pattern"])
            if os.path.isfile(file_path) and rule_re.match(file_name):
                with open(file_path, "r") as f:
                    lines = f.readlines(READLINES_HINT)
                comment_on_next_line = False
                for line in lines:
                    if comment_on_next_line or line.strip().startswith(rule["comment_prefix"]):
                        comment = line.strip().removeprefix(
                            rule["comment_prefix"]).removesuffix("\n").strip(
                        ).removesuffix(rule["comment_prefix"][::-1]).strip()
                        if comment:
                            break
                        else:
                            comment_on_next_line = True

            if comment:
                break
        return comment

    if not os.path.exists(path_):
        return f"{path_} does not exist."
    dir_desc_file_patterns = [r'README.md', r'__init__.py',
                              r'index.js', r'Dockerfile', r'docker-compose.ya?ml']
    exclude_patterns = [r'.*/node_modules/.*', r'.*/.venv/.*',
                        r'.*/.pytest_cache/.*', r'.*/__pycache__/.*', r'.*/issue_board/.*']
    dir_list = []
    tree = {}
    d = tree
    for (root, dirs, files) in os.walk(path_):
        if any(re.match(pattern, (root + '/')) for pattern in exclude_patterns):
            continue
        for dirpart in root.split('/'):
            if not dirpart:
                dirpart = '/'
            d = d.setdefault(dirpart, {'type': "directory"})
            for ddesc_pattern in dir_desc_file_patterns:
                descfile = [fl for fl in files if re.match(ddesc_pattern, fl)]
                if descfile:
                    d.setdefault('description', f"Directory for "
                                 f"{extract_desc(os.path.join(root, descfile[0]))}")
                    break
            else:
                d.setdefault('description', f"Directory of "
                             f"{len(dirs)} directories and {len(files)} files.")
            d = d.setdefault('contents', {})

        exclude_dirs = [dir_.removeprefix(r'.*/').removesuffix(r'/.*')
                        for dir_ in exclude_patterns if dir_.endswith("/.*")]
        for sub_dir in dirs:
            if sub_dir in exclude_dirs:
                dirs.remove(sub_dir)
                continue
            d.setdefault(sub_dir, {'type': "directory"})
            dir_list.append(
                (f"{os.path.join(root, sub_dir)}/", f"Directory for {sub_dir}"))

        exclude_files = [file_
                         for file_ in exclude_patterns if not file_.endswith("/.*")]
        for fl in files:
            if any((os.path.join(root, fl).endswith(exclude_file) for exclude_file in exclude_files)):
                continue
            cmt = extract_desc(os.path.join(root, fl))
            d.setdefault(fl, {'type': "file", 'description': cmt,
                         "size": os.path.getsize(os.path.join(root, fl))})
            dir_list.append((os.path.join(root, fl), cmt))
        d = tree
    if return_yaml:
        return yaml.dump(tree, sort_keys=False)
    else:
        dir_list.sort(key=lambda d: next(iter(d)))
        return "\n".join(["{}, {}".format(*d) for d in dir_list])


def dir_structure(path: str | dict = {}, action: str = 'read', *, actual_only: bool = True, output_format: str = "YAML") -> str:
    """update or return project directory structure

    Args:
        action - one of read|delete|update

    Returns:
        a YAML string representing the dir structure including plan .vs. actual 
    """
    def walk_obj(obj, parent_key=''):
        if isinstance(obj, dict):
            for key, value in obj.items():
                path = f"{parent_key}/{key}" if parent_key else key
                if isinstance(value, dict):
                    yield from walk_obj(value, path)
                else:
                    yield (path, value)
        else:
            yield (parent_key, obj)

    def get_grandchild(obj: dict, key='') -> dict:
        o = obj
        for k in key.split("/"):
            o = o.setdefault(k, {})
        return o

    match action:
        case "read":
            # return dir structure -
            if actual_only:
                return dir_tree(path or config.PROJECT_NAME, output_format.lower() == "yaml")

            with open(config.DIR_STRUCTURE_YAML, "r", encoding="utf-8") as f:
                dir_structure_plan = yaml.safe_load(f.read())
            current_dir_structure = yaml.safe_load(
                dir_tree(config.PROJECT_NAME, True))
            combined_structure = {}
            for path_, item in walk_obj(current_dir_structure):
                path_head, _, path_tail = path_.rpartition("/")
                item_plan_value = get_grandchild(
                    dir_structure_plan, path_head.replace('/contents', ''))
                match path_tail:
                    case "description":
                        item_plan_value = (item if isinstance(item_plan_value, dict)
                                           else item_plan_value) if item_plan_value else 'not planned'
                    case "type":
                        item_plan_value = ('directory' if isinstance(item_plan_value, dict)
                                           else "file") if item_plan_value else 'not planned'
                    case "size":
                        # size has no plan values, so should always equal to actual value
                        item_plan_value = item
                if item == item_plan_value:
                    get_grandchild(combined_structure, path_head)[
                        path_tail] = item
                else:
                    get_grandchild(combined_structure, path_head)[path_tail] = {
                        'planned': item_plan_value, 'actual': item}

            for path_, item in walk_obj(dir_structure_plan):
                path_head, _, path_tail = path_.rpartition("/")
                path_w_contents = path_.replace("/", "/contents/")
                if get_grandchild(combined_structure, path_w_contents):
                    # if the path_ already exist in the combined result
                    pass
                else:
                    get_grandchild(combined_structure, path_w_contents)[
                        'planned'] = item
                    get_grandchild(combined_structure, path_w_contents)[
                        'actual'] = 'not implemented'
            return yaml.dump(combined_structure, sort_keys=False)

        case "update":
            # update plan for the dir_structure
            with open(config.DIR_STRUCTURE_YAML, "r", encoding="utf-8") as f:
                dir_structure_plan = yaml.safe_load(f.read())
            if config.PROJECT_NAME in path:
                actual_path = path
            else:
                actual_path = {config.PROJECT_NAME: path}

            for path_, item in walk_obj(actual_path):
                path_head, _, path_tail = path_.rpartition("/")
                match path_tail:
                    case "description":
                        p_head, _, p_tail = path_.removesuffix(
                            "/description").rpartition("/")
                        item_parent = get_grandchild(
                            dir_structure_plan, p_head.replace('/contents', ''))
                        if isinstance(item_parent.setdefault(p_tail, {}), dict):
                            # p_head point to a dir
                            item_parent[p_tail]["README.md"] = re.sub(
                                r'(?i)^directory (of|for)\s*', '', item)
                        else:
                            # p_head point to a file
                            item_parent[p_tail] = item
                    case "type":
                        p_head, _, p_tail = path_.removesuffix(
                            "/type").rpartition("/")
                        item_parent = get_grandchild(
                            dir_structure_plan, p_head.replace('/contents', ''))
                        if item == 'directory' or item == 'dir':
                            # path_head point to a dir
                            item_parent.setdefault("README.md", '')
                        else:
                            item_parent.setdefault("p_tail", '')
                    case _:
                        logger.warning(f"While updating {config.DIR_STRUCTURE_YAML} "
                                       f"run into unknown key {path_}.{item}, ignoring")
            with open(config.DIR_STRUCTURE_YAML, "w", encoding='utf-8') as f:
                f.write(yaml.dump(dir_structure_plan))

        case "delete" | "del":
            pass
        case _:
            logger.warning(f"{action} is not a recognized action, please use only "
                           "read|update")
            raise ValueError(f"{action} is not a recognized action, please use only "
                             "read|update")

    return ""


def dir_contains(directory, files: bool = True, dirs: bool = False, pattern: str = '.*', recursive: bool = False):
    """Check if a directory contains files
    >>> import tempfile, os
    >>> # Test with an empty directory: should return False.
    >>> with tempfile.TemporaryDirectory() as tmp:
    ...     dir_contains(tmp)
    False

    >>> # Test with a file in the directory: should return True.
    >>> with tempfile.TemporaryDirectory() as tmp:
    ...     open(os.path.join(tmp, "file.txt"), "w").close()
    ...     dir_contains(tmp)
    True

    >>> # Test with a subdirectory when checking for directories: should return True.
    >>> with tempfile.TemporaryDirectory() as tmp:
    ...     os.mkdir(os.path.join(tmp, "subdir"))
    ...     dir_contains(tmp, files=False, dirs=True)
    True

    >>> # Test with a nested file not directly in the target directory: without recursion should return False.
    >>> with tempfile.TemporaryDirectory() as tmp:
    ...     os.mkdir(os.path.join(tmp, "subdir"))
    ...     open(os.path.join(tmp, "subdir", "file.txt"), "w").close()
    ...     dir_contains(tmp)
    False

    >>> # With recursion enabled, the nested file should be detected.
    >>> with tempfile.TemporaryDirectory() as tmp:
    ...     os.mkdir(os.path.join(tmp, "subdir"))
    ...     open(os.path.join(tmp, "subdir", "file.txt"), "w").close()
    ...     dir_contains(tmp, recursive=True)
    True
    """
    if not os.path.exists(directory):
        return False
    regex = re.compile(pattern)
    if recursive:
        for _, dirs_, files_ in os.walk(directory):
            if dirs and dirs_ and any(regex.match(s) for s in dirs_):
                return True
            if files and files_ and any(regex.match(s) for s in files_):
                return True
    else:
        for fd in os.listdir(directory):
            if (files and any(regex.match(s) for s in fd)
                    and os.path.isfile(os.path.join(directory, fd))):
                return True
            if (dirs and any(regex.match(s) for s in fd)
                    and os.path.isdir(os.path.join(directory, fd))):
                return True

    return False


if __name__ == "__main__":
    import doctest
    doctest.testmod()
