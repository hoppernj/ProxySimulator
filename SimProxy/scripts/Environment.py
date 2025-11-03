from assignments.models import User, Proxy, Assignment, Block
from django.db.models import F
import random
from config_basic import Parameters as P
from collections import defaultdict

def get_net(ip):
    return ip.split('.')[0]

class Environment:
    birth_period = P.BIRTH_PERIOD
    # "Alive" World, Static Proxies
    mu_b = P.DYN_USR_ARR_BIRTH
    mu_s = P.DYN_USR_ARR_STABLE
    lam_b = P.DYN_PROX_ARR_BIRTH
    lam_s = P.DYN_PROX_ARR_STABLE
    runid = 0
    r_c = P.CENSOR_RATIO
    r_c_b = P.CENSOR_RATIO_BIRTH
    p_user_active = P.DYN_P_ACTIVE_USR
    last_ip = {'proxy':"10.0.0.0", 'user':'0.1.0.0'}
    user_wait_start = {}
    userfile = {}
    proxyfile = {}
    summarylines = None
    wait_times_file = None
    uptimes_file = None

    def __init__(self,censor):
        self.censor=censor
        self.abandoned_users = []
        self.conns = {}
    
    def set_seed(self,s):
        self.runid = s
        for n in self.nets():
            self.userfile[n]=open(f"users.{n}.{s}.csv","w")
            print("step,user,assigned_proxies,waiting_time",file=self.userfile[n])
            self.proxyfile[n] = open(f"proxies.{n}.{s}.csv","w")
            print("step,proxy,users,blocked,uptime",file=self.proxyfile[n])
        self.summarylines = open(f"results.{s}.csv","w")
        if not self.summarylines: print("failed to open results file!")
        print("step,total_proxies,blocked_proxies,avg_uptimes,total_users,blocked_users,avg_waiting_time",file=self.summarylines)
        self.wait_times_file = open(f"wait_times.{s}.csv","w")
        print("step,user,wait",file=self.wait_times_file)
        self.uptimes_file = open(f"uptimes.{s}.csv","w")
        print("step,proxy,uptime",file=self.uptimes_file)

    def increment_ip(self,ty):
        nums = list(map(int, self.last_ip[ty].split(".")))
        nums[-1] += 1
        new_ip = ".".join(map(str, nums))
        self.last_ip[ty] = new_ip
        return new_ip

    def is_proxy(self,ip):
        return get_net(ip) == '10'

    def is_user(self,ip):
        return get_net(ip) in self.nets()

    def net(self):
        return '0'
    
    def nets(self):
        return ['0']

    def create_new_proxy(self,step):
        Proxy.objects.create(ip=self.increment_ip('proxy'), created_at=step, location=random.random())

    def create_new_user(self,step,net=''):
        user_ip = self.increment_ip('user'+net)
        is_censor_agent = random.random() < (self.r_c if step >= self.birth_period else self.r_c_b)
        user = User.objects.create(ip=user_ip, is_censor_agent=is_censor_agent, created_at=step, location=random.random())
        if is_censor_agent: self.censor.add_agent(user)
        self.user_wait_start[user.id] = step
        return user

    def poisson(r):
        f, n = random.expovariate(r), 0
        while f < 1.0:
            n += 1
            f += random.expovariate(r)
        return n

    def newUsers(self,step):
        abandoned = self.abandoned_users
        self.abandoned_users = []
        numusers = Environment.poisson(self.mu_b if step < self.birth_period else self.mu_s)
        return abandoned + [self.create_new_user(step) for _ in range(numusers)]

    def createNewProxies(self,step):
        numproxies = Environment.poisson(self.lam_b if step < self.birth_period else self.lam_s)
        for _ in range(numproxies):
            self.create_new_proxy(step)

    def removeUsers(self,step):
        return set()

    def removeProxies(self,step):
        pass

    def logStep(self,step):
        total_users = 0
        total_proxies = 0
        blocked_ucount = 0
        blocked_pcount = 0
        unblocked_pcount = 0
        total_waiting_time = 0.0
        total_uptime = 0.0
        uproxy_count = defaultdict(int)
        proxy_ucount = defaultdict(int)
        for a in Assignment.objects.filter(proxy__is_active=True,user__is_active=True):
            if not a.blocked and self.reachable(a.proxy.ip,a.user.ip):
                uproxy_count[a.user.ip] += 1
                proxy_ucount[a.proxy.ip,get_net(a.user.ip)] += 1

        for user in User.objects.filter(is_active=True):
            net = get_net(user.ip)
            wait_time = 0 if user.id not in self.user_wait_start else step-self.user_wait_start[user.id]
            print(f"{step},{user.ip},{uproxy_count[user.ip]},{wait_time}",file=self.userfile[net])
            total_users += 1
            total_waiting_time += wait_time
            if uproxy_count[user.ip] == 0: 
                blocked_ucount += 1
            elif wait_time > 0:
                print(f"{step},{user.ip},{wait_time}",file=self.wait_times_file)
                del self.user_wait_start[user.id]

        for proxy in Proxy.objects.filter(is_active=True):
            uptime = {}
            blocked = {}
            total_proxies += 1
            for n in self.nets(): 
                uptime[n] = step-proxy.created_at
                blocked[n] = (proxy.updated_at != 0)
            for block in Block.objects.filter(proxy=proxy):
                uptime[block.net] = block.blocked_at - proxy.created_at
                blocked[block.net] = True
            for n in self.nets():
                print(f"{step},{proxy.ip},{proxy_ucount[proxy.ip,n]},{blocked[n]},{uptime[n]}",file=self.proxyfile[n])
            uptime = max(u for u in uptime.values())
            if all(b for b in blocked.values()):
                blocked_pcount += 1
                if proxy.updated_at == 0:
                    proxy.updated_at = step
                    proxy.save()
                    print(f"{step},{proxy.ip},{uptime}",file=self.uptimes_file)
            else:
                unblocked_pcount += 1
                total_uptime += uptime
        if unblocked_pcount == 0: unblocked_pcount = 1
        avg_waiting_time = 0.0
        if total_users > 0: avg_waiting_time = total_waiting_time/total_users     
        print(f"{step},{total_proxies},{blocked_pcount},{total_uptime/unblocked_pcount},{total_users},{blocked_ucount},{avg_waiting_time}",file=self.summarylines)

    def connected(self,user_ip,proxy_ip,step,censor=None):
        if not step in self.conns: self.conns = {step:True}
        if not Assignment.objects.filter(proxy__ip=proxy_ip, proxy__is_active=True, proxy__is_blocked=False, user__ip=user_ip).exists():
            return False
        if not (step,user_ip,proxy_ip) in self.conns: 
            self.conns[step,user_ip,proxy_ip] = random.random() < self.p_user_active
        return self.conns[step,user_ip,proxy_ip]

    def contacts(self,ip,step,censor=None):
        contacts = []
        if Proxy.objects.filter(ip=ip,is_active=True,is_blocked=False).exists():
            for a in Assignment.objects.filter(proxy__ip=ip):
                if self.connected(a.user.ip,ip,step): contacts.append(a.user.ip)
        if User.objects.filter(ip=ip,is_active=True).exists():
            for a in Assignment.objects.filter(user__ip=ip,proxy__is_active=True,proxy__is_blocked=False):
                if self.connected(ip,a.proxy.ip,step): contacts.append(a.proxy.ip)
        return contacts
    
    def block(self,ip,step):
        user_ids = []
        proxy = Proxy.objects.filter(ip=ip)[:1]
        if proxy:
            proxy[0].is_blocked = True
            proxy[0].blocked_at = step
            proxy[0].save()
            user_ids = Assignment.objects.filter(proxy=proxy[0],user__is_active=True).values_list('user_id', flat=True)
            User.objects.filter(id__in=user_ids).update(
                known_blocked_proxies=F('known_blocked_proxies')+1
            )
            Assignment.objects.filter(proxy=proxy[0]).update(blocked=True)
            Block.objects.create(proxy=proxy[0],net=self.net(),blocked_at=step)
        return user_ids

    def connection_blocked(self,client,server,step):
        return Proxy.objects.filter(ip=server,is_blocked=True).exists()

    def user_is_blocked(self,user):
        return not Assignment.objects.filter(user=user, proxy__is_active=True, blocked=False).exists()

    def close_files(self):
        for n in self.nets():
            self.proxyfile[n].close()
            self.userfile[n].close()
        self.summarylines.close()
        self.wait_times_file.close()
        self.uptimes_file.close()

    def reachable(self,ip1,ip2):
        return True
    
    def get_clients(self,net):
        clist = []
        for u in User.objects.all():
            if net is None or get_net(u.ip) == net: clist.append(u.ip)
        return clist

