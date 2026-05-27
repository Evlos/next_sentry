#!/usr/bin/env python3
"""
Mini Sentry 异常上报测试脚本
使用方式：
    DSN=http://<key>@localhost:5000/api/<id> python test_report.py
    DSN=http://<key>@localhost:5000/api/<id> python test_report.py --case 3
"""

import os
import sys
import time
import argparse
import sentry_sdk
from sentry_sdk import capture_exception, capture_message, push_scope

# ── 读取 DSN ──────────────────────────────────────────────
DSN = os.environ.get("DSN")
if not DSN:
    print("❌  缺少环境变量 DSN")
    print("    用法: DSN=http://<key>@localhost:5000/api/<id> python test_report.py")
    sys.exit(1)

# ── 初始化 SDK ────────────────────────────────────────────
sentry_sdk.init(
    dsn=DSN,
    traces_sample_rate=1.0,
    environment="testing",
    release="mini-sentry-test@1.0.0",
    # 关闭默认去重，保证每次测试都能上报
    before_send=lambda event, hint: event,
)

print(f"✅  Sentry SDK 初始化完成")
print(f"    DSN: {DSN}\n")


# ══════════════════════════════════════════════════════════
# 测试用例
# ══════════════════════════════════════════════════════════

def case_zero_division():
    """除零异常 —— 最基础的 Python 异常"""
    print("▶  [1] ZeroDivisionError ...")
    try:
        result = 1 / 0
    except ZeroDivisionError as e:
        capture_exception(e)
        print("   ✓  已上报\n")


def case_key_error():
    """字典 KeyError —— 带 extra 附加信息"""
    print("▶  [2] KeyError + extra ...")
    try:
        data = {"user": "alice"}
        _ = data["token"]
    except KeyError as e:
        with push_scope() as scope:
            scope.set_extra("data_keys", list(data.keys()))
            scope.set_extra("accessed_key", "token")
            scope.set_tag("component", "auth")
            capture_exception(e)
        print("   ✓  已上报\n")


def case_type_error():
    """TypeError —— 带用户信息"""
    print("▶  [3] TypeError + user context ...")
    try:
        result = "version_" + 42          # type: ignore
    except TypeError as e:
        with push_scope() as scope:
            scope.set_user({"id": "u_001", "username": "bob", "email": "bob@example.com"})
            scope.set_tag("component", "serializer")
            capture_exception(e)
        print("   ✓  已上报\n")


def case_deep_stacktrace():
    """多层调用 —— 验证 stacktrace 深度"""
    print("▶  [4] Deep stacktrace (5 levels) ...")
    def level_5(): raise RuntimeError("Something went wrong at the bottom")
    def level_4(): level_5()
    def level_3(): level_4()
    def level_2(): level_3()
    def level_1(): level_2()

    try:
        level_1()
    except RuntimeError as e:
        with push_scope() as scope:
            scope.set_tag("depth", "5")
        capture_exception(e)
        print("   ✓  已上报\n")


def case_capture_message():
    """capture_message —— 非异常的 warning/info 消息"""
    print("▶  [5] capture_message (warning) ...")
    with push_scope() as scope:
        scope.set_tag("source", "scheduler")
        scope.set_extra("job_id", "cron_cleanup_20260527")
        sentry_sdk.capture_message("Scheduled job took longer than expected", level="warning")
    print("   ✓  已上报\n")

    print("▶  [6] capture_message (info) ...")
    sentry_sdk.capture_message("Application started successfully", level="info")
    print("   ✓  已上报\n")


def case_attribute_error():
    """AttributeError —— 带 tags 和 release 信息"""
    print("▶  [7] AttributeError + tags ...")
    try:
        obj = None
        obj.do_something()              # type: ignore
    except AttributeError as e:
        with push_scope() as scope:
            scope.set_tag("env", "testing")
            scope.set_tag("module", "core.processor")
            scope.level = "error"
            capture_exception(e)
        print("   ✓  已上报\n")


def case_import_error():
    """ImportError —— 模拟依赖缺失"""
    print("▶  [8] ImportError ...")
    try:
        import non_existent_package_xyz  # type: ignore  # noqa
    except ImportError as e:
        capture_exception(e)
        print("   ✓  已上报\n")


def case_chained_exception():
    """链式异常 —— 验证 __cause__ 上报"""
    print("▶  [9] Chained exception ...")
    try:
        try:
            int("not_a_number")
        except ValueError as original:
            raise RuntimeError("Failed to parse config") from original
    except RuntimeError as e:
        capture_exception(e)
        print("   ✓  已上报\n")


def case_unhandled(simulate: bool = False):
    """未捕获异常 —— sentry_sdk 会自动捕获（仅演示，不在批量运行中执行）"""
    if not simulate:
        print("▶  [10] Unhandled exception（跳过，加 --case 10 单独运行）\n")
        return
    print("▶  [10] 模拟未捕获异常，进程将退出 ...")
    time.sleep(0.5)
    raise SystemError("Unhandled! Sentry auto-captures this before exit.")


# ══════════════════════════════════════════════════════════
# 用例注册表
# ══════════════════════════════════════════════════════════

CASES = {
    1:  case_zero_division,
    2:  case_key_error,
    3:  case_type_error,
    4:  case_deep_stacktrace,
    5:  case_capture_message,
    6:  case_capture_message,   # 5 和 6 在同一个函数里，跳过单独调用
    7:  case_attribute_error,
    8:  case_import_error,
    9:  case_chained_exception,
    10: case_unhandled,
}


# ══════════════════════════════════════════════════════════
# 入口
# ══════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Mini Sentry 上报测试")
    parser.add_argument(
        "--case", type=int, default=0,
        help="指定单个用例编号 (1-10)，不填则运行全部"
    )
    args = parser.parse_args()

    if args.case == 10:
        case_unhandled(simulate=True)
        return

    if args.case and args.case in CASES:
        fn = CASES[args.case]
        if fn not in (case_capture_message,):
            fn()
        else:
            case_capture_message()
    else:
        # 运行全部（除 10）
        case_zero_division()
        case_key_error()
        case_type_error()
        case_deep_stacktrace()
        case_capture_message()
        case_attribute_error()
        case_import_error()
        case_chained_exception()
        case_unhandled(simulate=False)

    # 确保所有事件在进程退出前 flush 完毕
    print("⏳  等待事件 flush ...")
    sentry_sdk.flush(timeout=5)
    print("🎉  全部测试完成！请刷新 Mini Sentry 查看结果。")


if __name__ == "__main__":
    main()
