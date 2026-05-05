"""Flask-App für interaktive Gebäudevisualisierung."""

import os
import sys

# computing_functions/ zum Python-Pfad hinzufügen
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "2_COMPUTE", "computing_functions"))

from flask import Flask

from routes.buildings import buildings_bp
from routes.simulations import simulations_bp
from services.data_service import load_data, energy_parameters


def create_app() -> Flask:
    app = Flask(__name__, template_folder=os.path.dirname(os.path.abspath(__file__)))
    app.register_blueprint(buildings_bp)
    app.register_blueprint(simulations_bp)
    return app


if __name__ == '__main__':
    app = create_app()

    print("\n" + "=" * 60)
    print("Web-App gestartet!")
    print("Öffne http://127.0.0.1:5001 im Browser")
    print(f"Energie-Parameter: {len(energy_parameters)} Parameter")
    print("Gebäudedaten werden beim ersten Aufruf geladen.")
    print("=" * 60 + "\n")

    app.run(debug=True, port=5001)
