import os
import sys

cur_path = str(os.getcwd())
src_path = os.path.join(cur_path, "src")

if os.path.exists(src_path):
    sys.path.insert(0, src_path)
    
from uzcode.cli import main

raise SystemExit(main())
