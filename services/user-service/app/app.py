from flask import Flask, request, jsonify
from flask_cors import CORS

from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    jwt_required,
    get_jwt_identity
)

from werkzeug.security import (
    generate_password_hash,
    check_password_hash
)

from prometheus_client import (
    Counter,
    Histogram,
    generate_latest,
    CONTENT_TYPE_LATEST
)

import time

from database import (
    get_db_connection,
    initialize_database
)


# =========================================================
# APP CONFIGURATION
# =========================================================

app = Flask(__name__)

# Allow frontend to communicate with this backend
CORS(app)

# JWT configuration
app.config["JWT_SECRET_KEY"] = "change-this-secret-key"

jwt = JWTManager(app)


# =========================================================
# PROMETHEUS METRICS
# =========================================================

REQUEST_COUNT = Counter(
    "user_service_requests_total",
    "Total number of requests handled by User Service",
    ["method", "endpoint", "status"]
)

REQUEST_LATENCY = Histogram(
    "user_service_request_latency_seconds",
    "Request latency of User Service",
    ["method", "endpoint"]
)


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

initialize_database()


# =========================================================
# PROMETHEUS REQUEST MONITORING
# =========================================================

@app.before_request
def before_request():

    request.start_time = time.time()


@app.after_request
def after_request(response):

    latency = time.time() - request.start_time

    REQUEST_COUNT.labels(
        request.method,
        request.path,
        response.status_code
    ).inc()

    REQUEST_LATENCY.labels(
        request.method,
        request.path
    ).observe(latency)

    return response


# =========================================================
# PROMETHEUS METRICS ENDPOINT
# =========================================================

@app.route("/metrics", methods=["GET"])
def metrics():

    return generate_latest(), 200, {
        "Content-Type": CONTENT_TYPE_LATEST
    }


# =========================================================
# HEALTH CHECK
# =========================================================

@app.route("/health", methods=["GET"])
def health():

    return jsonify({
        "service": "user-service",
        "status": "UP"
    }), 200


# =========================================================
# VERSION
# =========================================================

@app.route("/version", methods=["GET"])
def version():

    return jsonify({
        "service": "user-service",
        "version": "1.0.0"
    }), 200


# =========================================================
# REGISTER
# =========================================================

@app.route("/register", methods=["POST"])
def register():

    data = request.get_json()

    if not data:

        return jsonify({
            "error": "Request body is required"
        }), 400

    username = data.get("username")
    email = data.get("email")
    password = data.get("password")

    # Validate fields
    if not username or not email or not password:

        return jsonify({
            "error": "All fields are required"
        }), 400

    connection = get_db_connection()
    cursor = connection.cursor()

    # Check username
    cursor.execute(
        "SELECT id FROM users WHERE username = ?",
        (username,)
    )

    if cursor.fetchone():

        connection.close()

        return jsonify({
            "error": "Username already exists"
        }), 409

    # Check email
    cursor.execute(
        "SELECT id FROM users WHERE email = ?",
        (email,)
    )

    if cursor.fetchone():

        connection.close()

        return jsonify({
            "error": "Email already exists"
        }), 409

    # Hash password before storing it
    hashed_password = generate_password_hash(
        password
    )

    # Insert user
    cursor.execute(
        """
        INSERT INTO users
        (username, email, password)
        VALUES (?, ?, ?)
        """,
        (
            username,
            email,
            hashed_password
        )
    )

    user_id = cursor.lastrowid

    connection.commit()
    connection.close()

    return jsonify({

        "message": "User registered successfully",

        "user_id": user_id

    }), 201


# =========================================================
# LOGIN
# =========================================================

@app.route("/login", methods=["POST"])
def login():

    data = request.get_json()

    if not data:

        return jsonify({
            "error": "Request body is required"
        }), 400

    username = data.get("username")
    password = data.get("password")

    # Validate fields
    if not username or not password:

        return jsonify({
            "error": "Username and password are required"
        }), 400

    connection = get_db_connection()
    cursor = connection.cursor()

    # Find user
    cursor.execute(
        """
        SELECT id, username, password
        FROM users
        WHERE username = ?
        """,
        (username,)
    )

    user = cursor.fetchone()

    connection.close()

    # User doesn't exist
    if not user:

        return jsonify({
            "error": "Invalid username or password"
        }), 401

    # Check password
    if not check_password_hash(
        user["password"],
        password
    ):

        return jsonify({
            "error": "Invalid username or password"
        }), 401

    # Create JWT token
    access_token = create_access_token(
        identity=str(user["id"])
    )

    return jsonify({

        "message": "Login successful",

        "user_id": user["id"],

        "username": user["username"],

        "access_token": access_token

    }), 200


# =========================================================
# PROFILE
# =========================================================

@app.route("/profile", methods=["GET"])
@jwt_required()
def profile():

    user_id = get_jwt_identity()

    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT id, username, email
        FROM users
        WHERE id = ?
        """,
        (user_id,)
    )

    user = cursor.fetchone()

    connection.close()

    if not user:

        return jsonify({
            "error": "User not found"
        }), 404

    return jsonify({

        "id": user["id"],

        "username": user["username"],

        "email": user["email"]

    }), 200


# =========================================================
# RUN APPLICATION
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5001,
        debug=True
    )