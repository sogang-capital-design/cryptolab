import importlib
import inspect
import os

from app.strategies.strategy import Strategy

STRATEGY_REGISTRY: dict[str, type[Strategy]] = {}

def _make_hyperparams_key(hyperparams: dict):
    hyperparams_str = {k: str(v) for k, v in hyperparams.items()}
    return tuple(sorted(hyperparams_str.items()))

def _get_strategies_dir() -> str:
    current_dir = os.path.dirname(__file__)
    strategies_dir = os.path.join(current_dir, '..', 'strategies')
    return os.path.abspath(strategies_dir)

def _get_params_dir() -> str:
    current_dir = os.path.dirname(__file__)
    params_dir = os.path.join(current_dir, '..', 'params')
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
                    STRATEGY_REGISTRY[name] = obj

def get_strategy_class(name: str) -> type[Strategy]:
    if not STRATEGY_REGISTRY:
        _discover_strategies()
    if name not in STRATEGY_REGISTRY:
        raise KeyError(f'Unknown strategy name: {name}. Available: {list(STRATEGY_REGISTRY.keys())}')
    return STRATEGY_REGISTRY[name]

def get_params_path(model_type: str, model_name: str, hyperparams: dict, create_path: bool) -> str:
    params_dir = _get_params_dir()
    cur_params_dir = os.path.join(params_dir, model_type, model_name)
    hyperparams_key = _make_hyperparams_key(hyperparams)
    hyperparam_parts = [f"{k}={v}" for k, v in hyperparams_key]
    file_name = model_name + '+' + '+'.join(hyperparam_parts) + '.crlb'
    params_file_dir = os.path.join(cur_params_dir, file_name)

    if not os.path.exists(cur_params_dir) or not os.path.exists(params_file_dir):
        if create_path:
            os.makedirs(cur_params_dir, exist_ok=True)
        else:
            raise FileNotFoundError(f'Parameters file not found: {params_file_dir}')
    return params_file_dir

