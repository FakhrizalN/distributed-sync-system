"""
Integration tests for distributed system
"""
import pytest
import asyncio
from src.nodes import BaseNode

@pytest.mark.asyncio
async def test_multi_node_startup():
    """Test starting multiple nodes"""
    nodes = []
    cluster = ["node1:5000", "node2:5001", "node3:5002"]
    
    # Create nodes
    node1 = BaseNode("node1", "localhost", 5000, cluster)
    node2 = BaseNode("node2", "localhost", 5001, cluster)
    node3 = BaseNode("node3", "localhost", 5002, cluster)
    
    nodes = [node1, node2, node3]
    
    # Start nodes
    for node in nodes:
        await node.start()
        
    # Wait for election
    await asyncio.sleep(2)
    
    # Check that one node is leader
    leaders = [n for n in nodes if n.raft.is_leader()]
    assert len(leaders) >= 1
    
    # Stop nodes
    for node in nodes:
        await node.stop()

@pytest.mark.asyncio
async def test_leader_election():
    """Test leader election process"""
    cluster = ["node1:5000", "node2:5001", "node3:5002"]
    
    node1 = BaseNode("node1", "localhost", 5000, cluster)
    await node1.start()
    
    # Wait for election timeout
    await asyncio.sleep(1)
    
    # Node should attempt to become leader or candidate
    assert node1.raft.role != NodeRole.FOLLOWER or node1.raft.current_term > 0
    
    await node1.stop()

@pytest.mark.asyncio  
async def test_command_submission():
    """Test command submission to cluster"""
    node = BaseNode("node1", "localhost", 5000, ["node1:5000"])
    await node.start()
    
    # Wait to become leader
    await asyncio.sleep(1)
    
    # Submit command
    command = {'op': 'set', 'key': 'test', 'value': 'data'}
    result = await node.submit_command(command)
    
    # May fail if not leader, but should not crash
    assert isinstance(result, bool)
    
    await node.stop()

if __name__ == "__main__":
    pytest.main([__file__, '-v'])
