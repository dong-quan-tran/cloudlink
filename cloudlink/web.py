"""CloudLink dashboard, with queued AWS jobs or a local synchronous fallback."""

from __future__ import annotations

import hashlib
import os
import secrets
import time
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, session as browser_session

from .history import HistoryStore
from .jobs import JobStore
from .network import analyze_network, configuration_result
from .probe import TEST_TYPES, discover_nodes, load_inventory, run_probe


def create_app(session: Any | None = None, data_path: Path | None = None, job_store: Any | None = None) -> Flask:
    app = Flask(__name__)
    inventory_path = os.getenv("CLOUDLINK_INVENTORY_PATH")
    table_name = os.getenv("CLOUDLINK_TABLE_NAME")
    if session is None and (table_name or not inventory_path):
        import boto3

        session = boto3.session.Session(region_name=os.getenv("AWS_REGION", "us-east-1"))
    if table_name and job_store is None:
        job_store = JobStore(session, table_name, os.environ["CLOUDLINK_QUEUE_URL"])
    store = job_store if job_store is not None else HistoryStore(
        data_path
        or Path(os.getenv("CLOUDLINK_DATA_PATH", str(Path(__file__).resolve().parents[1] / "data" / "history.sqlite3")))
    )
    key_path = os.getenv("CLOUDLINK_KEY_PATH")
    # Every replica derives the same session-signing secret from the private
    # management credential, with a distinct purpose prefix. No secret is in Git.
    app.secret_key = (hashlib.sha256(b"CloudLink session signing\0" + Path(key_path).read_bytes()).digest()
                      if key_path else secrets.token_bytes(32))
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=os.getenv("CLOUDLINK_SECURE_COOKIE") == "true",
                      MAX_CONTENT_LENGTH=16 * 1024)

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
        if "csrf_token" not in browser_session:
            browser_session["csrf_token"] = secrets.token_urlsafe(32)
        if "history_owner" not in browser_session:
            browser_session["history_owner"] = secrets.token_urlsafe(32)
        return render_template("index.html", csrf_token=browser_session["csrf_token"])

    @app.get("/healthz")
    def health() -> Any:
        return jsonify({"status": "ok"})

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
        history_owner = browser_session.get("history_owner")
        if not history_owner:
            return jsonify({"tests": []})
        try:
            return jsonify({"tests": store.recent(history_owner)})
        except Exception:
            app.logger.exception("History unavailable")
            return jsonify({"error": "History is temporarily unavailable."}), 503

    @app.get("/api/tests/<uuid:job_id>")
    def job_status(job_id: Any) -> Any:
        if job_store is None:
            return jsonify({"error": "Queued jobs are not enabled locally."}), 404
        history_owner = browser_session.get("history_owner")
        if not history_owner:
            return jsonify({"error": "This test was not found or has expired."}), 404
        try:
            job = job_store.get(str(job_id))
            if job is None or job.get("history_partition") != history_owner or int(job["expires_at"]) <= int(time.time()):
                return jsonify({"error": "This test was not found or has expired."}), 404
            return jsonify(job_store.view(job))
        except Exception:
            app.logger.exception("Job status unavailable")
            return jsonify({"error": "Test status is temporarily unavailable."}), 503

    @app.post("/api/tests")
    def test_connection() -> Any:
        csrf_token = browser_session.get("csrf_token")
        history_owner = browser_session.get("history_owner")
        if not history_owner or not csrf_token or not secrets.compare_digest(request.headers.get("X-CloudLink-Token", ""), csrf_token):
            return jsonify({"error": "Invalid page token. Refresh and try again."}), 403
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify({"error": "Expected a JSON request."}), 400
        source_id = payload.get("source_id")
        destination_id = payload.get("destination_id")
        mode = payload.get("mode", "live")
        address_type = payload.get("address_type", "private")
        test_type = payload.get("test_type", "overview" if mode == "configuration" else "ping")
        port = payload.get("port")
        if not isinstance(source_id, str) or not isinstance(destination_id, str):
            return jsonify({"error": "Choose a source and destination."}), 400
        if address_type not in ("private", "public"):
            return jsonify({"error": "Choose a private or public destination address."}), 400
        if mode not in ("live", "configuration"):
            return jsonify({"error": "Choose a live test or configuration review."}), 400
        if mode == "configuration" and address_type != "private":
            return jsonify({"error": "Configuration review supports private IPv4 addresses."}), 400
        valid_types = TEST_TYPES | {"overview"} if mode == "configuration" else TEST_TYPES
        if not isinstance(test_type, str) or test_type not in valid_types:
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
            if source_id == destination_id:
                return jsonify({"error": "Choose two different instances."}), 400
            if not (destination.private_ip if address_type == "private" else destination.public_ip):
                return jsonify({"error": f"The destination has no {address_type} IP address."}), 400
            if job_store is not None:
                options = {"mode": mode} if mode == "configuration" else {}
                job = job_store.submit(source, destination, history_owner=history_owner,
                                       address_type=address_type, test_type=test_type, port=port, **options)
                job["status_url"] = f"/api/tests/{job['id']}"
                return jsonify(job), 202
            if mode == "configuration":
                result = configuration_result(session, source, destination, address_type, test_type, port)
            else:
                result = run_probe(
                    session, source, destination, address_type=address_type, test_type=test_type, port=port,
                    existing_key_path=os.getenv("CLOUDLINK_KEY_PATH"),
                    source_address_type=os.getenv("CLOUDLINK_SOURCE_ADDRESS", "public"),
                )
                if not result["check"]["ok"]:
                    result["network_analysis"] = analyze_network(session, source, destination, address_type, test_type, port)
            result["id"] = store.add(result, history_owner)
            return jsonify(result)
        except ValueError as error:
            return jsonify({"error": str(error)}), 400
        except Exception as error:
            app.logger.exception("Connection test failed")
            return jsonify({"error": "The diagnostic could not complete. Check AWS access or try again."}), 503

    return app
