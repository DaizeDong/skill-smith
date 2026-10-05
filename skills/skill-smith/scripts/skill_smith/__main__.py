"""JSON CLI. Read a request from stdin or --request; emit a snapshot to stdout."""
import argparse
import json
import sys

from .catalog import discover


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", help="JSON request path (default: stdin)")
    args = parser.parse_args(argv)
    try:
        if args.request:
            with open(args.request, encoding="utf-8-sig") as stream:
                request = json.load(stream)
        else:
            request = json.load(sys.stdin)
        result = discover(request)
    except (OSError, ValueError, TypeError, KeyError):
        print(json.dumps({"error": "invalid or unreadable catalog request"}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 1 if any(c["status"] == "partial" for c in result["coverage"].values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
