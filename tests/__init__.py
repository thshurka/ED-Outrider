"""The unit tests (python3 -m unittest discover tests). This folder goes on sys.path, so a single file also runs as
python3 -m unittest tests.test_highway and the files can say `from support import ...`."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
