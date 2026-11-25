#!/usr/bin/env python3
"""Pack the MT7621 layout described by mt7621-u-boot.dtsi, without binman."""
import argparse
from pathlib import Path


def pack(spl, payload, align):
    if align <= 0 or align & (align - 1):
        raise ValueError("SPL alignment must be a positive power of two")
    return spl + b"\xff" * (-len(spl) % align) + payload


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spl", type=Path)
    parser.add_argument("--align", type=lambda s: int(s, 0), default=1)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_bytes(pack(args.spl.read_bytes() if args.spl else b"",
                                args.payload.read_bytes(), args.align))
