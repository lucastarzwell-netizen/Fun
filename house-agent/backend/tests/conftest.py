import os
import tempfile
from pathlib import Path

_tmp = tempfile.mkdtemp(prefix="house-agent-test-")
os.environ["HOUSE_AGENT_DATABASE_URL"] = f"sqlite:///{Path(_tmp) / 'test.db'}"
os.environ["HOUSE_AGENT_SCHEDULER"] = "0"

import pytest  # noqa: E402

from house_agent.db import Base, SessionLocal, engine, init_db  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(engine)
    init_db()
    yield


@pytest.fixture
def session():
    with SessionLocal() as s:
        yield s