class EphemeralEnv(Environment):
    def __init__(self,censor):
        super().__init__(censor)
        self.inactive_users = []
        self.mu_b = P.EPH_USR_ARR_BIRTH
        self.lam_b = P.EPH_PROX_ARR_BIRTH
        self.mu_s = P.EPH_USR_ARR_STABLE
        self.lam_s = P.EPH_PROX_ARR_STABLE
        self.churn = P.EPH_CHURN
        self.stable_p = P.EPH_STABLE_PROX_FRACTION
        self.unrestricted_p = P.EPH_UNRESTRICTED_FRACTION
        self.mu_return = P.EPH_USR_RETURN_RATE
        self.last_ip = {}
        self.last_ip['rcli'] = '0.0.0.1'
        self.last_ip['ucli'] = '0.1.0.1'
        self.last_ip['rprox'] = '10.0.0.1'
        self.last_ip['uprox'] = '10.1.0.1'
        self.last_ip['sprox'] = '10.2.0.1'

    def is_stable(self,ip):
        return ip[:4] == '10.2'
    
    def is_proxy(self,ip):
        return ip[:3] == '10.'
    
    def is_user(self,ip):
        return get_net(ip) != '10'

    def restricted(self,ip):
        return ip.split('.')[1] == '0'

    def reachable(self,ip1,ip2):
        return not (self.restricted(ip1) and self.restricted(ip2))
    
    # Hacky O(1) insert/remove-random implementation
    def random_inactive_user(self):
        n = len(self.inactive_users)
        idx = random.randrange(0,n)
        last_user = self.inactive_users.pop()
        if idx == n-1:
            user = last_user
        else:
            user = self.inactive_users[idx]
            self.inactive_users[idx] = last_user
        return user

    def create_new_user(self, step, net=''):
        # mu_return fraction of "new" users are previously inactivated users
        if random.random() < self.mu_return and self.inactive_users:
            user = self.random_inactive_user()
            user.is_active = True
            user.save()
            self.user_wait_start[user.id] = step
            return user
        # else create a new user
        ctype = 'rcli'
        if random.random() < self.unrestricted_p: ctype = 'ucli'
        user_ip = self.increment_ip(ctype+net)
        is_censor_agent = random.random() < (self.r_c if step >= self.birth_period else self.r_c_b)
        user = User.objects.create(ip=user_ip, is_censor_agent=is_censor_agent, created_at=step, location=random.random())
        if is_censor_agent: self.censor.add_agent(user)
        self.user_wait_start[user.id] = step
        return user

    def create_new_proxy(self, step):
        ptype = 'rprox'
        if random.random() < self.stable_p: ptype = 'sprox'
        if random.random() < self.unrestricted_p: ptype = 'uprox'
        Proxy.objects.create(ip=self.increment_ip(ptype), created_at=step, capacity=1,location=random.random())

    def removeUsers(self, step):
        removed = set()
        for user in User.objects.filter(is_active=True):
            if random.random() < self.churn:
                removed.add(user)
                user.is_active = False
                user.save()
                self.inactive_users.append(user)
                for a in Assignment.objects.filter(user=user):
                    a.proxy.capacity += 1
                    a.proxy.save()
                    a.delete()
        return removed

    def removeProxies(self,step):
        for proxy in Proxy.objects.filter(is_active=True):
            if random.random() < self.churn:
                proxy.is_active = False
                proxy.save()
                for a in Assignment.objects.filter(proxy=proxy):
                    self.abandoned_users.append(a.user)
                    a.delete()

    def connection_blocked(self,client,server,step):
        return super().connection_blocked(client,server,step) or not self.reachable(client,server) 

    def connected(self,user_ip,proxy_ip,step,censor=None):
        return Assignment.objects.filter(user__ip=user_ip,
                                         proxy__ip=proxy_ip,
                                         user__is_active=True,
                                         proxy__is_active=True,
                                         proxy__is_blocked=False).exists()

