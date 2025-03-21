"""Standard __main__.py file for debuging of a package, it import a module
 and launch a function or a class method according to commandline arguments. 

Args: 
    1st: module to load
    2nd: function or class.method to execute
    the rest: will be passed to the function or method as arguments

Return: 
    whatever the function/method will return, printed to the stdout
"""
import sys
import importlib


if __name__ == "__main__":
    alt_args = ["doctest", "testmod"]
    args = sys.argv[1:] or alt_args
    if args:
        module_name = args[0]
        module = importlib.import_module(module_name)
        if args[1:]:
            func_path = args[1].split('.')
            current = module
            for index, part in enumerate(func_path):
                if not hasattr(current, part):
                    raise AttributeError(f"Attribute '{part}' not found in {current}")
                attr = getattr(current, part)
                # If attr is a class and we're not at the final part, instantiate it
                if isinstance(attr, type) and index < len(func_path) - 1:
                    current = attr()
                else:
                    current = attr
            if callable(current):
                print(current(*args[2:]))
            else:
                raise AttributeError(f"{args[1]} is not callable")
