from pydantic import BaseModel, field_validator


class Config(BaseModel):
    max_nickname_length: int = 15  # 最大昵称长度限制
    # SQLite 绑定参数数量上限，用于 IN 子句分片查询
    # 默认为 999（SQLite 默认上限），如果 SQLite 配置了不同的 max_variable_number 可调整此值
    sqlite_max_variable_number: int = 999

    @field_validator("sqlite_max_variable_number")
    def validate_sqlite_max_variable_number(cls, value: int) -> int:
        """Validate SQLite bound parameter limit to avoid invalid SQL for chunked IN queries."""
        # Minimum 3 to ensure max_chunk_size = sqlite_max_variable_number - 2 stays >= 1.
        min_allowed = 3
        # SQLite default upper bound is 32,766 host parameters.
        max_allowed = 32766
        if not (min_allowed <= value <= max_allowed):
            raise ValueError(
                f"sqlite_max_variable_number must be between {min_allowed} and {max_allowed}, got {value}"
            )
        return value
