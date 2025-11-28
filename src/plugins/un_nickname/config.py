from pydantic import BaseModel


class Config(BaseModel):
    max_nickname_length: int = 15  # 最大昵称长度限制
    # SQLite 绑定参数数量上限，用于 IN 子句分片查询
    # 默认为 999（SQLite 默认上限），如果 SQLite 配置了不同的 max_variable_number 可调整此值
    sqlite_max_variable_number: int = 999
