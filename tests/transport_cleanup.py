"""Drain test-owned helpers before deleting a verified test directory."""
import shutil
import errno
import time


def drain_bridge(bridge):
    # Test callers release their helper gate first. Production close only sends EOF.
    try:
        bridge.close()
        process = bridge._process
        if process is not None and hasattr(process, "wait"):
            process.wait(timeout=10)
        reader = bridge._reader_thread
        if reader is not None:
            reader.join(timeout=10)
            if reader.is_alive():
                raise RuntimeError(f"Reader did not stop; preserved {bridge.root}")
        if process is not None and getattr(process, "stdout", None) is not None:
            process.stdout.close()
    finally:
        if bridge._lease is not None:
            bridge._lease.close()
            bridge._lease = None


def remove_test_root(root, base):
    for attempt in range(3):
        # Recheck resolved boundaries before every recursive deletion attempt.
        root.resolve().relative_to(base.resolve())
        if root.is_symlink() or (hasattr(root, 'is_junction') and root.is_junction()) or root.resolve() == base.resolve():
            raise RuntimeError(f"Unsafe cleanup target: {root}")
        try:
            shutil.rmtree(root)
            return
        except OSError as error:
            transient = (isinstance(error, PermissionError) or
                         error.errno in (errno.EACCES, errno.EBUSY, errno.ETXTBSY) or
                         getattr(error, 'winerror', None) in (5, 32, 33))
            if transient and attempt < 2:
                time.sleep((.05, .15)[attempt])
                continue
            raise RuntimeError(f"Test cleanup failed after {attempt + 1} attempt(s); preserved {root}") from error
