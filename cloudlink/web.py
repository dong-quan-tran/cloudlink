"""Local-only CloudLink dashboard and bounded test API."""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request

from .history import HistoryStore
from .probe import TEST_TYPES, discover_nodes, load_inventory, run_probe


def create_app(session: Any | None = None, data_path: Path | None = None) -> Flask:
    app = Flask(__name__)
    inventory_path = os.getenv("CLOUDLINK_INVENTORY_PATH")
    if session is None and not inventory_path:
        import boto3

        session = boto3.session.Session(region_name=os.getenv("AWS_REGION", "us-east-1"))
    store = HistoryStore(
        data_path
        or Path(os.getenv("CLOUDLINK_DATA_PATH", str(Path(__file__).resolve().parents[1] / "data" / "history.sqlite3")))
    )
    csrf_token = secrets.token_urlsafe(32)

    def available_nodes() -> list[Any]:
        if inventory_path:
            return load_inventory(Path(inventory_path))
        return discover_nodes(session.client("ec2"))

    @app.after_request
    def security_headers(response: Any) -> Any:
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'"
        )
        return response

    @app.get("/")
    def index() -> str:
        return render_template("index.html", csrf_token=csrf_token)

    @app.get("/api/instances")
    def instances() -> Any:
        try:
            nodes = available_nodes()
            return jsonify({"instances": [node.to_dict() for node in nodes]})
        except Exception as error:
            app.logger.warning("Instance discovery failed: %s", error)
            return jsonify({"error": "Could not list lab instances. Check the configured inventory or AWS access."}), 503

    @app.get("/api/history")
    def history() -> Any:
        return jsonify({"tests": store.recent()})

    @app.post("/api/tests")
    def test_connection() -> Any:
        if not secrets.compare_digest(request.headers.get("X-CloudLink-Token", ""), csrf_token):
            return jsonify({"error": "Invalid page token. Refresh and try again."}), 403
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Expected a JSON request."}), 400
        source_id = payload.get("source_id")
        destination_id = payload.get("destination_id")
        address_type = payload.get("address_type", "private")
        test_type = payload.get("test_type", "ping")
        port = payload.get("port")
        if not isinstance(source_id, str) or not isinstance(destination_id, str):
            return jsonify({"error": "Choose a source and destination."}), 400
        if address_type not in ("private", "public"):
            return jsonify({"error": "Choose a private or public destination address."}), 400
        if not isinstance(test_type, str) or test_type not in TEST_TYPES:
            return jsonify({"error": "Choose ping, HTTP, HTTPS, SSH, or a custom TCP port."}), 400
        if test_type == "tcp" and (type(port) is not int or not 1 <= port <= 65535):
            return jsonify({"error": "Custom TCP port must be between 1 and 65535."}), 400
        if test_type != "tcp" and port is not None:
            return jsonify({"error": "A custom port is only used for the TCP test."}), 400
        try:
            nodes = {node.instance_id: node for node in available_nodes()}
            source = nodes.get(source_id)
            destination = nodes.get(destination_id)
            if source is None or destination is None:
                return jsonify({"error": "Choose two running CloudLink lab instances."}), 400
            result = run_probe(
                session,
                source,
                destination,
                address_type=address_type,
                existing_key_path=os.getenv("CLOUDLINK_KEY_PATH"),
                source_address_type=os.getenv("CLOUDLINK_SOURCE_ADDRESS", "public"),
                test_type=test_type,
                port=port,
            )
            result["id"] = store.add(result)
            return jsonify(result)
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        except Exception as error:
            app.logger.exception("Connection test failed")
            return jsonify({"error": f"Test could not start: {type(error).__name__}. Check inventory and source SSH."}), 503

    return app
