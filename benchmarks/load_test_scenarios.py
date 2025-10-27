"""
Performance tests using Locust
"""
from locust import User, task, between
import requests
import random
import string

class DistributedSystemUser(User):
    """Load test user for distributed system"""
    wait_time = between(0.5, 2.0)
    
    def on_start(self):
        """Initialize user"""
        self.node_urls = [
            "http://localhost:5000",
            "http://localhost:5001",
            "http://localhost:5002"
        ]
        
    @task(3)
    def submit_command(self):
        """Submit random command to cluster"""
        node_url = random.choice(self.node_urls)
        
        key = ''.join(random.choices(string.ascii_letters, k=10))
        value = ''.join(random.choices(string.ascii_letters + string.digits, k=20))
        
        command = {
            'op': 'set',
            'key': key,
            'value': value
        }
        
        # This would need an actual API endpoint
        # response = requests.post(f"{node_url}/command", json=command)
        
    @task(2)
    def check_status(self):
        """Check node status"""
        node_url = random.choice(self.node_urls)
        # response = requests.get(f"{node_url}/status")
        
    @task(1)
    def acquire_lock(self):
        """Acquire distributed lock"""
        node_url = random.choice(self.node_urls)
        lock_id = f"lock_{random.randint(1, 100)}"
        
        # response = requests.post(f"{node_url}/lock/acquire", json={'lock_id': lock_id})

if __name__ == "__main__":
    import os
    os.system("locust -f tests/performance/load_test.py --host=http://localhost:5000")
