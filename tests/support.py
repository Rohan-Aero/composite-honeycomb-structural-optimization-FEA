"""Shared test helpers: the real repository data is imported once per test run; every test gets a private copy."""
import atexit
import hashlib
import shutil
import tempfile
import zipfile
from pathlib import Path

from plm import db, ingest, workflow

ROOT = Path(__file__).resolve().parent.parent
_base = {}


def base_db_path():
    if "path" not in _base:
        tmp = Path(tempfile.mkdtemp(prefix="plm_test_"))
        atexit.register(shutil.rmtree, tmp, True)
        conn = db.init_db(tmp / "base.sqlite")
        ingest.import_all(conn, ROOT)
        workflow.seed_demo(conn, ROOT)
        conn.close()
        _base["path"] = tmp / "base.sqlite"
    return _base["path"]


def fresh_db(testcase):
    """Private, writable copy of the imported database (closed automatically)."""
    tmp = Path(tempfile.mkdtemp(prefix="plm_case_"))
    testcase.addCleanup(shutil.rmtree, tmp, True)
    shutil.copy(base_db_path(), tmp / "t.sqlite")
    conn = db.connect(tmp / "t.sqlite")
    testcase.addCleanup(conn.close)
    return conn


def source_hashes(root=ROOT):
    """SHA-256 of every original project file (not the files added by this extension)."""
    out = {}
    for r in ingest.SOURCE_ROOTS:
        p = Path(root) / r
        for f in ([p] if p.is_file() else sorted(p.rglob("*"))):
            if f.is_file():
                out[f.relative_to(root).as_posix()] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def member_sha(rel, member, root=ROOT):
    with zipfile.ZipFile(Path(root) / rel) as zf:
        return hashlib.sha256(zf.read(member)).hexdigest()
