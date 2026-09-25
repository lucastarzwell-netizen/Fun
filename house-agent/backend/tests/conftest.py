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
    from house_agent.agent import runner

    Base.metadata.drop_all(engine)
    init_db()
    runner._stop_requested.clear()  # run ids restart with each fresh database
    yield


@pytest.fixture
def session():
    with SessionLocal() as s:
        yield s
