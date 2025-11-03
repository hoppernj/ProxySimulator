import random
from collections import defaultdict
import Environment
from assignments.models import Proxy, Assignment, User
from config_basic import Parameters as P

class OptimalCensor:
    def __init__(self,distributor=None):
        self.agents = []
        self.dist = distributor
        self.env = None
        self.net = None

    def set_env(self,env):
        self.env = env

    def add_agent(self,user):
        self.agents.append(user)

    def get_proxy_utility(self,proxy,agent,step):
        return self.dist.user_utility(proxy,agent,step)

    def get_proxy_utility_delta(self,a_to_p,step):
        return self.dist.user_utility_if_blocked(a_to_p,step)

    def run_setup(self,step):
        self.known_proxies = (
            Assignment.objects.filter(user__in=self.agents)
            .values_list("proxy", flat=True)
            .distinct()
        )
        self.proxies_for_blocking = Proxy.objects.filter(
            id__in=self.known_proxies, is_blocked=False, is_active=True
        )
        print("Step {}: Possible proxies: {}".format(step,len(self.proxies_for_blocking)))
        self.agent_assignments = Assignment.objects.filter(
            user__in=self.agents,
            proxy__in = self.proxies_for_blocking
        )
        self.agents_for_scoring=set()
        self.proxy_utility = {}
        self.proxy_agents = defaultdict(set)
        self.proxy_utility_change = defaultdict(int)
        self.proxy_count = defaultdict(int)
        for a_p in self.agent_assignments:
            self.agents_for_scoring.add(a_p.user)
            self.proxy_utility[a_p.proxy,a_p.user] = self.get_proxy_utility(a_p.proxy,a_p.user,step)
            self.proxy_utility_change[a_p.proxy,a_p.user] = self.get_proxy_utility_delta(a_p,step)
            self.proxy_count[a_p.user] += 1
            self.proxy_agents[a_p.proxy].add(a_p.user)

    def run(self, step):
        self.run_setup(step)
        subsets = [[]]
        for p in self.proxies_for_blocking:
            subsets += [s + [p] for s in subsets]

        best_subset = random.choice(subsets)
        best_utility = float('-inf')

        for s in subsets:
            r_blocked = Assignment.objects.filter(proxy__in=s).values('user').distinct().count()
            utility_s = r_blocked
            for (p,a) in self.proxy_utility.keys():
                utility_s += P.CENSOR_UTILITY_WEIGHT*self.proxy_utility[p,a]/self.proxy_count[a]
                if p in s: utility_s -= P.CENSOR_UTILITY_WEIGHT*self.proxy_utility_change[p,a]/self.proxy_count[a]
            if utility_s > best_utility:
                best_utility=utility_s
                best_subset = s
        print("Optimal: Step {}: Blocking proxies: {}".format(step,best_subset))
        return [proxy.ip for proxy in best_subset]

class GreedyOptimalCensor(OptimalCensor):
    def __init__(self, distributor=None):
        self.agents = []
        self.dist = distributor
        self.net = None

    def run(self, step):
        self.run_setup(step)
        proxies_for_blocking = list(self.proxies_for_blocking)
        random.shuffle(proxies_for_blocking)
        s = []
        utility_s = 0
        r_blocked = 0
        for (p,a) in self.proxy_utility.keys():
            utility_s += P.CENSOR_UTILITY_WEIGHT*self.proxy_utility[p,a]/self.proxy_count[a]
        
        for p in proxies_for_blocking:
            new_r_blocked = Assignment.objects.filter(proxy__in=s+[p]).values('user').distinct().count()
            new_a_utility = utility_s
            for a in self.proxy_agents[p]:
                new_a_utility -= P.CENSOR_UTILITY_WEIGHT*self.proxy_utility_change[p,a]/self.proxy_count[a]
            if new_a_utility + new_r_blocked > utility_s + r_blocked:
                s.append(p)
                r_blocked = new_r_blocked
                utility_s = new_a_utility
        print("Greedy: Step {}: Blocking proxies: {}".format(step,s))
        return [proxy.ip for proxy in s]


class AggressiveCensor(OptimalCensor):
    def run(self, step):
        known_proxies = (
            Assignment.objects.filter(user__in=self.agents)
            .values_list("proxy", flat=True)
            .distinct()
        )
        known_proxies_good_for_blocking = Proxy.objects.filter(
            id__in=known_proxies, is_blocked=False, is_active=True
        )
        num_possible=len(known_proxies_good_for_blocking)
        print("Aggressive: Step {}: Blocking {} proxies".format(step,num_possible))
        return [proxy.ip for proxy in known_proxies_good_for_blocking]

