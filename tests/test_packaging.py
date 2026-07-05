import tomllib
from pathlib import Path


def test_package_does_not_install_console_script():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    assert "scripts" not in pyproject["project"]


def test_wheel_includes_package_modules():
    pyproject = tomllib.loads(Path("pyproject.toml").read_text())

    assert pyproject["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"] == [
        "src/beancount_no_amex"
    ]
