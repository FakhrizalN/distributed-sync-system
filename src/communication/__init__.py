"""Communication package initialization"""
from .message_passing import MessagePassing, Message, MessageType, MessageHandler
from .failure_detector import FailureDetector, NodeState

__all__ = [
    'MessagePassing', 
    'Message', 
    'MessageType', 
    'MessageHandler',
    'FailureDetector',
    'NodeState'
]