class TargetedCensor:

    def __init__(self):
        self.env = None
        self.net = None
        self.agents = []

    def set_env(self,env):
        self.env = env
    
    def add_agent(self,user):
        self.agents.append(user)

    def run(self, step):
        active_proxies = Proxy.objects.filter(is_active=True, is_blocked=False)

        proxy_scores = []
        for proxy in active_proxies:
            honest_users = Assignment.objects.filter(proxy=proxy, user__is_censor_agent=False).count()
            proxy_scores.append((honest_users, proxy))

        proxy_scores.sort(key=lambda x: (x[0], x[1].id), reverse=True)
        to_block = [p.ip for _, p in proxy_scores[:max(1, len(proxy_scores) // 10)]]
        return to_block

class ConservativeCensor(AggressiveCensor):
    def __init__(self,fraction):
        super().__init__()
        self.fraction = fraction
    
    def run(self,step):
        proxies = super().run(step) 
        if proxies:
            num_to_block = int(self.fraction * len(proxies))
            print(f"Step {step} Conservative: blocking {num_to_block} of {len(proxies)} proxies")
            return random.sample(proxies,num_to_block)
        return []

class NullCensor:
    def __init__(self):
        self.net = None

    def add_agent(self,agent):
        pass

    def run(self,step):
        return []
    
    def set_env(self,env):
        pass



class ZigZagCensor:
    # for each proxy and user, we watch for watch_rounds steps
    # then block
    def __init__(self,watch_rounds):
        self.net = None
        self.watch_rounds = watch_rounds
        self.watch_proxies = {}
        self.watch_users = {}
        self.blocked = set()
        self.agents = []
        # the Environment tells us who communicates with whom in a round
        self.env = None

    def set_env(self,env):
        self.env = env

    def add_agent(self,user):
        self.agents.append(user)

    def run(self,step):
        new_proxies = Assignment.objects.filter(
                user__in=self.agents,
                user__is_active=True,
                created_at__gt=step-2)
        self.watch_proxies[step] = set(a.proxy.ip for a in new_proxies)
        self.watch_users[step] = set()
        for (_,watch_list) in self.watch_proxies.items():
            for proxy in watch_list:
                for user in self.env.contacts(proxy,step,self.net):
                    self.watch_users[step].add(user)
        for (_,watch_list) in self.watch_users.items():
            for user in watch_list:
                for proxy in self.env.contacts(user,step,self.net):
                    self.watch_proxies[step].add(proxy)
        to_block = []
        block_step = step - self.watch_rounds
        if block_step in self.watch_proxies:
            blockset = self.watch_proxies[block_step] - self.blocked
            to_block = list(blockset)
            del self.watch_proxies[block_step]
            del self.watch_users[block_step]
            print(f'Zig-Zag: blocking {len(to_block)} proxies at step {step}')
            self.blocked |= blockset
        return to_block

from collections import deque, Counter 
class ProfileCensor:
    def __init__(self, env=None):
        self.block_window = P.PROFILE_BLOCK_WINDOW
        self.block_threshold = P.PROFILE_BLOCK_THRESHOLD
        self.env = env
        self.net = None
        self.windows = deque(Counter())
        self.blocked = set()
        self.agents = []

    def add_agent(self,env):
        pass

    def set_env(self,env):
        self.env = env

    def run(self,step):
        if step < self.env.birth_period: return []
        servers = Counter()
        for c in User.objects.filter(is_active=True):
            servers.update(self.env.contacts(c.ip,step,self.net))
        for c in self.env.get_clients(self.net):
            servers.update(self.env.contacts(c,step,self.net))
        self.windows.append(servers)
        if step < self.env.birth_period + self.block_window: return []
        srv_count = self.windows.popleft()
        for w in self.windows: srv_count += w
        to_block = []
        for s in srv_count.keys():
            if srv_count[s] > self.block_threshold and s not in self.blocked: 
                to_block.append(s)
                self.blocked.add(s)
        print(f'ProfileCensor: blocking {to_block}')
        return to_block
        

class MultiCensor:
    
    def __init__(self, censor_map):
        self.censor_map = censor_map
        self.env = None
        for net in censor_map.keys():
            censor_map[net].net = net
    
    def set_env(self,env):
        self.env = env
        for censor in self.censor_map.values():
            censor.set_env(env)

    def add_agent(self,a):
        self.censor_map[Environment.get_net(a.ip)].add_agent(a)

    def run(self, step):
        all_to_block = []
        for net, censor in self.censor_map.items():
            blocked = censor.run(step)
            all_to_block.extend([(ip,net) for ip in blocked])
        return list(set(all_to_block))

