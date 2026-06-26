import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.analyzer import analyze
from app.models import TicketRequest


def main() -> None:
    request = TicketRequest.model_validate_json((ROOT / "sample_request.json").read_text(encoding="utf-8"))
    response = analyze(request)
    (ROOT / "sample_output.json").write_text(
        json.dumps(response.model_dump(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
