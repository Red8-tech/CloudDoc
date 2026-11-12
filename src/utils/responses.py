"""Build API Gateway responses in the shape documented in docs/api-contract.md."""
import json

STATUS_BY_CODE = {
    "INVALID_REQUEST": 400,
    "INVALID_FILE_TYPE": 400,
    "FILE_TOO_LARGE": 400,
    "NOT_FOUND": 404,
    "INTERNAL_ERROR": 500,
}


def json_response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def error_response(code: str, message: str) -> dict:
    status_code = STATUS_BY_CODE.get(code, 500)
    return json_response(status_code, {"error": {"code": code, "message": message}})