"""
Main entry point for Distributed Synchronization System
"""
import asyncio
import logging
import signal
import sys
import os
from pathlib import Path

from src.nodes.base_node import BaseNode
from src.utils.config import Config

# Create logs directory if it doesn't exist
LOG_DIR = Path('logs')
LOG_DIR.mkdir(exist_ok=True)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / 'distributed_system.log')
    ]
)

logger = logging.getLogger(__name__)


class DistributedSystem:
    """Main system orchestrator"""
    
    def __init__(self):
        self.config = Config()
        self.node = None
        self.running = False
        
    async def start(self):
        """Start the distributed system node"""
        try:
            logger.info(f"Starting node {self.config.NODE_ID}")
            
            # Get all cluster nodes including self
            cluster_nodes = []
            for node_str in self.config.CLUSTER_NODES.split(','):
                node_str = node_str.strip()
                if ':' in node_str:
                    host, port = node_str.rsplit(':', 1)
                    cluster_nodes.append({'host': host, 'port': int(port)})
            
            # Initialize node
            self.node = BaseNode(
                node_id=self.config.NODE_ID,
                host=self.config.NODE_HOST,
                port=self.config.NODE_PORT,
                cluster_nodes=cluster_nodes
            )
            
            # Start node
            await self.node.start()
            self.running = True
            
            logger.info(f"Node {self.config.NODE_ID} started successfully on {self.config.NODE_HOST}:{self.config.NODE_PORT}")
            logger.info(f"Connected to peers: {self.config.get_peers()}")
            
            # Keep running
            while self.running:
                await asyncio.sleep(1)
                
        except Exception as e:
            logger.error(f"Error starting system: {e}", exc_info=True)
            raise
            
    async def stop(self):
        """Stop the distributed system"""
        logger.info("Stopping distributed system...")
        self.running = False
        
        if self.node:
            await self.node.stop()
            
        logger.info("System stopped")


async def main():
    """Main entry point"""
    system = DistributedSystem()
    
    # Setup signal handlers
    def signal_handler(sig, frame):
        logger.info("Received shutdown signal")
        asyncio.create_task(system.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await system.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await system.stop()


if __name__ == "__main__":
    # Ensure data directory exists
    DATA_DIR = Path('data')
    DATA_DIR.mkdir(exist_ok=True)
    
    # Run the system
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("System shutdown complete")
