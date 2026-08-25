import sys
import os

# Add app directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'app'))

import uvicorn

if __name__ == "__main__":
     uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True, app_dir=os.path.dirname(__file__), access_log=False)


# python -m uvicorn app.main:app --port 8000
# запуск проекта через терминал

"""
сериал, нашикомедии, универноваяобщага, юмор, смешновидео, фильмы, приколы
"""


