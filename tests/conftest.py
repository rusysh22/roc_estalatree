"""Global pytest configuration and fixtures."""
import pytest


@pytest.fixture(scope="session")
def django_db_setup():
    """Use the test DB — set up in CI via DATABASE_URL env var."""
    pass
