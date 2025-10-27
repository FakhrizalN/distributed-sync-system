"""Consensus package initialization"""
from .raft import RaftNode, LogEntry, NodeRole

__all__ = ['RaftNode', 'LogEntry', 'NodeRole']
