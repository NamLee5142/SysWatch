from logging.config import fileConfig

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context

from app.db.models import Base
from config import ensure_data_dir, get_settings

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    # disable_existing_loggers defaults to True, which would silence every
    # logger the application has already configured. Running a migration must
    # not turn off the app's logging.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# The database URL lives in settings, not alembic.ini, so migrations and the
# application can never point at different databases.
# Created here as well as at app startup: `alembic upgrade head` is the first
# thing an install runs, and SQLite will not create a database inside a
# directory that does not exist.
_settings = get_settings()
ensure_data_dir(_settings)
config.set_main_option("sqlalchemy.url", _settings.database_url)

target_metadata = Base.metadata


def _is_sqlite():
    return get_settings().database_url.startswith("sqlite")


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        # SQLite cannot ALTER most things in place; batch mode rebuilds the
        # table instead. Harmless on backends that support ALTER directly.
        render_as_batch=_is_sqlite(),
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=_is_sqlite(),
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
