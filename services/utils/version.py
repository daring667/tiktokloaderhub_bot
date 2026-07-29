import os

_VERSION_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "VERSION",
)


def get_version() -> str:
    """Reads the project version from the VERSION file at the repo root."""
    try:
        with open(_VERSION_PATH, encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "unknown"
