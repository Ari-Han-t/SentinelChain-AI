import sys
from pathlib import Path

from .security import sign_import


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python -m app.sign_csv <csv-path>")
    content = Path(sys.argv[1]).read_bytes()
    print(sign_import(content))


if __name__ == "__main__":
    main()
