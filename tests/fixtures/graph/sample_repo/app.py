"""Sample application module for graph testing."""
import os
from utils import helper


class Processor:
    def __init__(self, filename: str) -> None:
        self.filename = filename

    def process(self) -> str:
        data = self.read_file()
        return helper(data)

    def read_file(self) -> str:
        with open(self.filename, "r", encoding="utf-8") as f:
            return f.read()


def main() -> None:
    p = Processor("data.txt")
    p.process()


if __name__ == "__main__":
    main()
