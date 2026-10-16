"""공개 가상 로그를 출력한다. --output을 주면 UTF-8 파일로 저장한다."""
import argparse
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="가상 로그를 저장할 경로")
    args = parser.parse_args()
    text = (BASE / "examples/sample.txt").read_text(encoding="utf-8")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"가상 로그 저장: {args.output}")
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
