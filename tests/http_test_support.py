"""Small complete-response fixture for anonymous urllib client tests."""
import io


class Response(io.BytesIO):
    def __init__(self, body=b"page", status=200, headers=None):
        super().__init__(body)
        self.status = status
        self.headers = {} if headers is None else headers
