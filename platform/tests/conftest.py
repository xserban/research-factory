import pytest

from factory.clock import FixedClock
from tests.helpers import T0


@pytest.fixture
def clock() -> FixedClock:
    return FixedClock(T0)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
