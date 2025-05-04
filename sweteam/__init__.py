import doctest
import importlib
import os


def run_doctests(module_file: str = '') -> None:
    """
    Run all the doctests in the module.
    """
    current_path = os.path.dirname(__file__)
    relative_path_to_modeule = os.path.relpath(module_file, current_path)
    module_path = "." + relative_path_to_modeule.replace('/', '.').replace('.py', '')
    module = importlib.import_module(module_path, package=__package__)
    if not module:
        raise ImportError(f"Module {module_path} could not be imported.")
    # Check if the module has a __doc__ attribute
    if hasattr(module, '__doc__'):
        # Run the doctests in the module
        doctest.testmod(module)
    else:
        raise AttributeError(f"Module {module_path} does not have a __doc__ attribute.")
