"""Allow `python -m kcd` invocation."""

from kcd.cli import app


def main() -> None:
    app()


if __name__ == "__main__":
    main()
