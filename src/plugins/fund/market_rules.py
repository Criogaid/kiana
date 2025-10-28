"""市场规则配置模块

本模块定义了中国证券市场的代码规则，包括股票、ETF、LOF 等各类证券的前缀规则。
这些规则用于代码类型识别和市场验证。

规则来源：
- 上海证券交易所（SSE）规则
- 深圳证券交易所（SZSE）规则
- 北京证券交易所（BSE）规则
- 全国性场外基金编码规则
"""

from typing import Final

# ==================== 股票市场前缀规则 ====================

# 上海证券交易所（SSE）：使用三位前缀（更精确）
# 使用 set 以实现 O(1) 查找性能（统一数据结构）
STOCK_PREFIXES_SH: Final[set[str]] = {
    "600",  # SSE 主板 A 股
    "601",
    "603",
    "605",
    "688",  # 科创板
    "689",  # 科创板相关存托凭证/特殊号段
    "900",  # 补充：SSE B 股
}

# 深圳证券交易所（SZSE）：使用三位前缀（更精确）
# 使用 set 以实现 O(1) 查找性能（统一数据结构）
STOCK_PREFIXES_SZ: Final[set[str]] = {
    "000",  # 主板
    "001",  # 主板/互补号段
    "002",  # 主板（原中小板）
    "300",  # 创业板
    "200",  # 补充：SZSE B 股
}

# 北京证券交易所（BSE）：使用两位前缀（北交所代码为8位数字，前两位标识）
# 使用 set 以实现 O(1) 查找性能（用于 in 操作）
STOCK_PREFIXES_BJ: Final[set[str]] = {
    "43",  # 精选层历史代码
    "83",  # 北交所上市代码段
    "87",  # 北交所上市代码段
    "88",  # 北交所上市代码段
}


# ==================== 场内基金（ETF / LOF / 其它上市基金）前缀规则 ====================

# 上海交易所常见基金/ETF/LOF 前缀（以三位为单位更精确）
# 扩充 ETF 覆盖范围 (51x/56x)
ETF_PREFIXES_SH: Final[set[str]] = {
    "510",  # 常见沪市 ETF 核心段
    "511",
    "512",
    "513",
    "515",
    "516",
    "517",
    "518",  # 商品/特定 ETF
    "550",  # 债券/货币 ETF 号段
    "560",  # 债券/特定 ETF
    "588",  # 科创/跨市场 ETF 号段
}

LOF_PREFIXES_SH: Final[set[str]] = {
    "501",  # 上市开放式基金（LOF）常见号段
    "506",  # 科创或特殊 LOF
    "500",  # 封闭式基金/老基金
}

# 深圳交易所常见场内基金号段
ETF_PREFIXES_SZ: Final[set[str]] = {
    "159",  # 深市交易型开放式指数基金（ETF）常见号段
    # 150 建议移除，因其主要用于分级基金子份额，非主流 ETF
}

LOF_PREFIXES_SZ: Final[set[str]] = {
    "160",  # LOF 在深交所常见以 160-169 为起始号段
    "161",
    "162",
    "163",
    "164",
    "165",
    "166",
    "167",
    "168",
    "169",
}

# 所有 ETF 前缀（合并）
ETF_PREFIXES_ALL: Final[set[str]] = ETF_PREFIXES_SH | ETF_PREFIXES_SZ

# 所有 LOF 前缀（合并）
LOF_PREFIXES_ALL: Final[set[str]] = LOF_PREFIXES_SH | LOF_PREFIXES_SZ


# ==================== 场外/开放式公募基金（非上市基金）前缀规则 ====================

# 场外开放式基金（全国统一的基金注册代码）
# 此为六位代码的前两位，与场内代码体系不同
OFF_MARKET_FUND_PREFIXES: Final[set[str]] = {f"{i:02d}" for i in range(10)}  # 00-09

# 场内开放式基金申赎代码（上交所）
OFF_MARKET_TRADING_PREFIX_SH: Final[set[str]] = {"519"}


# ==================== 纯指数代码前缀规则 (非交易标的) ====================

# 上海证券交易所指数代码前缀
INDEX_PREFIXES_SH: Final[set[str]] = {
    "000",  # 000xxx 系列，如上证指数 (000001)、沪深300指数 (000300) 等
    "999",  # 999xxx 系列，如上证国债指数等
}

# 深圳证券交易所指数代码前缀
INDEX_PREFIXES_SZ: Final[set[str]] = {
    "399",  # 399xxx 系列，如深证成指 (399001)、创业板指 (399006) 等
}

# 所有指数前缀（合并）
INDEX_PREFIXES_ALL: Final[set[str]] = INDEX_PREFIXES_SH | INDEX_PREFIXES_SZ


