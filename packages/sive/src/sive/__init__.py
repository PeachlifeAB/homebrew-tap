from functools import cache


@cache
def _package_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("sive")
    except PackageNotFoundError:  # Source imported without an installed distribution.
        return "0+unknown"


VERSION_ATTRIBUTE = "__version__"


def __getattr__(name: str) -> str:
    if name == VERSION_ATTRIBUTE:
        return _package_version()
    raise AttributeError(f"module 'sive' has no attribute {name!r}")
