#!/usr/bin/env python3
"""
Simple Flask server with Range request support for serving PMTiles files.
This server properly handles HTTP Range requests which are required for PMTiles to work.
"""

import os
from flask import Flask, send_from_directory, request, Response
from werkzeug.exceptions import RequestedRangeNotSatisfiable

app = Flask(__name__)

# Base directory for serving files
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


@app.route('/')
def index():
    """Serve the PMTiles map by default."""
    return send_from_directory(BASE_DIR, 'index.html')


@app.route('/<path:path>')
def serve_file(path):
    """
    Serve files with Range request support.
    This is essential for PMTiles to work properly.
    """
    file_path = os.path.join(BASE_DIR, path)

    # Check if file exists
    if not os.path.exists(file_path):
        return "File not found", 404

    # Get file size
    file_size = os.path.getsize(file_path)

    # Check if this is a Range request
    range_header = request.headers.get('Range')

    if not range_header:
        # Normal request - send entire file
        return send_from_directory(
            BASE_DIR,
            path,
            mimetype=get_mimetype(path)
        )

    # Parse Range header
    try:
        byte_range = parse_range_header(range_header, file_size)
        if byte_range is None:
            raise RequestedRangeNotSatisfiable()

        start, end = byte_range
        length = end - start + 1

        # Read the requested byte range
        with open(file_path, 'rb') as f:
            f.seek(start)
            data = f.read(length)

        # Create response with 206 Partial Content status
        response = Response(
            data,
            206,
            mimetype=get_mimetype(path),
            direct_passthrough=True
        )

        # Set Range-related headers
        response.headers['Content-Range'] = f'bytes {start}-{end}/{file_size}'
        response.headers['Accept-Ranges'] = 'bytes'
        response.headers['Content-Length'] = str(length)

        # Add CORS headers
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Range'

        return response

    except Exception as e:
        print(f"Error handling range request: {e}")
        return "Range request failed", 416


def parse_range_header(range_header, file_size):
    """
    Parse HTTP Range header.
    Returns (start, end) tuple or None if invalid.
    """
    if not range_header.startswith('bytes='):
        return None

    range_spec = range_header[6:]

    # Handle single range (e.g., "bytes=0-1023")
    if ',' in range_spec:
        # Multiple ranges not supported for simplicity
        return None

    parts = range_spec.split('-')
    if len(parts) != 2:
        return None

    try:
        # Parse start and end
        start_str, end_str = parts

        if start_str == '':
            # Suffix range (e.g., "bytes=-500" means last 500 bytes)
            if end_str == '':
                return None
            suffix_length = int(end_str)
            start = max(0, file_size - suffix_length)
            end = file_size - 1
        elif end_str == '':
            # Open-ended range (e.g., "bytes=500-" means from 500 to end)
            start = int(start_str)
            end = file_size - 1
        else:
            # Normal range (e.g., "bytes=0-1023")
            start = int(start_str)
            end = int(end_str)

        # Validate range
        if start < 0 or end >= file_size or start > end:
            return None

        return (start, end)

    except (ValueError, TypeError):
        return None


def get_mimetype(path):
    """Get MIME type based on file extension."""
    ext = os.path.splitext(path)[1].lower()

    mime_types = {
        '.html': 'text/html',
        '.css': 'text/css',
        '.js': 'application/javascript',
        '.json': 'application/json',
        '.pmtiles': 'application/octet-stream',
        '.png': 'image/png',
        '.jpg': 'image/jpeg',
        '.jpeg': 'image/jpeg',
        '.gif': 'image/gif',
        '.svg': 'image/svg+xml',
    }

    return mime_types.get(ext, 'application/octet-stream')


@app.after_request
def add_cors_headers(response):
    """Add CORS headers to all responses."""
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, HEAD, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Range'
    response.headers['Access-Control-Expose-Headers'] = 'Content-Range, Accept-Ranges, Content-Length'
    return response


if __name__ == '__main__':
    print("Starting Flask server with Range request support...")
    print("Server running at: http://localhost:8082")
    print("Open http://localhost:8082 in your browser to view the map")
    print("\nPress Ctrl+C to stop the server")

    app.run(host='0.0.0.0', port=8082, debug=True)
