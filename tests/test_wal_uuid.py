import pytest
import threading
from burnlens.storage.models import uuid7

def test_uuid7_sorting_and_format():
    id1 = uuid7()
    id2 = uuid7()
    
    # Verify format matches standard UUID (8-4-4-4-12 hex chars)
    parts1 = id1.split("-")
    assert len(parts1) == 5
    assert len(parts1[0]) == 8
    assert len(parts1[1]) == 4
    assert len(parts1[2]) == 4
    assert len(parts1[3]) == 4
    assert len(parts1[4]) == 12
    
    # Version should be 7 (first char of 3rd part)
    assert parts1[2][0] == "7"
    
    # Variant should be RFC 9562 variant 2 (top bits 10, i.e., 8, 9, a, or b)
    assert parts1[3][0] in {"8", "9", "a", "b"}
    
    # Chronological sort order: id2 should be greater than id1
    assert id2 > id1

def test_uuid7_monotonicity_large_sequential():
    """Verify that a large number of sequentially generated UUIDv7s are strictly monotonic."""
    count = 1000
    uuids = [uuid7() for _ in range(count)]
    
    for i in range(1, count):
        assert uuids[i] > uuids[i - 1], f"UUID at index {i} ({uuids[i]}) is not greater than the one at {i - 1} ({uuids[i - 1]})"

def test_uuid7_thread_safety():
    """Verify that concurrent uuid7 generation is thread-safe and produces unique IDs."""
    num_threads = 10
    uuids_per_thread = 200
    all_uuids = []
    lock = threading.Lock()
    
    def worker():
        local_uuids = [uuid7() for _ in range(uuids_per_thread)]
        with lock:
            all_uuids.extend(local_uuids)
            
    threads = []
    for _ in range(num_threads):
        t = threading.Thread(target=worker)
        threads.append(t)
        t.start()
        
    for t in threads:
        t.join()
        
    # Total generated
    expected_total = num_threads * uuids_per_thread
    assert len(all_uuids) == expected_total
    
    # Verify all are unique (no collisions due to race conditions)
    unique_uuids = set(all_uuids)
    assert len(unique_uuids) == expected_total
    
    # Verify each has the correct UUIDv7 format
    for uid in all_uuids:
        parts = uid.split("-")
        assert len(parts) == 5
        assert len(parts[0]) == 8
        assert len(parts[1]) == 4
        assert len(parts[2]) == 4
        assert len(parts[3]) == 4
        assert len(parts[4]) == 12
        assert parts[2][0] == "7"
        assert parts[3][0] in {"8", "9", "a", "b"}
