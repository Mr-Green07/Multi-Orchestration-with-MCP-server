"""Unit tests: calculator security, workspace path validation, SQL enforcement."""

import math

import pytest

import security as security
from security import SecurityError


# --------------------------- calculator security ---------------------------
def test_calculator_basic_arithmetic():
    assert security.safe_eval("25 * 4") == 100
    assert security.safe_eval("2 + 3 * 4") == 14
    assert security.safe_eval("(2 + 3) * 4") == 20
    assert security.safe_eval("10 / 4") == 2.5
    assert security.safe_eval("17 % 5") == 2
    assert security.safe_eval("2 ** 10") == 1024


def test_calculator_math_functions():
    assert security.safe_eval("sqrt(16)") == 4
    assert math.isclose(security.safe_eval("log(e)"), 1.0)
    assert security.safe_eval("max(1, 7, 3)") == 7
    assert security.safe_eval("abs(-5)") == 5


@pytest.mark.parametrize("expr", [
    "__import__('os')",          # imports
    "open('/etc/passwd')",       # file access
    "os.system('ls')",           # attribute access + shell
    "(1).__class__",             # attribute access
    "lambda: 1",                 # function definition
    "exec('x=1')",               # arbitrary code
    "eval('2+2')",               # nested eval
    "x + 1",                     # unknown name
    "[i for i in range(3)]",     # comprehension
    "2 ** 100000",               # oversized exponent (DoS)
])
def test_calculator_rejects_dangerous(expr):
    with pytest.raises(SecurityError):
        security.safe_eval(expr)


def test_calculator_division_by_zero():
    with pytest.raises(ZeroDivisionError):
        security.safe_eval("1/0")


# --------------------------- workspace path validation ---------------------
def test_path_valid_inside_workspace():
    p = security.resolve_in_workspace("notes/todo.txt")
    assert str(p).startswith(str(security.WORKSPACE_DIR.resolve()))


@pytest.mark.parametrize("bad", [
    "../security.py",
    "../../etc/passwd",
    "/etc/passwd",
    "\\\\server\\share\\file",
    "C:\\Windows\\system32",
    "sub/../../escape.txt",
])
def test_path_rejects_traversal_and_absolute(bad):
    with pytest.raises(SecurityError):
        security.resolve_in_workspace(bad)


def test_sanitize_filename():
    assert security.sanitize_filename("../../etc/passwd") == "passwd.md"
    assert security.sanitize_filename("my report!.md") == "my_report_.md"
    assert security.sanitize_filename("data.txt") == "data.txt"
    assert security.sanitize_filename("") == "report.md"


# --------------------------- SQL read-only enforcement ---------------------
@pytest.mark.parametrize("sql", [
    "SELECT * FROM users",
    "select name from users where age > 20",
    "PRAGMA table_info(users)",
    "WITH t AS (SELECT 1) SELECT * FROM t",
])
def test_sql_allows_readonly(sql):
    assert security.validate_sql(sql)


@pytest.mark.parametrize("sql", [
    "INSERT INTO users VALUES (1,'x',2)",
    "UPDATE users SET age=1",
    "DELETE FROM users",
    "DROP TABLE users",
    "ALTER TABLE users ADD COLUMN x TEXT",
    "CREATE TABLE t (id INT)",
    "ATTACH DATABASE 'x.db' AS y",
    "SELECT 1; DROP TABLE users",   # multiple statements
])
def test_sql_rejects_writes(sql):
    with pytest.raises(SecurityError):
        security.validate_sql(sql)
