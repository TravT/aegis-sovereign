"""Wave 3 item 5: the tree build pauses the cyclic GC (20.7 s -> 11.9 s first build in a loaded process)."""
import gc
import threading

from core.graphview.service import gc_paused


def test_gc_is_paused_inside_and_restored_after():
    assert gc.isenabled()
    with gc_paused():
        assert not gc.isenabled()
    assert gc.isenabled()


def test_overlapping_pauses_from_two_threads_restore_only_at_the_end():
    inside, release = threading.Event(), threading.Event()

    def other():
        with gc_paused():
            inside.set()
            release.wait(5)

    t = threading.Thread(target=other)
    with gc_paused():
        t.start()
        inside.wait(5)
    assert not gc.isenabled()  # the other thread's build is still running
    release.set()
    t.join(5)
    assert gc.isenabled()


def test_a_disabled_gc_stays_disabled():
    gc.disable()
    try:
        with gc_paused():
            pass
        assert not gc.isenabled()
    finally:
        gc.enable()


def test_exception_inside_still_restores():
    try:
        with gc_paused():
            raise RuntimeError("build failed")
    except RuntimeError:
        pass
    assert gc.isenabled()
