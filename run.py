"""動画自動投稿ツールの起動用ファイル。普段は .bat ファイルから呼ばれます。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from autopost.main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