# ==================== 市场验证函数 ====================


def is_shanghai_stock(code: str) -> bool:
    """判断代码是否为上海股票

    Args:
        code: 6位数字代码

    Returns:
        是否为上海股票
    """
    return code[:3] in STOCK_PREFIXES_SH


def is_shenzhen_stock(code: str) -> bool:
    """判断代码是否为深圳股票

    Args:
        code: 6位数字代码

    Returns:
        是否为深圳股票
    """
    return code[:3] in STOCK_PREFIXES_SZ


def is_beijing_stock(code: str) -> bool:
    """判断代码是否为北京股票

    注意：北交所股票代码为8位数字

    Args:
        code: 8位数字代码

    Returns:
        是否为北京股票
    """
    return len(code) == 8 and code[:2] in STOCK_PREFIXES_BJ


def is_etf(code: str) -> bool:
    """判断代码是否为 ETF

    使用三位前缀进行判断，更精确地识别 ETF

    Args:
        code: 6位数字代码

    Returns:
        是否为 ETF
    """
    return code[:3] in ETF_PREFIXES_ALL


def is_lof(code: str) -> bool:
    """判断代码是否为 LOF

    使用三位前缀进行判断，更精确地识别 LOF

    Args:
        code: 6位数字代码

    Returns:
        是否为 LOF
    """
    return code[:3] in LOF_PREFIXES_ALL


def is_off_market_fund(code: str) -> bool:
    """判断代码是否为场外基金

    场外基金使用两位前缀（00-09）

    Args:
        code: 6位数字代码

    Returns:
        是否为场外基金
    """
    # 场外基金使用两位前缀
    return code[:2] in OFF_MARKET_FUND_PREFIXES


def is_off_market_trading_code(code: str) -> bool:
    """判断代码是否为场内开放式基金申赎代码（上交所 519）

    Args:
        code: 6位数字代码

    Returns:
        是否为场内申赎代码
    """
    return code[:3] in OFF_MARKET_TRADING_PREFIX_SH


def is_index(code: str) -> bool:
    """判断代码是否为指数

    使用三位前缀进行判断

    Args:
        code: 6位数字代码

    Returns:
        是否为指数
    """
    return code[:3] in INDEX_PREFIXES_ALL


def is_shanghai_index(code: str) -> bool:
    """判断代码是否为上海指数

    Args:
        code: 6位数字代码

    Returns:
        是否为上海指数
    """
    return code[:3] in INDEX_PREFIXES_SH


def is_shenzhen_index(code: str) -> bool:
    """判断代码是否为深圳指数

    Args:
        code: 6位数字代码

    Returns:
        是否为深圳指数
    """
    return code[:3] in INDEX_PREFIXES_SZ


def validate_market_code(code: str, market: str) -> tuple[bool, str | None]:
    """验证代码和市场的匹配性

    Args:
        code: 6位或8位数字代码（北交所为8位）
        market: 市场标识（'sh'、'sz' 或 'bj'）

    Returns:
        (是否有效, 错误信息)。如果有效返回 (True, None)，否则返回 (False, 错误信息)
    """
    market = market.lower()

    if market == "sh":
        if not is_shanghai_stock(code):
            # 生成友好的前缀提示（只显示前两位作为简化）
            prefixes_simplified = sorted({p[:2] for p in STOCK_PREFIXES_SH})
            prefixes_str = "/".join(prefixes_simplified)
            return (
                False,
                f"股票代码 {code} 不属于上海市场(.SH)，上海股票应以 {prefixes_str}X 开头",
            )
    elif market == "sz":
        if not is_shenzhen_stock(code):
            # 生成友好的前缀提示（只显示前两位作为简化）
            prefixes_simplified = sorted({p[:2] for p in STOCK_PREFIXES_SZ})
            prefixes_str = "/".join(prefixes_simplified)
            return (
                False,
                f"股票代码 {code} 不属于深圳市场(.SZ)，深圳股票应以 {prefixes_str}X 开头",
            )
    elif market == "bj":
        if not is_beijing_stock(code):
            # 北交所前缀提示
            prefixes_str = "/".join(sorted(STOCK_PREFIXES_BJ))
            return (
                False,
                f"股票代码 {code} 不属于北京市场(.BJ)，北交所股票应为8位数字且以 {prefixes_str} 开头",
            )
    else:
        return False, f"未知的市场标识: {market}"

    return True, None


def infer_stock_market(code: str) -> str:
    """根据股票代码推断市场

    Args:
        code: 6位或8位数字代码

    Returns:
        市场标识：'sh'、'sz' 或 'bj'
    """
    if is_beijing_stock(code):
        return "bj"
    return "sh" if is_shanghai_stock(code) else "sz"
