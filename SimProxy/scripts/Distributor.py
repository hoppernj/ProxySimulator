from scripts.simulation_utils import get_user_proxy_utilization
from scripts.deferred_acceptance import get_matched_users
from config_basic import Parameters as P
#from scripts.config_basic import (
#    CENSOR_RATIO, CENSOR_UTILIZATION_RATIO, USER_UTILITY_THRESHOLD, MAX_PROXY_CAPACITY,
#    RBRIDGE_NEW_COST, RBRIDGE_INVITE_COST, RBRIDGE_RESERVE_RATIO, RBRIDGE_USER_PROXY_CAP,
#    RBRIDGE_MIN_CREDIT_DAYS, RBRIDGE_MAX_CREDIT_DAYS, RBRIDGE_RHO, RBRIDGE_INITIAL_USERS,
#    RBRIDGE_INITIAL_PROXIES, RBRIDGE_PROXIES_PER_DAY, RBRIDGE_INVITE_INTERVAL
#)
from assignments.models import Proxy, Assignment, User
from django.db.models import F
from collections import defaultdict
import random

class Distributor:
    def __init__(self):
        pass

    def set_env(self,env):
        pass

    def user_utility(self,proxy,user,step):
        return 0

    def user_utility_if_blocked(self,assignment,step):
        return 0
    
    def request_new_proxies(self,users,step):
        pass

    def update_users(self,step):
        pass

    def update_proxies(self,step):
        pass


class DeferredAcceptance(Distributor):
    def __init__(self,weights_profile):
        self.weights_profile = weights_profile
        self.general_user_utilities = {}
        self.general_proxy_utilities = {}
        self.matches = {}
        self.env = None

    def set_env(self,env):
        self.env = env

    def user_utility(self,proxy,user,step):
        alpha5 = self.weights_profile.get("alpha5", 1)
        if user.ip in self.general_user_utilities:
            dist = abs(user.location - proxy.location)
            return self.general_user_utilities[user.ip] - alpha5*dist
        
        alpha1 = self.weights_profile.get("alpha1", 1)
        alpha2 = self.weights_profile.get("alpha2", 1)
        alpha3 = self.weights_profile.get("alpha3", 1)
        alpha4 = self.weights_profile.get("alpha4", 1)

        some_cap_value = P.MAX_PROXY_CREDIT
        blocked_proxy_usage = 0
        user_assignments = Assignment.objects.filter(user=user)
        number_of_blocked_proxies_that_a_user_knows = user.known_blocked_proxies
        for assignment in user_assignments:
            if assignment.proxy.is_blocked:
                blocked_proxy_usage += (assignment.proxy.blocked_at - assignment.assignment_time)

        number_of_requests_for_new_proxies = user.request_count
        users_proxy_utilization = get_user_proxy_utilization(user, user_assignments, step)    
        if user.is_censor_agent:
            users_proxy_utilization = users_proxy_utilization * P.CENSOR_UTILIZATION_RATIO
        user_utility = (
            alpha1 * min(users_proxy_utilization, some_cap_value)
            - alpha2 * number_of_requests_for_new_proxies
            - alpha3 * blocked_proxy_usage
            - alpha4 * number_of_blocked_proxies_that_a_user_knows)
        self.general_user_utilities[user.ip] = user_utility
        if proxy:
            user_utility -= alpha5 * abs(user.location - proxy.location)
        return user_utility

    def proxy_utility(self,proxy,user,step):
        beta1 = self.weights_profile.get("beta1", 1)
        beta2 = self.weights_profile.get("beta2", 1)
        beta3 = self.weights_profile.get("beta3", 1)
        beta4 = self.weights_profile.get("beta4", 1)
        if proxy.ip in self.general_proxy_utilities:
            return self.general_proxy_utilities[proxy.ip] - beta4*abs(proxy.location - user.location)

        number_of_connected_users = P.MAX_PROXY_CAPACITY - proxy.capacity
        number_of_users_who_know_the_proxy = (
            Assignment.objects.filter(proxy=proxy)
            .values_list("user", flat=True)
            .distinct()
            .count()
        )
        total_utilization_of_proxy_for_users = 0
        proxy_utility = (
            beta1 * number_of_users_who_know_the_proxy
            + beta2 * number_of_connected_users
            + beta3 * total_utilization_of_proxy_for_users)
        self.general_proxy_utilities[proxy.ip] = proxy_utility
        if user:
            proxy_utility -= beta4*abs(user.location - proxy.location)
        return proxy_utility
    
    def user_utility_if_blocked(self, assign, step):
        return (self.weights_profile.get("alpha3",1)*(step-assign.assignment_time) +
                self.weights_profile.get("alpha4",1))
    
    def request_new_proxies(self, users, step):
        right_now = step
        user_prefrences = {}
        proxy_prefrences = {}
        proxy_capacities = {}
        self.general_user_utilities = {}
        self.general_proxy_utilities = {}
        self.matches = {}
        flagged_users = []

        active_proxies = Proxy.objects.filter(
            is_blocked=False, is_active=True, capacity__gt=0
        ).all()

        for proxy in active_proxies:
            utility_values_for_users = {}
            for user in users:
                if user.flagged == True:
                    continue
                user_utility = self.user_utility(proxy,user,step)

                if user_utility < P.USER_UTILITY_THRESHOLD:
                    user.flagged = True
                    user.save()
                    flagged_users.append(user)
                utility_values_for_users[user.ip] = user_utility

            proxy_prefrences[proxy.ip] = list(
                reversed(
                    sorted(
                        utility_values_for_users,
                        key=lambda k: utility_values_for_users[k],
                    )
                )
            )
            proxy_capacities[proxy.ip] = proxy.capacity

        for user in users:
            if user.flagged == True:
                continue
            utility_values_for_proxies = {}
            for proxy in active_proxies:
                utility_values_for_proxies[proxy.ip] = self.proxy_utility(proxy,user,step)
            user_prefrences[user.ip] = list(
                reversed(
                    sorted(
                        utility_values_for_proxies,
                        key=lambda k: utility_values_for_proxies[k],
                    )
                )
            )

        self.matches = get_matched_users(user_prefrences, proxy_prefrences, proxy_capacities)

        for proxy_id in self.matches.keys():
            proxy = Proxy.objects.get(ip=proxy_id)
            users_accepted = self.matches[proxy_id]
            users = User.objects.filter(ip__in=users_accepted)
            users.update(request_count=F("request_count") + 1)
            proxy.capacity -= len(users)
            proxy.save()
            for user in users:
                if self.env.connection_blocked(user.ip,proxy.ip,step): continue
                Assignment.objects.create(
                    proxy=proxy, user=user, assignment_time=right_now, created_at = right_now
                )
        return flagged_users

