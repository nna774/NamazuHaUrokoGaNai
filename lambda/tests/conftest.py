import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LAMBDA_ROOT = os.path.dirname(HERE)
TOOLS = os.path.normpath(os.path.join(LAMBDA_ROOT, "..", "tools"))

# common/, jismo/ を解決
sys.path.insert(0, LAMBDA_ROOT)
sys.path.insert(0, TOOLS)
