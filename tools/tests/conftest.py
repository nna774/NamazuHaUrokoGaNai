import os
import sys

# tools/ をインポートパスに追加（jismo, gen_synthetic を解決するため）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
