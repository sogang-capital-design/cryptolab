import importlib
import inspect
import os

from app.utils.data_utils import _get_data_path
from app.strategies.strategy import Strategy

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {}

def _get_strategies_dir() -> str:
    current_dir = os.path.dirname(__file__)
    strategies_dir = os.path.join(current_dir, '..', 'strategies')
    return os.path.abspath(strategies_dir)

def _get_params_dir() -> str:
    params_dir = _get_data_path()
    params_dir = os.path.join(params_dir, 'params')
    return os.path.abspath(params_dir)

def _discover_strategies() -> None:
    strategies_dir = _get_strategies_dir()
    for root, _, files in os.walk(strategies_dir):
        for file in files:
            if file.startswith("_") or not file.endswith(".py"):
                continue
            file_path = os.path.join(root, file)
            module_name = os.path.splitext(file)[0]
            spec = importlib.util.spec_from_file_location(module_name, file_path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            for name, obj in inspect.getmembers(module, inspect.isclass):
                if issubclass(obj, Strategy) and obj is not Strategy:
                    name = name.replace('Strategy', '')
                    STRATEGY_REGISTRY[name] = obj

def get_strategy_class(class_name: str) -> type[Strategy]:
    if not STRATEGY_REGISTRY:
        _discover_strategies()
    if class_name not in STRATEGY_REGISTRY:
        raise KeyError(f'Unknown strategy name: {class_name}. Available: {list(STRATEGY_REGISTRY.keys())}')
    return STRATEGY_REGISTRY[class_name]

def get_param_path(model_name: str, param_name: str) -> str:
    params_dir = _get_params_dir()
    file_name = model_name + '+' + param_name + '.crlb'
    params_file_dir = os.path.join(params_dir, file_name)
    return params_file_dir

def get_all_param_names() -> dict[str, list[str]]:
    params_dir = _get_params_dir()
    params_dict: dict[str, list[str]] = {}
    for file_name in os.listdir(params_dir):
        if not file_name.endswith('.crlb'):
            continue
        model_class, model_name_with_ext = file_name.split('+')
        model_name = model_name_with_ext.replace('.crlb', '')
        if model_class not in params_dict:
            params_dict[model_class] = []
        params_dict[model_class].append(model_name)
    return params_dict
