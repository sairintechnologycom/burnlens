import pytest
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