# Wraps around an "inner environment" adding innocent servers and clients
class Collateral(Environment):
    alpha = P.COLLATERAL_ZIPF_EXP

    detection_rate = {
        "client":{"server":P.COLLATERAL_FP_RATE},
        "user":{"server":P.COLLATERAL_FP_RATE, "proxy":P.COLLATERAL_TP_RATE}
    }  

    def __init__(self,inner):
        self.inner=inner
        self.clients_of = {} # user_of[server] = set of users that visit the server
        self.servers_of = {} # servers_of[client] = set of servers the client visits
        self.blocked_servers = set()
        self.blocked_connections = set()
        self.logfile = None
        self.last_ip = { 'server':'128.0.0.0'}
        for net in inner.nets(): self.last_ip['client'+net] = net+'.168.0.0'
        self.weights = [n**(-self.alpha) for n in range(1,P.COLLATERAL_SERVERS+1)]
        self.servers = [self.increment_ip('server') for _ in range(P.COLLATERAL_SERVERS)]
        self.clients = [self.increment_ip('client'+inner.net()) for _ in range(P.COLLATERAL_USERS)]
        for ip in self.servers: self.clients_of[ip] = set()
        for ip in self.clients: self.select_servers(0,ip)
        print(f"Initialized Collateral with Zipf parameter {self.alpha}")

    def set_seed(self,s):
        self.logfile = open(f"servers.{s}.csv","w")
        print("step,servers,blocked,connections,blocked_conns",file=self.logfile)
        self.inner.set_seed(s)

    def select_servers(self,step,ip):
        n = random.randrange(3,min(P.COLLATERAL_SERVERS,10))
        ips = random.choices(self.servers,weights=self.weights,k=n)
        self.servers_of[ip] = set(ips)
        for srvr in ips: self.clients_of[srvr].add(ip)

    def create_new_user(self, step, net=''):
        user = self.inner.create_new_user(step,net)
        self.select_servers(step,user.ip)
        return user
    
    def create_new_proxy(self, step):
        return self.inner.create_new_proxy(step)

    def is_user(self,ip):
        return self.inner.is_user(ip)
    
    def is_proxy(self, ip):
        return self.inner.is_proxy(ip)
    
    def is_client(self,ip):
        return ip.split('.')[1] == '168'
    
    def is_server(self,ip):
        return get_net(ip) == '128'

    def restricted(self,ip):
        return self.inner.restricted(ip)

    def newUsers(self,step):
        newusers = self.inner.newUsers(step)
        for c in newusers:
            if c.ip not in self.servers_of: self.select_servers(step,c.ip)
            else: 
                for s in self.servers_of[c.ip]: self.clients_of[s].add(c.ip)
        return newusers

    def createNewProxies(self,step):
        return self.inner.createNewProxies(step)

    def removeUsers(self,step):
        removed = self.inner.removeUsers(step)
        for c in removed:
            for s in self.servers_of[c.ip]:
                self.clients_of[s].remove(c.ip)
        return removed

    def removeProxies(self,step):
        return self.inner.removeProxies(step)

    def connected(self,client_ip,server_ip,step,censor=None):
        if censor and get_net(client_ip) != censor: return False
        if self.is_user(client_ip) and self.is_proxy(server_ip):
            return self.inner.connected(client_ip,server_ip,step,censor) and random.random() < self.detection_rate['user']['proxy']
        if self.is_user(client_ip) and self.is_server(server_ip):
            return client_ip in self.clients_of[server_ip] and random.random() < self.detection_rate['user']['server']
        if self.is_client(client_ip) and self.is_server(server_ip):
            return client_ip in self.clients_of[server_ip] and random.random() < self.detection_rate['client']['server']
        return False

    def contacts(self,ip,step,censor=None):
        contacts = []
        if self.is_user(ip):
            contacts = self.inner.contacts(ip,step,censor)
        elif self.is_proxy(ip):
            return self.inner.contacts(ip,step,censor)
        if self.is_server(ip):
            for c in self.clients_of[ip]:
                if self.connected(c,ip,step,censor): contacts.append(c)
        else:
            for s in self.servers_of[ip]:
                if self.connected(ip,s,step,censor): contacts.append(s)       
        return contacts
    
    def block(self,block,step):
        ip = block
        net = '0'
        if type(block) is tuple: 
            (ip, net) =  block
        if self.is_proxy(ip): return self.inner.block(block,step)
        if self.is_server(ip):
            self.blocked_servers.add(ip)
            for c in self.clients_of[ip]: 
                if get_net(c) == net: self.blocked_connections.add((c,ip))
        return []

    def logStep(self, step):
        self.inner.logStep(step)
        print(f'{step},{len(self.servers)},{len(self.blocked_servers)},'+
              f'{sum(len(self.clients_of[s]) for s in self.servers)},{len(self.blocked_connections)}',
              file=self.logfile)
        
    def close_files(self):
        self.logfile.close()
        self.inner.close_files()

    def clients(self,net):
        clientlist = []
        for c in self.servers_of.keys():
            if net is None or get_net(c)==net: clientlist.append(c)
        return clientlist

