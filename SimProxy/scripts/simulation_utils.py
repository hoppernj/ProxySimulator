from assignments.models import User, Proxy, Assignment
from scripts.logger import rblog
from django.db.models import F
from scripts.deferred_acceptance import get_matched_users
from config_basic import Parameters as P

import logging

RED = "\033[91m"
RESET = "\033[0m"
    
def get_user_proxy_utilization(user, user_assignments, right_now):
    proxy_checker = {}
    users_proxy_utilization = 0    
    for assignment in user_assignments:
        if proxy_checker.get(assignment.proxy.id, None):
            continue
        if assignment.proxy.is_blocked == True:
            users_proxy_utilization += (
                assignment.proxy.blocked_at - assignment.assignment_time
            )
#        if assignment.proxy.is_active == False:
#            users_proxy_utilization += (
#                assignment.proxy.deactivated_at - assignment.assignment_time
#            )
        else:
            users_proxy_utilization += right_now - assignment.assignment_time
        proxy_checker[assignment.proxy.id] = True

    if user.is_censor_agent:
        users_proxy_utilization = users_proxy_utilization * P.CENSOR_UTILIZATION_RATIO
    return users_proxy_utilization


def score_proxy_for_user(proxy, user, distributor_profile, step, xblock=[]):
    # Pull weight factors
    alpha1 = distributor_profile.get("alpha1", 1)
    alpha2 = distributor_profile.get("alpha2", 1)
    alpha3 = distributor_profile.get("alpha3", 1)
    alpha4 = distributor_profile.get("alpha4", 1)
    alpha5 = distributor_profile.get("alpha5", 1)

    some_cap_value = 100 * 24
    blocked_proxy_usage = 0
    user_assignments = Assignment.objects.filter(user=user)
    number_of_blocked_proxies_that_a_user_knows = user.known_blocked_proxies
    for assignment in user_assignments:
        if assignment.proxy.is_blocked:
            blocked_proxy_usage += (assignment.proxy.blocked_at - assignment.assignment_time)
        if assignment.proxy in xblock:
            blocked_proxy_usage += step-assignment.assignment_time
            number_of_blocked_proxies_that_a_user_knows += 1

    number_of_requests_for_new_proxies = user.request_count
    users_proxy_utilization = get_user_proxy_utilization(user, user_assignments, step)    
    if user.is_censor_agent:
            users_proxy_utilization = users_proxy_utilization * P.CENSOR_UTILIZATION_RATIO
    user_utility = (
        alpha1 * min(users_proxy_utilization, some_cap_value)
        - alpha2 * number_of_requests_for_new_proxies
        - alpha3 * blocked_proxy_usage
        - alpha4 * number_of_blocked_proxies_that_a_user_knows
        - alpha5 * abs(user.location - proxy.location))
    return user_utility


def request_new_proxies(proposing_users, distributor_profile, right_now: int):
    user_prefrences = {}
    proxy_prefrences = {}
    proxy_capacities = {}
    general_user_utilities = {}
    general_proxy_utilities = {}
    flagged_users = []

    # time1 = time()

    active_proxies = Proxy.objects.filter(
        is_blocked=False, is_active=True, capacity__gt=0
    ).all()

    # time2 = time()

    # alpha1, alpha2, alpha3, alpha4, alpha5 = 2, 1, 1, 2, 10
    alpha1 = distributor_profile.get("alpha1", 1)
    alpha2 = distributor_profile.get("alpha2", 1)
    alpha3 = distributor_profile.get("alpha3", 1)
    alpha4 = distributor_profile.get("alpha4", 1)
    alpha5 = distributor_profile.get("alpha5", 1)
    some_cap_value = 100 * 24
    for user in proposing_users:
        if user.flagged == True:
            continue
        # ################ Enem19 implementation ################
        user_assignments = Assignment.objects.filter(user=user).order_by(
            "created_at"
        )

        blocked_proxy_usage = 0
        for assignment in user_assignments:
            if assignment.proxy.is_blocked == True:
                blocked_proxy_usage += (
                    assignment.proxy.blocked_at - assignment.assignment_time
                )
        number_of_blocked_proxies_that_a_user_knows = user.known_blocked_proxies
        number_of_requests_for_new_proxies = user.request_count
        users_proxy_utilization = get_user_proxy_utilization(user, user_assignments, right_now)
        # users_proxy_utilization = right_now - user.created_at
        if user.is_censor_agent:
            users_proxy_utilization = (
                users_proxy_utilization * P.CENSOR_UTILIZATION_RATIO
            )
        user_utility = (
            alpha1 * min(users_proxy_utilization, some_cap_value)
            - alpha2 * number_of_requests_for_new_proxies
            - alpha3 * blocked_proxy_usage
            - alpha4 * number_of_blocked_proxies_that_a_user_knows
        )
        general_user_utilities[user.ip] = user_utility

    # time3 = time()

    for proxy in active_proxies:
        utility_values_for_users = {}
        for user in proposing_users:
            if user.flagged == True:
                continue
            # ################ Enem19 implementation ################
            #distance = get_normalized_distance(
            #    (proxy.latitude, proxy.longitude), (user.latitude, user.longitude)
            #)
            distance = abs(proxy.location - user.location)
            user_utility = general_user_utilities[user.ip] - alpha5 * distance

            if user_utility < USER_UTILITY_THRESHOLD:
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

    # time4 = time()

    beta1 = distributor_profile.get("beta1", 1)
    beta2 = distributor_profile.get("beta2", 1)
    beta3 = distributor_profile.get("beta3", 1)
    beta4 = distributor_profile.get("beta4", 1)
    for proxy in active_proxies:
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
            + beta3 * total_utilization_of_proxy_for_users
        )
        general_proxy_utilities[proxy.ip] = proxy_utility

    for user in proposing_users:
        if user.flagged == True:
            continue
        utility_values_for_proxies = {}
        beta4 = 1
        for proxy in active_proxies:
            distance = abs(proxy.location - user.location)
            proxy_utility = general_proxy_utilities[proxy.ip] - beta4 * distance
            utility_values_for_proxies[proxy.ip] = proxy_utility
        user_prefrences[user.ip] = list(
            reversed(
                sorted(
                    utility_values_for_proxies,
                    key=lambda k: utility_values_for_proxies[k],
                )
            )
        )

    # time5 = time()

    matches = get_matched_users(user_prefrences, proxy_prefrences, proxy_capacities)

    # time6 = time()

    for proxy_id in matches.keys():
        proxy = Proxy.objects.get(ip=proxy_id)
        users_accepted = matches[proxy_id]
        users = User.objects.filter(ip__in=users_accepted)
        users.update(request_count=F("request_count") + 1)
        proxy.capacity -= len(users)
        proxy.save()
        for user in users:
            Assignment.objects.create(
                proxy=proxy, user=user, assignment_time=right_now, created_at = right_now
            )
            # if Assignment.objects.filter(proxy=proxy, user=user).count() == 1:

    # time7 = time()

    # times = [time2-time1, time3-time2, time4-time3, time5-time4, time6-time5, time7-time6]
    # print(f"taking most time: {times.index(max(times))} ||||||| {times}")

    return flagged_users