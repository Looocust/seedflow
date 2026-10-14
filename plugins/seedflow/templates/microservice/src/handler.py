"""Lambda handler del microservicio."""

import json
import sys
from pathlib import Path
from typing import Any

from service.main import main


def run(event: dict[str, Any], stage: str) -> dict[str, Any]:
    """Procesa el evento recibido.

    Parameters
    ----------
    event : dict[str, Any]
        Evento que recibe la Lambda.
    stage : str
        Ambiente de ejecución (dev, prod).

    Returns
    -------
    dict[str, Any]
        Respuesta del microservicio.
    """
    print(f"Processing event in {stage} environment:")
    print(json.dumps(event, indent=2))
    return main(event)


if __name__ == "__main__":
    # En local, carga python/.env del proyecto (en la Lambda no hace falta).
    try:
        from dotenv import load_dotenv

        load_dotenv(Path(__file__).resolve().parents[3] / ".env")
    except ImportError:
        print("python-dotenv no está instalado: no se cargó el .env.")

    events_folder = Path(__file__).resolve().parent.parent / "events"
    event_file = events_folder / f"{sys.argv[1]}.json"
    with event_file.open(encoding="utf-8") as file:
        event_data = json.load(file)

    run(event_data, "dev")
