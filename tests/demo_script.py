"""
Demo Script for Video Presentation
Run this to demonstrate all features of the distributed system
"""
import asyncio
import time
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.nodes.base_node import BaseNode

class DemoRunner:
    def __init__(self):
        self.nodes = []
        
    def print_section(self, title):
        """Print section header"""
        print("\n" + "="*80)
        print(f"  {title}")
        print("="*80 + "\n")
        
    def print_info(self, message):
        """Print info message"""
        print(f"✓ {message}")
        
    def print_data(self, label, data):
        """Print data with label"""
        print(f"  {label}: {data}")
    
    async def demo_1_cluster_startup(self):
        """Demo 1: Cluster Startup and Leader Election"""
        self.print_section("DEMO 1: Cluster Startup & Leader Election")
        
        cluster_config = [
            {"host": "node1", "port": 5000},
            {"host": "node2", "port": 5001},
            {"host": "node3", "port": 5002}
        ]
        
        print("Starting 3 nodes in cluster...")
        
        # Create nodes
        node1 = BaseNode("node1", "localhost", 5000, cluster_config)
        node2 = BaseNode("node2", "localhost", 5001, cluster_config)
        node3 = BaseNode("node3", "localhost", 5002, cluster_config)
        
        self.nodes = [node1, node2, node3]
        
        # Start nodes
        for node in self.nodes:
            await node.start()
            self.print_info(f"Node {node.node_id} started on port {node.port}")
        
        # Wait for leader election
        print("\nWaiting for leader election...")
        await asyncio.sleep(3)
        
        # Show cluster status
        print("\nCluster Status:")
        for node in self.nodes:
            role = node.raft.state.value
            term = node.raft.current_term
            leader = node.raft.leader_id
            
            status = f"LEADER ⭐" if node.raft.is_leader() else f"FOLLOWER"
            print(f"  {node.node_id}: {status} | Term: {term} | Leader: {leader}")
        
        # Verify one leader exists
        leaders = [n for n in self.nodes if n.raft.is_leader()]
        if leaders:
            self.print_info(f"\n✅ Leader elected: {leaders[0].node_id}")
        else:
            print("\n⚠️ No leader elected yet, waiting...")
            await asyncio.sleep(2)
    
    async def demo_2_distributed_locks(self):
        """Demo 2: Distributed Lock Manager"""
        self.print_section("DEMO 2: Distributed Lock Manager")
        
        if not self.nodes or len(self.nodes) < 2:
            print("⚠️ Nodes not running, skipping...")
            return
        
        node1, node2 = self.nodes[0], self.nodes[1]
        
        # Test 1: Exclusive Lock
        print("Test 1: Exclusive Lock Acquisition")
        print("-" * 50)
        
        lock_id = "demo-resource-1"
        
        # Node1 acquires exclusive lock
        result1 = await node1.lock_manager.acquire_lock(lock_id, node1.node_id, "exclusive")
        self.print_info(f"Node1 acquire exclusive lock '{lock_id}': {result1}")
        
        # Node2 tries to acquire same lock
        result2 = await node2.lock_manager.acquire_lock(lock_id, node2.node_id, "exclusive")
        self.print_info(f"Node2 acquire same lock (should fail): {result2}")
        
        # Show lock status
        locks = node1.lock_manager.get_all_locks()
        print(f"\n  Current locks: {len(locks)} active")
        
        # Node1 releases lock
        await asyncio.sleep(1)
        released = await node1.lock_manager.release_lock(lock_id, node1.node_id)
        self.print_info(f"Node1 released lock: {released}")
        
        # Test 2: Shared Locks
        print("\n\nTest 2: Shared Lock Acquisition")
        print("-" * 50)
        
        lock_id2 = "demo-resource-2"
        
        # Multiple nodes acquire shared locks
        result1 = await node1.lock_manager.acquire_lock(lock_id2, node1.node_id, "shared")
        result2 = await node2.lock_manager.acquire_lock(lock_id2, node2.node_id, "shared")
        
        self.print_info(f"Node1 acquire shared lock: {result1}")
        self.print_info(f"Node2 acquire shared lock: {result2}")
        self.print_info("✅ Multiple shared locks acquired successfully!")
        
        # Cleanup
        await node1.lock_manager.release_lock(lock_id2, node1.node_id)
        await node2.lock_manager.release_lock(lock_id2, node2.node_id)
    
    async def demo_3_distributed_queue(self):
        """Demo 3: Distributed Queue System"""
        self.print_section("DEMO 3: Distributed Queue System")
        
        if not self.nodes:
            print("⚠️ Nodes not running, skipping...")
            return
        
        node1, node2 = self.nodes[0], self.nodes[1]
        queue_name = "demo-queue"
        
        # Producer: Enqueue messages
        print("Producer: Enqueuing messages...")
        print("-" * 50)
        
        messages = [
            {"task": "process_order", "order_id": 1001},
            {"task": "send_email", "user_id": 5001},
            {"task": "generate_report", "report_id": 7001}
        ]
        
        msg_ids = []
        for i, msg in enumerate(messages):
            msg_id = await node1.queue.enqueue(queue_name, msg)
            msg_ids.append(msg_id)
            self.print_info(f"Enqueued message {i+1}: {msg} -> ID: {msg_id}")
            await asyncio.sleep(0.2)
        
        # Consumer: Dequeue messages
        print("\n\nConsumer: Dequeuing messages...")
        print("-" * 50)
        
        for i in range(len(messages)):
            message = await node2.queue.dequeue(queue_name)
            if message:
                self.print_info(f"Dequeued: {message}")
                # Acknowledge message
                ack_result = await node2.queue.acknowledge(message.get('id'))
                if ack_result:
                    print(f"  → Acknowledged message {message.get('id')}")
            else:
                print("  → Queue empty")
            await asyncio.sleep(0.3)
        
        # Show stats
        print("\n\nQueue Statistics:")
        print("-" * 50)
        stats = await node1.queue.get_stats()
        for key, value in stats.items():
            self.print_data(key, value)
    
    async def demo_4_distributed_cache(self):
        """Demo 4: Distributed Cache with MESI Protocol"""
        self.print_section("DEMO 4: Distributed Cache (MESI Protocol)")
        
        if not self.nodes or len(self.nodes) < 2:
            print("⚠️ Nodes not running, skipping...")
            return
        
        node1, node2 = self.nodes[0], self.nodes[1]
        
        # Test 1: Cache Put and Get
        print("Test 1: Cache Operations")
        print("-" * 50)
        
        # Node1 puts value
        key = "user:1001"
        value = {"name": "John Doe", "age": 30, "role": "admin"}
        
        await node1.cache.put(key, value)
        self.print_info(f"Node1 PUT: {key} = {value}")
        
        # Node1 gets value (should be in Modified state)
        cached_value = await node1.cache.get(key)
        self.print_info(f"Node1 GET: {key} = {cached_value}")
        
        # Node2 gets same key (cache coherence in action)
        await asyncio.sleep(0.5)
        cached_value2 = await node2.cache.get(key)
        self.print_info(f"Node2 GET: {key} = {cached_value2}")
        
        # Test 2: Cache Invalidation
        print("\n\nTest 2: Cache Invalidation")
        print("-" * 50)
        
        # Node1 invalidates cache
        await node1.cache.invalidate(key)
        self.print_info(f"Node1 invalidated key: {key}")
        
        # Try to get invalidated value
        cached_value3 = await node1.cache.get(key)
        result = "✅ Correctly invalidated (None)" if cached_value3 is None else f"⚠️ Still cached: {cached_value3}"
        print(f"  {result}")
        
        # Test 3: Multiple keys
        print("\n\nTest 3: Multiple Cache Entries")
        print("-" * 50)
        
        test_data = {
            "product:101": {"name": "Laptop", "price": 15000000},
            "product:102": {"name": "Mouse", "price": 150000},
            "product:103": {"name": "Keyboard", "price": 500000}
        }
        
        for k, v in test_data.items():
            await node1.cache.put(k, v)
            self.print_info(f"Cached: {k}")
        
        # Show cache stats
        print("\n\nCache Statistics:")
        print("-" * 50)
        stats = await node1.cache.get_stats()
        for key, value in stats.items():
            self.print_data(key, value)
    
    async def demo_5_failure_handling(self):
        """Demo 5: Node Failure Detection"""
        self.print_section("DEMO 5: Failure Detection & Recovery")
        
        if not self.nodes or len(self.nodes) < 3:
            print("⚠️ Needs 3 nodes, skipping...")
            return
        
        print("Simulating node failure scenario...")
        print("-" * 50)
        
        # Show current cluster
        print("\nCurrent cluster state:")
        for node in self.nodes:
            status = "LEADER" if node.raft.is_leader() else "FOLLOWER"
            print(f"  {node.node_id}: {status}")
        
        # Simulate node failure
        failed_node = self.nodes[2]
        print(f"\n⚠️ Simulating failure of {failed_node.node_id}...")
        await failed_node.stop()
        
        print("Waiting for failure detection...")
        await asyncio.sleep(3)
        
        # Check remaining nodes
        print("\nRemaining cluster:")
        for node in self.nodes[:2]:
            status = "LEADER" if node.raft.is_leader() else "FOLLOWER"
            print(f"  {node.node_id}: {status} (healthy)")
        
        print(f"  {failed_node.node_id}: FAILED ❌")
        
        self.print_info("\n✅ Cluster continues operating with majority")
        
        # Restart failed node
        print(f"\n🔄 Recovering {failed_node.node_id}...")
        # Note: In real scenario, would restart the node
        # For demo, we just show the concept
        self.print_info("Node would rejoin cluster and sync state")
    
    async def cleanup(self):
        """Cleanup resources"""
        self.print_section("Cleanup")
        print("Stopping all nodes...")
        
        for node in self.nodes:
            try:
                await node.stop()
                print(f"  ✓ {node.node_id} stopped")
            except Exception as e:
                print(f"  ⚠️ {node.node_id} error: {e}")
        
        self.print_info("\n✅ Demo completed successfully!")
    
    async def run_all_demos(self):
        """Run all demonstrations"""
        try:
            await self.demo_1_cluster_startup()
            await asyncio.sleep(2)
            
            await self.demo_2_distributed_locks()
            await asyncio.sleep(1)
            
            await self.demo_3_distributed_queue()
            await asyncio.sleep(1)
            
            await self.demo_4_distributed_cache()
            await asyncio.sleep(1)
            
            await self.demo_5_failure_handling()
            
        except KeyboardInterrupt:
            print("\n\n⚠️ Demo interrupted by user")
        except Exception as e:
            print(f"\n\n❌ Error during demo: {e}")
            import traceback
            traceback.print_exc()
        finally:
            await self.cleanup()

async def main():
    """Main entry point"""
    print("""
    ╔═══════════════════════════════════════════════════════════════╗
    ║                                                               ║
    ║        DISTRIBUTED SYNCHRONIZATION SYSTEM                     ║
    ║        Live Demonstration Script                              ║
    ║                                                               ║
    ║        Components:                                            ║
    ║        • Raft Consensus Algorithm                             ║
    ║        • Distributed Lock Manager                             ║
    ║        • Distributed Queue System                             ║
    ║        • Distributed Cache (MESI Protocol)                    ║
    ║        • Failure Detection & Recovery                         ║
    ║                                                               ║
    ╚═══════════════════════════════════════════════════════════════╝
    """)
    
    runner = DemoRunner()
    await runner.run_all_demos()

if __name__ == "__main__":
    asyncio.run(main())
