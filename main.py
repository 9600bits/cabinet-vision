"""机柜视界 —— 启动入口。

用法：
    python main.py                      使用默认数据库
    python main.py --db D:/data/my.db   指定数据库文件
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def main() -> int:
    parser = argparse.ArgumentParser(description="机柜视界 —— 机柜台账与容量规划")
    parser.add_argument("--db", help="数据库文件路径，默认放在用户目录下", default=None)
    args = parser.parse_args()

    from frontend import run

    return run(args.db)


if __name__ == "__main__":
    raise SystemExit(main())