def multiblock(block,step):
    ip = block
    net = '0'
    if type(block) is tuple:
        (ip,net) = block
    user_ids = []
    for a in Assignment.objects.filter(proxy__ip=ip,user__is_active=True):
        if get_net(a.user.ip) != net: continue
        a.user.known_blocked_proxies += 1
        a.user.save()
        user_ids.append(a.user.id)
        a.blocked = True
        a.save()
        if not Block.objects.filter(proxy=a.proxy,net=net).exists():
            Block.objects.create(proxy=a.proxy,net=net,blocked_at=step)
    return user_ids

def multicontacts(self,ip,step,censor):
    contacts = []
    if Proxy.objects.filter(ip=ip,is_active=True,is_blocked=False).exists():
        for a in Assignment.objects.filter(proxy__ip=ip,blocked=False):
            if censor and get_net(a.user.ip) != censor: continue
            if self.connected(a.user.ip,ip,step): contacts.append(a.user.ip)
    if User.objects.filter(ip=ip,is_active=True).exists():
        if censor and get_net(ip) != censor: return contacts
        for a in Assignment.objects.filter(user__ip=ip,proxy__is_active=True,blocked=False):
            if self.connected(ip,a.proxy.ip,step): contacts.append(a.proxy.ip)
    return contacts

