import ssl
from typing import Any
from uuid import uuid4

from sqlalchemy.engine import URL, make_url

# libpq's "require" encrypts but never checks the server certificate, which leaves room for
# a man-in-the-middle. These modes are upgraded to full certificate + hostname verification.
_VERIFIED_MODES = {"require", "verify-ca", "verify-full"}


def verified_ssl_context() -> ssl.SSLContext:
    """TLS context that checks the certificate chain (OS trust store) and the hostname."""
    return ssl.create_default_context()


def to_asyncpg_url(raw: str) -> tuple[URL, dict[str, Any]]:
    """Turn a libpq-style URL (what Neon gives you) into an asyncpg URL plus connect_args.

    asyncpg rejects libpq-only query params such as sslmode and channel_binding,
    so SSL is moved into connect_args instead.
    """
    url = make_url(raw)
    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)

    connect_args: dict[str, Any] = {}
    is_neon = bool(url.host and url.host.endswith(".neon.tech"))
    if is_neon or sslmode in _VERIFIED_MODES:
        connect_args["ssl"] = verified_ssl_context()  # Neon refuses unencrypted connections anyway
    elif sslmode:
        connect_args["ssl"] = sslmode

    if url.host and "-pooler." in url.host:
        # Neon's pooled endpoint runs PgBouncer in transaction mode, which can't
        # share named prepared statements between clients.
        connect_args["statement_cache_size"] = 0
        connect_args["prepared_statement_name_func"] = lambda: f"__asyncpg_{uuid4()}__"
        query["prepared_statement_cache_size"] = "0"

    return url.set(drivername="postgresql+asyncpg", query=query), connect_args