class AntiZigZag(DeferredAcceptance):
    def __init__(self,weights_profile,alpha6):
        self.alpha6 = alpha6
        super().__init__(weights_profile)
        self.proxy_history = defaultdict(set)

    def request_new_proxies(self, users, step):
        flagged = super().request_new_proxies(users, step)
        for proxy_ip in self.matches.keys():
            for user_ip in self.matches[proxy_ip]:
                self.proxy_history[user_ip].add(proxy_ip)
        return flagged

    def user_utility(self, proxy, user, step):
        user_utility = super().user_utility(proxy, user, step)
        H = set()
        for c_p in Assignment.objects.filter(proxy__ip=proxy, proxy__is_active=True, proxy__is_blocked=False):
            H.update(self.proxy_history[c_p.user.ip])
        return user_utility - self.alpha6 * len(H - self.proxy_history[user])

class Snowflake(Distributor):
    def __init__(self,env):
        self.env = env # need an EphemeralEnv

    def set_env(self, env):
        self.env = env

    def user_utility(self,proxy,user,step):
        rcli = self.env.restricted(user.ip)
        rprox = self.env.restricted(proxy.ip)
        if rcli and rprox: return 0
        if not rcli and rprox: return 1
        if rcli and not rprox: return 1
        else: return 0.5

    def user_utility_if_blocked(self, assignment, step):
        return 0 # Snowflake doesn't care if the proxy you've been using is blocked
    
    def request_new_proxies(self, users, step):
        restricted_users = []
        unrestricted_users = []
        restricted_proxies = []
        unrestricted_proxies = []

        for user in users:
            if self.env.restricted(user.ip): restricted_users.append(user)
            else: unrestricted_users.append(user)

        for proxy in Proxy.objects.filter(capacity=1,is_active=True):
            if self.env.restricted(proxy.ip): restricted_proxies.append(proxy)
            else: unrestricted_proxies.append(proxy)

        assign = {}
        while restricted_users and unrestricted_proxies:
            user_index = random.randrange(0,len(restricted_users))
            user = restricted_users[user_index]
            last_user = restricted_users.pop()
            if user_index < len(restricted_users):
                restricted_users[user_index] = last_user
            proxy = unrestricted_proxies.pop()
            assign[proxy] = user

        while unrestricted_users and restricted_proxies:
            user_index = random.randrange(0,len(unrestricted_users))
            user = unrestricted_users[user_index]
            last_user = unrestricted_users.pop()
            if user_index < len(unrestricted_users):
                unrestricted_users[user_index] = last_user
            proxy = restricted_proxies.pop()
            assign[proxy] = user

        while unrestricted_users and unrestricted_proxies:
            user = unrestricted_users.pop()
            proxy = unrestricted_proxies.pop()
            assign[proxy] = user

        num_assigns = 0
        for proxy,user in assign.items():
            if self.env.connection_blocked(user.ip,proxy.ip,step): continue
            proxy.capacity -= 1
            proxy.save()
            Assignment.objects.create(
                proxy=proxy, user=user, assignment_time=step, created_at = step
            )
            num_assigns += 1
        
        print(f"Snowflake: Step {step}: made {num_assigns} assignments, "+
               f"{len(unrestricted_users)} unmatched uusers, " +
               f"{len(restricted_users)} unmatched rusers")
        

