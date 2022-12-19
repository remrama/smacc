from os import environ
from pathlib import Path


def get_data_directory():
    """Returns default data directory if environment variable is not set."""
    data_directory = environ.get("SMACC_DATA_DIRECTORY")
    if data_directory is None:
        data_directory = "~/smacc_data"
    data_directory = Path(data_directory).expanduser()
    return data_directory