def blockProxies(step,numCensors):
    # mark any proxies blocked by all censors as blocked
    for proxy in Proxy.objects.filter(is_active=True,is_blocked=False):
        blocks = Block.objects.filter(proxy=proxy)
        if Block.objects.filter(proxy=proxy).count() == numCensors:
            proxy.is_blocked=True
            proxy.blocked_at=step
            proxy.save()


class MultiNetwork(Environment):
    def __init__(self,censor,netweights):
        super().__init__(censor)
        self.netweights = netweights
        self.nets_ = [str(s) for s in range(len(netweights))]
        for n in self.nets_:
            self.last_ip['user'+n] = n+".1.0.0"
    def nets(self):
        return self.nets_    
    def net(self):
        return random.choices(self.nets_,weights=self.netweights,k=1)[0]  
    def create_new_user(self,step):
        return super().create_new_user(step,self.net())
    
    def block(self,block,step):
        return multiblock(block,step)
    
    def connection_blocked(self,client,server,step):
        return Block.objects.filter(proxy__ip=server,net=get_net(client)).exists()

    def user_is_blocked(self,user):
        has_reachable_proxy = False
        for a in Assignment.objects.filter(user=user,blocked=False):
            if not self.connection_blocked(user.ip,a.proxy.ip,None): 
                has_reachable_proxy=True
        return not has_reachable_proxy

    def contacts(self,ip,step,censor=None):
        return multicontacts(self,ip,step,censor)
    
    def removeProxies(self,step):
        blockProxies(step,len(self.nets_))
        super().removeProxies(step)
    

class EphemeralMultiNet(EphemeralEnv):
    def __init__(self,censor,netweights):
        super().__init__(censor)
        self.netweights = netweights
        self.nets_ = [str(s) for s in range(len(netweights))]
        for n in self.nets_:
            self.last_ip['ucli'+n] = n+".1.0.0"
            self.last_ip['rcli'+n] = n+".0.0.0"
    def nets(self):
        return self.nets_    
    def net(self):
        return random.choices(self.nets_,weights=self.netweights,k=1)[0]    
    def create_new_user(self,step):
        return super().create_new_user(step,self.net())
    
    def block(self,block,step):
        return multiblock(block,step)
    
    def connection_blocked(self,client,server,step):
        return Block.objects.filter(proxy__ip=server,net=get_net(client)).exists() or not self.reachable(client,server)

    def user_is_blocked(self,user):
        has_reachable_proxy = False
        for a in Assignment.objects.filter(user=user,blocked=False):
            if not self.connection_blocked(user.ip,a.proxy.ip,None): 
                has_reachable_proxy=True
        return not has_reachable_proxy
    
    def contacts(self,ip,step,censor=None):
        return multicontacts(self,ip,step,censor)
    
    def removeProxies(self,step):
        blockProxies(step,len(self.nets_))
        super().removeProxies(step)
    

