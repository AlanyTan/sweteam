import doctest
import unittest
import pkgutil
import importlib
import sys
import os


class TestKeyClasses(unittest.IsolatedAsyncioTestCase):

    async def test_fastapiapp(self):
        from sweteam.bootstrap.fastapi_app import IssueManagementApp
        with IssueManagementApp() as app:
            self.assertIsInstance(app, IssueManagementApp)

    async def test_orchestrator(self):
        from sweteam.bootstrap.orchestrator import OllamaOrchestrator, OrchestratorFactory

        async with OrchestratorFactory.create(agent_config_file="issue_evaluator/src/agents/orchestrator.json") as orchestrator:
            self.assertIsInstance(orchestrator, OllamaOrchestrator)


# Patch DocTestCase to hack the module path issue for VSCode testing grouping
original_init = doctest.DocTestCase.__init__


def patched_init(self, test, optionflags=0, setUp=None, tearDown=None, checker=None):
    # testing hacking the names
    if hasattr(test, 'name'):
        module_heirachy = test.name.split('.')
        # Check if the test name is a module path
        heirachy_level = 1
        module_name = ''
        while (heirachy_level := heirachy_level + 1) < len(module_heirachy):
            try_module_name = ".".join(module_heirachy[:heirachy_level])
            try:
                if sys.modules.get(try_module_name):
                    module_name = try_module_name
            except Exception as e:
                pass

        test_name = test.name.removeprefix(module_name + ".")
        if test.filename.endswith("__init__.py"):
            # If the test is in an __init__.py file, we need to adjust the module name
            test.name = module_name + ".__init__.module_level." + test_name
        elif not "." in test_name:
            test.name = module_name + ".module_level." + test_name

        #test.__unittest_location__ = (test.filename, test.lineno, test.name)
        test.line = test.lineno
    # Call original init
    original_init(self, test, optionflags, setUp, tearDown, checker)


# Apply the patch
doctest.DocTestCase.__init__ = patched_init

# original_id = doctest.DocTestCase.id


# def patched_id(self, *args, **kwargs):
#     orig_id = original_id(self, *args, **kwargs)
#     return f"{orig_id}.className.(Line: {self._dt_test.lineno})"


# doctest.DocTestCase.id = patched_id


def load_tests(loader, tests, ignore) -> unittest.TestSuite:
    """
    standard hook for unittest to load tests
    Load all doctests from the current package and its subpackages.
    """

    current_dir = os.path.dirname(__file__)
    for _, module_name, _ in pkgutil.walk_packages([current_dir]):
        #package_name = module_name.split(".")[0]
        # Fix duplicated levels in module names
        # if module_name.startswith(package_name + "."):
        #     module_name = module_name[len(package_name) + 1:]
        module = importlib.import_module(module_name)
        module.__name__ = module_name  # Ensure the module name is correctly set to avoid duplication

        tests.addTests(doctest.DocTestSuite(module))
    return tests


if __name__ == '__main__':
    unittest.main()
