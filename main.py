"""Compatibility entrypoint; prefer python -m seo_reviewer."""

from seo_reviewer.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main())
