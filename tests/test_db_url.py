import ssl

from app.db.url import to_asyncpg_url

NEON_DIRECT = "postgresql://alex:s3cret@ep-cool-name-123456.eu-central-1.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
NEON_POOLED = "postgresql://alex:s3cret@ep-cool-name-123456-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require"


def assert_verified(ctx):
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_neon_direct_url_moves_ssl_to_connect_args():
    url, connect_args = to_asyncpg_url(NEON_DIRECT)
    assert url.drivername == "postgresql+asyncpg"
    assert "sslmode" not in url.query
    assert "channel_binding" not in url.query
    assert set(connect_args) == {"ssl"}
    assert_verified(connect_args["ssl"])
    assert url.password == "s3cret"


def test_neon_pooled_url_disables_prepared_statement_cache():
    url, connect_args = to_asyncpg_url(NEON_POOLED)
    assert_verified(connect_args["ssl"])
    assert connect_args["statement_cache_size"] == 0
    assert url.query["prepared_statement_cache_size"] == "0"
    name_func = connect_args["prepared_statement_name_func"]
    assert name_func() != name_func()


def test_neon_url_without_sslmode_still_verifies_tls():
    _, connect_args = to_asyncpg_url("postgresql://a:b@ep-x.us-east-2.aws.neon.tech/neondb")
    assert_verified(connect_args["ssl"])


def test_sslmode_require_is_upgraded_to_verification_for_any_host():
    _, connect_args = to_asyncpg_url("postgresql://a:b@db.example.com/app?sslmode=require")
    assert_verified(connect_args["ssl"])


def test_local_url_without_ssl_is_left_alone():
    url, connect_args = to_asyncpg_url("postgresql+asyncpg://a:b@localhost:5432/skillbridge")
    assert url.drivername == "postgresql+asyncpg"
    assert connect_args == {}


def test_password_with_special_characters_survives():
    url, _ = to_asyncpg_url("postgresql://a:p%40ss%3Aword@ep-x.aws.neon.tech/neondb")
    assert url.password == "p@ss:word"
