"""Vercel serverless entry point. All logic lives in api/_core."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "_core"))
from http_handler import Handler  # noqa: E402


class handler(Handler):
    pass
