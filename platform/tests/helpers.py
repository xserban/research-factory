from datetime import UTC, datetime

from factory.model.base import StrictModel

T0 = datetime(2026, 10, 31, 12, 0, tzinfo=UTC)
SESSION = "01JZ9Q3K5M7N8P0R2S4T6V8W0X"
S2 = "01JZ9Q3K5M7N8P0R2S4T6V8W0Y"


class Demo(StrictModel):
    n: int
