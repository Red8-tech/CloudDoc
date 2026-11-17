"""Load test for a deployed CloudDoc stack.

Usage from the repo root:
    $env:API_URL = "https://<api-id>.execute-api.ap-southeast-2.amazonaws.com/dev"
    python scripts/load_test.py 25
"""
import io
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import requests
from pypdf import PdfWriter

API_URL = os.environ.get("API_URL", "").rstrip("/")
PACE_SECONDS = 0.25  # about 4 requests per second, under the API throttle of 5 per second
TIMEOUT = 60


def make_pdf(pages: int) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def build_files(count: int) -> list:
    """Mostly valid PDFs and TXT files, plus fake PDFs that must end up FAILED."""
    files = []
    for i in range(count):
        if i % 5 == 4:
            files.append((f"fake-{i}.pdf", "application/pdf", b"this is not a pdf", "FAILED"))
        elif i % 2 == 0:
            files.append((f"doc-{i}.pdf", "application/pdf", make_pdf(1 + i % 3), "COMPLETED"))
        else:
            files.append((f"note-{i}.txt", "text/plain", f"note number {i}".encode(), "COMPLETED"))
    return files


def upload(filename: str, content_type: str, content: bytes) -> str:
    response = requests.post(
        f"{API_URL}/documents",
        json={"filename": filename, "content_type": content_type, "size_bytes": len(content)},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()
    form = data["upload"]
    sent = requests.post(
        form["url"], data=form["fields"], files={"file": (filename, content)}, timeout=TIMEOUT
    )
    if sent.status_code != 204:
        raise RuntimeError(f"S3 rejected {filename}: HTTP {sent.status_code}")
    return data["document_id"]


def seconds_between(start_iso: str, end_iso: str) -> float:
    fmt = "%Y-%m-%dT%H:%M:%SZ"
    return (datetime.strptime(end_iso, fmt) - datetime.strptime(start_iso, fmt)).total_seconds()


def run_batch(count: int):
    expected = {}
    began = time.time()
    for filename, content_type, content, outcome in build_files(count):
        document_id = upload(filename, content_type, content)
        expected[document_id] = (filename, outcome)
        time.sleep(PACE_SECONDS)
    print(f"Uploaded {count} documents in {time.time() - began:.1f}s")

    results = {}
    deadline = time.time() + 180
    while len(results) < len(expected) and time.time() < deadline:
        for document_id in expected:
            if document_id in results:
                continue
            response = requests.get(f"{API_URL}/documents/{document_id}", timeout=TIMEOUT)
            if response.status_code == 200 and response.json()["status"] in ("COMPLETED", "FAILED"):
                results[document_id] = response.json()
            time.sleep(PACE_SECONDS)
    return expected, results, time.time() - began


def report(expected: dict, results: dict, wall_seconds: float) -> bool:
    unfinished = [name for doc_id, (name, _) in expected.items() if doc_id not in results]
    wrong = [
        f"{name}: expected {outcome}, got {results[doc_id]['status']}"
        for doc_id, (name, outcome) in expected.items()
        if doc_id in results and results[doc_id]["status"] != outcome
    ]
    latencies = [seconds_between(r["uploaded_at"], r["processed_at"]) for r in results.values()]

    print(f"\nFinished {len(results)} of {len(expected)} in {wall_seconds:.1f}s total")
    print(f"  COMPLETED: {sum(r['status'] == 'COMPLETED' for r in results.values())}")
    print(f"  FAILED:    {sum(r['status'] == 'FAILED' for r in results.values())}")
    if latencies:
        print(f"  request-to-processed seconds: min {min(latencies):.0f}, "
              f"median {statistics.median(latencies):.0f}, max {max(latencies):.0f}")
    for line in unfinished:
        print(f"  NOT FINISHED: {line}")
    for line in wrong:
        print(f"  WRONG OUTCOME: {line}")
    return not unfinished and not wrong


def burst(count: int = 150) -> None:
    """Fire many requests at once to show the API throttle (HTTP 429)."""
    time.sleep(5)  # let the throttle refill first
    url = f"{API_URL}/documents/00000000-0000-4000-8000-000000000000"
    with ThreadPoolExecutor(max_workers=count) as pool:
        codes = list(pool.map(lambda _: requests.get(url, timeout=TIMEOUT).status_code, range(count)))
    counts = {code: codes.count(code) for code in sorted(set(codes))}
    print(f"\nBurst of {count} simultaneous requests -> {counts}")
    print("  404 = reached the function (unknown ID), 429 = rejected by the API throttle")


def main() -> int:
    if not API_URL:
        print("Set API_URL first.")
        return 1
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    expected, results, wall = run_batch(count)
    ok = report(expected, results, wall)
    burst()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())