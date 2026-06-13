import os
import stat
import tempfile
from pathlib import Path


def _lexical_absolute(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path)))


def _trusted_boundary(target: Path) -> Path:
    candidates = (
        _lexical_absolute(Path.cwd()),
        _lexical_absolute(Path(tempfile.gettempdir())),
    )
    applicable = []
    for candidate in candidates:
        try:
            target.relative_to(candidate)
        except ValueError:
            continue
        applicable.append(candidate)
    if applicable:
        return max(applicable, key=lambda path: len(path.parts))
    return Path(target.anchor)


def validate_directory_path(path: Path, *, label: str) -> bool:
    """Validate path components without resolving symlinks.

    Returns True when the final directory exists and False when creation is safe.
    """
    target = _lexical_absolute(Path(path))
    boundary = _trusted_boundary(target)
    components = target.relative_to(boundary).parts
    current = boundary

    for index, component in enumerate(components):
        current /= component
        final_component = index == len(components) - 1
        try:
            mode = current.stat(follow_symlinks=False).st_mode
        except FileNotFoundError:
            return False
        except NotADirectoryError as error:
            raise ValueError(f"{label} must be below a real directory") from error

        if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
            requirement = (
                "a real directory"
                if final_component
                else "below a real directory"
            )
            raise ValueError(f"{label} must be {requirement}")

    return True
