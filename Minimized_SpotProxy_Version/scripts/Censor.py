import random
from assignments.models import Proxy, Assignment
from scripts.config_basic import SNOWFLAKE_BLOCK_INTERVAL, SNOWFLAKE_BLOCK_FRACTION

class OptimalCensor:
    def __init__(self):
        self.agents = []
    def run(self, step):
        if step % 10 == 0:              # Every 10 steps, pick one proxy to block
            proxies = list(Proxy.objects.filter(is_active=True, is_blocked=False))
            return random.sample(proxies, k=min(1, len(proxies)))
        return []

class AggresiveCensor(OptimalCensor):
    def run(self, step):
        if step % 10 == 0:              # Blocks two proxies every 10 steps
            proxies = list(Proxy.objects.filter(is_active=True, is_blocked=False))
            return random.sample(proxies, k=min(2, len(proxies)))
        return []

class TargetedCensor:
    def run(self, step):
        active_proxies = Proxy.objects.filter(is_active=True, is_blocked=False)

        proxy_scores = []
        for proxy in active_proxies:
            honest_users = Assignment.objects.filter(proxy=proxy, client__is_censor_agent=False).count()
            proxy_scores.append((honest_users, proxy))

        proxy_scores.sort(key=lambda x: (x[0], x[1].id), reverse=True)
        to_block = [p for _, p in proxy_scores[:max(1, len(proxy_scores) // 10)]]
        return to_block

class SnowflakeCensor:
    def __init__(self,
                 block_interval: int = SNOWFLAKE_BLOCK_INTERVAL,
                 block_fraction: float = SNOWFLAKE_BLOCK_FRACTION):
        self.block_interval = block_interval
        self.block_fraction = block_fraction

    def run(self, step):
        if step % self.block_interval != 0:
            return []

        volunteers = list(
            Proxy.objects.filter(
                is_test=True,
                is_active=True,
                is_blocked=False
            )
        )
        if not volunteers:
            return []
        k = max(1, int(len(volunteers) * self.block_fraction))
        return random.sample(volunteers, k)

class MultiCensor:
    def __init__(self, censor_map):
        self.censor_map = censor_map

    def run(self, step):
        all_to_block = []
        for _, censor in self.censor_map.items():
            blocked = censor.run(step)
            all_to_block.extend(blocked)
        return list(set(all_to_block))import random
from assignments.models import Proxy, Assignment

class OptimalCensor:
    def __init__(self):
        self.agents = []
    def run(self, step):
        if step % 10 == 0:              # Every 10 steps, pick one proxy to block
            proxies = list(Proxy.objects.filter(is_active=True, is_blocked=False))
            return random.sample(proxies, k=min(1, len(proxies)))
        return []

class AggresiveCensor(OptimalCensor):
    def run(self, step):
        if step % 10 == 0:              # Blocks two proxies every 10 steps
            proxies = list(Proxy.objects.filter(is_active=True, is_blocked=False))
            return random.sample(proxies, k=min(2, len(proxies)))
        return []

class TargetedCensor:
    def run(self, step):
        active_proxies = Proxy.objects.filter(is_active=True, is_blocked=False)

        proxy_scores = []
        for proxy in active_proxies:
            honest_users = Assignment.objects.filter(proxy=proxy, client__is_censor_agent=False).count()
            proxy_scores.append((honest_users, proxy))

        proxy_scores.sort(key=lambda x: (x[0], x[1].id), reverse=True)
        to_block = [p for _, p in proxy_scores[:max(1, len(proxy_scores) // 10)]]
        return to_block
