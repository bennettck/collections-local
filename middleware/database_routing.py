import re
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from database import database_context


class DatabaseRoutingMiddleware(BaseHTTPMiddleware):
    """
    Route requests to different databases based on Host header.

    Subdomains:
    - golden.* -> Golden database (for evaluation/testing)
    - Everything else -> Production database

    Query Parameter Override:
    - ?_db=golden -> Golden database
    - ?_db=prod -> Production database

    The middleware sets request.state.active_database and request.state.db_path
    for debugging and adds X-Database-Context response header.
    """

    def __init__(self, app, prod_db_path: str, golden_db_path: str):
        """
        Initialize database routing middleware.

        Args:
            app: ASGI application
            prod_db_path: Path to production database
            golden_db_path: Path to golden database
        """
        super().__init__(app)
        self.prod_db_path = prod_db_path
        self.golden_db_path = golden_db_path

    async def dispatch(self, request: Request, call_next):
        """
        Process request with appropriate database context.

        Args:
            request: Incoming request
            call_next: Next middleware/handler in chain

        Returns:
            Response with X-Database-Context header added
        """
        # 1. Check query parameter override first (for testing convenience)
        db_override = request.query_params.get("_db")
        if db_override == "golden":
            db_path = self.golden_db_path
        elif db_override == "prod":
            db_path = self.prod_db_path
        else:
            # 2. Fall back to host-based routing
            host = request.headers.get("host", "localhost")
            db_path = self._determine_db_path(host)

        # 3. Set up database context for this request
        with database_context(db_path):
            # 4. Attach metadata to request state for debugging
            request.state.active_database = "golden" if db_path == self.golden_db_path else "production"
            request.state.db_path = db_path

            # 5. Process request
            response = await call_next(request)

            # 6. Add custom header to indicate which DB was used
            response.headers["X-Database-Context"] = request.state.active_database

            return response

    def _determine_db_path(self, host: str) -> str:
        """
        Determine database path from host header.

        Args:
            host: Host header value (e.g., "golden.localhost:8000", "api.example.com")

        Returns:
            Database path string
        """
        # Strip port if present (e.g., "golden.localhost:8000" -> "golden.localhost")
        hostname = re.sub(r':\d+$', '', host)

        # Check for golden subdomain (case-insensitive)
        # Matches: golden.localhost, golden.api.example.com, etc.
        if hostname.lower().startswith("golden."):
            return self.golden_db_path

        # Default to production for all other hosts
        # Includes: localhost, 127.0.0.1, api.example.com, etc.
        return self.prod_db_path
