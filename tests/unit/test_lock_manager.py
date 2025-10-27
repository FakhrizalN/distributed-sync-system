"""
Unit tests for distributed lock manager
"""
import pytest
import asyncio
from src.nodes.lock_manager import LockManager, LockType

@pytest.mark.asyncio
async def test_lock_manager_initialization():
    """Test lock manager initialization"""
    manager = LockManager("node1", "localhost", 5000, ["node1:5000", "node2:5001"])
    assert manager.node_id == "node1"
    assert len(manager.locks) == 0

@pytest.mark.asyncio
async def test_exclusive_lock_acquisition():
    """Test exclusive lock acquisition"""
    manager = LockManager("node1", "localhost", 5000, ["node1:5000"])
    
    # Test internal lock granting
    granted = manager._try_grant_lock("resource1", "node1", LockType.EXCLUSIVE)
    assert granted == True
    assert "resource1" in manager.locks
    assert "node1" in manager.locks["resource1"].holders

@pytest.mark.asyncio
async def test_shared_lock_acquisition():
    """Test shared lock acquisition"""
    manager = LockManager("node1", "localhost", 5000, ["node1:5000"])
    
    # Grant first shared lock
    granted1 = manager._try_grant_lock("resource1", "node1", LockType.SHARED)
    assert granted1 == True
    
    # Grant second shared lock
    granted2 = manager._try_grant_lock("resource1", "node2", LockType.SHARED)
    assert granted2 == True
    
    assert len(manager.locks["resource1"].holders) == 2

@pytest.mark.asyncio
async def test_lock_conflict():
    """Test lock conflict detection"""
    manager = LockManager("node1", "localhost", 5000, ["node1:5000"])
    
    # Grant exclusive lock
    granted1 = manager._try_grant_lock("resource1", "node1", LockType.EXCLUSIVE)
    assert granted1 == True
    
    # Try to acquire conflicting lock
    granted2 = manager._try_grant_lock("resource1", "node2", LockType.SHARED)
    assert granted2 == False
    
    # Check waiter list
    assert len(manager.locks["resource1"].waiters) == 1

@pytest.mark.asyncio
async def test_lock_release():
    """Test lock release"""
    manager = LockManager("node1", "localhost", 5000, ["node1:5000"])
    
    # Acquire lock
    manager._try_grant_lock("resource1", "node1", LockType.EXCLUSIVE)
    
    # Release lock
    manager._release_lock_internal("resource1", "node1")
    
    # Verify lock is released
    assert "resource1" not in manager.locks or len(manager.locks["resource1"].holders) == 0

@pytest.mark.asyncio
async def test_deadlock_detection():
    """Test deadlock detection"""
    manager = LockManager("node1", "localhost", 5000, ["node1:5000"])
    
    # Create circular wait
    manager.wait_for_graph["node1"] = {"node2"}
    manager.wait_for_graph["node2"] = {"node3"}
    manager.wait_for_graph["node3"] = {"node1"}
    
    deadlocks = manager._detect_deadlocks()
    assert len(deadlocks) > 0

if __name__ == "__main__":
    pytest.main([__file__, '-v'])
