"""
One-time setup script to store API keys locally.

Run this once: python setup_env.py

It writes GROQ_API_KEY into a local .env file so you never need to
type 'export' by hand again. The .env file is gitignored and never
committed.
"""
from __future__ import annotations

import getpass
from pathlib import Path


ENV_PATH = Path(".env")


def main() -> None:
    print("Paste your Groq API key below.")
    print("(Input is hidden while you paste/type — this is normal.)")

    key = getpass.getpass("GROQ_API_KEY: ").strip()

    if not key:
        print("No key entered. Nothing was saved.")
        return

    if not key.startswith("gsk_"):
        print(
            "Warning: Groq keys normally start with 'gsk_'. "
            "Double-check you copied the right value."
        )

    lines = []

    if ENV_PATH.exists():
        existing = ENV_PATH.read_text().splitlines()
        lines = [
            line for line in existing
            if not line.startswith("GROQ_API_KEY=")
        ]

    lines.append(f"GROQ_API_KEY={key}")

    ENV_PATH.write_text("\n".join(lines) + "\n")

    print(f"Saved. {ENV_PATH} now contains your GROQ_API_KEY.")


if __name__ == "__main__":
    main()
