import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from omnihand_actions import create_actions, load_hand_config

import select
import tty
import termios
import time


def build_test_hand():
    cfg = load_hand_config(ROOT / "config" / "sort_trash_pipeline.example.yaml")
    # Test-only grip tuning:
    # - make the thumb side curl more aggressively
    # - keep the distal joints of the four fingers slightly straighter
    cfg["close_angles_rad"] = [
        0.18,
        -1.35,
        0.75,
        0.00,
        0.75,
        0.75,
        0.00,
        0.75,
        0.00,
        0.75,
    ]
    return create_actions(cfg)


hand = build_test_hand()

def main():
    # 保存原始终端设置
    old_settings = termios.tcgetattr(sys.stdin)
    tty.setcbreak(sys.stdin.fileno())  # 设置为 cbreak 模式，输入立即生效

    output_close = True   # True 输出 "Yes", False 输出 "No"

    try:
        while True:
            # 检查是否有输入可用（超时 0.1 秒）
            if select.select([sys.stdin], [], [], 0.1)[0]:
                key = sys.stdin.read(1)  # 读取一个字符
                if key == 'o':
                    output_close = False
                elif key == 'c':
                    output_close = True
                # 忽略其他按键

            # 输出当前状态
            if output_close:
                hand.close_hand()
            else:
                hand.open_hand()
            time.sleep(0.1)  # 控制输出频率

    except KeyboardInterrupt:
        print("\n程序已退出")
    finally:
        # 恢复终端设置
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)

if __name__ == "__main__":
    main()
