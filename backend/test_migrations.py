from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
import main


def test_migration_round_trip(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(main, "engine", engine)
    config = Config(str(Path(__file__).with_name("alembic.ini")))
    try:
        command.upgrade(config, "head")
        assert {"monitors", "checks"} <= set(inspect(engine).get_table_names())
        assert inspect(engine).get_indexes("checks")[0]["name"] == "ix_checks_monitor_id"
        command.check(config)
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO monitors (id, name, url, interval, retries, next_check) VALUES (1, 'test', 'https://example.com', 60, 1, '2026-01-01')"))
        command.upgrade(config, "head")
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM monitors")).scalar_one() == 1
        command.downgrade(config, "base")
        assert not {"monitors", "checks"} & set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