class RBridge(Distributor):
    new_cost = P.RBRIDGE_NEW_COST
    invite_cost = P.RBRIDGE_INVITE_COST
    reserve_ratio = P.RBRIDGE_RESERVE_RATIO
    user_proxy_cap = P.RBRIDGE_USER_PROXY_CAP
    proxy_max_users = P.MAX_PROXY_CAPACITY
    min_credit_days = P.RBRIDGE_MIN_CREDIT_DAYS
    max_credit_days = P.RBRIDGE_MAX_CREDIT_DAYS
    rho = P.RBRIDGE_RHO

    def __init__(self,env):
        self.env = None
        if env: self.set_env(env)

    def set_env(self, env):
        self.env = env
        env.birth_period = 1
        env.mu_b = P.RBRIDGE_INITIAL_USERS
        env.lam_b = P.RBRIDGE_INITIAL_PROXIES
        env.lam_s = P.RBRIDGE_PROXIES_PER_DAY


    def user_utility(self,proxy,user,step):
        return user.credits + (
            self.new_cost * self.user_proxy_cap if user.credits > self.invite_cost else 0
            )
    
    def user_utility_if_blocked(self, assign, step):
        if assign.user.credits >= self.invite_cost + self.new_cost: 
            return self.new_cost
        elif assign.user.credits >= self.invite_cost:
            return self.new_cost * (self.user_proxy_cap + 1)
        else:
            return self.new_cost
    
    def request_new_proxies(self, users, step):
        proxy_cap = {}
        proxies = []
        for proxy in Proxy.objects.filter(is_active=True,is_blocked=False,capacity__gt=0):
            proxy_cap[proxy] = proxy.capacity
            proxies.append(proxy)
        extra_cap = sum(cap for cap in proxy_cap.values())
        mappings = []
        if step == 0:
            print(f"Starting with {len(users)} users, {len(proxies)} proxies and {extra_cap} cap")
        for user in users:
            user_pcount=Assignment.objects.filter(
                user=user,
                proxy__is_active=True,
                proxy__is_blocked=False).count()
            newuser = user.created_at == step
            while ((user.credits >= self.new_cost) or newuser) and \
                user_pcount < self.user_proxy_cap and \
                extra_cap > 0:

                pindex = random.randrange(0,len(proxies))
                proxy = proxies[pindex]
                mappings.append((proxy,user))

                user_pcount += 1
                if not newuser: user.credits -= self.new_cost
                proxy_cap[proxy] -= 1
                extra_cap -= 1
                if proxy_cap[proxy] == 0:
                    rep = proxies.pop()
                    if pindex < len(proxies): proxies[pindex] = rep
            user.save()
            if newuser and user_pcount < self.user_proxy_cap:
                print(f"Step {step}: user {user} had only {user_pcount} proxies")

        for proxy,user in mappings:
            proxy.capacity -= 1
            proxy.save()
            Assignment.objects.create(
                proxy=proxy, user=user, assignment_time=step, created_at = step
            )
          
    def update_users(self, step):
        for a in Assignment.objects.filter(proxy__is_active=True,
                                           proxy__is_blocked=False):
            a_time = step - a.created_at
            if a_time >= self.min_credit_days and a_time <= self.max_credit_days:
                a.user.credits += self.rho
                a.user.save()
    
    # figure out how many invitations to send (new users to create) next step
    def update_proxies(self,step):
        if step > 0 and step % P.RBRIDGE_INVITE_INTERVAL != 0: return
        self.env.birth_period = 0
        avail_cap = 0
        total_cap = 0
        for p in Proxy.objects.filter(is_active=True,is_blocked=False):
            avail_cap += p.capacity
            total_cap += self.proxy_max_users
        num_invitations = (total_cap * self.reserve_ratio - avail_cap)/self.user_proxy_cap
        if num_invitations < 0: return
        num_censor_invites = 0.0
        num_eligible_invites = 0.0
        for c in User.objects.filter(is_active=True):
            if c.credits > self.invite_cost:
                num_eligible_invites += 1
                num_censor_invites += 1 if c.is_censor_agent else P.CENSOR_RATIO

        self.env.mu_s = min(num_invitations,num_eligible_invites)
        self.env.r_c = (num_censor_invites)/num_eligible_invites
