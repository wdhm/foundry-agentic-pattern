import shlex
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_container_includes_declared_packages() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dockerfile = (ROOT / "src/agents/documentation-agent/Dockerfile").read_text(encoding="utf-8")
    copied = {shlex.split(line)[1] for line in dockerfile.splitlines() if line.startswith("COPY ")}
    allowlist = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    for package in project["tool"]["setuptools"]["package-dir"].values():
        assert package in copied, f"Declared package is not copied into the image: {package}"
        assert f"!{package}/" in allowlist, f"Package directory is excluded from build context: {package}"
        assert f"!{package}/*.py" in allowlist, f"Package modules are excluded from build context: {package}"


def test_container_includes_declared_package_data() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    packages = project["tool"]["setuptools"]["package-dir"]
    allowlist = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    for package, patterns in project["tool"]["setuptools"]["package-data"].items():
        for pattern in patterns:
            path = Path(packages[package]) / pattern
            assert f"!{path.as_posix()}" in allowlist, f"Package data is excluded from build context: {path}"
            for parent in path.parents:
                if parent != Path("."):
                    assert f"!{parent.as_posix()}/" in allowlist, f"Package data directory is excluded: {parent}"
