import os

workers = min(20, (os.cpu_count() or 2) * 4)
