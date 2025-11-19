#!/usr/bin/env python3

from .cli import main

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Error:", e)
