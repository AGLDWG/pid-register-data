"""Pytest command-line options for redirect tests."""


def pytest_addoption(parser):
    parser.addoption("--pid", help="Test only one PID, identified by its RDF file or PID instance IRI")
