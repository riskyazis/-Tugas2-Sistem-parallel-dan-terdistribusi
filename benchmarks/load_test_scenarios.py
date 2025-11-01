"""
Load test scenarios for performance benchmarking
"""
import asyncio
import aiohttp
import time
import statistics
from typing import List, Dict
from datetime import datetime


class LoadTestScenario:
    """Base class for load testing scenarios"""
    
    def __init__(self, base_url: str = "http://localhost:5001"):
        self.base_url = base_url
        self.results = []
    
    async def send_request(self, method: str, endpoint: str, payload: dict = None) -> Dict:
        """Send HTTP request and measure latency"""
        url = f"{self.base_url}{endpoint}"
        start = time.time()
        
        try:
            async with aiohttp.ClientSession() as session:
                if method == "POST":
                    async with session.post(url, json=payload) as response:
                        data = await response.json()
                        latency = (time.time() - start) * 1000
                        return {"success": True, "latency": latency, "data": data}
                elif method == "GET":
                    async with session.get(url) as response:
                        data = await response.json()
                        latency = (time.time() - start) * 1000
                        return {"success": True, "latency": latency, "data": data}
        except Exception as e:
            latency = (time.time() - start) * 1000
            return {"success": False, "latency": latency, "error": str(e)}
    
    def calculate_stats(self, latencies: List[float]) -> Dict:
        """Calculate performance statistics"""
        if not latencies:
            return {}
        
        sorted_latencies = sorted(latencies)
        return {
            "min": min(latencies),
            "max": max(latencies),
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
            "p95": sorted_latencies[int(len(sorted_latencies) * 0.95)],
            "p99": sorted_latencies[int(len(sorted_latencies) * 0.99)],
            "throughput": len(latencies) / (sum(latencies) / 1000)
        }


class QueueLoadTest(LoadTestScenario):
    """Load test for distributed queue"""
    
    async def test_enqueue_throughput(self, num_requests: int = 1000):
        """Test queue enqueue throughput"""
        print(f"Testing Queue Enqueue with {num_requests} requests...")
        
        latencies = []
        tasks = []
        
        for i in range(num_requests):
            payload = {
                "queue": "load_test_queue",
                "message": {
                    "id": i,
                    "data": f"load_test_message_{i}",
                    "timestamp": datetime.now().isoformat()
                }
            }
            tasks.append(self.send_request("POST", "/api/queue/enqueue", payload))
        
        results = await asyncio.gather(*tasks)
        latencies = [r["latency"] for r in results if r["success"]]
        
        stats = self.calculate_stats(latencies)
        print(f"Queue Enqueue Stats: {stats}")
        return stats
    
    async def test_dequeue_throughput(self, num_requests: int = 1000):
        """Test queue dequeue throughput"""
        print(f"Testing Queue Dequeue with {num_requests} requests...")
        
        latencies = []
        tasks = []
        
        for i in range(num_requests):
            payload = {"queue": "load_test_queue"}
            tasks.append(self.send_request("POST", "/api/queue/dequeue", payload))
        
        results = await asyncio.gather(*tasks)
        latencies = [r["latency"] for r in results if r["success"]]
        
        stats = self.calculate_stats(latencies)
        print(f"Queue Dequeue Stats: {stats}")
        return stats


class CacheLoadTest(LoadTestScenario):
    """Load test for distributed cache"""
    
    async def test_cache_set_throughput(self, num_requests: int = 1000):
        """Test cache set throughput"""
        print(f"Testing Cache Set with {num_requests} requests...")
        
        latencies = []
        tasks = []
        
        for i in range(num_requests):
            payload = {
                "key": f"load_test_key_{i}",
                "value": {
                    "data": f"load_test_value_{i}",
                    "timestamp": datetime.now().isoformat()
                }
            }
            tasks.append(self.send_request("POST", "/api/cache/set", payload))
        
        results = await asyncio.gather(*tasks)
        latencies = [r["latency"] for r in results if r["success"]]
        
        stats = self.calculate_stats(latencies)
        print(f"Cache Set Stats: {stats}")
        return stats
    
    async def test_cache_get_throughput(self, num_requests: int = 1000):
        """Test cache get throughput"""
        print(f"Testing Cache Get with {num_requests} requests...")
        
        latencies = []
        tasks = []
        
        for i in range(num_requests):
            tasks.append(self.send_request("GET", f"/api/cache/get?key=load_test_key_{i}"))
        
        results = await asyncio.gather(*tasks)
        latencies = [r["latency"] for r in results if r["success"]]
        
        stats = self.calculate_stats(latencies)
        print(f"Cache Get Stats: {stats}")
        return stats


class MixedLoadTest(LoadTestScenario):
    """Mixed workload test"""
    
    async def test_mixed_workload(self, num_requests: int = 1000):
        """Test mixed workload (queue + cache operations)"""
        print(f"Testing Mixed Workload with {num_requests} total requests...")
        
        tasks = []
        
        for i in range(num_requests // 4):
            # Queue enqueue
            queue_payload = {
                "queue": "mixed_queue",
                "message": {"id": i, "data": f"msg_{i}"}
            }
            tasks.append(self.send_request("POST", "/api/queue/enqueue", queue_payload))
            
            # Queue dequeue
            tasks.append(self.send_request("POST", "/api/queue/dequeue", {"queue": "mixed_queue"}))
            
            # Cache set
            cache_payload = {
                "key": f"mixed_key_{i}",
                "value": {"data": f"value_{i}"}
            }
            tasks.append(self.send_request("POST", "/api/cache/set", cache_payload))
            
            # Cache get
            tasks.append(self.send_request("GET", f"/api/cache/get?key=mixed_key_{i}"))
        
        results = await asyncio.gather(*tasks)
        latencies = [r["latency"] for r in results if r["success"]]
        
        stats = self.calculate_stats(latencies)
        print(f"Mixed Workload Stats: {stats}")
        return stats


async def main():
    """Run all load test scenarios"""
    print("=" * 60)
    print("Distributed System Load Tests")
    print("=" * 60 + "\n")
    
    # Queue tests
    queue_test = QueueLoadTest()
    await queue_test.test_enqueue_throughput(100)
    await queue_test.test_dequeue_throughput(100)
    
    # Cache tests
    cache_test = CacheLoadTest()
    await cache_test.test_cache_set_throughput(100)
    await cache_test.test_cache_get_throughput(100)
    
    # Mixed workload
    mixed_test = MixedLoadTest()
    await mixed_test.test_mixed_workload(400)
    
    print("\n" + "=" * 60)
    print("Load Tests Completed")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
