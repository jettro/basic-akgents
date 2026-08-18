"""Kept so `uv run src/main.py <case id>` keeps working.

The console application lives in `basic_akgents.cli.app`, the framework code it
drives in the modules next to it.
"""

from basic_akgents.cli.app import main

if __name__ == "__main__":
    main()
