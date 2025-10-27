"""
Unit tests for Raft consensus algorithm
"""
import pytest
import asyncio
from src.consensus.raft import RaftNode, LogEntry, NodeRole

@pytest.mark.asyncio
async def test_raft_initialization():
    """Test Raft node initialization"""
    node = RaftNode("node1", ["node2", "node3"])
    assert node.node_id == "node1"
    assert node.role == NodeRole.FOLLOWER
    assert node.current_term == 0
    assert len(node.log) == 0

@pytest.mark.asyncio
async def test_election_timeout():
    """Test election timeout mechanism"""
    node = RaftNode("node1", ["node2", "node3"], election_timeout_range=(100, 200))
    
    await node.start()
    await asyncio.sleep(0.3)  # Wait for election timeout
    
    # Node should transition to candidate
    assert node.role in [NodeRole.CANDIDATE, NodeRole.LEADER]
    assert node.current_term >= 1
    
    await node.stop()

@pytest.mark.asyncio
async def test_log_entry_creation():
    """Test log entry creation"""
    entry = LogEntry(
        term=1,
        index=0,
        command={'op': 'set', 'key': 'test', 'value': 'value'}
    )
    
    assert entry.term == 1
    assert entry.index == 0
    assert entry.command['op'] == 'set'
    
    # Test serialization
    entry_dict = entry.to_dict()
    restored = LogEntry.from_dict(entry_dict)
    assert restored.term == entry.term
    assert restored.command == entry.command

@pytest.mark.asyncio
async def test_request_vote_handling():
    """Test RequestVote RPC handling"""
    node = RaftNode("node1", ["node2", "node3"])
    
    request = {
        'term': 2,
        'candidate_id': 'node2',
        'last_log_index': 0,
        'last_log_term': 0
    }
    
    response = await node.handle_request_vote(request)
    
    assert 'vote_granted' in response
    assert 'term' in response

@pytest.mark.asyncio
async def test_append_entries_handling():
    """Test AppendEntries RPC handling"""
    node = RaftNode("node1", ["node2", "node3"])
    
    request = {
        'term': 1,
        'leader_id': 'node2',
        'prev_log_index': -1,
        'prev_log_term': 0,
        'entries': [],
        'leader_commit': 0
    }
    
    response = await node.handle_append_entries(request)
    
    assert 'success' in response
    assert 'term' in response

if __name__ == "__main__":
    pytest.main([__file__, '-v'])
