import importlib

for name in ["sklearn", "xgboost", "lightgbm", "h2o", "flaml", "autogluon", "pandas", "numpy", "joblib"]:
    try:
        mod = importlib.import_module(name)
        version = getattr(mod, "__version__", getattr(mod, "VERSION", "?"))
        print(f"{name}: {version}")
    except ImportError:
        print(f"{name}: NOT INSTALLED")
