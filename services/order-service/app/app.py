from flask import Flask, request, jsonify
from flask_cors import CORS
import requests

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

CORS(app)


# =========================================================
# PROMETHEUS METRICS
# =========================================================

REQUEST_COUNT = Counter(
    "order_service_requests_total",
    "Total number of requests handled by Order Service",
    ["method", "endpoint", "status"]
)

REQUEST_LATENCY = Histogram(
    "order_service_request_latency_seconds",
    "Request latency of Order Service",
    ["method", "endpoint"]
)


# =========================================================
# PAYMENT SERVICE
# =========================================================

PAYMENT_SERVICE_URL = "http://payment-service:8083"


# =========================================================
# DATABASE
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
# HEALTH
# =========================================================

@app.route("/health", methods=["GET"])
def health():

    return jsonify({
        "service": "order-service",
        "status": "UP"
    }), 200


# =========================================================
# VERSION
# =========================================================

@app.route("/version", methods=["GET"])
def version():

    return jsonify({
        "service": "order-service",
        "version": "1.0.0"
    }), 200


# =========================================================
# CREATE ORDER
# =========================================================

@app.route("/api/orders", methods=["POST"])
def create_order():

    data = request.get_json()

    if not data:
        return jsonify({
            "error": "Request body is required"
        }), 400

    user_id = data.get("userId")
    item_name = data.get("itemName")
    quantity = data.get("quantity")
    amount = data.get("amount")

    # -----------------------------------------------------
    # VALIDATION
    # -----------------------------------------------------

    if not user_id:
        return jsonify({
            "error": "User ID is required"
        }), 400

    if not item_name:
        return jsonify({
            "error": "Item name is required"
        }), 400

    if not quantity or quantity < 1:
        return jsonify({
            "error": "Quantity must be at least 1"
        }), 400

    if not amount or amount <= 0:
        return jsonify({
            "error": "Amount must be greater than 0"
        }), 400

    # -----------------------------------------------------
    # CREATE ORDER AS PENDING
    # -----------------------------------------------------

    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO orders
        (
            user_id,
            item_name,
            quantity,
            amount,
            status
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            user_id,
            item_name,
            quantity,
            amount,
            "PENDING"
        )
    )

    order_id = cursor.lastrowid

    connection.commit()
    connection.close()

    # -----------------------------------------------------
    # CALL PAYMENT SERVICE
    # -----------------------------------------------------

    try:

        payment_response = requests.post(
            f"{PAYMENT_SERVICE_URL}/api/payments",
            json={
                "orderId": order_id,
                "userId": user_id,
                "amount": amount
            },
            timeout=5
        )

        # -------------------------------------------------
        # PAYMENT SUCCESS
        # -------------------------------------------------

        if payment_response.status_code == 201:

            payment_data = payment_response.json()

            connection = get_db_connection()
            cursor = connection.cursor()

            cursor.execute(
                """
                UPDATE orders
                SET status = ?
                WHERE id = ?
                """,
                (
                    "COMPLETED",
                    order_id
                )
            )

            connection.commit()
            connection.close()

            return jsonify({

                "message": "Order created successfully",

                "orderId": order_id,

                "userId": user_id,

                "itemName": item_name,

                "quantity": quantity,

                "amount": amount,

                "status": "COMPLETED",

                "paymentStatus": payment_data.get(
                    "status",
                    "SUCCESS"
                ),

                "paymentId": payment_data.get(
                    "paymentId"
                )

            }), 201

        # -------------------------------------------------
        # PAYMENT FAILED
        # -------------------------------------------------

        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE orders
            SET status = ?
            WHERE id = ?
            """,
            (
                "FAILED",
                order_id
            )
        )

        connection.commit()
        connection.close()

        return jsonify({

            "message": "Payment failed",

            "orderId": order_id,

            "status": "FAILED",

            "paymentStatus": "FAILED"

        }), 502

    # -----------------------------------------------------
    # PAYMENT SERVICE UNREACHABLE
    # -----------------------------------------------------

    except requests.exceptions.RequestException:

        connection = get_db_connection()
        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE orders
            SET status = ?
            WHERE id = ?
            """,
            (
                "FAILED",
                order_id
            )
        )

        connection.commit()
        connection.close()

        return jsonify({

            "message": "Payment service unavailable",

            "orderId": order_id,

            "status": "FAILED",

            "paymentStatus": "UNAVAILABLE"

        }), 503


# =========================================================
# GET ORDERS
# =========================================================

@app.route("/api/orders", methods=["GET"])
def get_orders():

    user_id = request.args.get("userId")

    connection = get_db_connection()
    cursor = connection.cursor()

    if user_id:

        cursor.execute(
            """
            SELECT
                id,
                user_id,
                item_name,
                quantity,
                amount,
                status
            FROM orders
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user_id,)
        )

    else:

        cursor.execute(
            """
            SELECT
                id,
                user_id,
                item_name,
                quantity,
                amount,
                status
            FROM orders
            ORDER BY id DESC
            """
        )

    orders = cursor.fetchall()

    connection.close()

    result = []

    for order in orders:

        result.append({

            "id": order["id"],

            "userId": order["user_id"],

            "itemName": order["item_name"],

            "quantity": order["quantity"],

            "amount": order["amount"],

            "status": order["status"]

        })

    return jsonify(result), 200


# =========================================================
# GET SINGLE ORDER
# =========================================================

@app.route(
    "/api/orders/<int:order_id>",
    methods=["GET"]
)
def get_order(order_id):

    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            id,
            user_id,
            item_name,
            quantity,
            amount,
            status
        FROM orders
        WHERE id = ?
        """,
        (order_id,)
    )

    order = cursor.fetchone()

    connection.close()

    if not order:

        return jsonify({
            "error": "Order not found"
        }), 404

    return jsonify({

        "id": order["id"],

        "userId": order["user_id"],

        "itemName": order["item_name"],

        "quantity": order["quantity"],

        "amount": order["amount"],

        "status": order["status"]

    }), 200


# =========================================================
# CIRCUIT BREAKER
# =========================================================

@app.route(
    "/api/orders/circuit-breaker",
    methods=["GET"]
)
def circuit_breaker():

    return jsonify({
        "status": "CLOSED"
    }), 200


# =========================================================
# CHAOS STATUS
# =========================================================

@app.route(
    "/api/chaos/status",
    methods=["GET"]
)
def chaos_status():

    return jsonify({

        "active": False,

        "description": ""

    }), 200


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=8082,
        debug=True
    )