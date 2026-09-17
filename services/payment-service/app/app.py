from flask import Flask, request, jsonify
from flask_cors import CORS

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
    "payment_service_requests_total",
    "Total number of requests handled by Payment Service",
    ["method", "endpoint", "status"]
)

REQUEST_LATENCY = Histogram(
    "payment_service_request_latency_seconds",
    "Request latency of Payment Service",
    ["method", "endpoint"]
)


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
        "service": "payment-service",
        "status": "UP"
    }), 200


# =========================================================
# VERSION
# =========================================================

@app.route("/version", methods=["GET"])
def version():

    return jsonify({
        "service": "payment-service",
        "version": "1.0.0"
    }), 200


# =========================================================
# CREATE PAYMENT
# =========================================================

@app.route("/api/payments", methods=["POST"])
def create_payment():

    data = request.get_json()

    if not data:

        return jsonify({
            "error": "Request body is required"
        }), 400

    order_id = data.get("orderId")
    user_id = data.get("userId")
    amount = data.get("amount")

    # Validate order ID
    if not order_id:

        return jsonify({
            "error": "Order ID is required"
        }), 400

    # Validate user ID
    if not user_id:

        return jsonify({
            "error": "User ID is required"
        }), 400

    # Validate amount
    if not amount or amount <= 0:

        return jsonify({
            "error": "Amount must be greater than 0"
        }), 400

    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        INSERT INTO payments
        (
            order_id,
            user_id,
            amount,
            status
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            order_id,
            user_id,
            amount,
            "SUCCESS"
        )
    )

    payment_id = cursor.lastrowid

    connection.commit()
    connection.close()

    return jsonify({

        "message": "Payment processed successfully",

        "paymentId": payment_id,

        "orderId": order_id,

        "userId": user_id,

        "amount": amount,

        "status": "SUCCESS"

    }), 201


# =========================================================
# GET PAYMENT
# =========================================================

@app.route(
    "/api/payments/<int:payment_id>",
    methods=["GET"]
)
def get_payment(payment_id):

    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            id,
            order_id,
            user_id,
            amount,
            status
        FROM payments
        WHERE id = ?
        """,
        (payment_id,)
    )

    payment = cursor.fetchone()

    connection.close()

    if not payment:

        return jsonify({
            "error": "Payment not found"
        }), 404

    return jsonify({

        "paymentId": payment["id"],

        "orderId": payment["order_id"],

        "userId": payment["user_id"],

        "amount": payment["amount"],

        "status": payment["status"]

    }), 200


# =========================================================
# GET PAYMENTS FOR ORDER
# =========================================================

@app.route(
    "/api/payments/order/<int:order_id>",
    methods=["GET"]
)
def get_order_payments(order_id):

    connection = get_db_connection()
    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT
            id,
            order_id,
            user_id,
            amount,
            status
        FROM payments
        WHERE order_id = ?
        ORDER BY id DESC
        """,
        (order_id,)
    )

    payments = cursor.fetchall()

    connection.close()

    result = []

    for payment in payments:

        result.append({

            "paymentId": payment["id"],

            "orderId": payment["order_id"],

            "userId": payment["user_id"],

            "amount": payment["amount"],

            "status": payment["status"]

        })

    return jsonify(result), 200


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=8083,
        debug=True
    )