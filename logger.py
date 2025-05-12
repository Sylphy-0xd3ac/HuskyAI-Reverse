#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本模块提供 Time 类和 Logger 类，功能类似原始 TypeScript 代码，
包括对时间常量、动态日志方法、格式化及颜色输出的支持。
"""

import re
import math
import json
import time
import datetime
import sys
from typing import Any, Callable, Dict, List, Optional, Union

# 颜色代码数组（16色和256色）
c16 = [6, 2, 3, 4, 5, 1]
c256 = [
    20, 21, 26, 27, 32, 33, 38, 39, 40, 41, 42, 43, 44, 45, 56, 57, 62, 63, 68,
    69, 74, 75, 76, 77, 78, 79, 80, 81, 92, 93, 98, 99, 112, 113, 129, 134, 135,
    148, 149, 160, 161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 171, 172,
    173, 178, 179, 184, 185, 196, 197, 198, 199, 200, 201, 202, 203, 204, 205,
    206, 207, 208, 209, 214, 215, 220, 221,
]


# ------------------------------------
# Time 类
# ------------------------------------
class Time:
    # 时间单位（毫秒）
    millisecond = 1
    second = 1000
    minute = second * 60
    hour = minute * 60
    day = hour * 24
    week = day * 7

    # 默认使用本地系统时区，注意：JS 中 getTimezoneOffset 返回的是分钟
    timezone_offset = int(datetime.datetime.now().astimezone().utcoffset().total_seconds() / 60)

    @staticmethod
    def set_timezone_offset(offset: int) -> None:
        Time.timezone_offset = offset

    @staticmethod
    def get_timezone_offset() -> int:
        return Time.timezone_offset

    @staticmethod
    def get_date_number(dt: Union[int, datetime.datetime] = None,
                        offset: Optional[int] = None) -> int:
        """将日期转为数字：相对于某一基准日的天数（与时区有关）"""
        if dt is None:
            dt = datetime.datetime.now()
        elif isinstance(dt, int):
            dt = datetime.datetime.fromtimestamp(dt / 1000)
        if offset is None:
            offset = Time.timezone_offset
        minutes = dt.timestamp() * 1000 / Time.minute
        return math.floor((minutes - offset) / 1440)

    @staticmethod
    def from_date_number(value: int, offset: Optional[int] = None) -> datetime.datetime:
        """由日期数字还原到日期对象"""
        base_date = datetime.datetime.fromtimestamp((value * Time.day) / 1000)
        if offset is None:
            offset = Time.timezone_offset
        return base_date + datetime.timedelta(minutes=offset)

    # 用于解析时间段的正则：支持 week/day/hour/minute/second 的简写或全称
    _numeric = r"\d+(?:\.\d+)?"
    _time_units = [
        r"w(?:eek(?:s)?)?",
        r"d(?:ay(?:s)?)?",
        r"h(?:our(?:s)?)?",
        r"m(?:in(?:ute)?(?:s)?)?",
        r"s(?:ec(?:ond)?(?:s)?)?"
    ]
    
    # 构建正则表达式
    _time_regexp = re.compile(
        "^" +
        "".join(r"(?:(\d+(?:\.\d+)?)" + unit + r")?" for unit in _time_units) +
        "$"
    )

    @staticmethod
    def parse_time(source: str) -> float:
        """
        解析类似 "1week2day3hour4min5sec" 的字符串，
        返回对应的毫秒数（浮点数）。如果无法匹配则返回 0。
        """
        m = Time._time_regexp.match(source.strip())
        if not m:
            return 0
        groups = m.groups()  # 顺序：week, day, hour, minute, second
        values = [float(g) if g is not None else 0 for g in groups]
        return (values[0] * Time.week +
                values[1] * Time.day +
                values[2] * Time.hour +
                values[3] * Time.minute +
                values[4] * Time.second)

    @staticmethod
    def parse_date(date_str: str) -> datetime.datetime:
        """
        对字符串进行解析，支持三种情况：
          1. 如果字符串能以 parse_time 得出一个时长，则返回当前时间 + 时长；
          2. 如果形如 "hh:mm" 或 "hh:mm:ss"，则补上今日日期；
          3. 如果形如 "mm-dd-yy hh:mm(:ss)"，则补上当前年份。
          4. 否则尝试直接解析 ISO 格式，失败则返回当前时间。
        """
        date_str = date_str.strip()
        # 情况 1
        delta_ms = Time.parse_time(date_str)
        if delta_ms:
            return datetime.datetime.now() + datetime.timedelta(milliseconds=delta_ms)

        # 情况 2：例如 "12:34" 或 "12:34:56"
        if re.match(r'''^\d{1,2}(:\d{1,2}){1,2}''', date_str):
            today = datetime.datetime.now().date()
            new_date_str = f"{today} {date_str}"
            try:
                return datetime.datetime.strptime(new_date_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    return datetime.datetime.strptime(new_date_str, "%Y-%m-%d %H:%M")
                except Exception:
                    pass

        # 情况 3：例如 "12-31-23 12:34" 或 "12-31-23 12:34:56"
        if re.match(r'''^\d{1,2}-\d{1,2}-\d{1,2}(:\d{1,2}){1,2}''', date_str):
            year = datetime.datetime.now().year
            new_date_str = f"{year}-{date_str}"
            try:
                return datetime.datetime.strptime(new_date_str, "%Y-%m-%d %H:%M:%S")
            except Exception:
                try:
                    return datetime.datetime.strptime(new_date_str, "%Y-%m-%d %H:%M")
                except Exception:
                    pass

        # 尝试直接解析 ISO 格式
        try:
            return datetime.datetime.fromisoformat(date_str)
        except Exception:
            return datetime.datetime.now()

    @staticmethod
    def format(ms: float) -> str:
        """
        将毫秒数转换为短格式字符串，如 "d", "h", "m", "s" 或 "ms"，
        根据毫秒的绝对值取最接近的时间单位。
        """
        abs_ms = abs(ms)
        if abs_ms >= Time.day - Time.hour / 2:
            return f"{round(ms / Time.day)}d"
        elif abs_ms >= Time.hour - Time.minute / 2:
            return f"{round(ms / Time.hour)}h"
        elif abs_ms >= Time.minute - Time.second / 2:
            return f"{round(ms / Time.minute)}m"
        elif abs_ms >= Time.second:
            return f"{round(ms / Time.second)}s"
        return f"{ms}ms"

    @staticmethod
    def to_digits(source: Union[int, str], length: int = 2) -> str:
        return str(source).zfill(length)

    @staticmethod
    def template(template_str: str, dt: Optional[datetime.datetime] = None) -> str:
        """
        根据模板生成日期字符串，例如：
          "yyyy-MM-dd hh:mm:ss.SSS" 会被替换成实际日期
        """
        if dt is None:
            dt = datetime.datetime.now()
        replacements = {
            "yyyy": str(dt.year),
            "yy": str(dt.year)[-2:],
            "MM": Time.to_digits(dt.month),
            "dd": Time.to_digits(dt.day),
            "hh": Time.to_digits(dt.hour),
            "mm": Time.to_digits(dt.minute),
            "ss": Time.to_digits(dt.second),
            "SSS": Time.to_digits(dt.microsecond // 1000, 3)
        }
        res = template_str
        for k, v in replacements.items():
            res = res.replace(k, v)
        return res


# ------------------------------------
# Logger 类
# ------------------------------------
# 类型别名
Level = Union[int, Dict[str, Any]]
LogFunction = Callable[..., None]
Formatter = Callable[[Any, Dict[str, Any], "Logger"], Any]
LabelStyle = Dict[str, Any]
Record = Dict[str, Any]
Target = Dict[str, Any]  # 存放配置，如：colors、showTime、label、record、print、levels、timestamp 等

def is_aggregate_error(error: Exception) -> bool:
    # Python 中可自定义聚合异常，可扩展此判断
    return hasattr(error, "errors") and isinstance(getattr(error, "errors"), list)


class Logger:
    # 日志级别常量
    SILENT = 0
    SUCCESS = 1
    ERROR = 1
    INFO = 2
    WARN = 2
    DEBUG = 3

    # 全局配置
    id = 0  # 自增 id
    targets: List[Target] = []
    formatters: Dict[str, Formatter] = {}
    levels: Level = {"base": 2}

    def __init__(self, name: str, meta: Any = None):
        self.name = name
        self.meta = meta
        # 动态生成日志方法
        self._create_method("success", Logger.SUCCESS)
        self._create_method("error", Logger.ERROR)
        self._create_method("info", Logger.INFO)
        self._create_method("warn", Logger.WARN)
        self._create_method("debug", Logger.DEBUG)

    @classmethod
    def format_formatter(cls, name: str, formatter: Formatter) -> None:
        cls.formatters[name] = formatter

    @staticmethod
    def color(target: Target, code: int, value: Any, decoration: str = "") -> str:
        # 若目标不支持颜色，则直接返回字符串
        if not target.get("colors"):
            return str(value)
        colors_list = c256 if target.get("colors", 0) >= 2 else c16
        if code < 8:
            col_code = f"3{code}"
        else:
            col_code = f"8;5;{code}"
        deco = decoration if target.get("colors", 0) >= 2 else ""
        return f"\033[{col_code}{deco}m{value}\033[0m"

    @staticmethod
    def code(name: str, target: Target) -> int:
        h = 0
        for ch in name:
            h = (h << 3) - h + ord(ch) + 13
            # 模拟 JS 位运算（32位整数处理）
            h = ((h + 2**31) % 2**32) - 2**31
        colors_list = c256 if target.get("colors", 0) >= 2 else c16
        return colors_list[abs(h) % len(colors_list)]

    @staticmethod
    def render(target: Target, record: Record) -> str:
        prefix = f"[{record['type'][0].upper()}]"
        label_style: LabelStyle = target.get("label", {})
        margin = label_style.get("margin", 1)
        space = " " * margin
        indent = 3 + len(space)
        output = ""
        if "showTime" in target and target["showTime"]:
            dt = datetime.datetime.fromtimestamp(record["timestamp"] / 1000)
            tstr = Time.template(target["showTime"], dt)
            output += Logger.color(target, 8, tstr) + space
            indent += len(tstr) + len(space)
        code_val = Logger.code(record["name"], target)
        label = Logger.color(target, code_val, record["name"], ";1")
        pad_width = label_style.get("width", 0)
        pad_length = pad_width + len(label) - len(record["name"])
        if label_style.get("align") == "right":
            output += label.rjust(pad_length) + space + prefix + space
            indent += pad_width + len(space)
        else:
            output += prefix + space + label.ljust(pad_length) + space
        content = record["content"].replace("\n", "\n" + " " * indent)
        output += content
        if target.get("showDiff") and target.get("timestamp") is not None:
            diff = record["timestamp"] - target["timestamp"]
            output += Logger.color(target, code_val, " +" + str(diff))
        return output

    def extend(self, namespace: str) -> "Logger":
        return Logger(f"{self.name}:{namespace}", self.meta)

    def _create_method(self, type_name: str, level: int) -> None:
        """
        动态定义日志方法，如 logger.error(...), logger.info(...) 等。
        """
        def log_method(*args: Any) -> None:
            if len(args) == 1 and isinstance(args[0], Exception):
                err = args[0]
                if getattr(err, "__cause__", None):
                    getattr(self, type_name)(err.__cause__)
                    return
                elif is_aggregate_error(err):
                    for e in getattr(err, "errors"):
                        getattr(self, type_name)(e)
                    return

            Logger.id += 1
            timestamp = int(time.time() * 1000)
            for target in Logger.targets:
                if self.get_level(target) < level:
                    continue
                content = self._format(target, *args)
                record: Record = {
                    "id": Logger.id,
                    "type": type_name,
                    "level": level,
                    "name": self.name,
                    "meta": self.meta,
                    "content": content,
                    "timestamp": timestamp
                }
                if callable(target.get("record")):
                    target["record"](record)
                elif callable(target.get("print")):
                    target["print"](Logger.render(target, record))
                target["timestamp"] = timestamp
        setattr(self, type_name, log_method)

    def _format(self, target: Target, *args: Any) -> str:
        """
        根据格式化规则生成最终日志字符串：
          如果第一个参数为异常，则使用其 str 信息；
          如果第一个参数不是字符串，则默认使用 "%o" 格式。
        支持 %s、%d、%j、%c、%C 格式标记。
        """
        args = list(args)
        if args and isinstance(args[0], Exception):
            err = args.pop(0)
            args.insert(0, str(err))
            fmt = "%s"
        elif not args or not isinstance(args[0], str):
            args.insert(0, "%o")
            fmt = args.pop(0)
        else:
            fmt = args.pop(0)

        def repl(match: re.Match) -> str:
            spec = match.group(1)
            if spec == "%":
                return "%"
            if spec in Logger.formatters and callable(Logger.formatters[spec]) and args:
                val = args.pop(0)
                return str(Logger.formatters[spec](val, target, self))
            return match.group(0)
        
        fmt = re.sub(r'%([a-zA-Z%])', repl, fmt)
        max_length = target.get("maxLength", 10240)
        lines = fmt.splitlines()
        lines = [line[:max_length] + ("..." if len(line) > max_length else "") for line in lines]
        return "\n".join(lines)

    def get_level(self, target: Target) -> int:
        """
        根据 Logger 的名称层次（用冒号分隔）以及目标 target 的 levels 配置，
        返回对应的日志级别，若没有配置则返回默认级别。
        """
        paths = self.name.split(":")
        config: Union[Level, Dict[str, Any]] = target.get("levels", Logger.levels)
        while paths and isinstance(config, dict):
            key = paths.pop(0)
            if key in config:
                config = config[key]
            else:
                config = config.get("base", config)
                break
        return int(config) if isinstance(config, (int, float)) else int(Logger.levels.get("base", 2))


# 在 Logger 类中注册格式化器
Logger.format_formatter("s", lambda v, t, l: str(v))
Logger.format_formatter("d", lambda v, t, l: int(v))
Logger.format_formatter("j", lambda v, t, l: json.dumps(v))
Logger.format_formatter("c", lambda v, t, l: Logger.color(t, Logger.code(l.name, t), v))
Logger.format_formatter("C", lambda v, t, l: Logger.color(t, 15, v, ";1"))