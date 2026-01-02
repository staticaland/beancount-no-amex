"""Sybil configuration for testing documentation examples."""

from sybil import Sybil
from sybil.parsers.markdown import PythonCodeBlockParser

# Configure Sybil to find and test Python code blocks in markdown files
# Only test examples.md (README.md has illustrative examples, not runnable doctests)
pytest_collect_file = Sybil(
    parsers=[PythonCodeBlockParser()],
    patterns=["examples.md"],
).pytest()
