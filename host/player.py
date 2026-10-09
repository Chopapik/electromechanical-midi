"""CLI alias for the same application runtime."""
from host.web.server import main
if __name__ == "__main__":
    raise SystemExit(main())
